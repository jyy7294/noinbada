"""Print the evidence-admission state of each showcase related-company set.

This script is intentionally read-only.  It is the curation handoff used
before replacing legacy showcase rows with reviewed ontology edges.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trzip.showcase_live_simulation import audit_showcase_relation_coverage


def main() -> int:
    payload = json.loads((ROOT / "frontend" / "showcase" / "showcase.json").read_text(encoding="utf-8"))
    print(json.dumps({"cards": audit_showcase_relation_coverage(payload)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
