from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


ALLOWED_RANKING_SOURCES = {"x", "google_trends"}
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

    public_text = json.dumps(documents, ensure_ascii=False)
    if any(pattern.search(public_text) for pattern in SECRET_PATTERNS):
        report.fail("public_bundle_contains_secret_or_local_path")


def _audit_ranking(intelligence: dict[str, Any], report: AuditReport) -> None:
    unified = intelligence.get("unified_ranking")
    home = intelligence.get("public_top10")
    if not isinstance(unified, list) or not isinstance(home, list):
        report.fail("ranking_not_array")
        return

    report.metrics["unified_count"] = len(unified)
    report.metrics["home_count"] = len(home)
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
        component_keys = (
            "rrf_points",
            "momentum_points",
            "persistence_points",
            "cross_source_points",
        )
        if not all(isinstance(components.get(key), (int, float)) for key in component_keys):
            score_mismatch_count += 1
        else:
            total = round(sum(float(components[key]) for key in component_keys), 2)
            if total != score or total != float(components.get("total_points", -1)):
                score_mismatch_count += 1
        if components.get("formula_version") != "rrf60_momentum20_persistence15_cross5_v1":
            score_mismatch_count += 1
        if components.get("rounding_policy") != "each_component_2dp_then_sum_2dp":
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

    home_failures = 0
    home_company_counts: dict[str, int] = {}
    for item in home:
        if not isinstance(item, dict):
            home_failures += 1
            continue
        name = str(item.get("display_name") or item.get("topic") or item.get("event_key"))
        event_key = str(item.get("event_key") or "")
        if event_key not in unified_rank_by_key or unified_rank_by_key[event_key] != item.get("rank"):
            home_failures += 1
        keywords = item.get("keywords") or []
        companies = item.get("companies") or []
        home_company_counts[name] = len(companies)
        if len(keywords) != 5 or any(keyword.get("affects_score") is not False for keyword in keywords):
            home_failures += 1
        if len(companies) < 5:
            home_failures += 1
        resolution = item.get("company_resolution") or {}
        if resolution.get("publish_status") != "published" or resolution.get("minimum_gold_companies") != 5:
            home_failures += 1
        tickers = [str(company.get("stock_code") or "") for company in companies]
        if not all(tickers) or len(tickers) != len(set(tickers)):
            home_failures += 1
        for company in companies:
            identity = company.get("official_identity") or {}
            if identity.get("status") != "verified" or identity.get("ranking_effect") != "none":
                home_failures += 1
            if company.get("ontology_complete") is not True:
                home_failures += 1
            evidence = company.get("evidence_sources") or []
            path = company.get("ontology_path") or []
            if not evidence or len(path) < 2:
                home_failures += 1
            if any(edge.get("review_status") not in {"observed", "approved"} or not edge.get("evidence_urls") for edge in path):
                home_failures += 1
    if home_failures:
        report.fail("home_quality_gate_failed")
    report.metrics["home_quality_failure_count"] = home_failures
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
        report.metrics["v3_source_hour_count"] = len(rows)
        report.metrics["clean_history_hours"] = len({row[0] for row in rows})
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
        for _, source, count, minimum, maximum, distinct_count, _ in rows:
            if source not in ALLOWED_RANKING_SOURCES:
                report.fail("v3_database_contains_disallowed_source")
            if minimum != 1 or maximum != count or distinct_count != count:
                report.fail("v3_source_hour_rank_incomplete")
        current_sources = {row[1] for row in rows}
        if "google_trends" not in current_sources:
            report.fail("google_v3_history_missing")
        if "x" not in current_sources:
            report.block("x_v3_history_missing")
        if report.metrics["clean_history_hours"] < 96:
            report.block("clean_history_under_96_hours")
        v3_row_count = sum(int(row[2]) for row in rows)
        coverage = metadata.get("coverage") or {}
        expected_first = min((row[0] for row in rows), default=None)
        expected_last = max((row[0] for row in rows), default=None)
        if (
            coverage.get("rows") != v3_row_count
            or coverage.get("observed_rows") != v3_row_count
            or coverage.get("hours") != report.metrics["clean_history_hours"]
            or coverage.get("first_hour") != expected_first
            or coverage.get("last_hour") != expected_last
        ):
            report.fail("published_coverage_does_not_match_sqlite")
        current_observed_at = metadata.get("observed_at")
        latest_rows = [row for row in rows if row[0] == current_observed_at]
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
