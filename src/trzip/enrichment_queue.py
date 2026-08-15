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

from .keyword_policy import keyword_fits_public_label


TASK_KINDS = {"trend_context", "related_keywords", "company_ontology"}
REQUIRED_COUNTS = {
    "trend_context": 1,
    "related_keywords": 5,
    "company_ontology": 10,
}
LLM_CANDIDATE_TARGETS = {
    "trend_context": 8,
    "related_keywords": 15,
    "company_ontology": 30,
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
    common = (
        "X·Google 관측 순위와 점수는 변경하지 마라. "
        "NAVER 뉴스 또는 공식 발표 URL만 공개 근거로 사용하고, "
        "YouTube·Instagram·NAVER 블로그·카페·검색트렌드·네이트는 사용하지 마라. "
    )
    if row["task_kind"] == "trend_context":
        return (
            f"트렌드 '{representative}'의 관측 표현({observed})이 왜 지금 화제인지 조사하라. "
            + common
            + "촉발 제목, 2문장 이내의 why_now, 발행시각, 언론사, 공개 URL을 제시하고 "
              "동음이의어와 사건 맥락을 검증하라. 확인되지 않은 인과는 만들지 마라."
        )
    if row["task_kind"] == "related_keywords":
        return (
            f"트렌드 '{representative}'의 관측 표현({observed})을 바탕으로 관련 키워드 후보를 제시하라. "
            + common
            + "각 후보는 공백을 제외하고 6글자 이하이며 관계 설명과 근거 URL을 포함해야 한다. "
              "최종 승인 계약은 서로 다른 키워드 정확히 5개다."
        )
    return (
        f"트렌드 '{representative}'의 관측 표현({observed})과 사업적으로 연결된 상장기업 후보를 조사하라. "
        + common
        + "트렌드→사용 장면→장비·서비스→산업→기업처럼 검증 가능한 관계 경로를 우선 탐색하라. "
        + "기업명, 종목코드, 거래소, 기업 설명, 연결 이유, 온톨로지 경로, 역할 카테고리, "
          "각 관계를 입증하는 공개 URL을 제시하라. 최종 공개 계약은 기업 10개와 역할 2~4개다. "
          "단어 연상만으로 기업 수를 채우지 마라."
    )


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("enrichment queue timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def initialize_enrichment_queue(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        existing = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='enrichment_tasks'"
        ).fetchone()
        # SQLite cannot alter a CHECK constraint in place. Preserve all queued
        # research when upgrading installations created before trend_context
        # became a first-class task kind.
        if existing and "'trend_context'" not in str(existing[0] or ""):
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE enrichment_tasks_v2 (
                    event_key TEXT NOT NULL,
                    task_kind TEXT NOT NULL CHECK(task_kind IN ('trend_context','related_keywords','company_ontology')),
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
                INSERT INTO enrichment_tasks_v2 SELECT * FROM enrichment_tasks;
                CREATE TABLE enrichment_task_observations_v2 (
                    event_key TEXT NOT NULL,
                    task_kind TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    rank INTEGER NOT NULL CHECK(rank > 0),
                    current_count INTEGER NOT NULL CHECK(current_count >= 0),
                    status TEXT NOT NULL CHECK(status IN ('pending','complete')),
                    PRIMARY KEY(event_key, task_kind, observed_at),
                    FOREIGN KEY(event_key, task_kind)
                        REFERENCES enrichment_tasks_v2(event_key, task_kind)
                );
                INSERT INTO enrichment_task_observations_v2
                    SELECT * FROM enrichment_task_observations;
                DROP TABLE enrichment_task_observations;
                DROP TABLE enrichment_tasks;
                ALTER TABLE enrichment_tasks_v2 RENAME TO enrichment_tasks;
                ALTER TABLE enrichment_task_observations_v2
                    RENAME TO enrichment_task_observations;
                COMMIT;
                """
            )
            connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS enrichment_tasks (
                event_key TEXT NOT NULL,
                task_kind TEXT NOT NULL CHECK(task_kind IN ('trend_context','related_keywords','company_ontology')),
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
            "trend_context": int(
                (item.get("context_research") or {}).get("status") == "ready"
            ),
            # The frontend consumes the reviewed ``related_keywords`` field.
            # Falling back to raw ``keywords`` keeps pre-enrichment candidates
            # visible, while preventing an already complete trend from being
            # queued again merely because the raw provider list is shorter.
            "related_keywords": sum(
                keyword_fits_public_label(
                    row.get("text") if isinstance(row, dict) else row
                )
                for row in (
                    item.get("related_keywords") or item.get("keywords") or []
                )
            ),
            "company_ontology": int(
                item.get("frontend_company_count")
                if item.get("frontend_company_count") is not None
                else (item.get("company_resolution") or {}).get("candidate_count") or 0
            ),
        }
        policies = {
            "trend_context": {
                "accepted_evidence": [
                    "google_related_query", "official_announcement", "reputable_news",
                    "naver_news",
                ],
                "minimum_evidence_count": 1,
                "cause_must_be_explicit": True,
                "homonym_check_required": True,
                "invented_explanation_forbidden": True,
                "llm_role": "evidence_research_and_summary",
                "llm_candidate_target": LLM_CANDIDATE_TARGETS["trend_context"],
                "promotion_gate": "one_or_more_timestamped_urls_supporting_why_now",
                "ranking_effect": "none",
            },
            "related_keywords": {
                "accepted_evidence": [
                    "x_or_google_observed_expression",
                    "google_related_query",
                    "approved_ontology_term",
                    "approved_ontology_related_term",
                    "reviewed_provider_expression",
                ],
                "invented_terms_forbidden": True,
                "maximum_non_whitespace_characters": 6,
                "truncation_forbidden": True,
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
                "promotion_gate": "minimum_10_complete_evidence_verified_listed_companies_with_2_to_4_roles",
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
               FROM enrichment_tasks
               WHERE last_seen_at=?
               GROUP BY task_kind,status""",
            (stamp,),
        ).fetchall()
        pending_rows = connection.execute(
            """SELECT event_key,task_kind,representative_term,last_seen_at,latest_rank,
                      latest_lane,priority,current_count,required_count,missing_count,
                      observed_terms_json,evidence_policy_json
               FROM enrichment_tasks
               WHERE status='pending' AND last_seen_at=?
               ORDER BY priority DESC,last_seen_at DESC,event_key,task_kind LIMIT ?""",
            (stamp, max(0, pending_limit)),
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
                "event_sponsorship",
            ],
            "llm_can_change_ranking": False,
            "unverified_candidates_public": False,
        },
        "ranking_effect": "none",
    }
