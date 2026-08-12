from __future__ import annotations

import argparse
import json
from pathlib import Path

from trzip.normalization_evaluation import write_holdout_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the frozen TRZIP normalization holdout")
    parser.add_argument("--output", type=Path, default=Path("work/normalization-evaluation.json"))
    args = parser.parse_args()
    print(json.dumps(write_holdout_report(args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
