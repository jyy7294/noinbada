"""Build and validate the static data contract published by the local runtime."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .hourly_store import HourlyObservation, collect_current, coverage, floor_hour, latest_audit
from .intelligence import build_intelligence
from .company_adapters import pykrx_stock
from .normalization_evaluation import evaluate_regression_set
from .provider_verification import (
    TrendReference,
    latest_verification_by_trend,
    mark_news_candidate_core_observed,
    persist_news_discovery,
    read_news_discovery_queue,
    verify_terms,
)


NEWS_DISCOVERY_SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "news_discovery_seed.json"


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _refresh_verification_layer(intelligence: dict, database_path: Path, at: datetime) -> dict:
    """Collect bounded context evidence without changing score or rank.

    Provider failures are recorded as data states and never block publication.
    Only the main presentation subset is queried to keep quotas bounded.
    """

    ranking_before = [
        (item.get("event_key"), item.get("rank"), item.get("score"))
        for item in intelligence.get("unified_ranking", [])
    ]
    references = [
        TrendReference(
            trend_key=str(item["event_key"]),
            representative_term=str(item["display_name"]),
        )
        for item in intelligence.get("public_top10", [])[:10]
        if item.get("event_key") and item.get("display_name")
    ]
    run_status = "skipped_no_main_candidates"
    error = None
    if references:
        try:
            verify_terms(
                references,
                path=database_path,
                at=at,
                naver_term_limit=10,
                youtube_term_limit=3,
            )
            run_status = "completed"
        except Exception as exc:  # verification must not take down the core collector
            run_status = "failed_non_blocking"
            error = f"{type(exc).__name__}: {exc}"

    latest = latest_verification_by_trend(database_path)
    for item in intelligence.get("unified_ranking", []):
        record = latest.get(str(item.get("event_key")), {})
        providers = record.get("providers", {})
        item["verification_layer"] = {
            **record,
            "status": (
                "observed"
                if any(row.get("matched") for row in providers.values())
                else "unavailable"
                if providers
                else "not_run"
            ),
            "observed_platforms": sorted(
                provider for provider, row in providers.items() if row.get("matched")
            ),
            "affects_score": False,
        }
    ranking_after = [
        (item.get("event_key"), item.get("rank"), item.get("score"))
        for item in intelligence.get("unified_ranking", [])
    ]
    if ranking_before != ranking_after:
        raise ValueError("verification must not mutate X+Google ranking")
    intelligence["verification_run"] = {
        "status": run_status,
        "requested_terms": len(references),
        "providers": ["naver", "youtube", "instagram"],
        "ranking_effect": "none",
        "error": error,
    }
    return intelligence


def _seed_news_discovery(database_path: Path) -> list[dict]:
    """Idempotently load reviewed article discoveries into the separate queue."""

    records = _read_json(NEWS_DISCOVERY_SEED_PATH, [])
    if records:
        persist_news_discovery(records, database_path)
    return read_news_discovery_queue(database_path)


def _refresh_news_core_gate(
    queue: list[dict],
    rows: list[HourlyObservation],
    database_path: Path,
    at: datetime,
) -> list[dict]:
    """Link article discoveries only after the exact term is seen by X/Google."""

    observed_by_term: dict[str, set[str]] = {}
    for row in rows:
        key = "".join(row.topic.casefold().split())
        observed_by_term.setdefault(key, set()).add(row.source)
    for candidate in queue:
        key = "".join(str(candidate.get("observed_term") or "").casefold().split())
        for source in observed_by_term.get(key, set()):
            mark_news_candidate_core_observed(
                path=database_path,
                observed_term=str(candidate["observed_term"]),
                source=source,
                observed_at=at,
            )
    return read_news_discovery_queue(database_path)


def _validate_contract(intelligence: dict, metadata: dict, status: dict | None = None) -> None:
    documents = [intelligence, metadata] + ([status] if status is not None else [])
    if any(document.get("mode") != "live" for document in documents):
        raise ValueError("Production output must be marked live")
    publication_ids = {document.get("publication_id") for document in documents}
    if None in publication_ids or len(publication_ids) != 1:
        raise ValueError("All publication documents must share one publication_id")
    generated_at = {document.get("generated_at") for document in documents}
    if None in generated_at or len(generated_at) != 1:
        raise ValueError("All publication documents must share one generated_at")
    observed_at = {
        intelligence.get("window", {}).get("to"),
        metadata.get("observed_at"),
    }
    if status is not None:
        observed_at.add(status.get("observed_at"))
    if None in observed_at or len(observed_at) != 1:
        raise ValueError("All publication documents must describe one observation window")
    collection = metadata["collection"]
    if collection.get("rank_sources") != ["x", "google_trends"]:
        raise ValueError("Production rank sources must be X and Google Trends only")
    if "trends_mcp_used" in collection or "generated" in collection:
        raise ValueError("Legacy collection flags are not allowed in the v3 contract")
    ranking = intelligence.get("unified_ranking", [])
    if [item.get("rank") for item in ranking] != list(range(1, len(ranking) + 1)):
        raise ValueError("Unified ranking must have continuous ranks")
    if any("generated" in item.get("provenance", []) for item in ranking):
        raise ValueError("Generated observations cannot enter the live ranking")
    for item in ranking:
        published_companies = item.get("companies", [])
        company_status = item.get("company_resolution", {}).get("publish_status")
        unique_stocks = {
            str(company.get("stock_code") or "").strip()
            for company in published_companies
            if str(company.get("stock_code") or "").strip()
        }
        if company_status == "published" and len(unique_stocks) < 5:
            raise ValueError("Published company Gold requires five unique listed stocks")
        if published_companies and company_status != "published":
            raise ValueError("Non-published company status cannot expose Gold companies")
        if any(not company.get("ontology_complete") for company in published_companies):
            raise ValueError("Published companies require complete ontology paths")
        for company in published_companies:
            if not company.get("relation_display_type") or not company.get("team_review_status"):
                raise ValueError(
                    f"Every company requires relation and review labels: {item.get('display_name')}"
                )
        for company in published_companies:
            if (company.get("verification_status") == "pending_evidence"
                    and company.get("opportunity_status") == "confirmed_relationship"):
                raise ValueError(
                    f"Pending evidence cannot be a confirmed relationship: {company.get('company')}"
                )


def _previous_market_by_code(payload: dict) -> dict[str, dict]:
    cache: dict[str, dict] = {}
    for trend in payload.get("unified_ranking", []):
        for company in trend.get("company_candidates", trend.get("companies", [])):
            code = company.get("stock_code")
            market = company.get("market_reference")
            if code and isinstance(market, dict) and market.get("status") == "observed":
                cache[code] = market
    return cache


def _fresh_market_reference(market: dict, at: datetime) -> bool:
    as_of = (market.get("summary") or {}).get("as_of")
    if not as_of:
        return False
    try:
        age = at.date() - datetime.strptime(as_of, "%Y-%m-%d").date()
    except ValueError:
        return False
    return 0 <= age.days <= 4


def _enrich_market_references(intelligence: dict, previous: dict, at: datetime) -> dict:
    """Attach verified daily market references to every listed company candidate.

    The previous production payload is reused while its latest trading date is
    fresh, so the hourly trend job does not repeatedly call the daily provider.
    Provider failures are explicit data states and never abort trend publishing.
    """
    cache = _previous_market_by_code(previous)
    requested: set[str] = set()
    reused = observed = unavailable = 0
    for trend in intelligence.get("unified_ranking", []):
        for company in trend.get("company_candidates", trend.get("companies", [])):
            code = company.get("stock_code")
            if not code or company.get("strength") == "excluded":
                company["market_reference"] = {
                    "status": "not_applicable",
                    "reason": "listed stock code unavailable or relation excluded",
                }
                continue
            market = cache.get(code)
            if market and _fresh_market_reference(market, at):
                reused += 1
            else:
                market = pykrx_stock(code, at.strftime("%Y%m%d"), lookback_days=21)
                requested.add(code)
                if market.get("status") == "observed":
                    cache[code] = market
                    observed += 1
                else:
                    unavailable += 1
            company["market_reference"] = market
    intelligence["market_data_status"] = {
        "provider": "pykrx",
        "kind": "daily_reference_not_realtime",
        "requested_stock_codes": len(requested),
        "newly_observed": observed,
        "reused_company_rows": reused,
        "unavailable_company_rows": unavailable,
    }
    return intelligence


def _prune_observations(root: Path, at: datetime, retention_days: int) -> int:
    if retention_days <= 0:
        return 0
    cutoff = (at - timedelta(days=retention_days - 1)).date().isoformat()
    removed = 0
    for path in (root / "observations").glob("*.json"):
        if path.stem < cutoff:
            path.unlink()
            removed += 1
    return removed


def _failure_class(detail: str) -> str:
    value = str(detail or "").casefold()
    if any(marker in value for marker in ("auth_required", "login", "로그인")):
        return "browser_authentication"
    if "region_unverified" in value:
        return "region_configuration"
    if any(marker in value for marker in ("selector_changed", "data-testid=trend")):
        return "browser_page_change"
    if any(marker in value for marker in ("401", "403", "unauthorized", "forbidden", "credential", "not configured")):
        return "api_authentication"
    if any(marker in value for marker in ("429", "quota", "rate limit", "too many requests")):
        return "quota_or_rate_limit"
    if any(marker in value for marker in ("timeout", "timed out", "dns", "connection", "network", "urlerror")):
        return "network"
    if any(marker in value for marker in ("parse", "parser", "jsondecode", "xml", "syntax")):
        return "parser_change"
    return "unknown"


def _collection_health(root: Path, at: datetime, collection: dict,
                       started_at: datetime, finished_at: datetime) -> dict:
    """Persist up to seven days of scheduler evidence instead of claiming uptime early."""
    history_path = root / "monitoring" / "run_history.json"
    history = _read_json(history_path, [])
    audit = collection.get("audit", {})
    source_ok = {
        "x": audit.get("x_korea_realtime", {}).get("status") == "observed",
        "google_trends": audit.get("google_geo_kr", {}).get("status") == "observed",
    }
    success = collection.get("observed", 0) > 0 and not collection.get("errors") and all(source_ok.values())
    source_failures = {}
    for source, ok in source_ok.items():
        if ok:
            continue
        audit_key = "x_korea_realtime" if source == "x" else "google_geo_kr"
        detail = collection.get("errors", {}).get(source) or audit.get(audit_key, {}).get("detail") or "unknown"
        source_failures[source] = {"class": _failure_class(detail), "detail": detail}
    current = {
        "scheduled_at": at.isoformat(),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "delay_seconds": max(0, round((started_at - at).total_seconds())),
        "duration_seconds": max(0, round((finished_at - started_at).total_seconds(), 2)),
        "success": success,
        "source_success": source_ok,
        "observed_rows": collection.get("observed", 0),
        "errors": collection.get("errors", {}),
        "source_failures": source_failures,
    }
    history = [row for row in history if row.get("scheduled_at") != at.isoformat()]
    history.append(current)
    history = sorted(history, key=lambda row: row["scheduled_at"])[-168:]
    _write_json(history_path, history)
    total = len(history)
    successes = sum(bool(row.get("success")) for row in history)
    source_rates = {
        source: round(sum(bool(row.get("source_success", {}).get(source)) for row in history) / total, 4)
        if total else None for source in ("x", "google_trends")
    }
    failure_counts = {
        source: {
            failure_class: sum(
                row.get("source_failures", {}).get(source, {}).get("class") == failure_class
                for row in history
            )
            for failure_class in (
                "browser_authentication", "region_configuration", "browser_page_change",
                "api_authentication", "quota_or_rate_limit", "network", "parser_change", "unknown",
            )
        }
        for source in ("x", "google_trends")
    }
    health = {
        "measurement_window_hours": 168,
        "recorded_runs": total,
        "successful_runs": successes,
        "success_rate": round(successes / total, 4) if total else None,
        "source_success_rate": source_rates,
        "source_failure_counts": failure_counts,
        "target_source_success_rate": 0.95,
        "source_targets_met": {
            source: bool(rate is not None and total >= 168 and rate >= 0.95)
            for source, rate in source_rates.items()
        },
        "on_time_within_15m_rate": round(sum(row.get("delay_seconds", 999999) <= 900 for row in history) / total, 4)
        if total else None,
        "latest_delay_seconds": current["delay_seconds"],
        "latest_duration_seconds": current["duration_seconds"],
        "status": "measured_7d" if total >= 168 else "measuring_3_to_7_days" if total >= 72 else "collecting_baseline",
        "remaining_runs_for_3d": max(0, 72 - total),
        "remaining_runs_for_7d": max(0, 168 - total),
        "warning": "Windows 작업 스케줄러 실측 기록이며 노트북 종료·로그아웃 중에는 실행되지 않을 수 있음",
    }
    _write_json(root / "monitoring" / "latest.json", health)
    return health


def _merge_daily(root: Path, rows: list[HourlyObservation], at: datetime) -> Path:
    daily_path = root / "observations" / f"{at.date().isoformat()}.json"
    stamp = at.isoformat()
    existing = [item for item in _read_json(daily_path, []) if item["observed_at"] != stamp]
    merged = {
        (
            item["observed_at"], item["source"], item["source_rank"],
            item["topic"], item["provenance"],
        ): item
        for item in existing
    }
    for row in rows:
        item = asdict(row)
        merged[
            (row.observed_at, row.source, row.source_rank, row.topic, row.provenance)
        ] = item
    ordered = sorted(merged.values(), key=lambda item: (
        item["observed_at"], item["source"], item["source_rank"], item["topic"]
    ))
    _write_json(daily_path, ordered)
    return daily_path


def run(root: Path, *, retention_days: int = 0, database_path: Path | None = None,
        now: datetime | None = None) -> dict:
    """Run the laptop-owned pipeline and write the static publication contract."""
    root.mkdir(parents=True, exist_ok=True)
    database_path = database_path or root / ".runtime" / "trzip-hourly.sqlite3"
    at = floor_hour(now or datetime.now(UTC))
    started_at = datetime.now(UTC)
    # Capture the last verified same-hour audit before a retry can record its
    # own failure. This keeps the provenance of an already persisted snapshot
    # while still reporting a genuine failure when no usable rows exist.
    persisted_audit = latest_audit(at, database_path)
    collection = collect_current(database_path, at)

    from .hourly_store import snapshot
    current_rows = [HourlyObservation(**item) for item in snapshot(at, database_path)]
    persisted_source_counts = {
        source: sum(row.source == source and row.provenance == "observed" for row in current_rows)
        for source in ("x", "google_trends")
    }
    audit_keys = {"x": "x_korea_realtime", "google_trends": "google_geo_kr"}
    for source, count in persisted_source_counts.items():
        audit_key = audit_keys[source]
        if count <= 0 or collection.get("audit", {}).get(audit_key, {}).get("status") == "observed":
            continue
        previous = persisted_audit.get(audit_key, {})
        previous_detail = str(previous.get("detail") or "")
        if previous.get("status") != "observed":
            previous_detail = ""
        collection.setdefault("audit", {})[audit_key] = {
            "status": "observed",
            "row_count": count,
            "detail": previous_detail or "valid same-hour snapshot preserved after collector retry failure",
        }
        collection.get("errors", {}).pop(source, None)
    collection["observed"] = sum(persisted_source_counts.values())
    daily_path = _merge_daily(root, current_rows, at)
    pruned_files = _prune_observations(root, at, retention_days)
    news_queue = _refresh_news_core_gate(
        _seed_news_discovery(database_path),
        current_rows,
        database_path,
        at,
    )
    news_context_by_term = {
        str(item["observed_term"]): item
        for item in news_queue
        if item.get("core_source_gate") == "satisfied_by_x_or_google"
    }
    intelligence = build_intelligence(
        at,
        hours=168,
        path=database_path,
        news_context_by_term=news_context_by_term,
    )
    intelligence = _refresh_verification_layer(intelligence, database_path, at)
    intelligence["news_discovery_queue"] = news_queue
    normalization_evaluation = evaluate_regression_set()
    intelligence["normalization_regression_evaluation"] = normalization_evaluation
    previous_intelligence = _read_json(root / "latest" / "intelligence.json", {})
    intelligence = _enrich_market_references(intelligence, previous_intelligence, at)
    stats = coverage(database_path)

    finished_at = datetime.now(UTC)
    collection_health = _collection_health(root, at, collection, started_at, finished_at)
    intelligence["collection_health"] = collection_health
    intelligence["collection_status"] = {
        "observed_at": collection.get("observed_at"),
        "observed_rows": collection.get("observed", 0),
        "source_status": {
            "x": collection.get("audit", {}).get("x_korea_realtime", {}).get("status", "unknown"),
            "google_trends": collection.get("audit", {}).get("google_geo_kr", {}).get("status", "unknown"),
        },
        "errors": collection.get("errors", {}),
        "partial": bool(collection.get("errors")) or any(
            collection.get("audit", {}).get(key, {}).get("status") != "observed"
            for key in ("x_korea_realtime", "google_geo_kr")
        ),
    }

    generated_at = datetime.now(UTC).isoformat()
    publication_id = f"pub-{uuid4().hex}"
    intelligence["publication_id"] = publication_id
    intelligence["generated_at"] = generated_at
    metadata = {
        "schema_version": "trzip-live-data-v3",
        "publication_id": publication_id,
        "generated_at": generated_at,
        "observed_at": at.isoformat(),
        "mode": "live",
        "storage": "local-sqlite-published-to-live-data",
        "retention_days": retention_days if retention_days > 0 else None,
        "retention_policy": "bounded" if retention_days > 0 else "indefinite",
        "history_rows_loaded": 0,
        "pruned_observation_files": pruned_files,
        "daily_file": daily_path.relative_to(root).as_posix(),
        "collection": collection,
        "coverage": stats,
        "market_data": intelligence["market_data_status"],
        "collection_health": collection_health,
    }
    status = {
        "schema_version": "trzip-runtime-status-v1",
        "publication_id": publication_id,
        "generated_at": generated_at,
        "observed_at": metadata["observed_at"],
        "mode": "live",
        "partial": intelligence["collection_status"]["partial"],
        "source_status": intelligence["collection_status"]["source_status"],
        "errors": intelligence["collection_status"]["errors"],
        "recorded_runs": collection_health["recorded_runs"],
        "measurement_status": collection_health["status"],
    }
    _validate_contract(intelligence, metadata, status)
    _write_json(root / "latest" / "intelligence.json", intelligence)
    _write_json(root / "latest" / "normalization_evaluation.json", normalization_evaluation)
    _write_json(root / "latest" / "coverage.json", stats)
    _write_json(root / "latest" / "metadata.json", metadata)
    _write_json(root / "latest" / "status.json", status)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Build TRZIP laptop-owned live data")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database", type=Path)
    parser.add_argument(
        "--retention-days", type=int, default=0,
        help="positive days enables pruning; 0 preserves raw history indefinitely",
    )
    args = parser.parse_args()
    result = run(
        args.output,
        retention_days=max(0, args.retention_days),
        database_path=args.database,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
