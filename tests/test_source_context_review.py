from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run-single-source-full-adjudication.py"
OVERLAY = ROOT / "data" / "source_context_review_20260814.json"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("single_source_full_adjudication", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_review_overlay_is_non_ranking_and_has_unique_final_decisions():
    raw = json.loads(OVERLAY.read_text(encoding="utf-8"))
    assert raw["policy"]["rank_effect"] == "none"
    assert raw["policy"]["manual_whitelist_for_future_rank"] is False
    assert raw["scope"]["reviewed_first_pass_not_selected"] == 660

    module = _load_script_module()
    x_decisions, _ = module._load_review_overlay(OVERLAY, "x")
    google_decisions, _ = module._load_review_overlay(OVERLAY, "google_trends")
    assert x_decisions
    assert google_decisions
    assert all(item["decision"] in {"included", "excluded"} for item in x_decisions.values())
    assert all(item["decision"] in {"included", "excluded"} for item in google_decisions.values())
    assert all(
        item["broad_category"] in module.ALLOWED_CATEGORIES
        for item in (*x_decisions.values(), *google_decisions.values())
        if item["decision"] == "included"
    )


def test_first_pass_non_selection_becomes_a_specific_final_exclusion():
    module = _load_script_module()
    generic = module._final_exclusion({
        "decision": "not_selected",
        "reason_code": "generic_expression_without_event_context",
        "broad_category": None,
        "evidence": [],
    })
    name_only = module._final_exclusion({
        "decision": "not_selected",
        "reason_code": "standalone_person_or_entity_name_without_event_context",
        "broad_category": None,
        "evidence": [],
    })
    assert generic["decision"] == "excluded"
    assert generic["reason_code"] == "excluded_generic_expression_without_trigger"
    assert name_only["decision"] == "excluded"
    assert name_only["reason_code"] == "excluded_standalone_name_without_trigger"
