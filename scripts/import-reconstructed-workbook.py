"""Convert a reviewed TRZIP XLSX research workbook into the demo-only catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from trzip.reconstructed_workbook import import_workbook


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = import_workbook(args.source, args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
