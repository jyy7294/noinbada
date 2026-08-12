import json

import pytest

from trzip.event_resolution import (
    GROUND_TRUTH,
    company_evidence_status,
    load_company_review_overrides,
    relation_display,
    resolve_event,
)


def test_ground_truth_has_at_least_thirty_cases():
    assert len(GROUND_TRUTH) >= 30


def test_bloody_game_is_screen_content_not_digital_game():
    event = resolve_event("피의 게임", {"google_trends"})
    assert event["category"] == "screen_content"
    assert "Google Trends KR" in event["phenomenon_summary"]
    assert "X 한국" not in event["phenomenon_summary"]


def test_unknown_person_name_is_not_falsely_resolved():
    event = resolve_event("홍길동", {"x"})
    assert event["context_status"] == "ambiguous_person"
    assert event["phenomenon_summary"].startswith("원인 미확인")


def test_four_syllable_products_are_not_guessed_as_person_names():
    assert resolve_event("유부초밥", {"google_trends"})["context_status"] == "needs_context"
    assert resolve_event("지오다노", {"x"})["context_status"] == "needs_context"


def test_spacing_hashtag_and_case_variants_resolve_without_semantic_guessing():
    assert resolve_event("#피의게임", {"x"})["canonical"] == "피의 게임"
    assert resolve_event("nct   시온", {"google_trends"})["canonical"] == "NCT WISH 시온"
    generic = resolve_event("테니스", {"x"})
    assert generic["context_status"] == "needs_context"
    assert generic["category"] is None


def test_company_relation_and_team_review_are_separate():
    company = {"company": "관찰기업", "relation_tier": "adjacent", "evidence_url": None}
    display = relation_display(company, {})
    assert display["relation_display_type"] == "산업 관찰"
    assert display["team_review_status"] == "unreviewed"


def test_review_override_rejects_unknown_status(tmp_path):
    path = tmp_path / "reviews.json"
    path.write_text(json.dumps({"회사|https://example.com": "done"}), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid company review status"):
        load_company_review_overrides(path)


def test_sector_watch_url_is_not_promoted_to_official_evidence():
    result = company_evidence_status({
        "strength": "sector_watch",
        "evidence_kind": "company_official_brochure",
        "evidence_url": "https://example.com/",
    })
    assert result["verification_status"] == "industry_structure_only"
    assert result["evidence_official"] is False
