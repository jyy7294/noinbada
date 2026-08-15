import json
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]


def test_public_json_schemas_are_valid_json_and_versioned():
    expected = {
        "intelligence-v3.schema.json": "TRZIP intelligence publication v3",
        "metadata-v3.schema.json": "TRZIP publication metadata v3",
        "status-v1.schema.json": "TRZIP runtime status v1",
    }
    for name, title in expected.items():
        payload = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(payload)
        assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert payload["title"] == title
        assert payload["type"] == "object"
        assert payload["required"]


def test_intelligence_schema_requires_observed_rank_and_evidence_contracts():
    payload = json.loads(
        (ROOT / "schemas" / "intelligence-v3.schema.json").read_text(encoding="utf-8")
    )
    trend_required = set(payload["$defs"]["trend"]["required"])
    company_required = set(payload["$defs"]["company"]["required"])
    assert {
        "display_name", "score_components", "keywords", "companies", "observed_rank",
        "home_rank", "rising_rank", "category_label", "trend_definition",
        "keyword_status", "company_status", "company_card_reason",
    } <= trend_required
    assert {
        "relationship_reason", "company_summary", "company_description", "ticker",
        "ontology_path", "evidence_sources", "investment_warning",
        "company_role_category", "company_role_label",
    } <= company_required
    assert payload["$defs"]["trend"]["properties"]["keywords"]["maxItems"] == 5
    assert payload["$defs"]["trend"]["properties"]["companies"]["oneOf"] == [
        {"maxItems": 0}, {"minItems": 3}
    ]
    assert "ranking_availability" in payload["required"]
    assert {
        "all_observed_ranking", "home_top10", "rising_top10", "category_summary",
        "trend_top10", "public_top10", "company_ready_trends", "home_feed",
    } <= set(payload["required"])
    assert not {
        "youtube_content_discovery", "youtube_content_ranking", "youtube_content_top10",
    } & set(payload["required"])
    assert {
        "ranking_default_period", "ranking_periods", "ranking_views",
        "ranking_top_level_alias",
    } <= set(payload["required"])
    assert set(payload["properties"]["ranking_views"]["required"]) == {
        "daily", "weekly", "monthly",
    }
    assert payload["$defs"]["rankingView"]["properties"]["company_count_affects_rank"] == {
        "const": False
    }
    assert "verification_run" in payload["required"]
    assert "ranking_availability_status" in trend_required
    assert payload["properties"]["verification_run"]["properties"]["ranking_effect"] == {"const": "none"}
    news_context = payload["$defs"]["trend"]["properties"]["news_context"]
    assert {"affects_score", "ranking_source"} <= set(news_context["required"])
    assert news_context["properties"]["affects_score"] == {"const": False}
    assert news_context["properties"]["ranking_source"] == {"const": False}


def test_presentation_schema_accepts_only_live_v4_exact_ten_company_cards():
    from trzip.publication_pipeline import _validate_presentation_feed

    payload = json.loads(
        (ROOT / "schemas" / "intelligence-v3.schema.json").read_text(encoding="utf-8")
    )
    presentation_schema = payload["properties"]["presentation_feed"]
    resolver_schema = {**payload, **presentation_schema}
    validator = Draft202012Validator(resolver_schema)
    companies = [
        {
            "company": f"기업{i}", "stock_code": f"{i:06d}", "exchange": "KRX",
            "company_description": "공개 기업 설명",
            "connection_explanation": "공개 근거로 확인된 트렌드 관계",
            "company_role_category": (
                "manufacturing_development" if i < 4
                else "distribution" if i < 7 else "platform_service"
            ),
            "company_role_label": "검증 역할",
            "ontology_path": ["테스트", "검증 역할", f"기업{i}"],
            "ontology_complete": True,
            "evidence_sources": [{"url": f"https://example.com/{i}"}],
            "relation_tier": "direct",
            "official_domain": None,
            "logo_url": "",
            "logo_render_mode": "initials",
            "logo_asset_source": "initials_fallback",
            "logo_asset_host": "",
            "logo_asset_verification": "initials_fallback",
            "logo_asset_format": "none",
            "logo_asset_mime": "",
            "logo_asset_width": 0,
            "logo_asset_height": 0,
            "logo_asset_sha256": "",
            "logo_source_page_url": "",
            "logo_minimum_dimension": 64,
            "logo_runtime_probe_required": False,
            "logo_asset_quality": "fail_closed_initials_no_verified_asset",
            "logo_quality_policy": "avatar-sharpness-v1",
            "logo_provenance": {
                "source_page_url": None,
                "asset_url": None,
                "mime": None,
                "width": 0,
                "height": 0,
                "sha256": None,
                "verification": "initials_fallback",
            },
            "market_snapshot": None,
        }
        for i in range(10)
    ]
    observed_at = "2026-08-15T00:00:00+00:00"
    sparse_point = {
        "at": observed_at,
        "x": 80,
        "google_trends": None,
        "combined": 80,
        "observed_sources": ["x"],
    }
    sparse_window = {
        "status": "insufficient_observed_history",
        "points": [sparse_point],
        "available_point_count": 1,
        "available_from": observed_at,
        "available_to": observed_at,
        "basis": "observed_x_google_hourly_points_only",
        "interpolation": "none",
        "missing_point_policy": "preserve_sparse_null_no_reuse",
        "ranking_effect": "none",
    }
    item = {
        "presentation_position": 1,
        "selection_origin": "canonical_validated_home_feed",
        "lane": "main",
        "display_name": "테스트", "event_key": "test",
        "category": "consumer", "category_label": "제품·브랜드",
        "sources": ["x", "google_trends"], "data_mode": "observed_live",
        "observed_within_24h": True,
        "trend_definition": "검증된 트렌드 정의", "why_now": "검증된 현재 맥락",
        "context_research": {
            "status": "ready", "trigger_title": "테스트 확산",
            "why_now": "검증된 현재 맥락",
            "evidence_urls": ["https://example.com/context"],
        },
        "evidence_urls": ["https://example.com/context"],
        "series": [
            {"at": observed_at, "source": "x", "value": 80, "provenance": "observed"}
        ],
        "visualization_series": {
            "metric": "normalized_attention_index",
            "canonical_series_unchanged": True,
            "data_mode": "observed_sparse", "interpolation": "none",
            "ranking_effect": "none",
            "1w": sparse_window, "1m": sparse_window, "3m": sparse_window,
        },
        "keywords": [{"text": f"키워드{i}"} for i in range(5)],
        "keyword_company_links": [
            {
                "keyword": f"키워드{i}", "company": f"기업{i}",
                "connection_explanation": "공개 근거로 확인된 연결",
                "evidence_urls": [f"https://example.com/{i}"],
            }
            for i in range(2)
        ],
        "companies": companies, "keyword_status": "ready",
        "company_role_category_count": 3, "company_card_status": "ready",
        "ranking_effect": "none",
    }
    feed = {
        "schema_version": "trzip-presentation-feed-v4", "status": "ready",
        "frontend_default": True, "observed_at": observed_at,
        "selection_policy": "validated_live_home_feed_v1",
        "logo_policy": {
            "version": "avatar-sharpness-v1", "avatar_size_px": 44,
            "minimum_raster_dimension_px": 64, "vector_assets_allowed": True,
            "low_resolution_fallback": "initials", "runtime_probe_for_generic_favicons": False,
            "official_page_resolver_required": True, "asset_sha256_required": True,
        },
        "items": [item],
        "transition": {
            "synthetic_data_used": False, "supplemental_display_data_used": False,
            "fallback_used": False, "padding_forbidden": True,
            "canonical_ranking_affected": False,
        },
    }

    validator.validate(feed)
    _validate_presentation_feed(feed)
    legacy = json.loads(json.dumps(feed))
    legacy["schema_version"] = "trzip-presentation-feed-v3"
    assert list(validator.iter_errors(legacy))
    reference = json.loads(json.dumps(feed))
    reference["items"][0]["data_mode"] = "observed_reference"
    assert list(validator.iter_errors(reference))
    nine = json.loads(json.dumps(feed))
    nine["items"][0]["companies"] = nine["items"][0]["companies"][:9]
    assert list(validator.iter_errors(nine))
    three_roles = json.loads(json.dumps(feed))
    for index, company in enumerate(three_roles["items"][0]["companies"]):
        company["company_role_category"] = (
            ("manufacturing_development", "distribution", "retail_sales")[index % 3]
        )
    three_roles["items"][0]["company_role_category_count"] = 3
    validator.validate(three_roles)
    _validate_presentation_feed(three_roles)
    two_roles = json.loads(json.dumps(feed))
    for index, company in enumerate(two_roles["items"][0]["companies"]):
        company["company_role_category"] = (
            "manufacturing_development" if index % 2 == 0 else "distribution"
        )
    two_roles["items"][0]["company_role_category_count"] = 2
    assert list(validator.iter_errors(two_roles))
    review_lane = json.loads(json.dumps(feed))
    review_lane["items"][0]["lane"] = "review"
    assert list(validator.iter_errors(review_lane))
    no_context = json.loads(json.dumps(feed))
    no_context["items"][0]["context_research"]["evidence_urls"] = []
    assert list(validator.iter_errors(no_context))
    synthetic_series = json.loads(json.dumps(feed))
    synthetic_series["items"][0]["series"][0]["provenance"] = "reconstructed"
    assert list(validator.iter_errors(synthetic_series))
    long_keyword = json.loads(json.dumps(feed))
    long_keyword["items"][0]["keywords"][0]["text"] = "일곱글자키워드"
    assert list(validator.iter_errors(long_keyword))
    incomplete_ontology = json.loads(json.dumps(feed))
    incomplete_ontology["items"][0]["companies"][0]["ontology_complete"] = False
    assert list(validator.iter_errors(incomplete_ontology))
    ranking_affected = json.loads(json.dumps(feed))
    ranking_affected["transition"]["canonical_ranking_affected"] = True
    assert list(validator.iter_errors(ranking_affected))

    valid_market = json.loads(json.dumps(feed))
    valid_market["items"][0]["companies"][0]["market_snapshot"] = {
        "status": "observed", "provider": "verified-provider",
        "source": "verified-provider", "source_url": "https://example.com/market",
        "price_source_url": "https://example.com/market",
        "as_of": observed_at, "last_price": 100, "last_price_krw": 135000,
        "change_percent": 1.2, "volume": 10,
        "market_cap": 135000000, "market_cap_krw": 135000000,
        "market_cap_currency": "KRW", "native_market_cap": 100000,
        "market_cap_source_url": "https://example.com/market",
        "currency": "USD", "fx_rate_to_krw": 1350,
        "fx_as_of": observed_at, "fx_provider": "verified-fx",
        "fx_source_url": "https://example.com/fx",
        "price_series": [100], "price_points": [{"close": 100}],
        "display_only": True, "ranking_effect": "none",
    }
    validator.validate(valid_market)
    _validate_presentation_feed(valid_market)
    missing_fx = json.loads(json.dumps(valid_market))
    del missing_fx["items"][0]["companies"][0]["market_snapshot"]["fx_provider"]
    assert list(validator.iter_errors(missing_fx))
    zero_per = json.loads(json.dumps(valid_market))
    zero_per["items"][0]["companies"][0]["market_snapshot"].update({
        "per": 0,
        "per_source_url": "https://example.com/fundamentals",
    })
    assert list(validator.iter_errors(zero_per))
    unproven_roe = json.loads(json.dumps(valid_market))
    unproven_roe["items"][0]["companies"][0]["market_snapshot"].update({
        "roe_pct": 0,
        "roe": 0,
        "roe_percent": 0,
    })
    assert list(validator.iter_errors(unproven_roe))
    assert payload["properties"]["home_quality_gate"]["properties"]["minimum_published_companies"] == {"const": 10}


def test_latest_generated_publication_conforms_to_all_public_schemas(tmp_path, monkeypatch):
    from trzip.hourly_store import HourlyObservation
    from trzip.publication_pipeline import run

    at = datetime(2026, 8, 12, 13, tzinfo=UTC)
    stamp = at.isoformat()
    monkeypatch.setattr("trzip.publication_pipeline.floor_hour", lambda value: at)
    monkeypatch.setattr(
        "trzip.hourly_store.collect_google",
        lambda value: [
            HourlyObservation(stamp, "google_trends", "말복", 1, 100, "observed")
        ],
    )
    monkeypatch.setattr(
        "trzip.hourly_store.collect_x",
        lambda value: [HourlyObservation(stamp, "x", "말복", 1, 100, "observed")],
    )
    monkeypatch.setattr("trzip.publication_pipeline.verify_terms", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "trzip.publication_pipeline.pykrx_stock",
        lambda *args, **kwargs: {"status": "unavailable", "reason": "test"},
    )
    run(tmp_path / "publication", database_path=tmp_path / "trzip.sqlite3", now=at)

    latest = tmp_path / "publication" / "latest"
    contracts = {
        "intelligence.json": "intelligence-v3.schema.json",
        "metadata.json": "metadata-v3.schema.json",
        "status.json": "status-v1.schema.json",
    }
    for document_name, schema_name in contracts.items():
        document = json.loads((latest / document_name).read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(document)

    manifest = json.loads((latest / "manifest.json").read_text(encoding="utf-8"))
    rankings_path = latest / manifest["bundle"]["rankings"]["path"].removeprefix(
        "latest/"
    )
    rankings = json.loads(rankings_path.read_text(encoding="utf-8"))
    presentation_path = latest / manifest["bundle"]["presentation"]["path"].removeprefix(
        "latest/"
    )
    presentation = json.loads(presentation_path.read_text(encoding="utf-8"))
    assert presentation["publication_id"] == rankings["publication_id"]
    assert presentation["generated_at"] == rankings["generated_at"]
    assert presentation["observed_at"] == rankings["observed_at"]
    assert presentation["unified_ranking"] == []
    assert presentation["presentation_feed"] == rankings["presentation_feed"]
    assert presentation_path.stat().st_size < rankings_path.stat().st_size
    assert rankings["presentation_feed"]["frontend_default"] is True
    assert rankings["presentation_feed"]["schema_version"] == "trzip-presentation-feed-v4"
    assert rankings["presentation_feed"]["status"] == "empty"
    assert rankings["presentation_feed"]["items"] == []
    assert rankings["presentation_feed"]["transition"]["synthetic_data_used"] is False
