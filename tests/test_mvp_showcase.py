from __future__ import annotations

import json

from trzip.mvp_showcase import SHOWCASE_SCENARIOS, build_mvp_showcase, validate_mvp_showcase


def test_mvp_showcase_is_complete_and_not_live(tmp_path):
    root = tmp_path / "mvp-showcase"
    manifest = build_mvp_showcase(root)
    assert manifest["mode"] == "mvp_showcase"
    assert manifest["live_eligible"] is False
    assert manifest["ranking_effect"] == "none"
    assert validate_mvp_showcase(root)["publication_id"] == manifest["publication_id"]

    payload = json.loads((root / "latest" / "showcase.json").read_text(encoding="utf-8"))
    assert [row["event_key"] for row in payload["trends"]] == [topic for topic, _ in SHOWCASE_SCENARIOS]
    assert all(len(row["related_keywords"]) == 5 for row in payload["trends"])
    assert all(len(row["company_candidates"]) >= 3 for row in payload["trends"])
    assert all(row["ranking_kind"] == "mvp_showcase_order" for row in payload["trends"])
