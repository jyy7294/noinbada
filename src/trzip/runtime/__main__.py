from __future__ import annotations
import argparse
from .core import connect, encode, home
from .pipeline import run, status

parser = argparse.ArgumentParser(description="TR ZIP production runtime")
parser.add_argument("command", choices=["collect", "enrich", "status", "maintain"])
parser.add_argument("--force",action="store_true",help="Recollect a completed slot using actual upstream data")
args = parser.parse_args()
if args.command == "collect":
    result = run(force=args.force)
elif args.command == "enrich":
    from .enrichment import run_enrichment
    result = run_enrichment()
elif args.command == "maintain":
    from .maintenance import maintain
    result = maintain()
else:
    with connect() as db:
        result = status(db)
print(encode(result))
