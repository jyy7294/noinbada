"""Build an auditable rolling source-only flow from valid SQLite snapshots."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trzip.event_resolution import normalize_event_key
from trzip.x_only_preview import classify_source_topic


def parse_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--observed-at must include a timezone")
    return parsed.astimezone(UTC)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--source", choices=("x", "google_trends"), required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--hours", type=int, default=48)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    end = parse_at(args.observed_at)
    start = end - timedelta(hours=max(1, args.hours))
    min_rows = 30 if args.source == "x" else 100
    exact_rows = 30 if args.source == "x" else None
    with sqlite3.connect(args.database) as connection:
        snapshot_rows = connection.execute(
            """SELECT observed_at, COUNT(*) AS row_count
               FROM hourly_observations
               WHERE source=? AND provenance='observed' AND observed_at BETWEEN ? AND ?
               GROUP BY observed_at ORDER BY observed_at""",
            (args.source, start.isoformat(), end.isoformat()),
        ).fetchall()
        if exact_rows is not None:
            valid_times = [
                observed_at for observed_at, row_count in snapshot_rows
                if int(row_count) == exact_rows
            ]
        else:
            valid_times = [
                observed_at for observed_at, row_count in snapshot_rows
                if int(row_count) >= min_rows
            ]
        placeholders = ",".join("?" for _ in valid_times) or "NULL"
        rows = connection.execute(
            f"""SELECT observed_at, topic, source_rank
                FROM hourly_observations
                WHERE source=? AND provenance='observed' AND observed_at IN ({placeholders})
                ORDER BY observed_at, source_rank, topic""",
            (args.source, *valid_times),
        ).fetchall() if valid_times else []

    current_time = end.isoformat()
    grouped: dict[str, dict] = {}
    for observed_at, topic, source_rank in rows:
        display_name = " ".join(str(topic).split())
        # Apply the same deterministic presentation normalization used by the
        # main event resolver: hashtag, spacing and Unicode variants become a
        # single source event before any exclusion decision is made.
        key = normalize_event_key(display_name)
        entry = grouped.setdefault(key, {
            "display_name": display_name, "raw_terms": [], "observed_at": [], "source_ranks": [],
        })
        if display_name not in entry["raw_terms"]:
            entry["raw_terms"].append(display_name)
        entry["observed_at"].append(observed_at)
        entry["source_ranks"].append(int(source_rank))

    audit: list[dict] = []
    for normalized_key, entry in grouped.items():
        decision, reason = classify_source_topic(entry["display_name"])
        observed_hours = len(set(entry["observed_at"]))
        current_rank = next((rank for at, rank in zip(entry["observed_at"], entry["source_ranks"]) if at == current_time), None)
        # This is only a stable audit sort, never a published score or rank.
        audit.append({
            "display_name": entry["display_name"], "decision": decision, "reason": reason,
            "normalized_event_key": normalized_key, "raw_terms": sorted(entry["raw_terms"]),
            "observed_hours": observed_hours, "best_source_rank": min(entry["source_ranks"]),
            "latest_source_rank": current_rank, "is_current": current_rank is not None,
        })
    audit.sort(key=lambda row: (-row["observed_hours"], row["best_source_rank"], row["display_name"].casefold()))
    # A single-source audit is a flow candidate list, not a Top10 product
    # surface. Keep every candidate so reviewers can see the exact boundary.
    selected = [row for row in audit if row["decision"] == "candidate"]
    cards = [{
        "display_name": row["display_name"],
        "normalized_event_key": row["normalized_event_key"],
        "raw_terms": row["raw_terms"],
        "selection_reason": row["reason"],
        "flow_group": "currently_observed" if row["is_current"] else "recently_observed",
        "data_status": f"{args.source}_rolling_source_only",
        "observation_summary": {
            "source": args.source, "is_current": row["is_current"],
            "observed_hours": row["observed_hours"], "best_source_rank": row["best_source_rank"],
            "latest_source_rank": row["latest_source_rank"],
        },
        "next_gate": "news_context_keywords_and_companies_required",
    } for row in selected]
    counts = {key: sum(row["decision"] == key for row in audit) for key in ("candidate", "review", "excluded")}
    output = {
        "schema_version": "trzip-rolling-single-source-preview-v1",
        "source": args.source, "window": {"from": start.isoformat(), "to": end.isoformat(), "hours": args.hours},
        "valid_snapshot_rule": "exactly_30_x_ranks" if args.source == "x" else "complete_google_rankings_at_least_100_rows",
        "valid_snapshots": len(valid_times), "observed_source_rows": len(rows),
        "source_only_feed": {"status": "ready" if cards else "empty", "cards": cards, "card_count": len(cards), "top_limit": None},
        "source_audit": {"unique_topics": len(audit), "counts": counts, "topics": audit},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({
        "source": args.source, "valid_snapshots": len(valid_times), "rows": len(rows),
        "unique_topics": len(audit), "candidates": len(cards), "output": str(args.output),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
