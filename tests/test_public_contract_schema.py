import json
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator
from trzip.presentation_feed import logo_asset_contract_is_valid


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
    assert len(rankings["presentation_feed"]["items"]) == 10
    for item in rankings["presentation_feed"]["items"]:
        assert len(item["companies"]) == 10
        assert 3 <= len({row["company_role_category"] for row in item["companies"]}) <= 4
        assert [row["key"] for row in item["attention_windows"]] == ["1w", "1m", "3m"]
        assert all(isinstance(row["percent"], (int, float)) for row in item["attention_windows"])
        for key, size in (("1w", 7), ("1m", 30), ("3m", 13)):
            assert len(item["visualization_series"][key]["combined"]) == size
        assert all(
            logo_asset_contract_is_valid(
                company["company"], company["official_domain"], company["logo_url"]
            )
            and company["logo_asset_verification"]
            == "static_allowlist_http_200_image_2026_08_15"
            and len(company["market_snapshot"]["price_series"]) == 30
            for company in item["companies"]
        )
