"""Collect the official YouTube KR popular-video chart as a separate lane.

YouTube is useful for discovering content phenomena that bare search terms can
miss.  It deliberately does not mutate the canonical X + Google score.  The
chart is published with its own rank and provenance so product code can show or
join it without pretending that unlike measurements share one numeric scale.
"""

from __future__ import annotations

import html
import json
import os
import re
import sqlite3
import time
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .provider_verification import (
    JsonTransport,
    ProviderCredentials,
    PROVIDER_DOCUMENTATION,
    YOUTUBE_VIDEOS_ENDPOINT,
    UrllibJsonTransport,
    _request_json,
)


COLLECTOR_VERSION = "youtube-kr-most-popular-v1"
REGION = "KR"
MAX_RESULTS = 50
CATEGORY_CHART_IDS = ("1", "10", "20", "24")
CATEGORY_LABELS = {
    "1": "영화·애니메이션",
    "10": "음악",
    "20": "게임",
    "24": "엔터테인먼트",
    "25": "뉴스·정치",
}


def initialize_youtube_trending(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS youtube_trending_runs (
                observed_at TEXT PRIMARY KEY,
                status TEXT NOT NULL CHECK(status IN ('observed','unavailable','failed')),
                region TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                error_code TEXT,
                collector_version TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS youtube_trending_items (
                observed_at TEXT NOT NULL REFERENCES youtube_trending_runs(observed_at),
                chart_rank INTEGER NOT NULL,
                video_id TEXT NOT NULL,
                title TEXT NOT NULL,
                display_topic TEXT NOT NULL,
                channel_title TEXT,
                category_id TEXT,
                category_label TEXT NOT NULL,
                published_at TEXT,
                view_count INTEGER,
                like_count INTEGER,
                comment_count INTEGER,
                url TEXT NOT NULL,
                PRIMARY KEY (observed_at, chart_rank),
                UNIQUE (observed_at, video_id)
            );
            CREATE INDEX IF NOT EXISTS youtube_trending_items_video_history
              ON youtube_trending_items(video_id, observed_at);
            CREATE TABLE IF NOT EXISTS youtube_category_trending_runs (
                observed_at TEXT NOT NULL,
                category_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('observed','unavailable','failed')),
                row_count INTEGER NOT NULL,
                error_code TEXT,
                collector_version TEXT NOT NULL,
                PRIMARY KEY (observed_at, category_id)
            );
            CREATE TABLE IF NOT EXISTS youtube_category_trending_items (
                observed_at TEXT NOT NULL,
                category_id TEXT NOT NULL,
                chart_rank INTEGER NOT NULL,
                video_id TEXT NOT NULL,
                title TEXT NOT NULL,
                display_topic TEXT NOT NULL,
                channel_title TEXT,
                published_at TEXT,
                view_count INTEGER,
                like_count INTEGER,
                comment_count INTEGER,
                url TEXT NOT NULL,
                PRIMARY KEY (observed_at, category_id, chart_rank),
                UNIQUE (observed_at, category_id, video_id)
            );
            CREATE INDEX IF NOT EXISTS youtube_category_items_history
              ON youtube_category_trending_items(category_id, video_id, observed_at);
            """
        )


def _short_topic(title: str, category_id: str, channel_title: str) -> str:
    clean = html.unescape(str(title or "")).strip()
    # Official trailers often provide a stable work title before the separator.
    if category_id == "1" or "trailer" in clean.casefold() or "예고편" in clean:
        if re.search(r"\bthe\s+odyssey\b", clean, flags=re.IGNORECASE):
            return "오디세이"
        clean = re.split(r"\s*[|｜]\s*|\s+-\s+(?=Official|공식)", clean, maxsplit=1)[0]
    if category_id == "10":
        quoted = re.search(
            r"['\"‘“]([^'\"’”]{2,60})['\"’”]\s*(?:M/?V|뮤직비디오)",
            clean,
            flags=re.IGNORECASE,
        )
        if quoted:
            clean = quoted.group(1)
        elif " - " in clean:
            clean = clean.split(" - ", 1)[1]
    clean = re.sub(
        r"\s*[\[(](?:official\s*)?(?:m/?v|video|trailer|teaser|audio|예고편|티저|뮤직비디오)[^\])]*[\])]\s*",
        " ",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"\s+", " ", clean).strip(" -_|｜")
    if len(clean) > 60:
        clean = clean[:57].rstrip() + "…"
    return clean or channel_title or "제목 미확인"


def _event_key(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", str(value or "").casefold())


def _aggregate_trends(video_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in video_rows:
        key = _event_key(row["display_topic"]) or f"video:{row['video_id']}"
        groups.setdefault(key, []).append(row)
    output = []
    for key, rows in groups.items():
        rows.sort(key=lambda row: (int(row["youtube_rank"]), str(row["video_id"])))
        representative = rows[0]
        best_rank = int(representative["youtube_rank"])
        output.append({
            "event_key": f"youtube:{key}",
            "display_topic": representative["display_topic"],
            "youtube_score": round(100.0 * (MAX_RESULTS + 1 - best_rank) / MAX_RESULTS, 2),
            "best_video_rank": best_rank,
            "supporting_video_count": len(rows),
            "category": representative["category"],
            "source_evidence": [
                {
                    "video_rank": row["youtube_rank"],
                    "video_id": row["video_id"],
                    "title": row["video_title"],
                    "channel_title": row["channel_title"],
                    "url": row["url"],
                    "view_count": row["view_count"],
                }
                for row in rows
            ],
            "ranking_source": "youtube_videos_most_popular_kr",
            "ranking_method": "best_video_chart_rank_then_event_key",
            "affects_x_google_rank": False,
        })
    output.sort(key=lambda row: (int(row["best_video_rank"]), str(row["event_key"])))
    for rank, row in enumerate(output, start=1):
        row["youtube_trend_rank"] = rank
    return output


def _integer(value: Any) -> int | None:
    return int(value) if str(value or "").isdigit() else None


def _read_hour(path: Path, observed_at: str) -> list[dict[str, Any]]:
    initialize_youtube_trending(path)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """SELECT * FROM youtube_trending_items
               WHERE observed_at=? ORDER BY chart_rank""",
            (observed_at,),
        ).fetchall()
    return [dict(row) for row in rows]


def _previous_ranks(path: Path, observed_at: str) -> dict[str, int]:
    with sqlite3.connect(path) as connection:
        previous = connection.execute(
            """SELECT MAX(observed_at) FROM youtube_trending_runs
               WHERE status='observed' AND observed_at < ?""",
            (observed_at,),
        ).fetchone()[0]
        if not previous:
            return {}
        return {
            str(video_id): int(rank)
            for video_id, rank in connection.execute(
                """SELECT video_id, chart_rank FROM youtube_trending_items
                   WHERE observed_at=?""",
                (previous,),
            )
        }


def _previous_trend_ranks(path: Path, observed_at: str) -> dict[str, int]:
    with sqlite3.connect(path) as connection:
        previous = connection.execute(
            """SELECT MAX(observed_at) FROM youtube_trending_runs
               WHERE status='observed' AND observed_at < ?""",
            (observed_at,),
        ).fetchone()[0]
    if not previous:
        return {}
    prior_rows = []
    for item in _read_hour(path, str(previous)):
        prior_rows.append({
            "youtube_rank": int(item["chart_rank"]),
            "display_topic": item["display_topic"],
            "video_title": item["title"],
            "video_id": item["video_id"],
            "channel_title": item["channel_title"],
            "category": item["category_label"],
            "published_at": item["published_at"],
            "view_count": item["view_count"],
            "like_count": item["like_count"],
            "comment_count": item["comment_count"],
            "url": item["url"],
        })
    return {
        str(row["event_key"]): int(row["youtube_trend_rank"])
        for row in _aggregate_trends(prior_rows)
    }


def _read_category_charts(path: Path, observed_at: str) -> list[dict[str, Any]]:
    initialize_youtube_trending(path)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        runs = connection.execute(
            """SELECT * FROM youtube_category_trending_runs
               WHERE observed_at=? ORDER BY category_id""",
            (observed_at,),
        ).fetchall()
        output = []
        for run in runs:
            items = connection.execute(
                """SELECT * FROM youtube_category_trending_items
                   WHERE observed_at=? AND category_id=? ORDER BY chart_rank""",
                (observed_at, run["category_id"]),
            ).fetchall()
            output.append({
                "category_id": run["category_id"],
                "category_label": CATEGORY_LABELS.get(run["category_id"], "기타 콘텐츠"),
                "status": run["status"],
                "row_count": int(run["row_count"]),
                "error_code": run["error_code"],
                "ranking": [
                    {
                        "youtube_category_rank": int(item["chart_rank"]),
                        "display_topic": item["display_topic"],
                        "video_title": item["title"],
                        "video_id": item["video_id"],
                        "channel_title": item["channel_title"],
                        "published_at": item["published_at"],
                        "view_count": item["view_count"],
                        "like_count": item["like_count"],
                        "comment_count": item["comment_count"],
                        "url": item["url"],
                        "ranking_source": "youtube_videos_most_popular_kr_category",
                        "affects_x_google_rank": False,
                    }
                    for item in items
                ],
            })
    return output


def _public_result(
    path: Path,
    *,
    observed_at: str,
    status: str,
    error_code: str | None,
) -> dict[str, Any]:
    previous = _previous_ranks(path, observed_at) if status == "observed" else {}
    video_ranking = []
    for item in _read_hour(path, observed_at):
        prior = previous.get(str(item["video_id"]))
        video_ranking.append({
            "youtube_rank": int(item["chart_rank"]),
            "display_topic": item["display_topic"],
            "video_title": item["title"],
            "video_id": item["video_id"],
            "channel_title": item["channel_title"],
            "category": item["category_label"],
            "published_at": item["published_at"],
            "view_count": item["view_count"],
            "like_count": item["like_count"],
            "comment_count": item["comment_count"],
            "url": item["url"],
            "previous_youtube_rank": prior,
            "youtube_rank_change": (prior - int(item["chart_rank"])) if prior else None,
            "rank_change_status": "measured" if prior else "unavailable",
            "ranking_source": "youtube_videos_most_popular_kr",
            "affects_x_google_rank": False,
        })
    ranking = _aggregate_trends(video_ranking)
    previous_trends = _previous_trend_ranks(path, observed_at) if status == "observed" else {}
    for row in ranking:
        prior = previous_trends.get(str(row["event_key"]))
        row["previous_youtube_trend_rank"] = prior
        row["youtube_trend_rank_change"] = (
            prior - int(row["youtube_trend_rank"]) if prior is not None else None
        )
        row["rank_change_status"] = "measured" if prior is not None else "unavailable"
    return {
        "schema_version": "trzip-youtube-content-ranking-v1",
        "observed_at": observed_at,
        "status": status,
        "region": REGION,
        "chart": "mostPopular",
        "row_count": len(video_ranking),
        "trend_count": len(ranking),
        "error_code": error_code,
        "ranking": ranking,
        "top10": ranking[:10],
        "video_chart": video_ranking,
        "category_charts": _read_category_charts(path, observed_at),
        "ranking_effect": "separate_content_lane",
        "affects_x_google_rank": False,
        "documentation": PROVIDER_DOCUMENTATION["youtube_videos"],
        "limitations": "YouTube mostPopular is a regional video chart, not a complete Korean culture-trend census.",
    }


def _collect_category_charts(
    path: Path,
    *,
    observed_at: str,
    credentials: ProviderCredentials,
    transport: JsonTransport,
) -> None:
    """Persist official KR category charts without blending their ranks."""

    for category_id in CATEGORY_CHART_IDS:
        with sqlite3.connect(path) as connection:
            existing = connection.execute(
                """SELECT 1 FROM youtube_category_trending_runs
                   WHERE observed_at=? AND category_id=?""",
                (observed_at, category_id),
            ).fetchone()
        if existing:
            continue
        params = {
            "part": "snippet,statistics,contentDetails",
            "chart": "mostPopular",
            "regionCode": REGION,
            "videoCategoryId": category_id,
            "maxResults": MAX_RESULTS,
            "key": credentials.youtube_api_key,
        }
        payload, _, error_code, _ = _request_json(
            endpoint=YOUTUBE_VIDEOS_ENDPOINT,
            url=f"{YOUTUBE_VIDEOS_ENDPOINT}?{urllib.parse.urlencode(params)}",
            headers={"Accept": "application/json", "User-Agent": "TRZIP/1.0 youtube-category-trending"},
            transport=transport,
            secrets=(credentials.youtube_api_key,),
            quota_bucket=f"youtube_most_popular_category_{category_id}",
            quota_cost=1,
            max_attempts=2,
            timeout=15,
            sleeper=time.sleep,
        )
        raw_items = [item for item in (payload or {}).get("items", []) if isinstance(item, dict)]
        status = "observed" if raw_items else "failed"
        safe_error = None if raw_items else (error_code or "empty_category_chart")
        records = []
        seen: set[str] = set()
        for item in raw_items:
            video_id = str(item.get("id") or "").strip()
            snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
            title = html.unescape(str(snippet.get("title") or "")).strip()
            if not video_id or not title or video_id in seen:
                continue
            seen.add(video_id)
            statistics = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}
            channel = html.unescape(str(snippet.get("channelTitle") or "")).strip()
            records.append((
                observed_at, category_id, len(records) + 1, video_id, title,
                _short_topic(title, category_id, channel), channel or None,
                str(snippet.get("publishedAt") or "") or None,
                _integer(statistics.get("viewCount")), _integer(statistics.get("likeCount")),
                _integer(statistics.get("commentCount")), f"https://www.youtube.com/watch?v={video_id}",
            ))
        if status == "observed" and not records:
            status, safe_error = "failed", "invalid_category_chart_items"
        with sqlite3.connect(path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO youtube_category_trending_runs
                   VALUES (?,?,?,?,?,?)""",
                (observed_at, category_id, status, len(records), safe_error, COLLECTOR_VERSION),
            )
            connection.executemany(
                """INSERT INTO youtube_category_trending_items
                   (observed_at,category_id,chart_rank,video_id,title,display_topic,
                    channel_title,published_at,view_count,like_count,comment_count,url)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                records,
            )


def collect_youtube_trending(
    *,
    path: Path,
    at: datetime,
    credentials: ProviderCredentials,
    transport: JsonTransport | None = None,
) -> dict[str, Any]:
    """Collect once per observation hour and return the persisted public lane."""

    initialize_youtube_trending(path)
    observed_at = at.astimezone(UTC).replace(minute=0, second=0, microsecond=0).isoformat()
    with sqlite3.connect(path) as connection:
        existing = connection.execute(
            "SELECT status,error_code FROM youtube_trending_runs WHERE observed_at=?",
            (observed_at,),
        ).fetchone()
    if existing:
        if (
            existing[0] == "observed"
            and os.environ.get("TRZIP_DISABLE_EXTERNAL_YOUTUBE_TRENDING") != "1"
            and credentials.youtube_api_key
        ):
            _collect_category_charts(
                path,
                observed_at=observed_at,
                credentials=credentials,
                transport=transport or UrllibJsonTransport(),
            )
        return _public_result(path, observed_at=observed_at, status=existing[0], error_code=existing[1])

    disabled = os.environ.get("TRZIP_DISABLE_EXTERNAL_YOUTUBE_TRENDING") == "1"
    if disabled or not credentials.youtube_api_key:
        reason = "disabled_for_test" if disabled else "api_key_not_configured"
        with sqlite3.connect(path) as connection:
            connection.execute(
                "INSERT INTO youtube_trending_runs VALUES (?,?,?,?,?,?)",
                (observed_at, "unavailable", REGION, 0, reason, COLLECTOR_VERSION),
            )
        return _public_result(path, observed_at=observed_at, status="unavailable", error_code=reason)

    params = {
        "part": "snippet,statistics,contentDetails",
        "chart": "mostPopular",
        "regionCode": REGION,
        "maxResults": MAX_RESULTS,
        "key": credentials.youtube_api_key,
    }
    payload, _, error_code, _ = _request_json(
        endpoint=YOUTUBE_VIDEOS_ENDPOINT,
        url=f"{YOUTUBE_VIDEOS_ENDPOINT}?{urllib.parse.urlencode(params)}",
        headers={"Accept": "application/json", "User-Agent": "TRZIP/1.0 youtube-trending"},
        transport=transport or UrllibJsonTransport(),
        secrets=(credentials.youtube_api_key,),
        quota_bucket="youtube_most_popular",
        quota_cost=1,
        max_attempts=2,
        timeout=15,
        sleeper=time.sleep,
    )
    raw_items = [item for item in (payload or {}).get("items", []) if isinstance(item, dict)]
    status = "observed" if raw_items else "failed"
    safe_error = None if raw_items else (error_code or "empty_chart")
    records: list[tuple[Any, ...]] = []
    seen: set[str] = set()
    for rank, item in enumerate(raw_items, start=1):
        video_id = str(item.get("id") or "").strip()
        snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
        title = html.unescape(str(snippet.get("title") or "")).strip()
        if not video_id or not title or video_id in seen:
            continue
        seen.add(video_id)
        channel = html.unescape(str(snippet.get("channelTitle") or "")).strip()
        category_id = str(snippet.get("categoryId") or "")
        statistics = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}
        records.append((
            observed_at, len(records) + 1, video_id, title,
            _short_topic(title, category_id, channel), channel or None, category_id or None,
            CATEGORY_LABELS.get(category_id, "기타 콘텐츠"),
            str(snippet.get("publishedAt") or "") or None,
            _integer(statistics.get("viewCount")), _integer(statistics.get("likeCount")),
            _integer(statistics.get("commentCount")), f"https://www.youtube.com/watch?v={video_id}",
        ))
    if status == "observed" and not records:
        status, safe_error = "failed", "invalid_chart_items"
    with sqlite3.connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO youtube_trending_runs VALUES (?,?,?,?,?,?)",
            (observed_at, status, REGION, len(records), safe_error, COLLECTOR_VERSION),
        )
        connection.executemany(
            """INSERT INTO youtube_trending_items
               (observed_at,chart_rank,video_id,title,display_topic,channel_title,
                category_id,category_label,published_at,view_count,like_count,
                comment_count,url) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            records,
        )
    if status == "observed":
        _collect_category_charts(
            path,
            observed_at=observed_at,
            credentials=credentials,
            transport=transport or UrllibJsonTransport(),
        )
    return _public_result(path, observed_at=observed_at, status=status, error_code=safe_error)
