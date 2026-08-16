"""Create a product-owner approval receipt from a final review pack."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from trzip.final_publication_approval import write_approval


def main() -> None:
    parser = argparse.ArgumentParser(description="Approve filtered TRZIP trends for one exact release hour")
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--approval-root", type=Path, required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--event-key", action="append", default=[])
    args = parser.parse_args()
    review = json.loads(args.review.read_text(encoding="utf-8"))
    path = write_approval(
        review,
        approval_root=args.approval_root,
        approved_event_keys=args.event_key,
        approved_by=args.approved_by,
    )
    print(json.dumps({"status": "approved", "path": str(path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
