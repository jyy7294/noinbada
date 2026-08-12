"""Build the isolated 60-day TRZIP frontend MVP replay."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from trzip.demo_replay import build_demo_replay, default_asset_paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "demo-replay-60d",
    )
    parser.add_argument("--as-of", help="ISO timestamp; defaults to the current UTC hour")
    parser.add_argument(
        "--research-input",
        type=Path,
        help="optional reconstructed reference JSONL; every row must declare reconstructed provenance",
    )
    args = parser.parse_args()
    as_of = (
        datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
        if args.as_of
        else datetime.now(UTC)
    )
    assets = default_asset_paths()
    if args.research_input is not None:
        assets["research_reconstruction_jsonl"] = args.research_input
    manifest = build_demo_replay(args.output, as_of=as_of, **assets)
    print(json.dumps({
        "output": str(args.output.resolve()),
        "publication_id": manifest["publication_id"],
        "observed_at": manifest["observed_at"],
        "observation_rows": manifest["bundle"]["observation_ledger"]["row_count"],
        "trend_count": manifest["bundle"]["trend_count"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
