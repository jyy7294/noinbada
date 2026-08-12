from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from html import unescape

from .hourly_store import load_local_env

TOKEN_RE = re.compile(r"#[0-9A-Za-z_가-힣]+|[A-Za-z][A-Za-z0-9_]{2,}|[가-힣]{2,}")
STOPWORDS = {
    "그리고", "그러나", "하지만", "오늘", "이번", "관련", "대한", "통해", "있는", "하는",
    "입니다", "합니다", "에서", "으로", "까지", "그냥", "진짜", "너무", "지금", "요즘",
    "가자", "https", "http", "the", "and", "for", "with", "this", "that", "from",
}


def _plain_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(str(value or "")))).strip()


def _repeated_terms(documents: list[str], query: str, candidates: list[str] | None,
                    limit: int) -> tuple[list[tuple[str, int]], int]:
    """Count a term once per document; one weighted hashtag never equals repetition."""
    query_tokens = {token.casefold().lstrip("#") for token in TOKEN_RE.findall(query)}
    document_terms: list[set[str]] = []
    display_by_key: dict[str, str] = {}
    for document in documents:
        text = re.sub(r"https?://\S+|@[0-9A-Za-z_]+", " ", _plain_text(document))
        folded = text.casefold()
        found: set[str] = set()
        if candidates:
            for candidate in candidates:
                candidate_text = " ".join(str(candidate).split())
                key = candidate_text.casefold().lstrip("#")
                if key and key != query.casefold().lstrip("#") and candidate_text.casefold() in folded:
                    found.add(key)
                    display_by_key.setdefault(key, candidate_text)
        else:
            for expression in TOKEN_RE.findall(text):
                key = expression.casefold().lstrip("#")
                if key in query_tokens or key in STOPWORDS or len(key) < 2:
                    continue
                found.add(key)
                display_by_key.setdefault(key, expression)
        document_terms.append(found)

    counts: Counter[str] = Counter(term for terms in document_terms for term in terms)
    ranked = sorted(
        ((display_by_key[key], count) for key, count in counts.items() if count >= 2),
        key=lambda item: (-item[1], item[0].casefold()),
    )[:max(1, min(limit, 5))]
    return ranked, len(documents)


def google_related_keywords(entries: list[dict], query: str, limit: int = 5,
                            candidates: list[str] | None = None) -> dict:
    """Extract repeated event expressions from Google Trends RSS title/description rows."""
    documents = [f"{item.get('title', '')} {item.get('description', '')}" for item in entries]
    ranked, document_count = _repeated_terms(documents, query, candidates, limit)
    return {
        "status": "observed" if ranked else "insufficient",
        "source": "google_trends",
        "query": " ".join(query.strip().split()),
        "document_count": document_count,
        "keywords": [
            {"text": text, "count": count, "status": "observed_google_rss_repetition"}
            for text, count in ranked
        ],
        "reason": None if ranked else "Google Trends RSS 제목·설명에서 2개 이상 문서에 반복된 관련 표현이 없음",
    }


def fetch_google_related_keywords(query: str, limit: int = 5,
                                  candidates: list[str] | None = None) -> dict:
    """Fetch the approved KR RSS surface and return aggregate repeated terms only."""
    clean_query = " ".join(query.strip().split())
    request = urllib.request.Request(
        "https://trends.google.com/trending/rss?geo=KR",
        headers={"User-Agent": "TRZIP/0.1 (+related keyword evidence)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            root = ET.fromstring(response.read())
        entries = [
            {
                "title": item.findtext("title", default=""),
                "description": item.findtext("description", default=""),
            }
            for item in root.findall(".//item")
        ]
        return google_related_keywords(entries, clean_query, limit, candidates)
    except Exception as exc:
        return {
            "status": "unavailable",
            "source": "google_trends",
            "query": clean_query,
            "document_count": 0,
            "keywords": [],
            "reason": f"Google Trends KR RSS 수집 실패: {type(exc).__name__}",
        }


def x_related_keywords(query: str, limit: int = 5, candidates: list[str] | None = None) -> dict:
    """Extract aggregate co-occurring expressions from recent X posts.

    Raw posts are not returned or persisted. This is supporting context only and
    never changes the trend rank.
    """
    load_local_env()
    token = os.environ.get("X_BEARER_TOKEN", "").strip()
    clean_query = " ".join(query.strip().split())
    if not token:
        return {"status": "unavailable", "query": clean_query, "keywords": [],
                "reason": "X_BEARER_TOKEN not configured"}
    if not clean_query:
        return {"status": "invalid", "query": clean_query, "keywords": [], "reason": "query required"}
    params = urllib.parse.urlencode({
        "query": f'"{clean_query}" -is:retweet',
        "max_results": "50",
        "tweet.fields": "entities,created_at,lang",
    })
    request = urllib.request.Request(
        "https://api.x.com/2/tweets/search/recent?" + params,
        headers={"Authorization": f"Bearer {token}", "User-Agent": "TRZIP/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
        posts = payload.get("data", [])
        ranked, post_count = _repeated_terms(
            [str(post.get("text", "")) for post in posts], clean_query, candidates, limit
        )
        return {
            "status": "observed" if ranked else "insufficient", "source": "x", "query": clean_query,
            "post_count": post_count,
            "keywords": [{"text": text, "count": count, "status": "observed_x_cooccurrence"}
                         for text, count in ranked],
            "reason": None if ranked else "X 최근 게시물에서 2개 이상 게시물에 반복된 관련 표현이 없음",
            "note": "aggregate co-occurrence only; raw posts are not returned and ranking is unchanged",
        }
    except Exception as exc:
        return {"status": "error", "source": "x", "query": clean_query, "keywords": [],
                "reason": f"{type(exc).__name__}: {exc}"}
