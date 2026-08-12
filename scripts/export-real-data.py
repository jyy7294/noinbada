from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from trzip.real_data_export import ExportInputs, build_real_data_export


def _existing(path: Path) -> Path | None:
    return path if path.exists() else None


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    legacy_root = Path(
        os.environ.get(
            "TRZIP_LEGACY_ROQK_ROOT",
            Path.home() / "Documents" / "Codex" / "2026-08-05" / "roqk",
        )
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(
        description="Export only real TRZIP observations and reviewed public evidence."
    )
    parser.add_argument(
        "--current-db",
        type=Path,
        default=local_app_data / "TRZIP" / "data" / "trzip-hourly.sqlite3",
    )
    parser.add_argument(
        "--legacy-current-db",
        type=Path,
        default=repo / "data" / "trzip-hourly.sqlite3",
    )
    parser.add_argument(
        "--legacy-x-db",
        type=Path,
        default=legacy_root / "work" / "trzip-live-x-v5-fixed2.sqlite3",
    )
    parser.add_argument(
        "--legacy-provider-db",
        action="append",
        type=Path,
        default=None,
        help="Canonical live legacy provider DB. Repeat to include additional real runs.",
    )
    parser.add_argument(
        "--ontology",
        action="append",
        type=Path,
        default=None,
        help="Reviewed ontology overlay. Repeat for more than one file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=repo / "work" / "real-data-export" / timestamp,
    )
    parser.add_argument("--no-zip", action="store_true")
    args = parser.parse_args()
    ontology_files = tuple(
        args.ontology
        or [
            repo / "data" / "ontology_seed.json",
            repo / "data" / "ontology_enrichment.json",
            repo / "data" / "ontology_humanoid_enrichment.json",
        ]
    )
    legacy_provider_databases = tuple(
        args.legacy_provider_db
        or [
            legacy_root / "work" / "current-run.sqlite3",
            legacy_root / "work" / "trzip-live-v5-20260809e.sqlite3",
            legacy_root / "work" / "trzip-live-x-v5-fixed2.sqlite3",
        ]
    )
    result = build_real_data_export(
        ExportInputs(
            current_db=_existing(args.current_db),
            legacy_current_db=_existing(args.legacy_current_db),
            legacy_x_db=_existing(args.legacy_x_db),
            legacy_provider_dbs=tuple(
                path for path in legacy_provider_databases if path.exists()
            ),
            ontology_files=tuple(path for path in ontology_files if path.exists()),
        ),
        args.output_dir,
        create_zip=not args.no_zip,
    )
    manifest = result["manifest"]
    print(
        json.dumps(
            {
                "output_dir": str(result["output_dir"].resolve()),
                "manifest_path": str(result["manifest_path"].resolve()),
                "jsonl_path": str(result["jsonl_path"].resolve()),
                "csv_path": str(result["csv_path"].resolve()),
                "zip_path": (
                    str(result["zip_path"].resolve()) if result["zip_path"] else None
                ),
                "row_count": manifest["overall"]["row_count"],
                "datasets": manifest["datasets"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
