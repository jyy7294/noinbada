from __future__ import annotations

import argparse
import json

from .hourly_store import backfill, collect_current, coverage, purge_generated_outside_demo_window


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("backfill", "collect", "purge-demo", "coverage"))
    args = parser.parse_args()
    if args.command == "backfill":
        result = backfill()
    elif args.command == "collect":
        result = collect_current(use_trends_mcp=False)
    elif args.command == "purge-demo":
        result = purge_generated_outside_demo_window()
    else:
        result = coverage()
    print(json.dumps({"rows_written": result} if isinstance(result, int) else result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
