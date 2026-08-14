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
    assert [item["presentation_rank"] for item in feed["items"]] == list(range(1, 11))
    assert [item["current_rank"] for item in feed["items"]] == list(range(1, 11))
    assert [item["display_name"] for item in REFERENCE_TOP10] == EXPECTED
    assert all(len(item["keywords"]) == 5 for item in feed["items"])
    assert all(
        keyword_character_count(keyword["text"]) <= 6
        for item in feed["items"]
        for keyword in item["keywords"]
    )
    assert all(item["companies"] for item in feed["items"])
    assert all(len(item["companies"]) == 10 for item in feed["items"])
    assert all(
        3 <= len({company["company_role_category"] for company in item["companies"]}) <= 4
        for item in feed["items"]
    )
    assert all(item["ranking_effect"] == "none" for item in feed["items"])
    assert all(
        [window["key"] for window in item["attention_windows"]] == ["1w", "1m", "3m"]
        for item in feed["items"]
    )
    assert all(
        window["status"] == "supplemented_display" and isinstance(window["percent"], float)
        for item in feed["items"]
        for window in item["attention_windows"]
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
            assert company.get("stock_code")
            assert company.get("exchange")
            assert company.get("company_description")
            assert company.get("connection_explanation")
            assert str(company.get("evidence_url", "")).startswith("http")
            assert company.get("official_domain") in company.get("logo_url", "")
            snapshot = company.get("market_snapshot") or {}
            assert snapshot.get("display_only") is True
            assert snapshot.get("ranking_effect") == "none"
            assert len(snapshot.get("price_series") or []) == 30
            assert all(
                isinstance(snapshot.get(field), (int, float))
                for field in ("last_price", "change_percent", "per", "pbr", "roe_percent")
            )


def test_presentation_visualization_is_complete_deterministic_and_rank_neutral():
    canonical_series = [
        {"at": "2026-08-14T00:00:00+00:00", "source": "x", "value": 87},
        {"at": "2026-08-14T00:00:00+00:00", "source": "google_trends", "value": 72},
    ]
    intelligence = {
        "unified_ranking": [{
            "event_key": "개기일식",
            "display_name": "개기일식",
            "series": canonical_series,
        }]
    }

    first = build_presentation_feed(intelligence)
    second = build_presentation_feed(intelligence)
    item = first["items"][0]

    assert item["series"] == canonical_series
    assert intelligence["unified_ranking"][0]["series"] == canonical_series
    assert first == second
    visualization = item["visualization_series"]
    assert visualization["canonical_series_unchanged"] is True
    assert visualization["ranking_effect"] == "none"
    for key, count in (("1w", 7), ("1m", 30), ("3m", 13)):
        window = visualization[key]
        assert len(window["labels"]) == count
        assert all(len(window[source]) == count for source in ("x", "google_trends", "combined"))
        assert all(
            0 <= value <= 100
            for source in ("x", "google_trends", "combined")
            for value in window[source]
        )

    _validate_presentation_feed(first)


def test_invalid_presentation_feed_is_rejected_before_publication():
    feed = build_presentation_feed({"unified_ranking": []})
    feed["items"][0]["keywords"][0]["text"] = "여섯글자초과키워드"

    with pytest.raises(ValueError, match="five unique keywords"):
        _validate_presentation_feed(feed)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda feed: feed["items"][0].__setitem__("display_name", "순서변경"),
            "approved Top10 order",
        ),
        (
            lambda feed: feed["items"][0].__setitem__(
                "trend_stage", {"key": "capture", "label": "포착", "index": 1}
            ),
            "trend stage",
        ),
        (
            lambda feed: feed["items"][0]["companies"][0].pop("connection_explanation"),
            "complete display identity",
        ),
        (
            lambda feed: feed["items"][0]["attention_windows"][0].__setitem__(
                "is_absolute_mention_count", True
            ),
            "must not claim absolute mention counts",
        ),
        (
            lambda feed: feed["items"][0]["companies"][0].pop("logo_url"),
            "official-domain logo",
        ),
        (
            lambda feed: feed["items"][0]["companies"][0].pop("market_snapshot"),
            "complete market snapshot",
        ),
        (
            lambda feed: feed["items"][0]["visualization_series"]["1w"]["x"].pop(),
            "visualization series values",
        ),
    ],
)
def test_invalid_presentation_contract_variants_are_rejected(mutate, message):
    feed = build_presentation_feed({"unified_ranking": []})
    mutate(feed)

    with pytest.raises(ValueError, match=message):
        _validate_presentation_feed(feed)
