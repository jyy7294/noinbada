"""Generate a non-publishable X-only preview from the current Chrome receipt."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trzip.x_only_preview import build_x_only_preview


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    preview = build_x_only_preview(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(preview, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({
        "observed_at": preview["observed_at"],
        "source_rows": preview["source_receipt"]["row_count"],
        "candidate_cards": preview["source_only_feed"]["card_count"],
        "audit_counts": preview["source_audit"]["counts"],
        "output": str(args.output),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
