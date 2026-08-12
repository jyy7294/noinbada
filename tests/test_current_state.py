import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]


def test_current_state_is_schema_valid_and_portable():
    payload = json.loads((ROOT / "CURRENT_STATE.json").read_text(encoding="utf-8"))
    schema = json.loads(
        (ROOT / "schemas" / "current-state-v1.schema.json").read_text(encoding="utf-8")
    )

    errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda item: list(item.path))
    assert errors == []
    serialized = json.dumps(payload, ensure_ascii=False)
    assert not re.search(r"[A-Za-z]:[\\/]Users[\\/]", serialized)
    assert "tmcp_live_" not in serialized
    assert "github_pat_" not in serialized
    assert "gho_" not in serialized
    assert payload["checkpoint"]["describes_commit"] == "self"
    assert payload["live_state_pointer"]["branch"] == "live-data"


def test_continuity_documents_point_to_machine_readable_state():
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    handoff = (ROOT / "docs" / "CODEX_CONTINUITY.md").read_text(encoding="utf-8")

    assert "CURRENT_STATE.json" in agents
    assert "CURRENT_STATE.json" in handoff
    assert "checkpoint-main.ps1" in agents
    assert "checkpoint-main.ps1" in handoff
