from __future__ import annotations

import pytest

from trzip.keyword_policy import keyword_character_count
from trzip.presentation_feed import (
    COMPANY_LOGO_ASSETS,
    LOGO_ASSET_VERIFICATION,
    LOGO_MINIMUM_DIMENSION,
    LOGO_QUALITY_POLICY,
    LEGACY_COMPANY_LOGO_URLS,
    REFERENCE_TOP10,
    build_presentation_feed,
    logo_asset_contract_is_valid,
    logo_display_contract_is_valid,
)
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

    assert feed["schema_version"] == "trzip-presentation-feed-v3"
    assert feed["logo_policy"] == {
        "version": LOGO_QUALITY_POLICY,
        "avatar_size_px": 44,
        "minimum_raster_dimension_px": LOGO_MINIMUM_DIMENSION,
        "vector_assets_allowed": True,
        "low_resolution_fallback": "initials",
        "runtime_probe_for_generic_favicons": True,
    }
    assert [item["display_name"] for item in feed["items"]] == EXPECTED
    assert [item["presentation_position"] for item in feed["items"]] == list(range(1, 11))
    assert [item["presentation_rank"] for item in feed["items"]] == list(range(1, 11))
    assert [item["current_rank"] for item in feed["items"]] == list(range(1, 11))
    assert [item["rank_movement"]["label"] for item in feed["items"]] == ["NEW"] * 10
    assert all(
        item["rank_movement"]["basis"] == "previous_published_presentation_feed"
        for item in feed["items"]
    )
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


def test_presentation_rank_movement_compares_only_the_previous_published_feed():
    previous = build_presentation_feed({"unified_ranking": []})
    previous["items"][0]["presentation_position"] = 2
    previous["items"][0]["current_rank"] = 2
    previous["items"][1]["presentation_position"] = 1
    previous["items"][1]["current_rank"] = 1

    current = build_presentation_feed(
        {"unified_ranking": []},
        previous_feed=previous,
    )

    assert current["items"][0]["rank_movement"] == {
        "current_rank": 1,
        "previous_rank": 2,
        "delta": 1,
        "status": "up",
        "label": "▲1",
        "basis": "previous_published_presentation_feed",
    }
    assert current["items"][1]["rank_movement"]["label"] == "▼1"
    assert current["items"][2]["rank_movement"]["label"] == "유지"


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
            if company["logo_render_mode"] == "initials":
                assert company["logo_url"] == ""
                assert company["logo_asset_source"] == "initials_fallback"
            else:
                assert logo_asset_contract_is_valid(
                    company["company"], company["official_domain"], company["logo_url"]
                )
            assert company["logo_asset_verification"] == LOGO_ASSET_VERIFICATION
            assert company["logo_quality_policy"] == LOGO_QUALITY_POLICY
            assert logo_display_contract_is_valid(company)
            snapshot = company.get("market_snapshot") or {}
            assert snapshot.get("display_only") is True
            assert snapshot.get("ranking_effect") == "none"
            assert len(snapshot.get("price_series") or []) == 30
            assert all(
                isinstance(snapshot.get(field), (int, float))
                for field in ("last_price", "change_percent", "per", "pbr", "roe_percent")
            )


def test_known_logo_assets_use_high_resolution_images_or_initials():
    feed = build_presentation_feed({"unified_ranking": []})
    companies = {
        company["company"]: company
        for item in feed["items"]
        for company in item["companies"]
    }
    expected_images = {
        "하림": "https://harim.com/main/img/ci.png",
        "GS리테일": "https://hpimg.gsretail.com/_ui/desktop/common/images/icon/gsretail_114.png",
        "Manchester United plc": COMPANY_LOGO_ASSETS["Manchester United plc"]["url"],
    }
    expected_initials = {
        "이마트",
        "롯데관광개발",
        "농심",
        "롯데웰푸드",
        "Teledyne Technologies",
    }
    assert set(expected_images) | expected_initials <= set(companies)
    for company_name, expected_url in expected_images.items():
        company = companies[company_name]
        assert company["logo_url"] == expected_url
        assert company["logo_asset_source"] == "official_page_asset"
        assert logo_asset_contract_is_valid(
            company_name, company["official_domain"], company["logo_url"]
        )
    for company_name in expected_initials:
        company = companies[company_name]
        assert company["logo_url"] == ""
        assert company["logo_render_mode"] == "initials"
        assert company["logo_asset_source"] == "initials_fallback"
        assert company["logo_rejected_asset_url"].startswith("https://")


def test_logo_display_policy_never_upscales_a_low_resolution_raster():
    feed = build_presentation_feed({"unified_ranking": []})
    companies = [company for item in feed["items"] for company in item["companies"]]

    assert len(companies) == 100
    assert all(logo_display_contract_is_valid(company) for company in companies)
    for company in companies:
        mode = company["logo_render_mode"]
        if mode == "image":
            if company["logo_asset_format"] != "svg":
                assert company["logo_asset_width"] >= LOGO_MINIMUM_DIMENSION
                assert company["logo_asset_height"] >= LOGO_MINIMUM_DIMENSION
        elif mode == "initials":
            assert min(company["logo_asset_width"], company["logo_asset_height"]) < (
                LOGO_MINIMUM_DIMENSION
            )
        else:
            assert mode == "runtime_probe"
            assert company["logo_runtime_probe_required"] is True


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
            lambda feed: feed["items"][0]["companies"][0].pop(
                "logo_asset_verification"
            ),
            "verified v3 logo metadata",
        ),
        (
            lambda feed: feed["items"][0]["companies"][0].pop(
                "logo_minimum_dimension"
            ),
            "blur-safe logo display contract",
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


def test_legacy_v2_feed_is_readable_without_v3_logo_metadata():
    feed = build_presentation_feed({"unified_ranking": []})
    feed["schema_version"] = "trzip-presentation-feed-v2"
    feed.pop("logo_policy", None)
    for item in feed["items"]:
        for company in item["companies"]:
            if not company.get("logo_url"):
                company["logo_url"] = company["logo_rejected_asset_url"]
            for field in (
                "logo_asset_source",
                "logo_asset_host",
                "logo_asset_verification",
                "logo_quality_policy",
                "logo_render_mode",
                "logo_asset_format",
                "logo_asset_width",
                "logo_asset_height",
                "logo_minimum_dimension",
                "logo_runtime_probe_required",
                "logo_asset_quality",
                "logo_rejected_asset_url",
            ):
                company.pop(field, None)

    _validate_presentation_feed(feed)


def test_immutable_pre_quality_policy_v3_feed_remains_auditable():
    feed = build_presentation_feed({"unified_ranking": []})
    feed.pop("logo_policy", None)
    for item in feed["items"]:
        for company in item["companies"]:
            company_name = company["company"]
            if company_name in LEGACY_COMPANY_LOGO_URLS:
                company["logo_url"] = LEGACY_COMPANY_LOGO_URLS[company_name]
            elif not company.get("logo_url"):
                company["logo_url"] = company["logo_rejected_asset_url"]
            if company.get("logo_asset_source") == "initials_fallback":
                company["logo_asset_source"] = "official_page_asset"
            company["logo_asset_verification"] = (
                "static_allowlist_http_200_image_2026_08_15"
            )
            for field in (
                "logo_quality_policy",
                "logo_render_mode",
                "logo_asset_format",
                "logo_asset_width",
                "logo_asset_height",
                "logo_minimum_dimension",
                "logo_runtime_probe_required",
                "logo_asset_quality",
                "logo_rejected_asset_url",
            ):
                company.pop(field, None)

    _validate_presentation_feed(feed)
