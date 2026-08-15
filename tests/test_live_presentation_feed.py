from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from trzip.presentation_feed import build_presentation_feed
from trzip.publication_pipeline import _validate_presentation_feed
from trzip.result_quality import evaluate_presentation_feed_quality


OBSERVED_AT = "2026-08-15T05:00:00+00:00"


@pytest.fixture(autouse=True)
def _verified_logo_resolver(monkeypatch):
    def resolve(homepage):
        if homepage == "https://www.harim.com/main/":
            return {
                "status": "verified",
                "source_page_url": homepage,
                "asset_url": "https://www.harim.com/main/img/ci.png",
                "mime": "image/png",
                "width": 198,
                "height": 149,
                "sha256": "ff67be9cdeeeff6a1d6b4f17111ed758dcf3b5e9c6950e1a974442237f8267de",
                "verification": "verified_raster_min_64px",
                "asset_scope": "same_official_domain",
            }
        return {
            "status": "verified",
            "source_page_url": homepage,
            "asset_url": "https://assets.example.com/logo.svg",
            "mime": "image/svg+xml",
            "width": 160,
            "height": 80,
            "sha256": "a" * 64,
            "verification": "verified_safe_svg",
        }

    monkeypatch.setattr("trzip.presentation_feed.resolve_company_logo", resolve)


def _company(index: int, *, complete: bool = True, source_url: bool = True) -> dict:
    role = (
        "manufacturing_development" if index < 5
        else "distribution" if index < 8
        else "platform_service"
    )
    role_label = {
        "manufacturing_development": "제조·개발",
        "distribution": "배급·유통",
        "platform_service": "플랫폼·서비스",
    }[role]
    row = {
        "company": f"기업{index}",
        "stock_code": f"{index:06d}",
        "market": "KOSPI",
        "company_description": f"기업{index} 설명",
        "relationship_reason": f"테스트 트렌드와 기업{index}의 검증된 사업 관계",
        "connection_explanation": f"테스트 트렌드에서 {role} 역할로 연결됩니다.",
        "evidence_url": f"https://example.com/company/{index}",
        "evidence_sources": [{"url": f"https://example.com/company/{index}"}],
        "ontology_complete": True,
        "ontology_path": [{"from": "테스트", "to": f"기업{index}"}],
        "company_role_category": role,
        "company_role_label": role_label,
        "company_role_public": True,
        "relation_tier": "direct",
        "official_identity": {
            "status": "verified",
            "homepage": f"https://company{index}.example/",
            "ranking_effect": "none",
        },
    }
    if complete:
        market_url = "https://example.com/market" if source_url else None
        listing = {
            "status": "verified_current",
            "current_listed": True,
            "exchange": "KOSPI",
            "stock_code": f"{index:06d}",
            "as_of": "2026-08-15",
            "evidence_owner": "KRX",
            "evidence_type": "exchange_current_security_universe",
            "evidence_url": "https://data.krx.co.kr/",
            "synthetic": False,
            "estimated": False,
            "ranking_effect": "none",
        }
        row["listing_verification"] = listing
        row["market_reference"] = {
            "status": "observed",
            "provider": "verified-provider",
            "source_url": market_url,
            "source_urls": {
                "price": market_url,
                "fundamentals": "https://example.com/fundamentals",
            },
            "field_sources": {
                "price_series": market_url,
                "market_cap_krw": "https://example.com/fundamentals",
                "per": "https://example.com/fundamentals",
                "pbr": "https://example.com/fundamentals",
                "roe_pct": "https://example.com/fundamentals",
            },
            "daily_ohlcv": [
                {
                    "date": (
                        f"2026-07-{index + 17:02d}"
                        if index < 15
                        else f"2026-08-{index - 14:02d}"
                    ),
                    "close": 76 + index,
                }
                for index in range(30)
            ],
            "summary": {
                "as_of": "2026-08-15",
                "currency": "KRW",
                "close": 105,
                "close_krw": 105,
                "daily_change_pct": 5.0,
                "volume": 1000,
                "market_cap": 1_000_000,
                "market_cap_krw": 1_000_000,
            },
            "fx_reference": {
                "status": "observed",
                "provider": "identity",
                "from_currency": "KRW",
                "to_currency": "KRW",
                "rate": 1.0,
                "as_of": "2026-08-15",
                "source_url": "https://example.com/market",
                "synthetic": False,
                "estimated": False,
            },
            "valuation": {
                "per": 12.5,
                "per_status": "observed",
                "per_as_of": "2026-08-15",
                "per_type": "trailingPeRatio",
                "per_period_type": "TTM",
                "pbr": 1.4,
                "pbr_as_of": "2026-08-15",
                "pbr_type": "calculatedMarketCapToEquity",
                "pbr_period_type": "POINT_IN_TIME_OVER_REPORTED_EQUITY",
                "market_cap_as_of": "2026-08-15",
                "roe_pct": 9.2,
                "roe_basis": (
                    "trailing_net_income / average_two_point_stockholders_equity * 100"
                ),
                "roe_calculated": True,
                "roe_numerator": {
                    "value": 92,
                    "type": "trailingNetIncome",
                    "period_type": "TTM",
                    "as_of": "2026-08-15",
                },
                "roe_denominator": {
                    "value": 1000,
                    "type": "averageStockholdersEquity",
                    "period_type": "TWO_POINT_AVERAGE",
                    "as_of": "2026-08-15",
                    "period_start": "2025-08-15",
                    "period_end": "2026-08-15",
                    "observations": [
                        {
                            "value": 900,
                            "type": "quarterlyStockholdersEquity",
                            "period_type": "3M",
                            "as_of": "2025-08-15",
                        },
                        {
                            "value": 1100,
                            "type": "quarterlyStockholdersEquity",
                            "period_type": "3M",
                            "as_of": "2026-08-15",
                        },
                    ],
                },
            },
            "listing_verification": listing,
            "synthetic": False,
            "estimated": False,
            "ranking_effect": "none",
        }
    if not complete:
        row["ontology_complete"] = False
        row["evidence_sources"] = []
    return row


def _candidate(*, market_source_url: bool = True) -> dict:
    companies = [_company(0, complete=False)] + [
        _company(index, source_url=market_source_url)
        for index in range(1, 11)
    ]
    keywords = [
        {"text": text, "source": ["https://example.com/context"]}
        for text in ("kw0", "kw1", "kw2", "kw3", "kw4")
    ]
    for index, company in enumerate(companies):
        company["matched_keywords"] = [f"kw{index % 5}"]
    links = [
        {
            "keyword": f"kw{index % 5}",
            "company": f"기업{index}",
            "stock_code": f"{index:06d}",
            "company_role_category": companies[index]["company_role_category"],
            "company_role_label": companies[index]["company_role_label"],
            "connection_explanation": "공개 근거로 확인된 연결",
            "evidence_urls": [f"https://example.com/company/{index}"],
        }
        for index in range(1, 11)
    ]
    return {
        "event_key": "테스트트렌드",
        "display_name": "테스트 트렌드",
        "topic": "테스트 트렌드",
        "lane": "main",
        "broad_category": "consumer",
        "category": "consumer",
        "category_label": "제품·브랜드",
        "is_current": False,
        "hours_since_last_seen": 1,
        "lifecycle": "cooling",
        "source_badge": "X + Google",
        "latest_source_ranks": {"x": 3, "google_trends": 7},
        "observed_rank": 1,
        "rank": 1,
        "score": 88.5,
        "trend_definition": "최근 24시간 실제 관측으로 확인된 테스트 흐름입니다.",
        "disclaimer": "정보 제공 목적",
        "context_research": {
            "status": "ready",
            "trigger_title": "테스트 트렌드 확산",
            "why_now": "최근 공개 행사로 검색 관심이 늘었습니다.",
            "evidence_urls": ["https://example.com/context"],
        },
        "related_keywords": keywords,
        "companies": companies,
        "keyword_company_links": links,
        "frontend_readiness_status": "ready",
        "series": [
            {"at": "2026-08-15T04:00:00+00:00", "source": "x", "value": 60, "provenance": "observed"},
            {"at": "2026-08-15T04:00:00+00:00", "source": "google_trends", "value": 40, "provenance": "observed"},
            {"at": OBSERVED_AT, "source": "x", "value": 80, "provenance": "observed"},
        ],
    }


def _intelligence(candidate: dict) -> dict:
    return {
        "window": {"to": OBSERVED_AT},
        "unified_ranking": [candidate],
        "home_top10": [{"event_key": candidate["event_key"]}],
    }


def test_live_feed_skips_incomplete_company_then_keeps_exactly_ten_complete_rows():
    feed = build_presentation_feed(_intelligence(_candidate()))

    assert feed["schema_version"] == "trzip-presentation-feed-v4"
    assert feed["status"] == "ready"
    assert len(feed["items"]) == 1
    card = feed["items"][0]
    assert len(card["companies"]) == 10
    assert "기업0" not in {row["company"] for row in card["companies"]}
    assert {row["company_role_category"] for row in card["companies"]} == {
        "manufacturing_development", "distribution", "platform_service"
    }
    assert "score" not in card and "observed_rank" not in card and "rank" not in card
    assert card["currently_observed"] is False
    assert card["observed_within_24h"] is True
    _validate_presentation_feed(feed)


def test_production_v4_never_calls_demo_hash_market_snapshot(monkeypatch):
    def reject_demo_snapshot(*_args, **_kwargs):
        raise AssertionError("production v4 must never call the deterministic demo snapshot")

    monkeypatch.setattr(
        "trzip.presentation_feed._market_snapshot", reject_demo_snapshot
    )

    feed = build_presentation_feed(_intelligence(_candidate(market_source_url=True)))

    assert feed["schema_version"] == "trzip-presentation-feed-v4"
    assert feed["transition"]["synthetic_data_used"] is False
    assert feed["items"][0]["companies"][0]["market_snapshot"] is not None


def test_incomplete_duplicate_identity_does_not_hide_later_complete_company():
    candidate = _candidate()
    candidate["companies"][0]["market"] = candidate["companies"][1]["market"]
    candidate["companies"][0]["stock_code"] = candidate["companies"][1]["stock_code"]

    feed = build_presentation_feed(_intelligence(candidate))

    assert feed["status"] == "ready"
    assert len(feed["items"][0]["companies"]) == 10
    _validate_presentation_feed(feed)


def test_live_feed_is_sparse_and_never_reuses_previous_feed_when_current_is_empty():
    previous = build_presentation_feed(_intelligence(_candidate()))
    empty = build_presentation_feed(
        {"window": {"to": OBSERVED_AT}, "unified_ranking": [], "home_top10": []},
        previous_feed=previous,
    )

    points = previous["items"][0]["visualization_series"]["1w"]["points"]
    assert len(points) == 2
    assert points[0]["combined"] == 50.0
    assert points[1]["google_trends"] is None
    card = previous["items"][0]
    assert all(
        card["visualization_series"][key]["status"]
        == "insufficient_observed_history"
        for key in ("1w", "1m", "3m")
    )
    assert all(
        row["status"] == "insufficient_observed_history"
        and row["percent"] is None
        for row in card["attention_windows"]
    )
    assert card["visualization_series"]["1w"]["observed_span_hours"] == 1.0
    assert card["visualization_series"]["1w"]["minimum_span_hours"] == 134.4
    assert empty["status"] == "empty"
    assert empty["items"] == []
    assert empty["transition"]["fallback_used"] is False
    _validate_presentation_feed(empty)


def test_only_window_with_qualified_actual_span_and_coverage_is_measured():
    candidate = _candidate()
    end = datetime.fromisoformat(OBSERVED_AT).astimezone(UTC)
    candidate["series"] = [
        {
            "at": (end - timedelta(hours=offset)).isoformat(),
            "source": "x",
            "value": 50 + ((136 - offset) // 4),
            "provenance": "observed",
        }
        for offset in range(136, -1, -4)
    ]

    feed = build_presentation_feed(_intelligence(candidate))
    card = feed["items"][0]

    assert card["visualization_series"]["1w"]["status"] == "measured"
    assert card["visualization_series"]["1w"]["observed_span_hours"] == 136.0
    assert card["visualization_series"]["1w"]["observed_hour_count"] == 35
    assert card["attention_windows"][0] == {
        "key": "1w",
        "label": "1주",
        "metric": "normalized_attention_index_change",
        "status": "measured",
        "percent": 68.0,
        "basis": "first_and_last_qualified_observed_point",
        "is_absolute_mention_count": False,
        "ranking_effect": "none",
    }
    assert all(
        row["status"] == "insufficient_observed_history"
        and row["percent"] is None
        for row in card["attention_windows"][1:]
    )
    _validate_presentation_feed(feed)


def test_live_market_snapshot_requires_public_source_url():
    without_source = build_presentation_feed(
        _intelligence(_candidate(market_source_url=False))
    )
    assert without_source["status"] == "empty"
    assert without_source["items"] == []

    with_source_candidate = _candidate(market_source_url=True)
    with_source = build_presentation_feed(_intelligence(with_source_candidate))
    snapshot = with_source["items"][0]["companies"][0]["market_snapshot"]
    assert snapshot["provider"] == "verified-provider"
    assert snapshot["source_url"] == "https://example.com/market"
    assert snapshot["currency"] == "KRW"
    assert snapshot["market_cap"] == 1_000_000
    assert snapshot["market_cap_krw"] == 1_000_000
    assert snapshot["market_cap_currency"] == "KRW"
    assert snapshot["market_cap_source_url"] == "https://example.com/fundamentals"
    assert snapshot["fx_rate_to_krw"] == 1.0
    assert snapshot["fx_source_url"] == "https://example.com/market"
    assert (snapshot["per"], snapshot["pbr"], snapshot["roe_pct"]) == (12.5, 1.4, 9.2)
    assert snapshot["roe"] == snapshot["roe_percent"] == 9.2
    assert snapshot["per_source_url"] == "https://example.com/fundamentals"
    assert snapshot["pbr_source_url"] == "https://example.com/fundamentals"
    assert snapshot["roe_source_url"] == "https://example.com/fundamentals"
    assert snapshot["roe_calculated"] is True
    assert snapshot["roe_numerator"]["type"] == "trailingNetIncome"
    assert snapshot["roe_denominator"]["type"] == "averageStockholdersEquity"
    _validate_presentation_feed(with_source)

    wrong_role_count = deepcopy(with_source)
    wrong_role_count["items"][0]["company_role_category_count"] = 2
    with pytest.raises(ValueError, match="role count must match"):
        _validate_presentation_feed(wrong_role_count)

    foreign_labeled_cap = deepcopy(with_source)
    foreign_labeled_cap["items"][0]["companies"][0]["market_snapshot"][
        "market_cap_currency"
    ] = "USD"
    with pytest.raises(ValueError, match="complete actual market snapshot"):
        _validate_presentation_feed(foreign_labeled_cap)

    tampered_roe = deepcopy(with_source)
    tampered_roe["items"][0]["companies"][0]["market_snapshot"][
        "roe_numerator"
    ]["type"] = "quarterlyNetIncome"
    with pytest.raises(ValueError, match="TTM/annual calculated provenance"):
        _validate_presentation_feed(tampered_roe)


def test_live_market_snapshot_allows_explicit_per_na_but_rejects_stale_positive_per():
    candidate = _candidate(market_source_url=True)
    valuation = candidate["companies"][1]["market_reference"]["valuation"]
    valuation.update({
        "per": None,
        "per_status": "unavailable_loss_making",
        "per_reported_as_of": "2026-03-19",
    })
    valuation.pop("per_as_of", None)
    valuation.pop("per_type", None)
    valuation.pop("per_period_type", None)

    feed = build_presentation_feed(_intelligence(candidate))
    snapshot = feed["items"][0]["companies"][0]["market_snapshot"]

    assert snapshot["per_status"] == "unavailable_loss_making"
    assert "per" not in snapshot
    assert snapshot["pbr"] == 1.4
    assert snapshot["roe_pct"] == 9.2
    _validate_presentation_feed(feed)
    quality = evaluate_presentation_feed_quality(feed)
    assert quality["passed"] is True
    assert quality["trends"][0]["per_na_company_count"] == 1
    assert quality["trends"][0]["measured_attention_window_count"] == 0

    stale = deepcopy(feed)
    stale_snapshot = stale["items"][0]["companies"][0]["market_snapshot"]
    stale_snapshot.update({
        "per_status": "observed",
        "per": 53.8,
        "per_source_url": "https://example.com/fundamentals",
        "per_as_of": "2026-03-19",
        "per_type": "trailingPeRatio",
        "per_period_type": "TTM",
    })
    stale_snapshot["field_provenance"]["per"] = {
        "provider": "verified-provider",
        "as_of": "2026-03-19",
        "source_url": "https://example.com/fundamentals",
        "synthetic": False,
        "estimated": False,
    }
    with pytest.raises(ValueError, match="complete actual market snapshot"):
        _validate_presentation_feed(stale)


def test_live_market_snapshot_fails_closed_on_partial_observed_series():
    candidate = _candidate(market_source_url=True)
    candidate["companies"][1]["market_reference"]["daily_ohlcv"] = candidate[
        "companies"
    ][1]["market_reference"]["daily_ohlcv"][-28:]

    feed = build_presentation_feed(_intelligence(candidate))

    assert feed["status"] == "empty"
    assert feed["items"] == []


@pytest.mark.parametrize("mutation", ["extra_row", "duplicate_date", "reverse_order"])
def test_live_market_snapshot_requires_exact_distinct_chronological_sessions(mutation):
    candidate = _candidate(market_source_url=True)
    daily = candidate["companies"][1]["market_reference"]["daily_ohlcv"]
    if mutation == "extra_row":
        daily.append({"date": "2026-08-15", "close": 101})
    elif mutation == "duplicate_date":
        daily[-1]["date"] = daily[-2]["date"]
    else:
        daily.reverse()

    feed = build_presentation_feed(_intelligence(candidate))

    assert feed["status"] == "empty"
    assert feed["items"] == []


@pytest.mark.parametrize(("metric", "invalid"), [("per", 0.0), ("pbr", float("inf"))])
def test_live_market_snapshot_rejects_invalid_required_ratios(metric, invalid):
    candidate = _candidate(market_source_url=True)
    candidate["companies"][1]["market_reference"]["valuation"][metric] = invalid

    feed = build_presentation_feed(_intelligence(candidate))

    assert feed["status"] == "empty"
    assert feed["items"] == []


def test_live_card_rejects_fewer_than_two_distinct_linked_keywords():
    candidate = _candidate()
    candidate["keyword_company_links"] = candidate["keyword_company_links"][:1]
    feed = build_presentation_feed(_intelligence(candidate))
    assert feed["status"] == "empty"
    assert feed["items"] == []


def test_source_candidate_with_eleven_complete_companies_projects_exactly_ten():
    candidate = _candidate()
    candidate["companies"].append(_company(11))

    feed = build_presentation_feed(_intelligence(candidate))

    assert feed["status"] == "ready"
    assert len(feed["items"][0]["companies"]) == 10
    _validate_presentation_feed(feed)


def test_source_candidate_with_only_nine_complete_companies_is_rejected():
    candidate = _candidate()
    candidate["companies"] = candidate["companies"][:-1]

    feed = build_presentation_feed(_intelligence(candidate))

    assert feed["status"] == "empty"
    assert feed["items"] == []


def test_current_listing_proof_is_fail_closed_for_delisted_company():
    candidate = _candidate()
    company = candidate["companies"][1]
    company["listing_verification"].update({
        "status": "verified_inactive",
        "current_listed": False,
    })
    company["market_reference"]["listing_verification"] = company[
        "listing_verification"
    ]

    feed = build_presentation_feed(_intelligence(candidate))

    assert feed["status"] == "empty"
    assert feed["items"] == []


def test_foreign_market_history_without_official_current_listing_proof_is_rejected():
    """Yahoo history alone is not accepted as an exchange current-list proof."""

    candidate = _candidate()
    company = candidate["companies"][1]
    company.update({"market": "NASDAQ", "stock_code": "AAPL"})
    company["market_reference"].update({
        "provider": "yahoo_finance",
        "source_url": "https://finance.yahoo.com/quote/AAPL",
        "listing_verification": None,
    })
    company.pop("listing_verification", None)

    feed = build_presentation_feed(_intelligence(candidate))

    assert feed["status"] == "empty"
    assert feed["items"] == []


def test_live_feed_accepts_three_company_roles_and_rejects_two_roles():
    three_role_candidate = _candidate()
    three_roles = ("manufacturing_development", "distribution", "retail_sales")
    for index, company in enumerate(three_role_candidate["companies"]):
        company["company_role_category"] = three_roles[index % 3]

    three_role_feed = build_presentation_feed(_intelligence(three_role_candidate))

    assert three_role_feed["status"] == "ready"
    assert three_role_feed["items"][0]["company_role_category_count"] == 3
    _validate_presentation_feed(three_role_feed)

    two_role_candidate = _candidate()
    two_roles = ("manufacturing_development", "distribution")
    for index, company in enumerate(two_role_candidate["companies"]):
        company["company_role_category"] = two_roles[index % 2]

    two_role_feed = build_presentation_feed(_intelligence(two_role_candidate))

    assert two_role_feed["status"] == "empty"
    assert two_role_feed["items"] == []


def test_live_company_projects_only_verified_official_page_logo(monkeypatch):
    candidate = _candidate()
    candidate["companies"][1]["official_identity"] = {
        "status": "verified",
        "homepage": "https://company.example/",
        "ranking_effect": "none",
    }
    monkeypatch.setattr(
        "trzip.presentation_feed.resolve_company_logo",
        lambda _homepage: {
            "status": "verified",
            "source_page_url": "https://company.example/",
            "asset_url": "https://cdn.company-assets.example/logo.svg",
            "mime": "image/svg+xml",
            "width": 320,
            "height": 80,
            "sha256": "a" * 64,
            "verification": "verified_safe_svg",
        },
    )

    feed = build_presentation_feed(_intelligence(candidate))
    company = feed["items"][0]["companies"][0]

    assert company["logo_render_mode"] == "image"
    assert company["logo_url"] == "https://cdn.company-assets.example/logo.svg"
    assert company["logo_asset_format"] == "svg"
    assert company["logo_asset_width"] == 320
    assert company["logo_asset_height"] == 80
    assert company["logo_asset_sha256"] == "a" * 64
    assert company["logo_source_page_url"] == "https://company.example/"
    assert company["logo_provenance"] == {
        "source_page_url": "https://company.example/",
        "asset_url": "https://cdn.company-assets.example/logo.svg",
        "mime": "image/svg+xml",
        "width": 320,
        "height": 80,
        "sha256": "a" * 64,
        "verification": "verified_safe_svg",
        "candidate_kind": None,
        "asset_scope": None,
        "verified_at": None,
    }
    _validate_presentation_feed(feed)

    tampered = deepcopy(feed)
    tampered["items"][0]["companies"][0]["logo_asset_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="verified image logo"):
        _validate_presentation_feed(tampered)
    quality = evaluate_presentation_feed_quality(tampered)
    assert quality["passed"] is False
    assert any("invalid_live_logo" in failure for failure in quality["failures"])


def test_unverified_homepage_logo_excludes_public_card(monkeypatch):
    candidate = _candidate()
    candidate["companies"][1]["official_identity"] = {
        "status": "verified",
        "homepage": "https://company.example/",
        "ranking_effect": "none",
    }
    monkeypatch.setattr(
        "trzip.presentation_feed.resolve_company_logo",
        lambda _homepage: {
            "status": "fallback",
            "source_page_url": "https://company.example/",
            "asset_url": None,
            "mime": None,
            "width": None,
            "height": None,
            "sha256": None,
            "verification": "initials_fallback",
        },
    )

    feed = build_presentation_feed(_intelligence(candidate))

    assert feed["status"] == "empty"
    assert feed["items"] == []
    _validate_presentation_feed(feed)


def test_invalid_official_homepage_recovers_only_from_exact_reviewed_identity(monkeypatch):
    candidate = _candidate()
    company = candidate["companies"][1]
    company.update({
        "company": "하림",
        "stock_code": "136480",
        "official_identity": {
            "status": "verified",
            "homepage": "https://-",
            "ranking_effect": "none",
        },
    })
    company["listing_verification"].update({
        "stock_code": "136480",
    })
    company["market_reference"]["listing_verification"].update({
        "stock_code": "136480",
    })
    company["market_reference"]["stock_code"] = "136480"
    candidate["keyword_company_links"][0].update({
        "company": "하림",
        "stock_code": "136480",
    })

    feed = build_presentation_feed(_intelligence(candidate))
    projected = next(
        row for row in feed["items"][0]["companies"] if row["company"] == "하림"
    )

    assert projected["logo_render_mode"] == "image"
    assert projected["logo_url"] == "https://www.harim.com/main/img/ci.png"
    assert projected["logo_source_page_url"] == "https://www.harim.com/main/"
    assert projected["logo_asset_width"] == 198
    assert projected["logo_asset_height"] == 149
    assert projected["logo_asset_sha256"] == (
        "ff67be9cdeeeff6a1d6b4f17111ed758dcf3b5e9c6950e1a974442237f8267de"
    )
    assert projected["logo_provenance"]["asset_scope"] == "same_official_domain"
    _validate_presentation_feed(feed)
    assert evaluate_presentation_feed_quality(feed)["passed"] is True


def test_projection_failure_before_ten_is_replenished_from_later_candidate():
    invalid_projection = _candidate()
    invalid_projection["companies"][1]["company_role_category"] = "bogus_role"
    valid_later = deepcopy(_candidate())
    valid_later["event_key"] = "later-complete"
    valid_later["display_name"] = "later complete"
    valid_later["home_eligible"] = True
    valid_later["observed_rank"] = 11
    intelligence = {
        "window": {"to": OBSERVED_AT},
        "unified_ranking": [invalid_projection, valid_later],
        "home_top10": [{"event_key": invalid_projection["event_key"]}],
    }

    feed = build_presentation_feed(intelligence)

    assert [row["event_key"] for row in feed["items"]] == ["later-complete"]
    _validate_presentation_feed(feed)


@pytest.mark.parametrize("card_count", [3, 10])
def test_live_feed_supports_variable_three_or_ten_complete_cards(card_count):
    candidates = []
    for index in range(card_count):
        candidate = deepcopy(_candidate())
        candidate["event_key"] = f"observed-event-{index}"
        candidate["display_name"] = f"observed trend {index}"
        candidates.append(candidate)
    intelligence = {
        "window": {"to": OBSERVED_AT},
        "unified_ranking": candidates,
        "home_top10": [{"event_key": row["event_key"]} for row in candidates],
    }

    feed = build_presentation_feed(intelligence)

    assert feed["status"] == "ready"
    assert len(feed["items"]) == card_count
    assert [row["presentation_position"] for row in feed["items"]] == list(
        range(1, card_count + 1)
    )
    _validate_presentation_feed(feed)
