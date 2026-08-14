from trzip.x_only_preview import build_x_only_preview


def test_x_only_preview_keeps_source_audit_and_filters_without_enrichment():
    payload = {
        "source": "x", "region": "KR", "region_verified": True,
        "collector": "codex_chrome_current_session",
        "observed_at": "2026-08-14T07:00:00+00:00", "row_count": 30,
        "trends": [
            {"rank": 1, "topic": "RIIZE Popmart"},
            {"rank": 2, "topic": "President"},
            {"rank": 3, "topic": "#FanBirthday"},
            *[{"rank": rank, "topic": f"term {rank}"} for rank in range(4, 31)],
        ],
    }
    result = build_x_only_preview(payload)

    assert result["source_only_feed"]["card_count"] == 1
    card = result["source_only_feed"]["cards"][0]
    assert card["display_name"] == "RIIZE Popmart"
    assert "source_rank" not in card
    assert result["source_audit"]["all_x_trends"][1]["decision"] == "excluded"
    assert result["source_audit"]["all_x_trends"][2]["decision"] == "review"
