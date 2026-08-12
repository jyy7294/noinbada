"""Evidence-backed provider document candidates for human keyword review.

The extraction rules are adapted from teammate branch ``jiyu`` commit
``5e3031c``.  Production integration deliberately stops at a review queue:
provider titles are observed evidence, but they are not X/Google ranking input
and must never become public related keywords without approval.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .provider_verification import initialize_verification_ledger


BEHAVIOR_WORDS = (
    "레시피", "만들기", "챌린지", "안무", "품절", "구매처", "오픈런",
    "맛집", "후기", "먹방", "직캠", "리뷰", "언박싱",
)
GENERIC_CANDIDATES = {
    "shorts", "short", "쇼츠", "youtube", "유튜브", "official", "공식",
}


def normalize_expression(value: str) -> str:
    value = str(value).strip().lstrip("#")
    return re.sub(r"\s+", "", value).casefold()


def clean_document_text(text: str) -> str:
    text = re.sub(r"https?://\S+|www\.\S+|\S+@\S+", " ", str(text))
    text = re.sub(r"@[A-Za-z0-9_가-힣]+", " ", text)
    return re.sub(r"[^0-9A-Za-z가-힣#\s]", " ", text)


def extract_review_candidates(text: str, aliases: list[str]) -> list[str]:
    """Extract only explicit hashtags and alias-plus-behaviour expressions."""

    cleaned = clean_document_text(text)
    found = re.findall(r"#([A-Za-z가-힣0-9]{2,})", cleaned)
    action_pattern = "|".join(map(re.escape, BEHAVIOR_WORDS))
    for alias in sorted({alias.strip() for alias in aliases if alias.strip()}, key=len, reverse=True):
        if alias.casefold() not in cleaned.casefold():
            continue
        alias_pattern = re.escape(alias).replace(r"\ ", r"\s+")
        found.extend(re.findall(
            rf"({alias_pattern}(?:\s+[A-Za-z가-힣0-9]+){{0,2}}?\s+(?:{action_pattern}))"
            rf"(?:[은는이가을를의와과도만]{{0,2}})?",
            cleaned,
            flags=re.IGNORECASE,
        ))

    alias_keys = {normalize_expression(alias) for alias in aliases}
    selected: list[str] = []
    seen: set[str] = set()
    for value in found:
        display = " ".join(str(value).lstrip("#").split())
        key = normalize_expression(display)
        if len(key) < 2 or key in alias_keys or key in GENERIC_CANDIDATES or key in seen:
            continue
        selected.append(display)
        seen.add(key)
    return selected


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("keyword candidate timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def initialize_keyword_candidate_queue(path: Path) -> None:
    initialize_verification_ledger(path)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS keyword_candidate_tasks (
                event_key TEXT NOT NULL,
                candidate_key TEXT NOT NULL,
                display_text TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                provider_count INTEGER NOT NULL DEFAULT 0,
                evidence_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'evidence_building'
                    CHECK(status IN ('evidence_building','review_required','approved','rejected')),
                ranking_effect TEXT NOT NULL DEFAULT 'none' CHECK(ranking_effect='none'),
                PRIMARY KEY(event_key,candidate_key)
            );
            CREATE TABLE IF NOT EXISTS keyword_candidate_evidence (
                event_key TEXT NOT NULL,
                candidate_key TEXT NOT NULL,
                provider TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                published_at TEXT,
                observed_at TEXT NOT NULL,
                PRIMARY KEY(event_key,candidate_key,url),
                FOREIGN KEY(event_key,candidate_key)
                    REFERENCES keyword_candidate_tasks(event_key,candidate_key)
            );
            """
        )


def sync_provider_keyword_candidates(
    intelligence: dict,
    *,
    path: Path,
    at: datetime,
    pending_limit: int = 100,
) -> dict:
    """Persist title-derived candidates without publishing or scoring them."""

    initialize_keyword_candidate_queue(path)
    stamp = _iso(at)
    trend_by_key = {
        str(item.get("event_key") or ""): item
        for item in intelligence.get("unified_ranking", [])
        if str(item.get("event_key") or "")
    }
    rank_by_key = {
        key: int(item.get("rank") or 10**6) for key, item in trend_by_key.items()
    }
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        event_keys = sorted(trend_by_key)
        documents = [] if not event_keys else connection.execute(
            f"""SELECT r.trend_key,r.provider,r.observed_at,e.title,e.url,e.published_at
                FROM provider_verification_runs r
                JOIN provider_evidence_items e ON e.run_id=r.id
                WHERE r.status='observed'
                  AND r.trend_key IN ({','.join('?' for _ in event_keys)})
                ORDER BY r.id,e.item_order""",
            event_keys,
        ).fetchall()
        for document in documents:
            event_key = str(document["trend_key"])
            item = trend_by_key.get(event_key)
            if item is None:
                continue
            aliases = list(dict.fromkeys([
                str(item.get("display_name") or ""),
                *[str(term) for term in item.get("raw_terms", [])],
                *[str(keyword.get("text") or "") for keyword in item.get("keywords", [])],
            ]))
            title = str(document["title"])
            title_key = normalize_expression(title)
            if not any(
                normalize_expression(alias) in title_key
                for alias in aliases
                if normalize_expression(alias)
            ):
                continue
            for candidate in extract_review_candidates(title, aliases):
                candidate_key = normalize_expression(candidate)
                evidence_seen_at = str(document["observed_at"])
                connection.execute(
                    """INSERT INTO keyword_candidate_tasks
                       (event_key,candidate_key,display_text,first_seen_at,last_seen_at)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(event_key,candidate_key) DO UPDATE SET
                         display_text=excluded.display_text,
                         last_seen_at=CASE
                           WHEN excluded.last_seen_at > last_seen_at THEN excluded.last_seen_at
                           ELSE last_seen_at END""",
                    (event_key, candidate_key, candidate, evidence_seen_at, evidence_seen_at),
                )
                connection.execute(
                    """INSERT OR IGNORE INTO keyword_candidate_evidence
                       (event_key,candidate_key,provider,title,url,published_at,observed_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (
                        event_key, candidate_key, str(document["provider"]),
                        str(document["title"]), str(document["url"]),
                        document["published_at"], str(document["observed_at"]),
                    ),
                )
        connection.execute(
            """UPDATE keyword_candidate_tasks
               SET evidence_count=(
                     SELECT COUNT(*) FROM keyword_candidate_evidence e
                     WHERE e.event_key=keyword_candidate_tasks.event_key
                       AND e.candidate_key=keyword_candidate_tasks.candidate_key
                   ),
                   provider_count=(
                     SELECT COUNT(DISTINCT provider) FROM keyword_candidate_evidence e
                     WHERE e.event_key=keyword_candidate_tasks.event_key
                       AND e.candidate_key=keyword_candidate_tasks.candidate_key
                   ),
                   status=CASE
                     WHEN status IN ('approved','rejected') THEN status
                     WHEN (SELECT COUNT(*) FROM keyword_candidate_evidence e
                           WHERE e.event_key=keyword_candidate_tasks.event_key
                             AND e.candidate_key=keyword_candidate_tasks.candidate_key) >= 2
                     THEN 'review_required'
                     ELSE 'evidence_building' END"""
        )
        task_rows = connection.execute(
            """SELECT event_key,candidate_key,display_text,first_seen_at,last_seen_at,
                      provider_count,evidence_count,status
               FROM keyword_candidate_tasks WHERE status='review_required'"""
        ).fetchall()
        building_total = int(connection.execute(
            "SELECT COUNT(*) FROM keyword_candidate_tasks WHERE status='evidence_building'"
        ).fetchone()[0])
        evidence_rows = connection.execute(
            """SELECT event_key,candidate_key,provider,title,url,published_at,observed_at
               FROM keyword_candidate_evidence ORDER BY observed_at,url"""
        ).fetchall()

    evidence_by_key: dict[tuple[str, str], list[dict]] = {}
    for row in evidence_rows:
        payload = dict(row)
        evidence_by_key.setdefault(
            (str(payload.pop("event_key")), str(payload.pop("candidate_key"))), []
        ).append(payload)
    pending = []
    for row in sorted(
        (dict(value) for value in task_rows),
        key=lambda value: (
            rank_by_key.get(str(value["event_key"]), 10**6),
            -int(value["provider_count"]),
            -int(value["evidence_count"]),
            str(value["candidate_key"]),
        ),
    )[: max(0, pending_limit)]:
        key = (str(row["event_key"]), str(row["candidate_key"]))
        row["latest_rank"] = rank_by_key.get(key[0])
        row["evidence"] = evidence_by_key.get(key, [])
        row["publishable"] = False
        row["affects_score"] = False
        pending.append(row)
    return {
        "schema_version": "trzip-provider-keyword-candidates-v1",
        "observed_at": stamp,
        "pending_total": len(task_rows),
        "building_total": building_total,
        "pending_returned": len(pending),
        "pending": pending,
        "approval_policy": "human_or_reviewed_ontology_required_before_publication",
        "ranking_effect": "none",
        "source_commit": "jiyu/5e3031c-adapted",
    }
