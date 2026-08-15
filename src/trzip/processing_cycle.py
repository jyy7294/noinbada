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
from .public_company_contract import (
    keyword_company_link_coverage,
    market_reference_is_public_ready,
    market_snapshot_is_public_ready,
    verified_image_logo_is_public_ready,
)


SCHEMA_VERSION = "trzip-processing-cycle-v2"
CHECKPOINT_POLICY = "four-hour-enrichment-checkpoint-v2"
COMPLETE_CARD_POLICY = "complete-live-card-v5"
RANK_SOURCES = ("x", "google_trends")
CHECKPOINT_MAX_AGE_HOURS = 4


def _component_execution_status(component: str, raw_status: str) -> str:
    """Collapse provider-specific wording into one auditable state vocabulary.

    The raw status is retained separately.  This normalized state deliberately
    does not call a missing LLM configuration ``completed`` merely because the
    rest of the checkpoint finished.
    """

    status = str(raw_status or "unknown")
    if status in {
        "disabled_missing_config", "disabled_not_configured",
        "disabled_by_runtime_policy", "not_configured",
    }:
        return "disabled_missing_config"
    if status in {
        "deferred_to_enrichment_checkpoint", "exported_waiting_review",
    }:
        return "deferred"
    if "failed" in status or "rejected" in status:
        return "failed_non_blocking"
    if status in {"attempted", "attempted_no_accepted_decision"}:
        return "attempted"
    if component == "approved_cache" and status in {"empty", "reapplied"}:
        return "completed"
    if status in {
        "completed", "skipped_no_candidates", "skipped_no_eligible_candidates",
        "skipped_already_recorded_for_hour", "reviewed_imported",
        "reviewed_imported_previous", "reviewed_empty", "reviewed_empty_previous",
    }:
        return "completed"
    return "attempted"


def _checkpoint_age_hours(observed_at: str, at: datetime) -> float | None:
    try:
        stamp = datetime.fromisoformat(str(observed_at)).astimezone(UTC)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, (floor_hour(at) - stamp).total_seconds() / 3600), 6)


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


def observed_coverage_24h(
    path: Path,
    at: datetime,
    *,
    live_only: bool = False,
) -> dict:
    """Summarise usable observed source-hours without manufacturing coverage."""

    expected = _expected_hours(at)
    rows = source_hour_quality(
        floor_hour(at) - timedelta(hours=23),
        floor_hour(at),
        path,
        live_only=live_only,
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
    observed_at = floor_hour(observed_at or datetime.now(UTC))
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
        public_company_data_ready = (
            market_snapshot_is_public_ready(company, observed_at=observed_at)
            and verified_image_logo_is_public_ready(company)
            if public_projection
            else market_reference_is_public_ready(company, observed_at=observed_at)
        )
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
            and public_company_data_ready
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
    # Source enrichment may retain more than ten candidates.  An otherwise
    # complete eleventh row without an exact reviewed keyword bridge must not
    # displace one of the ten linked rows during role-diverse projection.
    source_link_coverage = keyword_company_link_coverage(
        keywords=keywords,
        companies=unique_complete_companies,
        links=item.get("keyword_company_links") or [],
        require_link_metadata=False,
    )
    link_ineligible_names = set(source_link_coverage["unlinked_companies"]) | set(
        source_link_coverage["matched_keyword_mismatches"]
    )
    link_complete_companies = [
        company for company in unique_complete_companies
        if str(company.get("company") or "").strip() not in link_ineligible_names
    ]
    projected_companies = select_role_diverse_company_projection(
        link_complete_companies,
        limit=10,
    )
    role_categories = {
        str(row.get("company_role_category") or "").strip()
        for row in projected_companies
        if str(row.get("company_role_category") or "").strip()
    }
    projected_company_names = {
        str(row.get("company") or "").strip() for row in projected_companies
    }
    projected_links = [
        link for link in item.get("keyword_company_links") or []
        if isinstance(link, dict)
        and str(link.get("company") or "").strip() in projected_company_names
    ]
    link_coverage = keyword_company_link_coverage(
        keywords=keywords,
        companies=projected_companies,
        links=projected_links,
        require_link_metadata=public_projection,
    )

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
    projected_company_count = len(projected_companies)
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
        "every_public_keyword_linked": bool(
            len(keyword_set) == 5
            and link_coverage["linked_keyword_count"] == len(keyword_set)
        ),
        "every_public_company_linked": bool(
            projected_company_count == 10
            and link_coverage["linked_company_count"] == projected_company_count
        ),
        "company_matched_keywords_match_links": bool(
            not link_coverage["matched_keyword_mismatches"]
        ),
        "keyword_company_link_contract": link_coverage["ready"],
    }
    missing = [key for key, passed in checks.items() if not passed]
    return {
        "policy_version": COMPLETE_CARD_POLICY,
        "ready": not missing,
        "checks": checks,
        "missing": missing,
        "keyword_count": len(keywords),
        "complete_company_count": company_count,
        "projected_company_count": projected_company_count,
        "public_projection": public_projection,
        "role_category_count": len(role_categories),
        "valid_keyword_company_link_count": link_coverage["valid_link_count"],
        "linked_keyword_count": link_coverage["linked_keyword_count"],
        "linked_company_count": link_coverage["linked_company_count"],
        "keyword_company_link_coverage": link_coverage,
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
    live_only: bool = False,
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
    handoff = handoff_status or {}
    approved_cache = handoff.get("approved_cache") or {}
    checkpoint_components = {
        "naver_context": str(verification_status or "unknown"),
        "semantic_llm": str(semantic_status or "unknown"),
        "approved_cache": str(approved_cache.get("status") or "empty"),
        "review_handoff": str(handoff.get("status") or "not_configured"),
        "complete_card_gate": "completed",
    }
    component_execution = {
        name: {
            "status": _component_execution_status(name, status),
            "detail": status,
            # All four enrichment sources are optional for ranking and release.
            # The deterministic complete-card gate is the only required stage;
            # incomplete candidates remain internal and are never padded.
            "required_for_release": name == "complete_card_gate",
            "ranking_effect": "none",
        }
        for name, status in checkpoint_components.items()
    }
    if approved_cache:
        component_execution["approved_cache"].update({
            "reapplied_count": int(approved_cache.get("reapplied_count") or 0),
            "rejected_count": int(approved_cache.get("rejected_count") or 0),
        })
        if component_execution["approved_cache"]["rejected_count"]:
            component_execution["approved_cache"].update({
                "status": "failed_non_blocking",
                "detail": "invalid_cache_entries_rejected",
            })
    attempted = enrichment_checkpoint_executed
    normalized_states = {
        row["status"] for row in component_execution.values()
    }
    optional_disabled = sorted(
        name for name, row in component_execution.items()
        if not row["required_for_release"]
        and row["status"] == "disabled_missing_config"
    )
    deferred_components = sorted(
        name for name, row in component_execution.items()
        if row["status"] == "deferred"
    )
    nonblocking_failures = sorted(
        name for name, row in component_execution.items()
        if not row["required_for_release"]
        and row["status"] == "failed_non_blocking"
    )
    blocking_failures = sorted(
        name for name, row in component_execution.items()
        if row["required_for_release"]
        and row["status"] != "completed"
    )
    release_gate = {
        "policy_version": "daily-checkpoint-release-gate-v1",
        "checkpoint_recorded": bool(enrichment_checkpoint_executed),
        "recent_checkpoint_max_age_hours": CHECKPOINT_MAX_AGE_HOURS,
        "complete_card_gate_completed": not blocking_failures,
        "optional_disabled_components": optional_disabled,
        "deferred_components": deferred_components,
        "nonblocking_component_failures": nonblocking_failures,
        "unresolved_candidate_count": batch_summary["pending_card_count"],
        "unresolved_candidates_excluded": True,
        "padding_forbidden": True,
        "release_ready": bool(enrichment_checkpoint_executed and not blocking_failures),
    }
    batch_summary.update({
        "component_status": checkpoint_components,
        "component_execution": component_execution,
        "release_gate": release_gate,
        "review_cutoff_at": handoff.get("review_cutoff_at"),
        "deferred_after_cutoff_count": int(
            handoff.get("deferred_after_cutoff_count") or 0
        ),
    })

    if enrichment_checkpoint_executed:
        # Completing the dispatcher and recording its component outcomes is a
        # different fact from every optional component succeeding.  Every due
        # run therefore receives an immutable ledger row even when the semantic
        # model is unconfigured or a review remains queued.
        if blocking_failures:
            batch_status = "failed_blocking"
        elif nonblocking_failures:
            batch_status = "completed_with_nonblocking_failures"
        elif deferred_components and optional_disabled:
            batch_status = "completed_with_deferred_work_and_optional_components_disabled"
        elif deferred_components:
            batch_status = "completed_with_deferred_work"
        elif optional_disabled:
            batch_status = "completed_with_optional_components_disabled"
        elif "attempted" in normalized_states:
            batch_status = "completed_with_attempted_optional_work"
        else:
            batch_status = "completed"
        batch_summary["execution_status"] = batch_status
        _initialize_checkpoint_store(path)
        completed_at = datetime.now(UTC).isoformat()
        serialized = json.dumps(batch_summary, ensure_ascii=False, sort_keys=True)
        with connect(path) as connection:
            connection.execute(
                """INSERT INTO enrichment_checkpoints
                   (observed_at,completed_at,summary_json) VALUES (?,?,?)
                   ON CONFLICT(observed_at) DO NOTHING""",
                (at.isoformat(), completed_at, serialized),
            )
        latest = _latest_checkpoint(path, at)
        if latest is None:
            raise RuntimeError("enrichment checkpoint execution was not recorded")
    else:
        latest = _latest_checkpoint(path, at)
        batch_status = "missed_due_checkpoint" if due else "deferred_to_enrichment_checkpoint"

    latest_age_hours = (
        _checkpoint_age_hours(latest.get("observed_at"), at)
        if latest else None
    )
    recent_checkpoint_recorded = bool(
        latest is not None
        and latest_age_hours is not None
        and latest_age_hours <= CHECKPOINT_MAX_AGE_HOURS
        and (latest.get("summary") or {}).get("release_gate", {}).get(
            "checkpoint_recorded"
        ) is True
    )
    release_gate["recent_checkpoint_recorded"] = recent_checkpoint_recorded
    release_gate["latest_checkpoint_age_hours"] = latest_age_hours
    # The current row was serialized before the derived recency values were
    # known. Keep the published execution view explicit; the preflight also
    # proves recency independently against SQLite.
    release_gate["release_ready"] = bool(
        release_gate["release_ready"] and recent_checkpoint_recorded
    )

    kst_hour = (at + timedelta(hours=9)).hour
    return {
        "schema_version": SCHEMA_VERSION,
        "observed_at": at.isoformat(),
        "rank_sources": list(RANK_SOURCES),
        "ranking_input_policy": "observed_x_google_only",
        "collector_policy": (
            "actual_production_collectors_only"
            if live_only
            else "fixture_replay_compatible_local_lane"
        ),
        "collector_versions": (
            {
                "x": "x_current_session_kr_v1",
                "google_trends": "google_trending_now_kr_v1",
            }
            if live_only
            else {
                "x": ["x_current_session_kr_v1", "trzip_v3"],
                "google_trends": ["google_trending_now_kr_v1", "trzip_v3"],
            }
        ),
        "context_provider_policy": "naver_news_context_only_no_rank_effect",
        "disabled_active_providers": ["youtube", "instagram", "naver_blog", "naver_search_trend"],
        "coverage_24h": observed_coverage_24h(path, at, live_only=live_only),
        "enrichment_batch": {
            "policy_version": CHECKPOINT_POLICY,
            "scheduled_hours_kst": [0, 4, 6, 8, 12, 16, 20],
            "current_kst_hour": kst_hour,
            "due": due,
            "executed": enrichment_checkpoint_executed,
            "attempted": attempted,
            "status": batch_status,
            "component_status": checkpoint_components,
            "component_execution": component_execution,
            "current_summary": batch_summary,
            "last_executed": latest,
            # Backward-compatible alias: this means the checkpoint dispatcher
            # finished and recorded its truthful component states, not that an
            # optional LLM or human review necessarily completed.
            "last_completed": latest,
            "release_gate": release_gate,
            "review_cutoff_at": handoff.get("review_cutoff_at"),
            "deferred_after_cutoff_count": int(
                handoff.get("deferred_after_cutoff_count") or 0
            ),
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
