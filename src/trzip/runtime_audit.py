from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .ontology import MINIMUM_FRONTEND_COMPANIES
from .intelligence import select_balanced_home_top10
from .readiness import (
    LONG_HORIZON_HISTORY_HOURS,
    MVP_HISTORY_HOURS,
    OPERATIONAL_HISTORY_TARGET_HOURS,
    history_stage,
)


ALLOWED_RANKING_SOURCES = {"x", "google_trends"}
ALLOWED_COLLECTOR_VERSIONS = {
    "x": {"x_current_session_kr_v1"},
    "google_trends": {"google_trending_now_kr_v1"},
}
ALLOWED_X_COLLECTOR_TRANSPORTS = {
    "codex_chrome_current_session": "codex_browser_snapshot",
}
EXPECTED_DELIVERY_SCHEMA = "trzip-frontend-delivery-v1"
SCORE_FORMULA_CONTRACTS = {
    "current40_momentum20_persistence20_decay15_cross5_v2": {
        "components": (
            ("current_points", 40.0),
            ("momentum_points", 20.0),
            ("persistence_points", 20.0),
            ("decayed_history_points", 15.0),
            ("cross_source_points", 5.0),
        ),
        "freshness_multiplier": True,
    },
    "spread35_velocity25_breadth20_persistence10_recency10_v2": {
        "components": (
            ("period_strength_points", 35.0),
            ("momentum_points", 25.0),
            ("persistence_points", 10.0),
            ("recency_points", 10.0),
            ("cross_source_points", 20.0),
        ),
        "freshness_multiplier": False,
    },
}
PERIOD_SCORE_FORMULA = "spread35_velocity25_breadth20_persistence10_recency10_v2"
EXPECTED_SCHEMAS = {
    "intelligence": "trzip-intelligence-v3",
    "metadata": "trzip-live-data-v3",
    "status": "trzip-runtime-status-v1",
}
SECRET_PATTERNS = (
    re.compile(r"tmcp_live_[A-Za-z0-9_-]+", re.IGNORECASE),
    re.compile(r"bearer\s+[A-Za-z0-9._~+/-]+=*", re.IGNORECASE),
    re.compile(r"(?:api[_-]?key|client[_-]?secret|access[_-]?token)\s*[=:]\s*[^\s,}\"]+", re.IGNORECASE),
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+", re.IGNORECASE),
    re.compile(r"/Users/[^/\s]+", re.IGNORECASE),
)


@dataclass
class AuditReport:
    checked_at: str
    status: str = "pass"
    failures: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def fail(self, code: str) -> None:
        if code not in self.failures:
            self.failures.append(code)

    def block(self, code: str) -> None:
        if code not in self.blockers:
            self.blockers.append(code)

    def warn(self, code: str) -> None:
        if code not in self.warnings:
            self.warnings.append(code)

    def finalize(self) -> dict[str, Any]:
        if self.failures:
            self.status = "fail"
        elif self.blockers:
            self.status = "provisional"
        else:
            self.status = "pass"
        return {
            "checked_at": self.checked_at,
            "status": self.status,
            "failures": self.failures,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "metrics": self.metrics,
        }


def default_runtime_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is required when --runtime-root is omitted")
    return Path(local_app_data) / "TRZIP"


def _load_document(path: Path, report: AuditReport, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report.fail(f"{code}_unreadable")
        return {}
    if not isinstance(value, dict):
        report.fail(f"{code}_not_object")
        return {}
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_child(latest: Path, relative_path: object) -> Path | None:
    value = str(relative_path or "")
    if not value:
        return None
    candidate = (latest / value).resolve()
    try:
        candidate.relative_to(latest.resolve())
    except ValueError:
        return None
    return candidate


def _observed_at(document: dict[str, Any], kind: str) -> Any:
    if kind == "intelligence":
        return (document.get("window") or {}).get("to")
    return document.get("observed_at")


def _audit_bundle(
    intelligence: dict[str, Any],
    metadata: dict[str, Any],
    status: dict[str, Any],
    report: AuditReport,
) -> None:
    documents = {
        "intelligence": intelligence,
        "metadata": metadata,
        "status": status,
    }
    for kind, expected in EXPECTED_SCHEMAS.items():
        if documents[kind].get("schema_version") != expected:
            report.fail(f"{kind}_schema_mismatch")

    for field_name in ("publication_id", "generated_at"):
        values = {document.get(field_name) for document in documents.values()}
        if None in values or len(values) != 1:
            report.fail(f"bundle_{field_name}_mismatch")
    observed_values = {
        _observed_at(document, kind) for kind, document in documents.items()
    }
    if None in observed_values or len(observed_values) != 1:
        report.fail("bundle_observed_at_mismatch")
    if any(document.get("mode") != "live" for document in documents.values()):
        report.fail("bundle_not_live")
    publishable_values = {document.get("publishable") for document in documents.values()}
    if len(publishable_values) != 1 or None in publishable_values:
        report.fail("bundle_publishable_mismatch")

    collection = metadata.get("collection") or {}
    collection_audit = collection.get("audit") or {}
    google = collection_audit.get("google_geo_kr") or {}
    google_count = google.get("row_count")
    if (
        google.get("status") != "observed"
        or google.get("completion_verified") is not True
        or not isinstance(google_count, int)
        or google_count < 100
        or google_count != google.get("declared_total")
        or not isinstance(google.get("page_count"), int)
        or google.get("page_count") < 1
    ):
        report.fail("google_full_collection_unverified")
    x_audit = collection_audit.get("x_korea_realtime") or {}
    if x_audit.get("status") == "observed" and x_audit.get("row_count") != 30:
        report.fail("x_current_collection_not_30")
    if x_audit.get("status") == "observed":
        collector = str(x_audit.get("collector") or "")
        transport = str(x_audit.get("transport") or "")
        if ALLOWED_X_COLLECTOR_TRANSPORTS.get(collector) != transport:
            report.fail("x_collector_provenance_invalid")
        if x_audit.get("profile") != "current_logged_in_chrome":
            report.fail("x_collector_profile_invalid")
        if collector == "current_logged_in_chrome_snapshot":
            report.warn("x_collector_transport_unresolved")
    observed_count = sum(
        int(row.get("row_count") or 0)
        for row in collection_audit.values()
        if isinstance(row, dict) and row.get("status") == "observed"
    )
    if collection.get("observed") != observed_count:
        report.fail("collection_observed_count_mismatch")

    status_sources = status.get("source_status") or {}
    intelligence_sources = (intelligence.get("collection_status") or {}).get("source_status") or {}
    if status_sources != intelligence_sources:
        report.fail("bundle_source_status_mismatch")
    status_partial = status.get("partial")
    intelligence_partial = (intelligence.get("collection_status") or {}).get("partial")
    if status_partial != intelligence_partial:
        report.fail("bundle_partial_status_mismatch")
    expected_publishable = (
        status_partial is False
        and all(status_sources.get(source) == "observed" for source in ALLOWED_RANKING_SOURCES)
    )
    if any(
        document.get("publishable") is not expected_publishable
        for document in documents.values()
    ):
        report.fail("bundle_publishable_state_invalid")

    health = metadata.get("collection_health")
    health_invalid = not isinstance(health, dict)
    if isinstance(health, dict):
        current_source_success = health.get("current_publication_source_success")
        latest_source_success = health.get("latest_scheduled_attempt_source_success")
        attempt_type = health.get("current_publication_attempt_type")
        current_success = health.get("current_publication_success")
        initial_success = health.get("current_schedule_initial_attempt_success")
        latest_success = health.get("latest_scheduled_attempt_success")
        recovered = health.get("recovered_from_scheduled_failure")
        current_status = health.get("current_publication_status")
        expected_source_success = {
            source: status_sources.get(source) == "observed"
            for source in ("x", "google_trends")
        }
        bool_fields = (current_success, initial_success, latest_success, recovered)
        if (
            any(not isinstance(value, bool) for value in bool_fields)
            or current_source_success != expected_source_success
            or not isinstance(latest_source_success, dict)
            or set(latest_source_success) != {"x", "google_trends"}
            or any(not isinstance(value, bool) for value in latest_source_success.values())
            or health.get("current_publication_scheduled_at") != metadata.get("observed_at")
            or not health.get("latest_scheduled_at")
            or current_success is not (status_partial is False)
        ):
            health_invalid = True
        elif attempt_type == "scheduled":
            expected_status = "scheduled_complete" if current_success else "scheduled_partial"
            if (
                current_status != expected_status
                or initial_success is not current_success
                or recovered is not False
            ):
                health_invalid = True
        elif attempt_type == "recovery":
            expected_status = (
                "recovered_complete"
                if current_success and not initial_success
                else "republished_complete"
                if current_success
                else "recovery_partial"
            )
            if (
                current_status != expected_status
                or recovered is not (current_success and not initial_success)
            ):
                health_invalid = True
        else:
            health_invalid = True
        if health.get("latest_scheduled_at") == health.get("current_publication_scheduled_at"):
            if latest_success is not initial_success:
                health_invalid = True
        report.metrics["collection_health_publication"] = {
            "attempt_type": attempt_type,
            "publication_status": current_status,
            "current_publication_success": current_success,
            "latest_scheduled_attempt_success": latest_success,
            "recovered_from_scheduled_failure": recovered,
        }
    if health_invalid:
        report.fail("collection_health_publication_state_invalid")

    public_text = json.dumps(documents, ensure_ascii=False)
    if any(pattern.search(public_text) for pattern in SECRET_PATTERNS):
        report.fail("public_bundle_contains_secret_or_local_path")


def _audit_frontend_delivery(
    latest: Path,
    intelligence: dict[str, Any],
    metadata: dict[str, Any],
    status: dict[str, Any],
    report: AuditReport,
) -> None:
    manifest = _load_document(
        latest / "manifest.json", report, "frontend_delivery_manifest"
    )
    if not manifest:
        return
    if manifest.get("schema_version") != EXPECTED_DELIVERY_SCHEMA:
        report.fail("frontend_delivery_schema_mismatch")
    expected_identity = (
        metadata.get("publication_id"),
        metadata.get("generated_at"),
        metadata.get("observed_at"),
    )
    if (
        manifest.get("publication_id"),
        manifest.get("generated_at"),
        manifest.get("observed_at"),
    ) != expected_identity or manifest.get("mode") != "live":
        report.fail("frontend_delivery_identity_mismatch")

    compatibility = manifest.get("compatibility_documents") or {}
    compatibility_payloads = {
        "intelligence": intelligence,
        "metadata": metadata,
        "status": status,
    }
    for kind, payload in compatibility_payloads.items():
        entry = compatibility.get(kind) or {}
        path = _manifest_child(latest, entry.get("path"))
        if path is None or not path.is_file():
            report.fail(f"frontend_delivery_{kind}_missing")
            continue
        try:
            digest = _sha256_file(path)
        except OSError:
            report.fail(f"frontend_delivery_{kind}_unreadable")
            continue
        if digest != entry.get("sha256"):
            report.fail(f"frontend_delivery_{kind}_hash_mismatch")
        observed_at = (
            (payload.get("window") or {}).get("to")
            if kind == "intelligence"
            else payload.get("observed_at")
        )
        if (
            payload.get("publication_id"),
            payload.get("generated_at"),
            observed_at,
        ) != expected_identity:
            report.fail(f"frontend_delivery_{kind}_identity_mismatch")

    bundle = manifest.get("bundle") or {}
    rankings_entry = bundle.get("rankings") or {}
    rankings_path = _manifest_child(latest, rankings_entry.get("path"))
    rankings: dict[str, Any] = {}
    if rankings_path is None or not rankings_path.is_file():
        report.fail("frontend_rankings_missing")
    else:
        try:
            rankings = json.loads(rankings_path.read_text(encoding="utf-8"))
            if _sha256_file(rankings_path) != rankings_entry.get("sha256"):
                report.fail("frontend_rankings_hash_mismatch")
        except (OSError, json.JSONDecodeError):
            report.fail("frontend_rankings_unreadable")
            rankings = {}
    if rankings:
        if rankings.get("schema_version") != "trzip-rankings-v1":
            report.fail("frontend_rankings_schema_mismatch")
        if (
            rankings.get("publication_id"),
            rankings.get("generated_at"),
            rankings.get("observed_at"),
        ) != expected_identity:
            report.fail("frontend_rankings_identity_mismatch")
        expected_keys = [
            str(item.get("event_key") or "")
            for item in intelligence.get("unified_ranking") or []
        ]
        published_keys = [
            str(item.get("event_key") or "")
            for item in rankings.get("unified_ranking") or []
        ]
        if published_keys != expected_keys:
            report.fail("frontend_rankings_order_mismatch")
        expected_youtube = intelligence.get("youtube_content_discovery")
        # YouTube is no longer part of the active home-feed contract.  Audit
        # the legacy lane only when a delivery explicitly publishes it.
        if expected_youtube is not None and "youtube_content_discovery" in rankings:
            youtube = rankings.get("youtube_content_discovery") or {}
            if (
                youtube != expected_youtube
                or youtube.get("ranking") != rankings.get("youtube_content_ranking")
                or youtube.get("top10") != rankings.get("youtube_content_top10")
                or youtube.get("affects_x_google_rank") is not False
                or youtube.get("ranking_effect") != "separate_content_lane"
            ):
                report.fail("frontend_youtube_content_contract_mismatch")
        _audit_period_rankings(rankings, report)

    detail_index = bundle.get("trend_index") or []
    expected_event_keys: list[str] = []
    seen_event_keys: set[str] = set()
    ranking_lists = [intelligence.get("unified_ranking") or []]
    views = intelligence.get("ranking_views") or {}
    ranking_lists.extend(
        (views.get(period) or {}).get("unified_ranking") or []
        for period in ("daily", "weekly", "monthly")
    )
    for ranking in ranking_lists:
        for item in ranking:
            event_key = str((item if isinstance(item, dict) else {}).get("event_key") or "")
            if event_key and event_key not in seen_event_keys:
                seen_event_keys.add(event_key)
                expected_event_keys.append(event_key)
    expected_count = len(expected_event_keys)
    if (
        not isinstance(detail_index, list)
        or bundle.get("trend_count") != expected_count
        or len(detail_index) != expected_count
    ):
        report.fail("frontend_trend_detail_count_mismatch")
        detail_index = []
    event_keys: list[str] = []
    detail_failures = 0
    for entry in detail_index:
        event_key = str((entry if isinstance(entry, dict) else {}).get("event_key") or "")
        path = _manifest_child(
            latest,
            (entry if isinstance(entry, dict) else {}).get("path"),
        )
        event_keys.append(event_key)
        if not event_key or path is None or not path.is_file():
            detail_failures += 1
            continue
        try:
            detail = json.loads(path.read_text(encoding="utf-8"))
            digest = _sha256_file(path)
        except (OSError, json.JSONDecodeError):
            detail_failures += 1
            continue
        if (
            digest != entry.get("sha256")
            or detail.get("schema_version") != "trzip-trend-detail-v1"
            or (
                detail.get("publication_id"),
                detail.get("generated_at"),
                detail.get("observed_at"),
            ) != expected_identity
            or (detail.get("trend") or {}).get("event_key") != event_key
        ):
            detail_failures += 1
    if event_keys != expected_event_keys or detail_failures:
        report.fail("frontend_trend_detail_integrity_error")
    report.metrics["frontend_delivery"] = {
        "publication_id": manifest.get("publication_id"),
        "trend_detail_count": len(detail_index),
        "detail_failure_count": detail_failures,
    }


def _audit_period_rankings(intelligence: dict[str, Any], report: AuditReport) -> None:
    expected = [("daily", 24), ("weekly", 168), ("monthly", 720)]
    periods = intelligence.get("ranking_periods")
    views = intelligence.get("ranking_views")
    failures = 0
    if (
        intelligence.get("ranking_default_period") != "daily"
        or not isinstance(periods, list)
        or not isinstance(views, dict)
        or [
            (item.get("key"), (item.get("window") or {}).get("hours"))
            for item in (periods or [])
        ] != expected
        or set(views or {}) != {key for key, _ in expected}
    ):
        report.fail("ranking_period_contract_invalid")
        return
    if intelligence.get("ranking_top_level_alias") != {
        "period": "daily",
        "unified_ranking": "daily_period_aggregate",
        "trend_top10": "daily_home_top10",
    }:
        report.fail("ranking_period_contract_invalid")
        return
    period_counts: dict[str, int] = {}
    for key, hours in expected:
        view = views[key]
        ranking = view.get("unified_ranking")
        top10 = view.get("period_top10")
        window = view.get("window") or {}
        if (
            not isinstance(ranking, list)
            or not isinstance(top10, list)
            or window.get("hours") != hours
            or window.get("score_history_hours") != hours
            or window.get("lifecycle_baseline_days") != 60
            or view.get("formula_version") != PERIOD_SCORE_FORMULA
            or view.get("company_count_affects_rank") is not False
            or view.get("company_detail_policy") != "shared_by_detail_event_key"
        ):
            failures += 1
            continue
        if [item.get("rank") for item in ranking] != list(range(1, len(ranking) + 1)):
            failures += 1
        if [item.get("score") for item in ranking] != sorted(
            (item.get("score") for item in ranking), reverse=True
        ):
            failures += 1
        if any(
            item.get("detail_event_key") != item.get("event_key")
            or not item.get("latest_source_ranks")
            or item.get("candidate_status") not in {"is_current", "period_observed"}
            or item.get("is_current") is not (
                item.get("candidate_status") == "is_current"
            )
            or not item.get("last_seen_at")
            or item.get("detail_status") not in {
                "shared_full_detail", "period_summary_only"
            }
            or not isinstance(item.get("freshness"), dict)
            or (item.get("freshness") or {}).get("half_life_hours") != hours / 2
            or not _score_contract_matches(item, required_formula=PERIOD_SCORE_FORMULA)
            or "companies" in item
            or "company_candidates" in item
            for item in ranking
        ):
            failures += 1
        main = [
            item for item in ranking
            if item.get("lane") == "main" and item.get("home_eligible") is True
        ]
        expected_top10 = select_balanced_home_top10(main)
        if (
            [item.get("main_rank") for item in main] != list(range(1, len(main) + 1))
            or [item.get("event_key") for item in top10]
            != [item.get("event_key") for item in expected_top10]
        ):
            failures += 1
        period_counts[key] = len(ranking)
    default_view = views["daily"]
    if [
        (
            item.get("event_key"),
            item.get("rank"),
            item.get("score"),
            item.get("candidate_status"),
            item.get("last_seen_at"),
            item.get("freshness"),
        )
        for item in default_view.get("unified_ranking") or []
    ] != [
        (
            item.get("event_key"),
            item.get("rank"),
            item.get("score"),
            item.get("candidate_status"),
            item.get("last_seen_at"),
            item.get("freshness"),
        )
        for item in intelligence.get("unified_ranking") or []
    ]:
        failures += 1
    if [item.get("event_key") for item in default_view.get("period_top10") or []] != [
        item.get("event_key") for item in intelligence.get("trend_top10") or []
    ]:
        failures += 1
    if failures:
        report.fail("ranking_period_integrity_error")
    report.metrics["ranking_periods"] = {
        "default": "daily",
        "counts": period_counts,
        "failure_count": failures,
    }


def _score_contract_matches(
    item: dict[str, Any],
    *,
    required_formula: str | None = None,
) -> bool:
    try:
        score = float(item.get("score"))
    except (TypeError, ValueError):
        return False
    components = item.get("score_components") or {}
    formula_version = components.get("formula_version")
    if required_formula is not None and formula_version != required_formula:
        return False
    formula = SCORE_FORMULA_CONTRACTS.get(formula_version)
    if formula is None:
        return False
    values: list[float] = []
    for key, maximum in formula["components"]:
        value = components.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        numeric = float(value)
        if numeric < 0 or numeric > maximum:
            return False
        values.append(numeric)
    subtotal = round(sum(values), 2)
    total = subtotal
    if formula["freshness_multiplier"]:
        declared_subtotal = components.get("component_subtotal_points")
        multiplier = components.get("freshness_multiplier")
        if (
            not isinstance(declared_subtotal, (int, float))
            or isinstance(declared_subtotal, bool)
            or float(declared_subtotal) != subtotal
            or not isinstance(multiplier, (int, float))
            or isinstance(multiplier, bool)
            or not 0.0 <= float(multiplier) <= 1.0
        ):
            return False
        total = round(subtotal * float(multiplier), 2)
    elif "freshness_multiplier" in components:
        return False
    try:
        declared_total = float(components.get("total_points"))
    except (TypeError, ValueError):
        return False
    return (
        components.get("rounding_policy") == "each_component_2dp_then_sum_2dp"
        and total == score
        and total == declared_total
    )


def _audit_ranking(intelligence: dict[str, Any], report: AuditReport) -> None:
    _audit_period_rankings(intelligence, report)
    unified = intelligence.get("unified_ranking")
    trend_top10 = intelligence.get("trend_top10")
    home_top10 = intelligence.get("home_top10")
    rising_top10 = intelligence.get("rising_top10")
    all_observed = intelligence.get("all_observed_ranking")
    public_top10 = intelligence.get("public_top10")
    company_ready = intelligence.get("company_ready_trends")
    if not all(
        isinstance(value, list)
        for value in (
            unified, all_observed, home_top10, rising_top10,
            trend_top10, public_top10, company_ready,
        )
    ):
        report.fail("ranking_not_array")
        return

    report.metrics["unified_count"] = len(unified)
    report.metrics["home_count"] = len(trend_top10)
    report.metrics["company_ready_count"] = len(company_ready)
    expected_ranks = list(range(1, len(unified) + 1))
    actual_ranks = [item.get("rank") for item in unified if isinstance(item, dict)]
    if actual_ranks != expected_ranks:
        report.fail("unified_rank_not_contiguous")

    scores: list[float] = []
    event_keys: list[str] = []
    unified_rank_by_key: dict[str, int] = {}
    score_mismatch_count = 0
    invalid_source_count = 0
    generated_count = 0
    issue_company_leak_count = 0
    for item in unified:
        if not isinstance(item, dict):
            report.fail("ranking_item_not_object")
            continue
        event_key = str(item.get("event_key") or "")
        event_keys.append(event_key)
        unified_rank_by_key[event_key] = int(item.get("rank") or 0)
        score = float(item.get("score") or 0.0)
        scores.append(score)
        components = item.get("score_components") or {}
        if not _score_contract_matches(item, required_formula=PERIOD_SCORE_FORMULA):
            score_mismatch_count += 1
        if (
            item.get("candidate_status") not in {"is_current", "period_observed"}
            or item.get("is_current") is not (
                item.get("candidate_status") == "is_current"
            )
            or not item.get("last_seen_at")
            or not isinstance(item.get("freshness"), dict)
        ):
            score_mismatch_count += 1

        source_ranks = item.get("latest_source_ranks") or {}
        if set(source_ranks) - ALLOWED_RANKING_SOURCES:
            invalid_source_count += 1
        if any(value != "observed" for value in item.get("provenance") or []):
            generated_count += 1
        if item.get("lane") == "issue" and item.get("companies"):
            issue_company_leak_count += 1

    if scores != sorted(scores, reverse=True):
        report.fail("unified_score_not_descending")
    if not all(event_keys) or len(event_keys) != len(set(event_keys)):
        report.fail("event_key_missing_or_duplicate")
    if score_mismatch_count:
        report.fail("score_component_mismatch")
    if invalid_source_count:
        report.fail("ranking_uses_disallowed_source")
    if generated_count:
        report.fail("generated_observation_in_live_ranking")
    if issue_company_leak_count:
        report.fail("issue_lane_company_leak")
    report.metrics.update(
        {
            "score_mismatch_count": score_mismatch_count,
            "invalid_ranking_source_count": invalid_source_count,
            "generated_ranking_count": generated_count,
            "issue_company_leak_count": issue_company_leak_count,
        }
    )

    main_ranking = [item for item in unified if item.get("lane") == "main"]
    home_failures = 0
    if [item.get("main_rank") for item in main_ranking] != list(
        range(1, len(main_ranking) + 1)
    ):
        home_failures += 1
    if any(
        item.get("main_rank") is not None
        for item in unified
        if item.get("lane") != "main"
    ):
        home_failures += 1
    home_ranking = [
        item for item in unified
        if item.get("lane") == "main" and item.get("home_eligible") is True
    ]
    if [item.get("home_rank") for item in home_ranking] != list(
        range(1, len(home_ranking) + 1)
    ):
        home_failures += 1
    completed_home_ranking = [
        item for item in home_ranking
        if item.get("frontend_readiness_status") == "ready"
    ]
    from .intelligence import select_balanced_home_top10
    expected_home_top10 = select_balanced_home_top10(completed_home_ranking)
    if (
        [
            (item.get("event_key"), item.get("rank"), item.get("score"))
            for item in all_observed
        ]
        != [
            (item.get("event_key"), item.get("rank"), item.get("score"))
            for item in unified
        ]
        or [item.get("event_key") for item in home_top10]
        != [item.get("event_key") for item in expected_home_top10]
        or trend_top10 != home_top10
        or public_top10 != home_top10
    ):
        home_failures += 1
    if any(
        (item.get("ranking_data_readiness") or {}).get("momentum_status") != "measured"
        or float(item.get("momentum_delta") or 0.0) <= 0.0
        for item in rising_top10
    ):
        home_failures += 1
    for item in trend_top10:
        if not isinstance(item, dict):
            home_failures += 1
            continue
        event_key = str(item.get("event_key") or "")
        if event_key not in unified_rank_by_key or unified_rank_by_key[event_key] != item.get("rank"):
            home_failures += 1
        if item.get("lane") != "main" or item.get("company_card_status") not in {
            "ready", "enrichment_pending", "not_applicable"
        }:
            home_failures += 1
        if item.get("broad_category") not in {
            "food", "content", "sports", "lifestyle", "culture",
            "consumer", "technology", "market",
        }:
            home_failures += 1
        keywords = item.get("keywords") or []
        if len(keywords) > 5 or any(
            keyword.get("affects_score") is not False for keyword in keywords
        ):
            home_failures += 1

    if home_failures:
        report.fail("home_quality_gate_failed")
    report.metrics["home_quality_failure_count"] = home_failures

    company_failures = 0
    expected_company_ready = [
        item for item in home_ranking
        if item.get("company_card_status") == "ready"
    ]
    if [item.get("event_key") for item in company_ready] != [
        item.get("event_key") for item in expected_company_ready
    ]:
        company_failures += 1
    home_company_counts: dict[str, int] = {}
    for item in company_ready:
        if not isinstance(item, dict):
            company_failures += 1
            continue
        name = str(item.get("display_name") or item.get("topic") or item.get("event_key"))
        companies = item.get("companies") or []
        home_company_counts[name] = len(companies)
        if item.get("lane") != "main" or item.get("company_card_status") != "ready":
            company_failures += 1
        resolution = item.get("company_resolution") or {}
        if resolution.get("publish_status") != "published":
            company_failures += 1
        tickers = [str(company.get("stock_code") or "") for company in companies]
        if len(tickers) < MINIMUM_FRONTEND_COMPANIES or not all(tickers) or len(tickers) != len(set(tickers)):
            company_failures += 1
        for company in companies:
            identity = company.get("official_identity") or {}
            if (
                identity.get("status") not in {"verified", "unavailable", "not_found", "error", "stock_code_mismatch"}
                or (
                    identity.get("provider") is not None
                    and identity.get("provider") not in {"opendart", "exchange_official", "sec_edgar"}
                )
                or identity.get("ranking_effect") != "none"
            ):
                company_failures += 1
            if company.get("ontology_complete") is not True:
                company_failures += 1
            if company.get("relation_tier") not in {"direct", "value_chain", "industry_watch"}:
                company_failures += 1
            if not company.get("company_role_category") or not company.get("company_role_label"):
                company_failures += 1
            evidence = company.get("evidence_sources") or []
            path = company.get("ontology_path") or []
            if not evidence or len(path) < 2:
                company_failures += 1
            if any(
                edge.get("review_status")
                not in {"observed", "approved", "verified", "published", "historical_reference"}
                or not edge.get("evidence_urls")
                for edge in path
            ):
                company_failures += 1
    if company_failures:
        report.fail("company_ready_contract_failed")
    report.metrics["company_ready_failure_count"] = company_failures
    report.metrics["home_company_counts"] = home_company_counts

    verification_policy = intelligence.get("verification_policy") or {}
    verification_run = intelligence.get("verification_run") or {}
    if verification_policy.get("verification_affects_score") is not False:
        report.fail("verification_may_affect_score")
    if verification_run.get("ranking_effect") != "none":
        report.fail("verification_run_may_affect_score")

    availability = intelligence.get("ranking_availability") or {}
    current_sources = set(availability.get("current_sources") or [])
    missing_sources = set(availability.get("missing_sources") or [])
    report.metrics["current_sources"] = sorted(current_sources)
    report.metrics["missing_sources"] = sorted(missing_sources)
    if current_sources != ALLOWED_RANKING_SOURCES:
        report.block("combined_x_google_not_ready")
    if availability.get("is_combined_rank") is not True:
        report.block("ranking_is_provisional")


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _parse_audit_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _audit_database(
    db_path: Path,
    report: AuditReport,
    intelligence: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    if not db_path.exists():
        report.fail("sqlite_database_missing")
        return
    try:
        connection = sqlite3.connect(db_path)
    except sqlite3.Error:
        report.fail("sqlite_database_unreadable")
        return
    try:
        if not _table_exists(connection, "hourly_observations"):
            report.fail("hourly_observations_missing")
            return
        total = connection.execute("SELECT COUNT(*) FROM hourly_observations").fetchone()[0]
        generated = connection.execute(
            "SELECT COUNT(*) FROM hourly_observations WHERE provenance != 'observed'"
        ).fetchone()[0]
        rows = connection.execute(
            """
            SELECT observed_at, source, COUNT(*), MIN(source_rank), MAX(source_rank),
                   COUNT(DISTINCT source_rank), collector_version
            FROM hourly_observations
            WHERE collector_version IS NOT NULL
            GROUP BY observed_at, source, collector_version
            ORDER BY observed_at
            """
        ).fetchall()
        report.metrics["sqlite_observation_count"] = total
        report.metrics["sqlite_generated_count"] = generated
        publication_observed_at = _parse_audit_timestamp(metadata.get("observed_at"))
        publication_rows: list[tuple[Any, ...]] = []
        post_publication_rows: list[tuple[Any, ...]] = []
        for row in rows:
            row_observed_at = _parse_audit_timestamp(row[0])
            if publication_observed_at is None or (
                row_observed_at is not None and row_observed_at <= publication_observed_at
            ):
                publication_rows.append(row)
            else:
                post_publication_rows.append(row)
        publication_hours = {row[0] for row in publication_rows}
        operational_hours = {row[0] for row in rows}
        report.metrics["v3_source_hour_count"] = len(rows)
        report.metrics["publication_source_hour_count"] = len(publication_rows)
        report.metrics["post_publication_source_hour_count"] = len(post_publication_rows)
        report.metrics["post_publication_observation_count"] = sum(
            int(row[2]) for row in post_publication_rows
        )
        # Publication integrity is evaluated as-of its immutable observed_at.
        # Later hourly collections are valid operational progress, not drift in
        # the already-published daily snapshot.
        report.metrics["clean_history_hours"] = len(publication_hours)
        report.metrics["publication_clean_history_hours"] = len(publication_hours)
        report.metrics["operational_clean_history_hours"] = len(operational_hours)
        report.metrics["latest_source_hours"] = [
            {
                "observed_at": row[0],
                "source": row[1],
                "count": row[2],
                "collector_version": row[6],
            }
            for row in rows[-6:]
        ]
        if generated:
            report.fail("sqlite_contains_generated_observations")
        invalid_collector_pairs: set[tuple[str, str]] = set()
        for _, source, count, minimum, maximum, distinct_count, collector_version in rows:
            if source not in ALLOWED_RANKING_SOURCES:
                report.fail("v3_database_contains_disallowed_source")
            elif collector_version not in ALLOWED_COLLECTOR_VERSIONS[source]:
                invalid_collector_pairs.add((str(source), str(collector_version)))
            if minimum != 1 or maximum != count or distinct_count != count:
                report.fail("v3_source_hour_rank_incomplete")
        invalid_collector_versions = [
            {"source": source, "collector_version": version}
            for source, version in sorted(invalid_collector_pairs)
        ]
        report.metrics["invalid_collector_versions"] = invalid_collector_versions
        if invalid_collector_versions:
            report.fail("collector_version_not_allowlisted")
        current_sources = {row[1] for row in publication_rows}
        if "google_trends" not in current_sources:
            report.fail("google_v3_history_missing")
        if "x" not in current_sources:
            report.block("x_v3_history_missing")
        clean_history_hours = report.metrics["clean_history_hours"]
        report.metrics["history_stage"] = history_stage(clean_history_hours)
        report.metrics["mvp_required_history_hours"] = MVP_HISTORY_HOURS
        report.metrics["operational_target_history_hours"] = (
            OPERATIONAL_HISTORY_TARGET_HOURS
        )
        report.metrics["long_horizon_history_hours"] = LONG_HORIZON_HISTORY_HOURS
        if clean_history_hours < MVP_HISTORY_HOURS:
            report.block("clean_history_under_24_hours")
        elif clean_history_hours < OPERATIONAL_HISTORY_TARGET_HOURS:
            report.warn("operational_history_under_48_hours")
        v3_row_count = sum(int(row[2]) for row in publication_rows)
        coverage = metadata.get("coverage") or {}
        expected_first = min((row[0] for row in publication_rows), default=None)
        expected_last = max((row[0] for row in publication_rows), default=None)
        if (
            coverage.get("rows") != v3_row_count
            or coverage.get("observed_rows") != v3_row_count
            or coverage.get("hours") != report.metrics["clean_history_hours"]
            or coverage.get("first_hour") != expected_first
            or coverage.get("last_hour") != expected_last
        ):
            report.fail("published_coverage_does_not_match_sqlite")
        current_observed_at = publication_observed_at
        latest_rows = [
            row
            for row in publication_rows
            if current_observed_at is not None
            and _parse_audit_timestamp(row[0]) == current_observed_at
        ]
        latest_counts = {row[1]: int(row[2]) for row in latest_rows}
        collection_audit = ((metadata.get("collection") or {}).get("audit") or {})
        if latest_counts.get("google_trends") != (
            collection_audit.get("google_geo_kr") or {}
        ).get("row_count"):
            report.fail("latest_google_count_does_not_match_sqlite")
        if (collection_audit.get("x_korea_realtime") or {}).get("status") == "observed":
            if latest_counts.get("x") != 30:
                report.fail("latest_x_count_does_not_match_sqlite")
        _audit_daily_aggregates(intelligence, report)
        _audit_provider_ledger(connection, report)
    except sqlite3.Error:
        report.fail("sqlite_audit_query_failed")
    finally:
        connection.close()


def _audit_daily_aggregates(intelligence: dict[str, Any], report: AuditReport) -> None:
    rows = intelligence.get("daily_aggregates")
    if not isinstance(rows, list):
        report.fail("daily_aggregates_not_array")
        return
    keys: list[tuple[str, str]] = []
    invalid = 0
    for row in rows:
        if not isinstance(row, dict):
            invalid += 1
            continue
        key = (str(row.get("kst_date") or ""), str(row.get("event_key") or ""))
        keys.append(key)
        if (
            not all(key)
            or not isinstance(row.get("hours_present"), int)
            or row.get("hours_present") < 1
            or not isinstance(row.get("best_rank"), int)
            or row.get("best_rank") < 1
            or not isinstance(row.get("mean_rank"), (int, float))
            or row.get("mean_rank") < row.get("best_rank")
            or row.get("source_count") not in (1, 2)
        ):
            invalid += 1
    if len(keys) != len(set(keys)) or invalid:
        report.fail("daily_aggregate_integrity_error")
    report.metrics["daily_aggregate_count"] = len(rows)


def _audit_provider_ledger(connection: sqlite3.Connection, report: AuditReport) -> None:
    if not _table_exists(connection, "provider_verification_runs"):
        report.warn("provider_verification_ledger_missing")
        return
    run_count = connection.execute(
        "SELECT COUNT(*) FROM provider_verification_runs"
    ).fetchone()[0]
    invalid_effect = connection.execute(
        "SELECT COUNT(*) FROM provider_verification_runs WHERE ranking_effect != 'none'"
    ).fetchone()[0]
    invalid_provider = connection.execute(
        """SELECT COUNT(*) FROM provider_verification_runs
           WHERE provider NOT IN ('naver','youtube','instagram')"""
    ).fetchone()[0]
    duplicate_groups = connection.execute(
        """SELECT COUNT(*) FROM (
             SELECT observed_at,trend_key,provider,COUNT(*) AS row_count
             FROM provider_verification_runs GROUP BY observed_at,trend_key,provider
             HAVING row_count > 1
           )"""
    ).fetchone()[0]
    latest_observed_at = connection.execute(
        "SELECT MAX(observed_at) FROM provider_verification_runs"
    ).fetchone()[0]
    latest_duplicate_groups = 0
    if latest_observed_at:
        latest_duplicate_groups = connection.execute(
            """SELECT COUNT(*) FROM (
                 SELECT trend_key,provider,COUNT(*) AS row_count
                 FROM provider_verification_runs WHERE observed_at=?
                 GROUP BY trend_key,provider HAVING row_count > 1
               )""",
            (latest_observed_at,),
        ).fetchone()[0]
    orphan_attempts = 0
    attempt_count_mismatch = 0
    youtube_search_cost_today = 0
    if _table_exists(connection, "provider_verification_attempts"):
        orphan_attempts = connection.execute(
            """SELECT COUNT(*) FROM provider_verification_attempts AS attempts
               LEFT JOIN provider_verification_runs AS runs ON runs.id=attempts.run_id
               WHERE runs.id IS NULL"""
        ).fetchone()[0]
        attempt_count_mismatch = connection.execute(
            """SELECT COUNT(*) FROM provider_verification_runs AS runs
               WHERE runs.attempt_count != (
                 SELECT COUNT(*) FROM provider_verification_attempts AS attempts
                 WHERE attempts.run_id=runs.id
               )"""
        ).fetchone()[0]
        kst_date = datetime.now(timezone.utc).astimezone(
            timezone(timedelta(hours=9))
        ).date().isoformat()
        youtube_search_cost_today = connection.execute(
            """SELECT COALESCE(SUM(quota_cost),0)
               FROM provider_verification_attempts
               WHERE quota_bucket='youtube_search_queries'
                 AND date(started_at, '+9 hours')=?""",
            (kst_date,),
        ).fetchone()[0]
    report.metrics["provider_verification"] = {
        "run_count": run_count,
        "duplicate_groups": duplicate_groups,
        "latest_duplicate_groups": latest_duplicate_groups,
        "invalid_ranking_effect_count": invalid_effect,
        "invalid_provider_count": invalid_provider,
        "orphan_attempt_count": orphan_attempts,
        "attempt_count_mismatch": attempt_count_mismatch,
        "youtube_search_cost_today": youtube_search_cost_today,
        "youtube_daily_search_budget": 96,
    }
    if invalid_effect:
        report.fail("provider_verification_affects_ranking")
    if invalid_provider:
        report.fail("provider_verification_unknown_provider")
    if orphan_attempts or attempt_count_mismatch:
        report.fail("provider_verification_ledger_referential_error")
    if latest_duplicate_groups:
        report.fail("provider_verification_latest_hour_duplicate")
    elif duplicate_groups:
        report.warn("provider_verification_historical_duplicates")
    if youtube_search_cost_today > 96:
        report.fail("youtube_daily_search_budget_exceeded")


def audit_runtime(runtime_root: Path) -> dict[str, Any]:
    report = AuditReport(checked_at=datetime.now(timezone.utc).isoformat())
    latest = runtime_root / "publication" / "latest"
    intelligence = _load_document(latest / "intelligence.json", report, "intelligence")
    metadata = _load_document(latest / "metadata.json", report, "metadata")
    status = _load_document(latest / "status.json", report, "status")
    if intelligence and metadata and status:
        _audit_bundle(intelligence, metadata, status, report)
        _audit_frontend_delivery(
            latest,
            intelligence,
            metadata,
            status,
            report,
        )
        _audit_ranking(intelligence, report)
    _audit_database(
        runtime_root / "data" / "trzip-hourly.sqlite3",
        report,
        intelligence,
        metadata,
    )
    return report.finalize()


def _human_lines(result: dict[str, Any]) -> Iterable[str]:
    yield f"TRZIP runtime audit: {result['status'].upper()}"
    metrics = result.get("metrics") or {}
    yield (
        f"ranking={metrics.get('unified_count', 0)} home={metrics.get('home_count', 0)} "
        f"history_hours={metrics.get('clean_history_hours', 0)} "
        f"sources={','.join(metrics.get('current_sources') or []) or '-'}"
    )
    for label, key in (("FAIL", "failures"), ("BLOCK", "blockers"), ("WARN", "warnings")):
        for code in result.get(key) or []:
            yield f"{label}: {code}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit the actual TRZIP laptop runtime")
    parser.add_argument("--runtime-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--require-combined", action="store_true")
    args = parser.parse_args(argv)
    result = audit_runtime(args.runtime_root or default_runtime_root())
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("\n".join(_human_lines(result)))
    if result["failures"]:
        return 1
    if args.require_combined and result["blockers"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
