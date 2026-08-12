from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from collections import Counter

from .hourly_store import load_local_env

TOKEN_RE = re.compile(r"#[0-9A-Za-z_가-힣]+|[A-Za-z][A-Za-z0-9_]{2,}|[가-힣]{2,}")
STOPWORDS = {
    "그리고", "그러나", "하지만", "오늘", "이번", "관련", "대한", "통해", "있는", "하는",
    "입니다", "합니다", "에서", "으로", "까지", "그냥", "진짜", "너무", "지금", "요즘",
    "가자", "https", "http", "the", "and", "for", "with", "this", "that", "from",
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
        counts: Counter[str] = Counter()
        candidate_counts: Counter[str] = Counter()
        query_tokens = {token.casefold().lstrip("#") for token in TOKEN_RE.findall(clean_query)}
        for post in payload.get("data", []):
            text = re.sub(r"https?://\S+|@[0-9A-Za-z_]+", " ", str(post.get("text", "")))
            folded_text = text.casefold()
            for candidate in candidates or []:
                if candidate.casefold() in folded_text and candidate.casefold() != clean_query.casefold():
                    candidate_counts[candidate] += 1
            for entity in post.get("entities", {}).get("hashtags", []):
                tag = str(entity.get("tag", "")).strip()
                if tag and tag.casefold() not in query_tokens:
                    counts["#" + tag] += 2
            for expression in TOKEN_RE.findall(text):
                normalized = expression.casefold().lstrip("#")
                if normalized in query_tokens or normalized in STOPWORDS or len(normalized) < 2:
                    continue
                counts[expression] += 1
        verified = sorted(candidate_counts.items(), key=lambda item: (-item[1], item[0].casefold()))
        fallback = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
        ranked = []
        seen = set()
        # When an event-specific vocabulary is available, only promote terms
        # from that vocabulary. Unrestricted co-occurrence often captures an
        # unrelated realtime hashtag that happened to share one post.
        source_rows = verified if candidates else fallback
        for text, count in source_rows:
            key = text.casefold().lstrip("#")
            if key in seen or count < 2:
                continue
            seen.add(key)
            ranked.append((text, count))
            if len(ranked) >= max(1, min(limit, 5)):
                break
        return {
            "status": "observed", "source": "x", "query": clean_query,
            "post_count": len(payload.get("data", [])),
            "keywords": [{"text": text, "count": count, "status": "observed_x_cooccurrence"}
                         for text, count in ranked],
            "note": "aggregate co-occurrence only; raw posts are not returned and ranking is unchanged",
        }
    except Exception as exc:
        return {"status": "error", "source": "x", "query": clean_query, "keywords": [],
                "reason": f"{type(exc).__name__}: {exc}"}
