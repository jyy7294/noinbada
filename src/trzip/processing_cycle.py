"""Operational audit for the hourly ledger and four-hour enrichment cadence.

The ranking engine always reads the observed X/Google ledger.  This module
describes *when* the slower context/keyword/company pass ran and how much of
the latest 24-hour window was actually observed.  Missing hours are reported;
they are never interpolated, copied from an earlier hour, or converted into a
pipeline failure by this audit layer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .company_roles import (
    public_company_role_count_is_valid,
    select_role_diverse_company_projection,
)
from .hourly_store import connect, floor_hour, source_hour_quality
from .keyword_policy import keyword_fits_public_label


SCHEMA_VERSION = "trzip-processing-cycle-v1"
CHECKPOINT_POLICY = "four-hour-enrichment-checkpoint-v1"
COMPLETE_CARD_POLICY = "complete-live-card-v4"
RANK_SOURCES = ("x", "google_trends")


def checkpoint_due(at: datetime, *, daily_publish_hour_kst: int = 6) -> bool:
    """Return whether the slower enrichment pass is scheduled for this hour."""

    kst_hour = (floor_hour(at) + timedelta(hours=9)).hour
    return kst_hour % 4 == 0 or kst_hour == daily_publish_hour_kst


def _expected_hours(at: datetime, hours: int = 24) -> list[str]:
    end = floor_hour(at)
    return [
        (end - timedelta(hours=offset)).isoformat()
        for offset in range(hours - 1, -1, -1)
    ]


def observed_coverage_24h(path: Path, at: datetime) -> dict:
    """Summarise usable observed source-hours without manufacturing coverage."""

    expected = _expected_hours(at)
    rows = source_hour_quality(
        floor_hour(at) - timedelta(hours=23),
        floor_hour(at),
        path,
    )
    eligible_by_hour: dict[str, set[str]] = {stamp: set() for stamp in expected}
    row_counts = {source: 0 for source in RANK_SOURCES}
    quarantined: list[dict] = []
    for row in rows:
        stamp = str(row.get("observed_at") or "")
        source = str(row.get("source") or "")
        if stamp not in eligible_by_hour or source not in RANK_SOURCES:
            continue
        row_count = int(row.get("row_count") or 0)
        expected_size = (
            row_count == 30 if source == "x" else row_count >= 100
        )
        audited = (
            row.get("audited_row_count") == row_count
        )
        if row.get("quality_status") == "eligible" and expected_size and audited:
            eligible_by_hour[stamp].add(source)
            row_counts[source] += row_count
        else:
            quarantined.append({
                "observed_at": stamp,
                "source": source,
                "quality_status": row.get("quality_status"),
            })

    missing_hours = [stamp for stamp, sources in eligible_by_hour.items() if not sources]
    partial_hours = [
        {
            "observed_at": stamp,
            "observed_sources": sorted(sources),
            "missing_sources": sorted(set(RANK_SOURCES) - sources),
        }
        for stamp, sources in eligible_by_hour.items()
        if sources and len(sources) < len(RANK_SOURCES)
    ]
    dual_source_hours = sum(
        set(RANK_SOURCES).issubset(sources) for sources in eligible_by_hour.values()
    )
    any_source_hours = sum(bool(sources) for sources in eligible_by_hour.values())
    source_hours = {
        source: sum(source in sources for sources in eligible_by_hour.values())
        for source in RANK_SOURCES
    }
    status = (
        "complete" if dual_source_hours == len(expected)
        else "partial" if any_source_hours
        else "empty"
    )
    return {
        "window": {
            "from": expected[0],
            "to": expected[-1],
            "expected_hours": len(expected),
        },
        "status": status,
        "any_source_hour_count": any_source_hours,
        "dual_source_hour_count": dual_source_hours,
        "source_hour_count": source_hours,
        "source_row_count": row_counts,
        "missing_hour_count": len(missing_hours),
        "missing_hours": missing_hours,
        "partial_source_hours": partial_hours,
        "quarantined_source_hours": quarantined,
        "observed_hour_ratio": round(any_source_hours / len(expected), 6),
        "dual_source_hour_ratio": round(dual_source_hours / len(expected), 6),
        "missing_hour_policy": "allowed_no_fill_no_reuse",
        "ranking_uses_available_observed_hours_only": True,
        "fabricated_hour_count": 0,
        "reused_previous_hour_count": 0,
    }


def _public_url(value: object) -> bool:
    return str(value or "").startswith(("http://", "https://"))


def complete_card_gate(
    item: dict,
    *,
    observed_at: datetime | None = None,
    public_projection: bool = False,
) -> dict:
    """Evaluate evidence completeness without looking at ranking score.

    Enriched source candidates may retain more than ten complete companies so
    the public projection can skip a malformed row without losing the card.
    The projected public DTO is stricter and must contain exactly ten.
    """

    context = item.get("context_research") or {}
    context_urls = [url for url in context.get("evidence_urls") or [] if _public_url(url)]
    keywords = list(item.get("related_keywords") or item.get("keywords") or [])
    keyword_texts = [
        str(row.get("text") if isinstance(row, dict) else row).strip()
        for row in keywords
    ]
    keyword_set = set(keyword_texts)
    companies = list(item.get("companies") or [])
    complete_companies = []
    for company in companies:
        evidence_urls = [
            str(row.get("url") or "")
            for row in company.get("evidence_sources") or []
            if _public_url(row.get("url"))
        ]
        if (
            str(company.get("company") or "").strip()
            and str(company.get("stock_code") or company.get("ticker") or "").strip()
            and str(company.get("market") or company.get("exchange") or "").strip()
            and str(company.get("company_description") or "").strip()
            and str(company.get("relationship_reason") or company.get("connection_explanation") or "").strip()
            and evidence_urls
            and company.get("ontology_complete") is True
            and isinstance(company.get("ontology_path"), list)
            and bool(company.get("ontology_path"))
            and str(company.get("company_role_category") or "").strip()
        ):
            complete_companies.append(company)
    unique_complete_companies = []
    complete_identities: set[tuple[str, str]] = set()
    for company in complete_companies:
        identity = (
            str(company.get("market") or company.get("exchange") or "").strip(),
            str(company.get("stock_code") or company.get("ticker") or "").strip(),
        )
        if identity in complete_identities:
            continue
        complete_identities.add(identity)
        unique_complete_companies.append(company)
    projected_companies = select_role_diverse_company_projection(
        unique_complete_companies,
        limit=10,
    )
    company_names = {
        str(row.get("company") or "").strip() for row in projected_companies
    }
    role_categories = {
        str(row.get("company_role_category") or "").strip()
        for row in projected_companies
        if str(row.get("company_role_category") or "").strip()
    }
    linked_keywords: set[str] = set()
    linked_companies: set[str] = set()
    valid_links = 0
    for link in item.get("keyword_company_links") or []:
        keyword = str(link.get("keyword") or "").strip()
        company = str(link.get("company") or "").strip()
        evidence = list(link.get("evidence_urls") or [])
        if (
            keyword in keyword_set
            and company in company_names
            and str(link.get("connection_explanation") or link.get("relationship_reason") or "").strip()
            and evidence
            and all(_public_url(url) for url in evidence)
        ):
            valid_links += 1
            linked_keywords.add(keyword)
            linked_companies.add(company)

    observed_at = floor_hour(observed_at or datetime.now(UTC))
    window_start = observed_at - timedelta(hours=23)
    observed_stamps = []
    for row in item.get("series") or []:
        if row.get("provenance") != "observed" or row.get("source") not in RANK_SOURCES:
            continue
        try:
            stamp = datetime.fromisoformat(str(row.get("at") or "")).astimezone(UTC)
        except (TypeError, ValueError):
            continue
        if window_start <= stamp <= observed_at:
            observed_stamps.append(stamp)

    company_count = len(unique_complete_companies)
    company_count_check = (
        company_count == 10 if public_projection else company_count >= 10
    )
    company_count_check_name = (
        "exactly_ten_evidence_backed_companies"
        if public_projection
        else "at_least_ten_evidence_backed_companies"
    )
    checks = {
        "main_lane": item.get("lane") == "main",
        # A trend does not need to reappear in the final hourly snapshot.  Any
        # genuine X/Google observation inside the publication window remains
        # eligible and the canonical recency component decays it naturally.
        "observed_within_24h": bool(observed_stamps),
        "context_with_public_url": bool(
            context.get("status") == "ready"
            and str(context.get("trigger_title") or "").strip()
            and str(context.get("why_now") or "").strip()
            and context_urls
        ),
        "exactly_five_public_keywords": bool(
            len(keywords) == 5
            and len(keyword_set) == 5
            and all(keyword_fits_public_label(text) for text in keyword_texts)
        ),
        company_count_check_name: company_count_check,
        "three_to_four_company_roles": public_company_role_count_is_valid(
            len(role_categories)
        ),
        "at_least_two_keywords_linked_to_companies": len(linked_keywords) >= 2,
    }
    missing = [key for key, passed in checks.items() if not passed]
    return {
        "policy_version": COMPLETE_CARD_POLICY,
        "ready": not missing,
        "checks": checks,
        "missing": missing,
        "keyword_count": len(keywords),
        "complete_company_count": company_count,
        "public_projection": public_projection,
        "role_category_count": len(role_categories),
        "valid_keyword_company_link_count": valid_links,
        "ranking_effect": "none",
    }


def _initialize_checkpoint_store(path: Path) -> None:
    with connect(path) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS enrichment_checkpoints (
                observed_at TEXT PRIMARY KEY,
                completed_at TEXT NOT NULL,
                summary_json TEXT NOT NULL
            )
        """)


def _latest_checkpoint(path: Path, at: datetime) -> dict | None:
    _initialize_checkpoint_store(path)
    with connect(path) as connection:
        row = connection.execute(
            """SELECT observed_at,completed_at,summary_json
               FROM enrichment_checkpoints
               WHERE observed_at <= ?
               ORDER BY observed_at DESC LIMIT 1""",
            (floor_hour(at).isoformat(),),
        ).fetchone()
    if row is None:
        return None
    return {
        "observed_at": row["observed_at"],
        "completed_at": row["completed_at"],
        "summary": json.loads(row["summary_json"]),
    }


def build_processing_cycle(
    intelligence: dict,
    *,
    path: Path,
    at: datetime,
    enrichment_checkpoint_executed: bool,
    verification_status: str | None = None,
    semantic_status: str | None = None,
    handoff_status: dict | None = None,
    daily_publish_hour_kst: int = 6,
) -> dict:
    """Build and persist auditable cadence state for this exact-hour run."""

    at = floor_hour(at)
    due = checkpoint_due(at, daily_publish_hour_kst=daily_publish_hour_kst)
    gates = {
        str(item.get("event_key") or item.get("display_name") or index): complete_card_gate(
            item, observed_at=at
        )
        for index, item in enumerate(intelligence.get("unified_ranking") or [], 1)
    }
    ready_keys = [key for key, gate in gates.items() if gate["ready"]]
    batch_summary = {
        "candidate_count": len(gates),
        "complete_card_count": len(ready_keys),
        "complete_event_keys": ready_keys,
        "pending_card_count": len(gates) - len(ready_keys),
        "gate_policy_version": COMPLETE_CARD_POLICY,
    }
    checkpoint_components = {
        "naver_context": verification_status or "unknown",
        "semantic_llm": semantic_status or "unknown",
        "review_handoff": (handoff_status or {}).get("status", "not_configured"),
    }
    attempted = enrichment_checkpoint_executed
    disabled_missing_config = attempted and all(
        status in {
            "disabled_by_runtime_policy",
            "disabled_missing_config",
            "disabled_not_configured",
            "not_configured",
        }
        for status in checkpoint_components.values()
    )
    component_failed = any(
        "failed" in status or "rejected" in status
        for status in checkpoint_components.values()
    )
    waiting_for_review = checkpoint_components["review_handoff"] == "exported_waiting_review"
    batch_summary["component_status"] = checkpoint_components

    if enrichment_checkpoint_executed:
        batch_status = (
            "failed_non_blocking" if component_failed
            else "disabled_missing_config" if disabled_missing_config
            else "attempted" if waiting_for_review
            else "completed"
        )
        # Only a checkpoint whose configured components actually completed is
        # eligible to advance ``last_completed``.  Exporting a handoff queue is
        # useful work, but it is still waiting for review and must not be
        # recorded as a completed enrichment pass.
        if batch_status == "completed":
            _initialize_checkpoint_store(path)
            completed_at = datetime.now(UTC).isoformat()
            with connect(path) as connection:
                connection.execute(
                    """INSERT INTO enrichment_checkpoints
                       (observed_at,completed_at,summary_json) VALUES (?,?,?)
                       ON CONFLICT(observed_at) DO UPDATE SET
                         completed_at=excluded.completed_at,
                         summary_json=excluded.summary_json""",
                    (
                        at.isoformat(),
                        completed_at,
                        json.dumps(batch_summary, ensure_ascii=False, sort_keys=True),
                    ),
                )
            latest = {
                "observed_at": at.isoformat(),
                "completed_at": completed_at,
                "summary": batch_summary,
            }
        else:
            latest = _latest_checkpoint(path, at)
    else:
        latest = _latest_checkpoint(path, at)
        batch_status = "missed_due_checkpoint" if due else "deferred_to_enrichment_checkpoint"

    kst_hour = (at + timedelta(hours=9)).hour
    return {
        "schema_version": SCHEMA_VERSION,
        "observed_at": at.isoformat(),
        "rank_sources": list(RANK_SOURCES),
        "ranking_input_policy": "observed_x_google_only",
        "context_provider_policy": "naver_news_context_only_no_rank_effect",
        "disabled_active_providers": ["youtube", "instagram", "naver_blog", "naver_search_trend"],
        "coverage_24h": observed_coverage_24h(path, at),
        "enrichment_batch": {
            "policy_version": CHECKPOINT_POLICY,
            "scheduled_hours_kst": [0, 4, 6, 8, 12, 16, 20],
            "current_kst_hour": kst_hour,
            "due": due,
            "executed": enrichment_checkpoint_executed,
            "attempted": attempted,
            "status": batch_status,
            "component_status": checkpoint_components,
            "current_summary": batch_summary,
            "last_completed": latest,
            "remote_publish_performed": False,
        },
        "daily_publication": {
            "scheduled_hour_kst": daily_publish_hour_kst,
            "due": kst_hour == daily_publish_hour_kst,
            "window_hours": 24,
            "missing_hours_allowed": True,
            "padding_forbidden": True,
            "requires_complete_cards_only": True,
        },
        "score_explainability": {
            "canonical_formula": intelligence.get("score_formula"),
            "canonical_formula_version": (intelligence.get("score_policy") or {}).get("formula_version"),
            "home_selection_formula": "35% velocity + 25% X-Google cross-spread + 20% current attention + 10% persistence + 10% recency",
            "keyword_company_or_cache_affects_rank": False,
        },
        "complete_card_gates": gates,
    }
