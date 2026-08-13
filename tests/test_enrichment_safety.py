from datetime import UTC, datetime

from trzip.editorial_review import apply_frontend_enrichment_cache
from trzip.publication_pipeline import _enrich_official_company_identities


def test_issue_lane_never_exposes_company_cards():
    row = {
        "event_key": "perseids",
        "display_name": "페르세우스 유성우",
        "lane": "issue",
        "related_keywords": [],
        "companies": [{"company": "Example", "stock_code": "000001"}],
        "company_candidates": [{"company": "Example", "stock_code": "000001"}],
    }
    payload = {"unified_ranking": [row]}

    apply_frontend_enrichment_cache(payload, verified_at="2026-08-13T16:00:00+00:00")

    assert row["companies"] == []
    assert row["company_candidates"] == []
    assert row["company_eligible"] is False
    assert row["company_card_status"] == "not_applicable"
    assert row["company_resolution"]["publish_status"] == "not_published"


def test_foreign_company_is_not_sent_through_opendart_contract(tmp_path, monkeypatch):
    at = datetime(2026, 8, 13, 16, tzinfo=UTC)
    company = {"company": "Apple", "stock_code": "AAPL", "market": "NASDAQ"}
    intelligence = {"unified_ranking": [{"companies": [company], "company_candidates": []}]}
    monkeypatch.setattr(
        "trzip.publication_pipeline.enrich_company_identities",
        lambda *args, **kwargs: (
            {"AAPL": {"status": "not_found", "provider": "opendart", "stock_code": "AAPL", "ranking_effect": "none"}},
            {"status": "complete"},
        ),
    )

    _enrich_official_company_identities(
        intelligence, database_path=tmp_path / "db.sqlite3", at=at
    )

    identity = company["official_identity"]
    assert identity["status"] == "unavailable"
    assert identity["provider"] == "exchange_official"
    assert identity["market_class"] == "NASDAQ"
    assert identity["ranking_effect"] == "none"
