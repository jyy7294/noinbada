"""Combine exhaustive X and Google adjudication outputs into one ranking."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trzip.combined_source_ranking import build_combined_ranking


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(body, encoding="utf-8")
    temporary.replace(path)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--x", type=Path, required=True)
    parser.add_argument("--google", type=Path, required=True)
    parser.add_argument("--exclude-home-event", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = build_combined_ranking(
        _load(args.x),
        _load(args.google),
        home_excluded_names=tuple(args.exclude_home_event),
    )
    sha256 = _write_json(args.output, result)
    print(json.dumps({
        "combined_event_count": result["combined_event_count"],
        "cross_source_event_count": result["cross_source_event_count"],
        "top10": [item["canonical_name"] for item in result["top10"]],
        "sha256": sha256,
        "output": str(args.output),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
