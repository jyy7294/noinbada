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
        stats = coverage(sqlite_path)

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
