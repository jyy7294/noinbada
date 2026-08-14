from __future__ import annotations

import hashlib
import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cli_json_writers_report_the_persisted_file_hash(tmp_path: Path) -> None:
    for script_name in (
        "run-combined-source-e2e.py",
        "run-single-source-full-adjudication.py",
    ):
        module = runpy.run_path(str(ROOT / "scripts" / script_name))
        output = tmp_path / f"{script_name}.json"
        reported = module["_write_json"](output, {"한글": "검증", "rows": [1, 2]})
        assert reported == hashlib.sha256(output.read_bytes()).hexdigest()
        assert b"\r\n" not in output.read_bytes()
