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
REQUIRED_COUNTS = {
    "related_keywords": 5,
    "company_ontology": 6,
}
LLM_CANDIDATE_TARGETS = {
    "related_keywords": 15,
    "company_ontology": 18,
}
ONTOLOGY_EXPANSION_PATHS = (
    "trend -> user_activity -> equipment_or_service -> listed_company",
    "trend -> venue_or_event -> sponsor_or_operator -> listed_company",
    "trend -> content_or_product -> producer_or_distributor -> listed_company",
    "trend -> technology -> component_or_infrastructure -> listed_company",
    "trend -> consumption_context -> measurable_demand_exposure -> listed_company",
)


def _llm_research_prompt(row: dict) -> str:
    """Return a provider-neutral prompt for proposal generation only.

    The LLM may expand a plausible ontology creatively, but cannot publish a
    keyword/company or influence ranking.  A deterministic evidence/review gate
    promotes only fully sourced listed-company relations to the Gold contract.
    """

    representative = row["representative_term"]
    observed = ", ".join(row["observed_terms"][:20])
    if row["task_kind"] == "related_keywords":
        return (
            f"트렌드 '{representative}'의 관측 표현({observed})을 바탕으로 관련 검색어 후보를 "
            "최대 15개 제안하라. 동시 등장 표현, 사용 장면, 제품·행사·작품·기술 맥락을 우선하고 "
            "단순 동의어 반복과 투자 종목명 끼워 넣기는 금지한다. 각 후보에 관계 유형과 근거 URL을 붙여라."
        )
    return (
        f"트렌드 '{representative}'의 관측 표현({observed})에서 시작해 상장기업 후보를 최대 18개 제안하라. "
        "트렌드→사용 장면→장비·서비스→산업→기업처럼 3~5단계 관계 경로를 창의적으로 탐색하되, "
        "직접 관계·가치사슬·산업 관찰을 구분하라. 기업명, 종목코드, 거래소, 기업 설명, 연결 이유, "
        "경로의 각 핵심 간선을 입증하는 공식·공시·신뢰 가능한 근거 URL을 제공하라. "
        "관련성이 약한 기업으로 숫자를 채우거나 순위·점수 변경을 제안하지 마라."
    )


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
    # Once the public arrays are fail-closed, incomplete high-ranked candidates
    # are intentionally absent from them.  Prioritise the first ten eligible
    # score-ordered candidates instead so research closes the most visible gaps
    # first without changing rank.
    public_keys = {
        str(item.get("event_key") or "")
        for item in intelligence.get("unified_ranking", [])
        if item.get("lane") == "main" and item.get("home_eligible") is True
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
                item.get("frontend_company_count")
                if item.get("frontend_company_count") is not None
                else (item.get("company_resolution") or {}).get("candidate_count") or 0
            ),
        }
        policies = {
            "related_keywords": {
                "accepted_evidence": [
                    "x_or_google_observed_expression",
                    "google_related_query",
                    "approved_ontology_term",
                    "approved_ontology_related_term",
                    "reviewed_provider_expression",
                ],
                "invented_terms_forbidden": True,
                "llm_role": "candidate_generation_only",
                "llm_candidate_target": LLM_CANDIDATE_TARGETS["related_keywords"],
                "promotion_gate": "exactly_5_reviewed_evidence_terms",
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
                "llm_role": "creative_graph_expansion_only",
                "llm_candidate_target": LLM_CANDIDATE_TARGETS["company_ontology"],
                "creative_path_templates": list(ONTOLOGY_EXPANSION_PATHS),
                "allowed_relation_tiers": ["direct", "value_chain", "industry_watch"],
                "promotion_gate": "minimum_6_complete_evidence_verified_listed_companies",
            },
        }
        for task_kind in sorted(TASK_KINDS):
            required_count = REQUIRED_COUNTS[task_kind]
            current_count = min(required_count, counts[task_kind])
            missing_count = max(0, required_count - current_count)
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
                "required_count": required_count,
                "missing_count": missing_count,
                "status": "complete" if missing_count == 0 else "pending",
                "observed_terms": observed_terms,
                "evidence_policy": policies[task_kind],
            })
            rows[-1]["llm_research_prompt"] = _llm_research_prompt(rows[-1])
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
        item["llm_research_prompt"] = _llm_research_prompt({
            **item,
            "observed_terms": item["observed_terms"],
        })
        item["affects_score"] = False
        pending.append(item)
    return {
        "schema_version": "trzip-enrichment-queue-v1",
        "observed_at": stamp,
        "required_evidence_count": dict(REQUIRED_COUNTS),
        "counts": counts,
        "tracked_observations": int(total_observations),
        "pending_total": sum(item["pending"] for item in counts.values()),
        "pending_returned": len(pending),
        "pending": pending,
        "llm_research_contract": {
            "mode": "proposal_then_deterministic_review",
            "candidate_targets": dict(LLM_CANDIDATE_TARGETS),
            "ontology_expansion_paths": list(ONTOLOGY_EXPANSION_PATHS),
            "required_company_fields": [
                "company", "ticker", "market", "company_description",
                "relationship_reason", "relation_tier", "ontology_path",
                "evidence_urls", "company_role_category", "company_role_label",
            ],
            "allowed_relation_tiers": ["direct", "value_chain", "industry_watch"],
            "allowed_company_role_categories": [
                "manufacturing_development", "raw_materials_components",
                "content_production", "distribution", "retail_sales",
                "brand_marketing", "platform_service", "ownership_investment",
                "event_sponsorship", "industry_adjacent",
            ],
            "llm_can_change_ranking": False,
            "unverified_candidates_public": False,
        },
        "ranking_effect": "none",
    }
