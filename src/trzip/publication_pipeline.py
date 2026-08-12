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
    verification_trend_keys_at,
    verify_terms,
)


NEWS_DISCOVERY_SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "news_discovery_seed.json"
DEFAULT_HOURLY_VERIFICATION_TERM_LIMIT = 3
MAX_HOURLY_VERIFICATION_TERM_LIMIT = 3
MONITORING_CONTRACT_VERSION = "trzip-v3-hourly"


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _hourly_verification_term_limit(environment: dict[str, str] | None = None) -> int:
    source = os.environ if environment is None else environment
    raw = str(source.get("TRZIP_PROVIDER_VERIFICATION_TERM_LIMIT", "")).strip()
    try:
        requested = int(raw) if raw else DEFAULT_HOURLY_VERIFICATION_TERM_LIMIT
    except ValueError:
        requested = DEFAULT_HOURLY_VERIFICATION_TERM_LIMIT
    return min(MAX_HOURLY_VERIFICATION_TERM_LIMIT, max(0, requested))


def _public_verification_references(
    intelligence: dict,
    *,
    limit: int,
) -> list[TrendReference]:
    """Select the highest displayed X/Google trends without inventing terms."""

    if limit <= 0:
        return []
    candidates = sorted(
        intelligence.get("public_top10", []),
        key=lambda item: int(item.get("rank") or 10**9),
    )
    references: list[TrendReference] = []
    seen: set[str] = set()
    for item in candidates:
        source_ranks = item.get("latest_source_ranks") or {}
        if not any(source in source_ranks for source in ("x", "google_trends")):
            continue
        event_key = str(item.get("event_key") or "").strip()
        representative_term = str(item.get("display_name") or "").strip()
        if not event_key or not representative_term or event_key in seen:
            continue
        seen.add(event_key)
        references.append(TrendReference(event_key, representative_term))
        if len(references) >= limit:
            break
    return references


def _refresh_verification_layer(intelligence: dict, database_path: Path, at: datetime) -> dict:
    """Collect bounded context evidence without changing score or rank.

    Provider failures are recorded as data states and never block publication.
    Only the top three trends displayed in the current public list are queried each hour. A
    retry of the same observation hour reuses the append-only ledger.
    """

    ranking_before = [
        (item.get("event_key"), item.get("rank"), item.get("score"))
        for item in intelligence.get("unified_ranking", [])
    ]
    hourly_limit = _hourly_verification_term_limit()
    references = _public_verification_references(intelligence, limit=hourly_limit)
    pending_references = list(references)
    run_status = "skipped_no_public_candidates"
    attempted_term_count = 0
    error = None
    try:
        completed_this_hour = verification_trend_keys_at(database_path, at)
        pending_references = [
            reference for reference in references
            if reference.trend_key not in completed_this_hour
        ]
        if references and not pending_references:
            run_status = "skipped_already_recorded_for_hour"
        elif pending_references:
            attempted_term_count = len(pending_references)
            verify_terms(
                pending_references,
                path=database_path,
                at=at,
                naver_term_limit=len(pending_references),
                youtube_term_limit=len(pending_references),
            )
            run_status = "completed"
    except Exception as exc:  # verification must not take down the core collector
        run_status = "failed_non_blocking"
        error = "provider_verification_failed"

    try:
        latest = latest_verification_by_trend(database_path)
    except Exception as exc:  # a provider-ledger read is non-critical too
        latest = {}
        run_status = "failed_non_blocking"
        error = "provider_verification_ledger_unavailable"
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
        "attempted_terms": attempted_term_count,
        "hourly_term_limit": hourly_limit,
        "providers": ["naver", "youtube", "instagram"],
        "ranking_effect": "none",
        "affects_collection_partial": False,
        "blocks_publication": False,
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


def _public_market_reference(market: object, stock_code: str) -> dict:
    """Allowlist pykrx output and replace exception text with stable codes."""

    value = market if isinstance(market, dict) else {}
    status = str(value.get("status") or "unavailable")
    if status != "observed":
        safe_status = status if status in {
            "invalid", "not_found", "error", "unavailable", "not_applicable"
        } else "unavailable"
        return {
            "status": safe_status,
            "stock_code": str(value.get("stock_code") or stock_code),
            "reason": f"market_reference_{safe_status}",
        }
    return {
        "status": "observed",
        "provider": "pykrx",
        "stock_code": str(value.get("stock_code") or stock_code),
        "name": value.get("name"),
        "daily_ohlcv": list(value.get("daily_ohlcv") or []),
        "latest_daily": value.get("latest_daily"),
        "summary": dict(value.get("summary") or {}),
        "market_reaction": dict(value.get("market_reaction") or {}),
        "note": "daily reference data; not realtime, not a forecast, and not relation evidence",
    }


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
            company["market_reference"] = _public_market_reference(market, code)
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


PUBLIC_SOURCE_FAILURE_CODES = frozenset({
    "extension_not_ready",
    "auth_required",
    "selector_changed",
    "empty",
    "region_unverified",
    "incomplete_scroll",
    "snapshot_invalid",
    "snapshot_stale",
    "unavailable",
    "api_authentication",
    "quota_or_rate_limit",
    "network",
    "parser_change",
    "unknown",
})
PUBLIC_FAILURE_CLASSES = frozenset({
    "browser_authentication", "region_configuration", "browser_page_change",
    "api_authentication", "quota_or_rate_limit", "network", "parser_change", "unknown",
})


def _public_iso_timestamp(value: object) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    if parsed.tzinfo is None:
        return ""
    return parsed.astimezone(UTC).isoformat()


def _nonnegative_number(value: object, *, floating: bool = False) -> int | float:
    try:
        parsed = float(value) if floating else int(value)
    except (TypeError, ValueError):
        return 0.0 if floating else 0
    return max(0.0, parsed) if floating else max(0, parsed)


def _public_source_status(source: str, detail: object, raw_status: object = None) -> str:
    """Reduce operational exceptions to an allowlisted public status code."""

    status = str(raw_status or "").strip().casefold()
    if status == "observed":
        return "observed"
    if status in PUBLIC_SOURCE_FAILURE_CODES:
        return status
    value = str(detail or "").casefold()
    if source == "x":
        for code in (
            "extension_not_ready", "auth_required", "selector_changed", "empty",
            "region_unverified", "incomplete_scroll", "snapshot_invalid", "snapshot_stale",
        ):
            if code in value:
                return code
    failure_class = _failure_class(value)
    if failure_class != "unknown":
        return failure_class
    if "not configured" in value or "no rows" in value:
        return "unavailable"
    return "unknown"


def _sanitize_collection_for_public(collection: dict) -> dict:
    """Build an allowlist-only collection block for JSON publication.

    Raw exception details remain in SQLite ``collection_audit``. Public static
    files expose only stable status codes and counts, never laptop paths,
    request URLs/query strings, credentials, or arbitrary exception text.
    """

    raw_audit = collection.get("audit", {}) if isinstance(collection, dict) else {}
    audit: dict[str, dict] = {}
    for source, key in (("x", "x_korea_realtime"), ("google_trends", "google_geo_kr")):
        item = raw_audit.get(key, {}) if isinstance(raw_audit, dict) else {}
        item = item if isinstance(item, dict) else {}
        raw_error = (collection.get("errors", {}) or {}).get(source)
        code = _public_source_status(source, raw_error or item.get("detail"), item.get("status"))
        row_count = _nonnegative_number(item.get("row_count"))
        public_item = {
            "status": code,
            "row_count": row_count,
            "detail": "verified_current_hour_snapshot" if code == "observed" else code,
        }
        if source == "google_trends":
            declared_total = _nonnegative_number(item.get("declared_total"))
            page_count = _nonnegative_number(item.get("page_count"))
            completion_verified = bool(item.get("completion_verified"))
            public_item.update({
                "declared_total": declared_total,
                "page_count": page_count,
                "completion_verified": completion_verified,
            })
        audit[key] = public_item
    errors = {
        source: audit[key]["status"]
        for source, key in (("x", "x_korea_realtime"), ("google_trends", "google_geo_kr"))
        if audit[key]["status"] != "observed"
    }
    return {
        "observed": _nonnegative_number(collection.get("observed")),
        "errors": errors,
        "rank_sources": ["x", "google_trends"],
        "audit": audit,
        "observed_at": _public_iso_timestamp(collection.get("observed_at")),
    }


def _sanitize_health_history_row(row: dict) -> dict:
    source_success = row.get("source_success", {}) if isinstance(row, dict) else {}
    source_success = source_success if isinstance(source_success, dict) else {}
    raw_failures = row.get("source_failures", {}) if isinstance(row, dict) else {}
    failures = {}
    for source in ("x", "google_trends"):
        failure = raw_failures.get(source, {}) if isinstance(raw_failures, dict) else {}
        if bool(source_success.get(source)):
            continue
        code = _public_source_status(
            source,
            (failure if isinstance(failure, dict) else {}).get("detail"),
            (failure if isinstance(failure, dict) else {}).get("detail"),
        )
        raw_class = str((failure if isinstance(failure, dict) else {}).get("class") or "")
        failure_class = raw_class if raw_class in PUBLIC_FAILURE_CLASSES else _failure_class(code)
        failures[source] = {"class": failure_class, "detail": code}
    return {
        "contract_version": MONITORING_CONTRACT_VERSION,
        "scheduled_at": _public_iso_timestamp(row.get("scheduled_at")),
        "started_at": _public_iso_timestamp(row.get("started_at")),
        "finished_at": _public_iso_timestamp(row.get("finished_at")),
        "delay_seconds": _nonnegative_number(row.get("delay_seconds")),
        "duration_seconds": _nonnegative_number(row.get("duration_seconds"), floating=True),
        "success": bool(row.get("success")),
        "source_success": {
            source: bool(source_success.get(source))
            for source in ("x", "google_trends")
        },
        "observed_rows": _nonnegative_number(row.get("observed_rows")),
        "errors": {source: failure["detail"] for source, failure in failures.items()},
        "source_failures": failures,
    }


def _collection_health(root: Path, at: datetime, collection: dict,
                       started_at: datetime, finished_at: datetime) -> dict:
    """Persist up to seven days of scheduler evidence instead of claiming uptime early."""
    history_path = root / "monitoring" / "run_history.json"
    # A v2 run cannot prove that the current X/Google collectors completed.
    # Keep the public baseline pure by dropping unversioned legacy rows rather
    # than carrying their historical success flags into v3 reliability rates.
    history = [
        _sanitize_health_history_row(row)
        for row in _read_json(history_path, [])
        if isinstance(row, dict)
        and row.get("contract_version") == MONITORING_CONTRACT_VERSION
    ]
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
        code = _public_source_status(source, detail, audit.get(audit_key, {}).get("status"))
        source_failures[source] = {"class": _failure_class(detail), "detail": code}
    current = {
        "contract_version": MONITORING_CONTRACT_VERSION,
        "scheduled_at": at.isoformat(),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "delay_seconds": max(0, round((started_at - at).total_seconds())),
        "duration_seconds": max(0, round((finished_at - started_at).total_seconds(), 2)),
        "success": success,
        "source_success": source_ok,
        "observed_rows": collection.get("observed", 0),
        "errors": {source: row["detail"] for source, row in source_failures.items()},
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
    public_collection = _sanitize_collection_for_public(collection)
    intelligence["collection_health"] = collection_health
    intelligence["collection_status"] = {
        "observed_at": public_collection.get("observed_at"),
        "observed_rows": public_collection.get("observed", 0),
        "source_status": {
            "x": public_collection["audit"]["x_korea_realtime"]["status"],
            "google_trends": public_collection["audit"]["google_geo_kr"]["status"],
        },
        "errors": public_collection.get("errors", {}),
        "partial": bool(public_collection.get("errors")) or any(
            public_collection.get("audit", {}).get(key, {}).get("status") != "observed"
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
        "collection": public_collection,
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
