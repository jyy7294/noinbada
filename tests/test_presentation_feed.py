from __future__ import annotations

import pytest

from trzip.keyword_policy import keyword_character_count
from trzip.presentation_feed import REFERENCE_TOP10, build_presentation_feed
from trzip.publication_pipeline import _validate_presentation_feed


EXPECTED = [
    "개기일식",
    "페르세우스 유성우",
    "말복·삼계탕",
    "불꽃축제",
    "메츠 대 브레이브스",
    "맨유 vs 리즈",
    "오디세이 영화",
    "데포르티보 vs 레알 마드리드",
    "휴머노이드 로봇",
    "홈플러스 재개장",
]


def test_reviewed_presentation_feed_is_exact_and_enriched():
    feed = build_presentation_feed({"unified_ranking": []})

    assert feed["schema_version"] == "trzip-presentation-feed-v2"
    assert [item["display_name"] for item in feed["items"]] == EXPECTED
    assert [item["presentation_position"] for item in feed["items"]] == list(range(1, 11))
    assert [item["display_name"] for item in REFERENCE_TOP10] == EXPECTED
    assert all(len(item["keywords"]) == 5 for item in feed["items"])
    assert all(
        keyword_character_count(keyword["text"]) <= 6
        for item in feed["items"]
        for keyword in item["keywords"]
    )
    assert all(item["companies"] for item in feed["items"])
    assert all(item["ranking_effect"] == "none" for item in feed["items"])
    assert all(
        [window["key"] for window in item["attention_windows"]] == ["1w", "1m", "3m"]
        for item in feed["items"]
    )
    assert all(
        window["is_absolute_mention_count"] is False
        for item in feed["items"]
        for window in item["attention_windows"]
    )
    assert feed["transition"]["enabled"] is False


def test_presentation_company_groups_are_explicit_and_explainable():
    feed = build_presentation_feed({"unified_ranking": []})

    for item in feed["items"]:
        for company in item["companies"]:
            assert company["company_role_public"] is True
            assert company["company_role_label"] != "역할 미확정"
            assert company.get("reason")
            assert str(company.get("evidence_url", "")).startswith("http")


def test_invalid_presentation_feed_is_rejected_before_publication():
    feed = build_presentation_feed({"unified_ranking": []})
    feed["items"][0]["keywords"][0]["text"] = "여섯글자초과키워드"

    with pytest.raises(ValueError, match="five unique keywords"):
        _validate_presentation_feed(feed)
