"""Generate a non-publishable Google-only preview from the latest hourly ledger."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trzip.x_only_preview import build_source_only_preview


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads(args.observations.read_text(encoding="utf-8"))
    selected = [
        row for row in rows
        if row.get("observed_at") == args.observed_at and row.get("source") == "google_trends"
    ]
    selected.sort(key=lambda row: int(row["source_rank"]))
    ranks = [int(row["source_rank"]) for row in selected]
    if ranks != list(range(1, len(selected) + 1)):
        raise ValueError("Google snapshot is not complete contiguous observed ranking")
    collector_counts = Counter(str(row.get("collector_version") or "") for row in selected)
    payload = {
        "source": "google_trends", "region": "KR", "region_verified": True,
        "collector": next(iter(collector_counts), "google_trends"),
        "observed_at": args.observed_at, "row_count": len(selected),
        "trends": [{"rank": int(row["source_rank"]), "topic": row["topic"]} for row in selected],
    }
    preview = build_source_only_preview(payload, source="google_trends")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(preview, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({
        "observed_at": preview["observed_at"], "source_rows": len(selected),
        "candidate_cards": preview["source_only_feed"]["card_count"],
        "audit_counts": preview["source_audit"]["counts"], "output": str(args.output),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
