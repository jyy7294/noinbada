"""Persistent evidence-research queue for related terms and company ontology.

The queue does not create keywords or company links.  It records which live
X/Google trends still need evidence so deterministic ranking can remain
separate from slower research and team review.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


TASK_KINDS = {"related_keywords", "company_ontology"}
REQUIRED_EVIDENCE_COUNT = 5


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("enrichment queue timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def initialize_enrichment_queue(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS enrichment_tasks (
                event_key TEXT NOT NULL,
                task_kind TEXT NOT NULL CHECK(task_kind IN ('related_keywords','company_ontology')),
                representative_term TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                latest_rank INTEGER NOT NULL CHECK(latest_rank > 0),
                latest_lane TEXT NOT NULL,
                priority INTEGER NOT NULL,
                current_count INTEGER NOT NULL CHECK(current_count >= 0),
                required_count INTEGER NOT NULL CHECK(required_count > 0),
                missing_count INTEGER NOT NULL CHECK(missing_count >= 0),
                status TEXT NOT NULL CHECK(status IN ('pending','complete')),
                observed_terms_json TEXT NOT NULL,
                evidence_policy_json TEXT NOT NULL,
                affects_score INTEGER NOT NULL DEFAULT 0 CHECK(affects_score = 0),
                PRIMARY KEY(event_key, task_kind)
            );

            CREATE TABLE IF NOT EXISTS enrichment_task_observations (
                event_key TEXT NOT NULL,
                task_kind TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                rank INTEGER NOT NULL CHECK(rank > 0),
                current_count INTEGER NOT NULL CHECK(current_count >= 0),
                status TEXT NOT NULL CHECK(status IN ('pending','complete')),
                PRIMARY KEY(event_key, task_kind, observed_at),
                FOREIGN KEY(event_key, task_kind)
                    REFERENCES enrichment_tasks(event_key, task_kind)
            );
            """
        )


def _priority(item: dict, *, public_keys: set[str]) -> int:
    rank = int(item.get("rank") or 10**6)
    event_key = str(item.get("event_key") or "")
    lane = str(item.get("lane") or "review")
    base = 3000 if event_key in public_keys else 2000 if lane == "main" else 1000
    return max(0, base - rank)


def _task_rows(intelligence: dict, at: datetime) -> list[dict]:
    public_keys = {
        str(item.get("event_key") or "") for item in intelligence.get("public_top10", [])
    }
    stamp = _iso(at)
    rows: list[dict] = []
    for item in intelligence.get("unified_ranking", []):
        event_key = str(item.get("event_key") or "").strip()
        representative = str(item.get("display_name") or "").strip()
        if not event_key or not representative:
            continue
        observed_terms = sorted({
            representative,
            *[str(term).strip() for term in item.get("raw_terms", []) if str(term).strip()],
            *[
                str(keyword.get("text") or "").strip()
                for keyword in item.get("keywords", [])
                if str(keyword.get("text") or "").strip()
            ],
        })
        counts = {
            "related_keywords": len(item.get("keywords", [])),
            "company_ontology": int(
                (item.get("company_resolution") or {}).get("candidate_count") or 0
            ),
        }
        policies = {
            "related_keywords": {
                "accepted_evidence": [
                    "x_or_google_observed_expression",
                    "google_related_query",
                    "approved_ontology_term",
                    "reviewed_provider_expression",
                ],
                "invented_terms_forbidden": True,
            },
            "company_ontology": {
                "accepted_evidence": [
                    "company_official",
                    "regulatory_filing",
                    "reputable_news",
                    "reviewed_industry_structure",
                ],
                "unique_listed_stocks_required": True,
                "padding_forbidden": True,
            },
        }
        for task_kind in sorted(TASK_KINDS):
            current_count = min(REQUIRED_EVIDENCE_COUNT, counts[task_kind])
            missing_count = max(0, REQUIRED_EVIDENCE_COUNT - current_count)
            rows.append({
                "event_key": event_key,
                "task_kind": task_kind,
                "representative_term": representative,
                "first_seen_at": stamp,
                "last_seen_at": stamp,
                "latest_rank": int(item["rank"]),
                "latest_lane": str(item.get("lane") or "review"),
                "priority": _priority(item, public_keys=public_keys),
                "current_count": current_count,
                "required_count": REQUIRED_EVIDENCE_COUNT,
                "missing_count": missing_count,
                "status": "complete" if missing_count == 0 else "pending",
                "observed_terms": observed_terms,
                "evidence_policy": policies[task_kind],
            })
    return rows


def sync_enrichment_queue(
    intelligence: dict,
    *,
    path: Path,
    at: datetime,
    pending_limit: int = 100,
) -> dict:
    """Upsert the current live gaps and return a frontend-safe work summary."""

    initialize_enrichment_queue(path)
    rows = _task_rows(intelligence, at)
    stamp = _iso(at)
    with sqlite3.connect(path) as connection:
        for row in rows:
            connection.execute(
                """INSERT INTO enrichment_tasks
                   (event_key,task_kind,representative_term,first_seen_at,last_seen_at,
                    latest_rank,latest_lane,priority,current_count,required_count,
                    missing_count,status,observed_terms_json,evidence_policy_json,affects_score)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)
                   ON CONFLICT(event_key,task_kind) DO UPDATE SET
                     representative_term=excluded.representative_term,
                     last_seen_at=excluded.last_seen_at,
                     latest_rank=excluded.latest_rank,
                     latest_lane=excluded.latest_lane,
                     priority=excluded.priority,
                     current_count=excluded.current_count,
                     required_count=excluded.required_count,
                     missing_count=excluded.missing_count,
                     status=excluded.status,
                     observed_terms_json=excluded.observed_terms_json,
                     evidence_policy_json=excluded.evidence_policy_json""",
                (
                    row["event_key"], row["task_kind"], row["representative_term"],
                    row["first_seen_at"], row["last_seen_at"], row["latest_rank"],
                    row["latest_lane"], row["priority"], row["current_count"],
                    row["required_count"], row["missing_count"], row["status"],
                    json.dumps(row["observed_terms"], ensure_ascii=False, sort_keys=True),
                    json.dumps(row["evidence_policy"], ensure_ascii=False, sort_keys=True),
                ),
            )
            connection.execute(
                """INSERT INTO enrichment_task_observations
                   (event_key,task_kind,observed_at,rank,current_count,status)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(event_key,task_kind,observed_at) DO UPDATE SET
                     rank=excluded.rank,current_count=excluded.current_count,status=excluded.status""",
                (
                    row["event_key"], row["task_kind"], stamp, row["latest_rank"],
                    row["current_count"], row["status"],
                ),
            )
        connection.row_factory = sqlite3.Row
        summary_rows = connection.execute(
            """SELECT task_kind,status,COUNT(*) AS count
               FROM enrichment_tasks GROUP BY task_kind,status"""
        ).fetchall()
        pending_rows = connection.execute(
            """SELECT event_key,task_kind,representative_term,last_seen_at,latest_rank,
                      latest_lane,priority,current_count,required_count,missing_count,
                      observed_terms_json,evidence_policy_json
               FROM enrichment_tasks WHERE status='pending'
               ORDER BY priority DESC,last_seen_at DESC,event_key,task_kind LIMIT ?""",
            (max(0, pending_limit),),
        ).fetchall()
        total_observations = connection.execute(
            "SELECT COUNT(*) FROM enrichment_task_observations"
        ).fetchone()[0]

    counts = {
        task_kind: {"pending": 0, "complete": 0}
        for task_kind in sorted(TASK_KINDS)
    }
    for row in summary_rows:
        counts[str(row["task_kind"])][str(row["status"])] = int(row["count"])
    pending = []
    for row in pending_rows:
        item = dict(row)
        item["observed_terms"] = json.loads(item.pop("observed_terms_json"))
        item["evidence_policy"] = json.loads(item.pop("evidence_policy_json"))
        item["affects_score"] = False
        pending.append(item)
    return {
        "schema_version": "trzip-enrichment-queue-v1",
        "observed_at": stamp,
        "required_evidence_count": REQUIRED_EVIDENCE_COUNT,
        "counts": counts,
        "tracked_observations": int(total_observations),
        "pending_total": sum(item["pending"] for item in counts.values()),
        "pending_returned": len(pending),
        "pending": pending,
        "ranking_effect": "none",
    }
