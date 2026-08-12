from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .hourly_store import HourlyObservation, collect_current, connect, coverage, floor_hour, upsert
from .intelligence import build_intelligence
from .company_adapters import pykrx_stock


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _validate_contract(intelligence: dict, metadata: dict) -> None:
    if intelligence.get("mode") != "live" or metadata.get("mode") != "live":
        raise ValueError("GitHub production output must be marked live")
    collection = metadata["collection"]
    if collection.get("trends_mcp_used") or collection.get("generated"):
        raise ValueError("Production collection must not use Trends MCP or generated rows")
    ranking = intelligence.get("unified_ranking", [])
    if [item.get("rank") for item in ranking] != list(range(1, len(ranking) + 1)):
        raise ValueError("Unified ranking must have continuous ranks")
    if any("generated" in item.get("provenance", []) for item in ranking):
        raise ValueError("Generated observations cannot enter the live ranking")
    for item in ranking:
        if not item.get("company_eligible"):
            continue
        companies = item.get("companies", [])
        categories = {company.get("relation_category") for company in companies}
        if len(companies) < 3 or len(categories - {None}) < 3:
            raise ValueError(
                f"Company-eligible trend requires three companies and relation categories: "
                f"{item.get('display_name')}"
            )


def _previous_market_by_code(payload: dict) -> dict[str, dict]:
    cache: dict[str, dict] = {}
    for trend in payload.get("unified_ranking", []):
        for company in trend.get("companies", []):
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
        for company in trend.get("companies", []):
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


def _observation_files(root: Path, at: datetime, retention_days: int) -> list[Path]:
    start = (at - timedelta(days=retention_days - 1)).date().isoformat()
    end = at.date().isoformat()
    folder = root / "observations"
    return sorted(path for path in folder.glob("*.json") if start <= path.stem <= end)


def _prune_observations(root: Path, at: datetime, retention_days: int) -> int:
    cutoff = (at - timedelta(days=retention_days - 1)).date().isoformat()
    removed = 0
    for path in (root / "observations").glob("*.json"):
        if path.stem < cutoff:
            path.unlink()
            removed += 1
    return removed


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
    health = {
        "measurement_window_hours": 168,
        "recorded_runs": total,
        "successful_runs": successes,
        "success_rate": round(successes / total, 4) if total else None,
        "source_success_rate": source_rates,
        "on_time_within_15m_rate": round(sum(row.get("delay_seconds", 999999) <= 900 for row in history) / total, 4)
        if total else None,
        "latest_delay_seconds": current["delay_seconds"],
        "latest_duration_seconds": current["duration_seconds"],
        "status": "measured_7d" if total >= 168 else "measuring_3_to_7_days" if total >= 72 else "collecting_baseline",
        "remaining_runs_for_3d": max(0, 72 - total),
        "remaining_runs_for_7d": max(0, 168 - total),
        "warning": "GitHub Actions 예약 실행은 정각 시작을 보장하지 않으며 실제 지연시간으로 평가",
    }
    _write_json(root / "monitoring" / "latest.json", health)
    return health


def _load_history(root: Path, sqlite_path: Path, at: datetime, retention_days: int) -> int:
    rows: list[HourlyObservation] = []
    for path in _observation_files(root, at, retention_days):
        for item in _read_json(path, []):
            rows.append(HourlyObservation(**item))
    if rows:
        upsert(rows, sqlite_path)
    return len(rows)


def _clear_hour(sqlite_path: Path, at: datetime) -> None:
    stamp = at.isoformat()
    with connect(sqlite_path) as connection:
        connection.execute("DELETE FROM hourly_observations WHERE observed_at = ?", (stamp,))
        connection.execute("DELETE FROM collection_audit WHERE observed_at = ?", (stamp,))


def _merge_daily(root: Path, rows: list[HourlyObservation], at: datetime) -> Path:
    daily_path = root / "observations" / f"{at.date().isoformat()}.json"
    stamp = at.isoformat()
    existing = [item for item in _read_json(daily_path, []) if item["observed_at"] != stamp]
    merged = {
        (item["observed_at"], item["source"], item["topic"], item["provenance"]): item
        for item in existing
    }
    for row in rows:
        item = asdict(row)
        merged[(row.observed_at, row.source, row.topic, row.provenance)] = item
    ordered = sorted(merged.values(), key=lambda item: (
        item["observed_at"], item["source"], item["source_rank"], item["topic"]
    ))
    _write_json(daily_path, ordered)
    return daily_path


def run(root: Path, *, retention_days: int = 104) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    at = floor_hour(datetime.now(UTC))
    started_at = datetime.now(UTC)
    with tempfile.TemporaryDirectory(prefix="trzip-live-") as temporary:
        sqlite_path = Path(temporary) / "pipeline.sqlite3"
        historical_rows = _load_history(root, sqlite_path, at, retention_days)
        _clear_hour(sqlite_path, at)
        collection = collect_current(sqlite_path, at, use_trends_mcp=False)

        from .hourly_store import snapshot
        current_rows = [HourlyObservation(**item) for item in snapshot(at, sqlite_path)]
        daily_path = _merge_daily(root, current_rows, at)
        pruned_files = _prune_observations(root, at, retention_days)
        intelligence = build_intelligence(at, hours=168, path=sqlite_path)
        previous_intelligence = _read_json(root / "latest" / "intelligence.json", {})
        intelligence = _enrich_market_references(
            intelligence, previous_intelligence, at
        )
        stats = coverage(sqlite_path)

    finished_at = datetime.now(UTC)
    collection_health = _collection_health(root, at, collection, started_at, finished_at)
    intelligence["collection_health"] = collection_health

    metadata = {
        "schema_version": "github-live-data-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "observed_at": at.isoformat(),
        "mode": "live",
        "storage": "github-live-data-branch",
        "retention_days": retention_days,
        "history_rows_loaded": historical_rows,
        "pruned_observation_files": pruned_files,
        "daily_file": daily_path.relative_to(root).as_posix(),
        "collection": collection,
        "coverage": stats,
        "market_data": intelligence["market_data_status"],
        "collection_health": collection_health,
    }
    _validate_contract(intelligence, metadata)
    _write_json(root / "latest" / "intelligence.json", intelligence)
    _write_json(root / "latest" / "coverage.json", stats)
    _write_json(root / "latest" / "metadata.json", metadata)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Build TRZIP GitHub-hosted live data")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--retention-days", type=int, default=104)
    args = parser.parse_args()
    result = run(args.output, retention_days=max(7, args.retention_days))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
