from datetime import UTC, datetime

from trzip.showcase_live_simulation import (
    SHOWCASE_SELECTION,
    audit_relation_set_for_publication,
    audit_showcase_relation_coverage,
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
    assert payload["display_status"] == "NOW"
    assert payload["display_as_of"].endswith("17:00:00+09:00")
    assert len(payload["cards"]) == 10
    validate_showcase_enrichment(payload)
    for card in payload["cards"]:
        assert len(card["related_keywords"]) == 5
        direct_only = card["companies"] and all(
            company["relation_tier"] == "direct" for company in card["companies"]
        )
        assert (3 if direct_only else 5) <= len(card["companies"]) <= 10
        assert 3 <= card["company_role_category_count"] <= 4
        assert card["category"]
        assert card["trend_definition"]
        assert card["enrichment_mode"] == "reconstructed_demo"
        assert all(company["relationship_status"] == "reconstructed_demo" for company in card["companies"])
        assert all(company["connection_explanation"] for company in card["companies"])
        assert all("연결 시나리오" not in company["connection_explanation"] for company in card["companies"])

    doomsday = next(card for card in payload["cards"] if card["event_key"] == "둠스데이")
    assert doomsday["companies"][0]["company"] == "월트 디즈니 컴퍼니"
    assert doomsday["companies"][0]["stock_code"] == "DIS"
    assert doomsday["companies"][0]["market"] == "NYSE"
    assert "마블 스튜디오" in doomsday["companies"][0]["connection_explanation"]


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


def test_ontology_relation_admission_requires_ten_evidenced_companies_and_three_roles():
    companies = [
        {
            "company": f"회사 {index}",
            "stock_code": f"{index:06d}",
            "company_role_category": ("manufacturing_development", "distribution", "platform_service")[index % 3],
            "relation_tier": "direct" if index % 2 else "value_chain",
            "evidence_scope": "ontology_verified_trend_to_company_relation",
            "relationship_evidence_url": f"https://evidence.example/{index}",
            "connection_explanation": "공식 근거로 확인한 트렌드-기업 연결",
        }
        for index in range(1, 11)
    ]
    assert audit_relation_set_for_publication(companies)["status"] == "ready"

    incomplete = audit_relation_set_for_publication(companies[:9])
    assert incomplete["status"] == "review_required"
    assert "minimum_ten_ontology_verified_companies" in incomplete["failures"]


def test_legacy_showcase_is_reported_as_review_required_not_relabelled_as_ontology_verified():
    ranking = [
        {"event_key": event_key, "rank": rank, "score": 100 - rank}
        for rank, (event_key, _display, _universe) in enumerate(SHOWCASE_SELECTION, 1)
    ]
    payload = build_showcase_enrichment(
        ranking,
        source_observed_at="2026-08-16T00:00:00+00:00",
    )
    receipts = audit_showcase_relation_coverage(payload)
    assert len(receipts) == 10
    assert all(receipt["status"] == "review_required" for receipt in receipts)
