from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
from urllib.parse import urlencode

from defusedxml import ElementTree

from .core import event_id, now_iso
from .net import fetch

GOOGLE_PAGE = "https://trends.google.com/trending?geo=KR&hl=ko"
GOOGLE_RSS = "https://trends.google.com/trending/rss?geo=KR"
NS = {"ht": "https://trends.google.com/trending/rss"}


def google_rss(xml: bytes | None = None) -> tuple[list[dict], dict]:
    document = ElementTree.fromstring(xml if xml is not None else fetch(GOOGLE_RSS).body)
    rows = []
    for item in document.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        articles = []
        for news in item.findall("ht:news_item", NS):
            url = news.findtext("ht:news_item_url", namespaces=NS) or ""
            if url.startswith("https://"):
                articles.append({"title": news.findtext("ht:news_item_title", namespaces=NS) or "",
                                 "url": url, "publisher": news.findtext("ht:news_item_source", namespaces=NS) or ""})
        date = item.findtext("pubDate")
        try:
            source_at = parsedate_to_datetime(date).astimezone(UTC).isoformat() if date else None
        except (ValueError, TypeError):
            source_at = None
        rows.append({"event_id": event_id(title), "title": title, "position": len(rows) + 1,
                     "source_url": GOOGLE_PAGE, "source_created_at": source_at,
                     "volume_text": item.findtext("ht:approx_traffic", namespaces=NS),
                     "related_terms": [], "articles": articles, "rank_basis": "rss_feed_position"})
    if not rows or len({r["event_id"] for r in rows}) != len(rows):
        raise ValueError("empty or duplicate RSS feed")
    return rows, {"sampling_frame": "google_kr_rss_limited_v1", "coverage": "limited",
                  "scope_label": "Google 한국 RSS 공개 목록", "population_total": None,
                  "rank_basis": "피드 노출 순서", "source_url": GOOGLE_RSS}


def google_page(root: Path) -> tuple[list[dict], dict]:
    from trzip.google_web_collector import collect_google_page
    records, receipt = collect_google_page(profile_dir=root / "google-profile", minimum_rows=1,
                                           browser_channel=os.environ.get("TRZIP_BROWSER_CHANNEL") or None,
                                           timeout_ms=35_000)
    rows = [{"event_id": event_id(r.topic), "title": r.topic, "position": r.rank,
             "source_url": GOOGLE_PAGE, "source_created_at": None,
             "volume_text": r.volume_text, "growth_text": r.growth_text,
             "related_terms": list(r.related_terms), "articles": [],
             "rank_basis": "google_page_relevance_order"} for r in records]
    return rows, {"sampling_frame": "google_kr_page_relevance_v1", "coverage": "complete",
                  "scope_label": "Google 한국 급상승 공개 목록", "population_total": receipt["declared_total"],
                  "rank_basis": "Google 공개 목록 순서", "source_url": GOOGLE_PAGE}


def collect_google(root: Path) -> tuple[list[dict], dict]:
    reason = None
    if os.environ.get("TRZIP_GOOGLE_PAGE_ENABLED", "true").lower() == "true":
        try:
            rows, receipt = google_page(root)
            # RSS supplies linked news context only, never additional rank inputs.
            try:
                rss, _ = google_rss()
                by_id = {r["event_id"]: r for r in rss}
                for row in rows:
                    row["articles"] = by_id.get(row["event_id"], {}).get("articles", [])
            except Exception:
                pass
            return rows, receipt
        except Exception as exc:
            reason = getattr(exc, "code", type(exc).__name__)
    rows, receipt = google_rss()
    receipt["fallback_reason"] = reason or "page_collector_disabled"
    return rows, receipt


def youtube() -> tuple[list[dict], dict]:
    token = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not token:
        raise ValueError("credential_missing")
    url = "https://www.googleapis.com/youtube/v3/videos?" + urlencode({
        "part": "snippet,statistics", "chart": "mostPopular", "regionCode": "KR", "maxResults": 50, "key": token})
    payload = json.loads(fetch(url).body)
    rows = []
    for position, item in enumerate(payload.get("items", []), 1):
        snippet = item["snippet"]
        title = snippet["title"]
        # Videos remain their own observed objects; no title-based semantic invention.
        rows.append({"event_id": "yt_" + item["id"], "title": title, "position": position,
                     "source_url": "https://www.youtube.com/watch?v=" + item["id"],
                     "source_created_at": snippet.get("publishedAt"), "related_terms": [], "articles": [],
                     "rank_basis": "youtube_kr_most_popular", "category_hint": "콘텐츠",
                     "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url")})
    if not rows:
        raise ValueError("empty YouTube chart")
    return rows, {"sampling_frame": "youtube_kr_most_popular_50_v1", "coverage": "limited",
                  "scope_label": "YouTube 한국 인기 동영상 50개", "population_total": None,
                  "quota_units": 1, "source_url": "https://www.youtube.com/feed/trending"}
