from __future__ import annotations

import argparse
import json
from pathlib import Path

from trzip.archive_feed import write_archive_feed


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the isolated TRZIP historical archive feed")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("data/reconstructed/trzip-final-50-20260814"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reconstructed/trzip-final-50-20260814/archive-feed.json"),
    )
    args = parser.parse_args()
    feed = write_archive_feed(
        args.source_dir / "events.ndjson",
        args.source_dir / "manifest.json",
        args.output,
    )
    print(json.dumps({"output": str(args.output), "item_count": feed["item_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
