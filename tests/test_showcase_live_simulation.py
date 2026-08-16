from datetime import UTC, datetime

from trzip.showcase_live_simulation import (
    SHOWCASE_SELECTION,
    build_showcase_enrichment,
    validate_showcase_enrichment,
)


def test_showcase_has_ten_ranked_cards_five_keywords_and_five_to_ten_specific_companies():
    ranking = [
        {"event_key": event_key, "rank": rank, "score": 100 - rank}
        for rank, (event_key, _display, _universe) in enumerate(SHOWCASE_SELECTION, 1)
    ]
    payload = build_showcase_enrichment(
        ranking,
        source_observed_at="2026-08-16T00:00:00+00:00",
        display_now=datetime(2026, 8, 16, 8, 5, 33, tzinfo=UTC),
    )

    assert payload["mode"] == "showcase_live_simulation"
    assert payload["display_status"] == "시연 LIVE"
    assert payload["display_as_of"].endswith("17:00:00+09:00")
    assert len(payload["cards"]) == 10
    validate_showcase_enrichment(payload)
    for card in payload["cards"]:
        assert len(card["related_keywords"]) == 5
        assert 5 <= len(card["companies"]) <= 10
        assert 3 <= card["company_role_category_count"] <= 4
        assert card["category"]
        assert card["trend_definition"]
        assert card["enrichment_mode"] == "reconstructed_demo"
        assert all(company["relationship_status"] == "reconstructed_demo" for company in card["companies"])
        assert all(company["connection_explanation"] for company in card["companies"])
        assert all("연결 시나리오" not in company["connection_explanation"] for company in card["companies"])


def test_showcase_never_changes_observed_rank_or_claims_observed_company_relations():
    ranking = [
        {"event_key": event_key, "rank": rank * 7, "score": 90.0 - rank}
        for rank, (event_key, _display, _universe) in enumerate(SHOWCASE_SELECTION, 1)
    ]
    payload = build_showcase_enrichment(
        ranking,
        source_observed_at="2026-08-16T00:00:00+00:00",
    )

    assert [card["full_ledger_rank"] for card in payload["cards"]] == [
        row["rank"] for row in ranking
    ]
    assert all(card["ranking_effect"] == "none" for card in payload["cards"])
    assert all(
        company["evidence_scope"] == "company_identity_only_not_observed_trend_relation"
        for card in payload["cards"]
        for company in card["companies"]
    )
