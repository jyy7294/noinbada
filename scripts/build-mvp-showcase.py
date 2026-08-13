from __future__ import annotations

import argparse
from pathlib import Path

from trzip.mvp_showcase import build_mvp_showcase


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the isolated TRZIP MVP showcase bundle")
    parser.add_argument("--output", type=Path, default=Path("data/mvp-showcase"))
    args = parser.parse_args()
    manifest = build_mvp_showcase(args.output)
    print(f"{manifest['publication_id']} -> {args.output / 'latest'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
