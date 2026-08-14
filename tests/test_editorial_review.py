from pathlib import Path
from datetime import UTC, datetime

from trzip.editorial_review import (
    apply_frontend_enrichment_cache,
    build_editorial_review_pack,
    load_daily_editorial_review,
)
from trzip.intelligence import _category


def _company(index: int) -> dict:
    return {
        "company": f"기업{index}",
        "stock_code": f"{index:06d}",
        "market": "KRX",
        "company_summary": f"기업{index} 설명",
        "reason": f"제품 공급 관계 {index}",
        "evidence_url": f"https://example.com/company/{index}",
        "verification_status": "ontology_evidence",
    }


def _automatic_row(
    rank: int,
    name: str,
    *,
    keywords: int = 5,
    companies: int = 10,
    lane: str = "main",
    category: str = "product_brand",
    broad_category: str = "consumer",
) -> dict:
    return {
        "rank": rank,
        "main_rank": rank if lane == "main" else None,
        "event_key": name,
        "display_name": name,
        "score": 100 - rank,
        "period_sources": ["google_trends"],
        "lane": lane,
        "category": category,
        "broad_category": broad_category,
        "context_status": "resolved_reference",
        "trend_fit": {"generic_category_word": False},
        "keywords": [{"text": f"키워드{index}"} for index in range(1, keywords + 1)],
        "companies": [_company(index) for index in range(1, companies + 1)],
    }


def test_unregistered_automatic_candidate_can_qualify_without_whitelist():
    source = {"unified_ranking": [_automatic_row(1, "새로운 제품 트렌드")]}

    pack = build_editorial_review_pack(source)

    assert [item["display_name"] for item in pack["trends"]] == ["새로운 제품 트렌드"]
    assert pack["trends"][0]["selection_basis"] == "automatic_product_fit_then_enrichment"
    assert pack["candidate_policy"]["product_fit_filter"]["registry_membership_affects_selection"] is False


def test_registered_cache_entry_cannot_override_lane_or_rank():
    rows = [
        _automatic_row(1, "새로운 제품 트렌드"),
        _automatic_row(2, "아이폰", lane="review"),
    ]

    pack = build_editorial_review_pack({"unified_ranking": rows})

    assert [item["display_name"] for item in pack["trends"]] == ["새로운 제품 트렌드"]
    iphone_audit = next(row for row in pack["selection_audit"] if row["event_key"] == "아이폰")
    assert iphone_audit["automatic_eligible"] is False
    assert iphone_audit["reason"] == "not_main_or_x_discovery"
    assert iphone_audit["cache_membership_affects_selection"] is False


def test_product_fit_item_outside_top_main_candidates_is_not_selected():
    row = _automatic_row(31, "후순위 로봇", category="technology_tool", broad_category="technology")

    pack = build_editorial_review_pack({"unified_ranking": [row]})

    assert pack["trends"] == []
    assert pack["selection_audit"][0]["reason"] == "outside_top_main_candidates"


def test_broad_raw_expression_is_not_promoted_by_a_specific_related_query():
    row = _automatic_row(8, "포괄 표현", category="screen_content", broad_category="content")
    row["context_status"] = "needs_context"
    row["category_basis"] = "observed_related_terms_general_rule"

    pack = build_editorial_review_pack({"unified_ranking": [row]})

    assert pack["trends"] == []
    assert pack["selection_audit"][0]["reason"] == "raw_expression_not_specific"


def test_incomplete_automatic_candidate_is_hidden_and_enters_enrichment_queue():
    source = {"unified_ranking": [_automatic_row(1, "자동 후보", keywords=2, companies=1)]}

    pack = build_editorial_review_pack(source)

    assert pack["trends"] == []
    assert pack["preview_ready"] is False
    assert pack["publication_ready"] is False
    assert pack["enrichment_queue"] == [{
        "observed_rank": 1,
        "event_key": "자동 후보",
        "keyword_count": 2,
        "company_count": 1,
        "missing_keywords": 3,
        "missing_companies": 9,
        "status": "enrichment_pending",
        "selection_reason": "automatic_product_fit",
    }]


def test_enrichment_cache_is_applied_only_after_automatic_selection():
    row = _automatic_row(7, "개기일식", keywords=0, companies=0)

    pack = build_editorial_review_pack({"unified_ranking": [row]})

    assert pack["trends"] == []
    assert pack["enrichment_queue"][0]["observed_rank"] == 7
    assert pack["enrichment_queue"][0]["company_count"] == 6


def test_frontend_cache_completes_display_data_without_changing_rank_or_selection():
    row = _automatic_row(7, "개기일식", keywords=0, companies=0)
    row.update({
        "observed_rank": 7,
        "home_rank": 3,
        "home_eligible": True,
        "score": 83.25,
    })
    immutable = {
        field: row[field]
        for field in ("rank", "observed_rank", "home_rank", "home_eligible", "score", "lane", "category")
    }
    payload = {"unified_ranking": [row]}

    apply_frontend_enrichment_cache(payload, verified_at="2026-08-13T12:00:00+00:00")

    item = payload["unified_ranking"][0]
    assert {field: item[field] for field in immutable} == immutable
    assert len(item["related_keywords"]) == 5
    assert item["companies"] == []
    assert len({company["stock_code"] for company in item["company_candidates"]}) == 6
    assert item["company_status"] == "enrichment_pending"


def test_frontend_cache_preserves_observed_keyword_provenance_before_filling_slots():
    row = _automatic_row(7, "아이폰", keywords=0, companies=0)
    observed_keyword = {
        "text": "아이폰 출시일",
        "source": ["google_trends"],
        "observed_hours": 2,
        "status": "observed_related_query",
        "role": "observed_related_expression",
        "role_status": "observed_evidence",
        "evidence_urls": [],
        "affects_score": False,
    }
    row["related_keywords"] = [observed_keyword]
    payload = {"unified_ranking": [row]}

    apply_frontend_enrichment_cache(payload, verified_at="2026-08-13T12:00:00+00:00")

    keywords = payload["unified_ranking"][0]["related_keywords"]
    assert len(keywords) == 5
    assert keywords[0] == observed_keyword
    assert all(keyword["affects_score"] is False for keyword in keywords)


def test_frontend_cache_replaces_three_structurally_incomplete_companies():
    row = _automatic_row(7, "개기일식", keywords=0, companies=0)
    row["companies"] = [
        {
            "company": f"미완성 기업 {index}",
            "stock_code": f"BAD{index}",
            "market": "NASDAQ",
        }
        for index in range(6)
    ]
    payload = {"unified_ranking": [row]}

    apply_frontend_enrichment_cache(payload, verified_at="2026-08-13T12:00:00+00:00")

    item = payload["unified_ranking"][0]
    assert item["companies"] == []
    assert len({company["stock_code"] for company in item["company_candidates"]}) == 6
    assert item["company_status"] == "enrichment_pending"


def test_astronomy_trends_share_evidence_backed_equipment_ontology_without_rank_changes():
    rows = [
        _automatic_row(
            1,
            "개기일식",
            keywords=0,
            companies=0,
            category="public_observation_event",
            broad_category="culture",
        ),
        _automatic_row(
            2,
            "유성우 시간",
            keywords=0,
            companies=0,
            category="public_observation_event",
            broad_category="culture",
        ),
    ]
    before = [(row["rank"], row["score"], row["lane"]) for row in rows]
    payload = {"unified_ranking": rows}

    apply_frontend_enrichment_cache(payload, verified_at="2026-08-13T12:00:00+00:00")

    assert [(row["rank"], row["score"], row["lane"]) for row in rows] == before
    for row in rows:
        assert row["keyword_status"] == "ready"
        assert len(row["related_keywords"]) == 5
        assert row["company_status"] == "enrichment_pending"
        assert row["companies"] == []
        assert {company["company"] for company in row["company_candidates"]} == {
            "Canon", "Nikon", "Ricoh", "FUJIFILM Holdings", "Sony Group", "Adobe",
        }
        assert all(company["ontology_complete"] is True for company in row["company_candidates"])
        assert all(company["evidence_sources"][0]["url"] for company in row["company_candidates"])


def test_additional_live_enrichment_caches_are_complete_and_do_not_select_trends():
    names = ["커피믹스", "용인반도체클러스터", "아시안 게임"]
    rows = [_automatic_row(index, name, keywords=0, companies=0) for index, name in enumerate(names, 1)]
    payload = {"unified_ranking": rows}

    apply_frontend_enrichment_cache(payload, verified_at="2026-08-13T12:00:00+00:00")

    for index, row in enumerate(rows, 1):
        assert row["rank"] == index
        assert row["score"] == 100 - index
        assert len(row["related_keywords"]) == 5
        assert row["keyword_status"] == "ready"
        assert row["companies"] == []
        assert len(row["company_candidates"]) == 6
        assert row["company_status"] == "enrichment_pending"


def test_coffee_mix_cache_keeps_six_verified_candidates_pending():
    row = _automatic_row(8, "커피믹스", keywords=0, companies=0)
    payload = {"unified_ranking": [row]}

    apply_frontend_enrichment_cache(payload, verified_at="2026-08-13T13:00:00+00:00")

    assert len(row["related_keywords"]) == 5
    assert row["companies"] == []
    assert len(row["company_candidates"]) == 6
    assert row["company_status"] == "enrichment_pending"
    assert all(company["ontology_complete"] is True for company in row["company_candidates"])
    assert all(company["evidence_sources"][0]["url"] for company in row["company_candidates"])


def test_live_frontend_caches_keep_six_role_categorized_candidates_pending():
    names = ["불꽃축제", "광 통신", "지스타", "코난 극장판", "휴머노이드 로봇"]
    rows = [_automatic_row(index, name, keywords=0, companies=0) for index, name in enumerate(names, 1)]
    payload = {"unified_ranking": rows}

    apply_frontend_enrichment_cache(payload, verified_at="2026-08-13T13:00:00+00:00")

    allowed_roles = {
        "manufacturing_development", "raw_materials_components", "content_production",
        "distribution", "retail_sales", "brand_marketing", "platform_service",
        "ownership_investment", "event_sponsorship", "unclassified",
    }
    for row in rows:
        assert len(row["related_keywords"]) == 5
        assert row["companies"] == []
        assert len(row["company_candidates"]) >= 6
        assert row["company_status"] == "enrichment_pending"
        assert all(company["company_role_category"] in allowed_roles for company in row["company_candidates"])
        assert all(company["company_role_label"] for company in row["company_candidates"])
        assert all(company["evidence_sources"][0]["url"] for company in row["company_candidates"])
        assert row["company_resolution"]["category_count"] >= 1

    conan = next(row for row in rows if row["display_name"] == "코난 극장판")
    assert {company["market"] for company in conan["company_candidates"]} == {"TSE"}
    assert {company["company_role_category"] for company in conan["company_candidates"]} >= {
        "content_production", "distribution", "brand_marketing",
    }


def test_every_emitted_trend_satisfies_complete_display_contract():
    source = {"unified_ranking": [_automatic_row(1, "완성 제품")]}

    item = build_editorial_review_pack(source)["trends"][0]

    assert len(item["related_keywords"]) == 5
    assert len(item["company_candidates"]) >= 6
    assert item["company_verification_status"] == "ready_for_team_selection"
    assert item["display_contract_status"] == "complete"
    assert item["trend_definition"] == "‘완성 제품’은(는) 특정 제품이나 브랜드를 중심으로 형성된 관심 흐름입니다."
    assert item["observation_summary"] == "선택 기간에 Google Trends 한국에서 ‘완성 제품’이(가) 실제 관측됐습니다."
    assert item["definition_status"] == "category_based_observed_topic_definition"


def test_top_ten_complete_automatic_candidates_form_publication_in_score_order():
    rows = [_automatic_row(rank, f"자동 제품 {rank}") for rank in range(1, 12)]

    pack = build_editorial_review_pack({"unified_ranking": list(reversed(rows))})

    assert pack["publication_ready"] is True
    assert pack["preview_ready"] is True
    assert pack["complete_trend_count"] == 10
    assert [item["observed_rank"] for item in pack["trends"]] == list(range(1, 11))


def test_daily_editorial_pack_cannot_change_automatic_selection_or_rank():
    root = Path(__file__).resolve().parents[1]
    review = load_daily_editorial_review(root / "config" / "daily-editorial" / "2026-08-13.json")
    source_rows = []
    for rank, item in enumerate(review["items"], start=1):
        for source_key in item["source_event_keys"]:
            row = _automatic_row(rank, source_key, keywords=0, companies=0)
            row["period_sources"] = ["x"]
            source_rows.append(row)

    generated_at = datetime(2026, 8, 13, tzinfo=UTC)
    automatic = build_editorial_review_pack(
        {"unified_ranking": source_rows}, generated_at=generated_at
    )
    reviewed = build_editorial_review_pack(
        {"unified_ranking": source_rows}, generated_at=generated_at, daily_review=review
    )

    assert reviewed["trends"] == automatic["trends"]
    assert reviewed["selection_audit"] == automatic["selection_audit"]
    assert reviewed["manual_review_supplied"] is True
    assert reviewed["manual_review_selection_effect"] == "none"


def test_x_top30_discovery_stays_in_queue_until_enrichment_is_complete():
    row = _automatic_row(
        17,
        "#NewCultureMoment",
        keywords=0,
        companies=0,
        lane="review",
        category="unclassified",
        broad_category="other",
    )
    row["latest_source_ranks"] = {"x": 9, "google_trends": None}
    row["period_sources"] = ["x"]
    row["context_status"] = "needs_context"

    pack = build_editorial_review_pack({"unified_ranking": [row]})

    assert pack["trends"] == []
    assert pack["enrichment_queue"][0]["observed_rank"] == 17
    assert pack["enrichment_queue"][0]["selection_reason"] == "x_top30_discovery_signal"
    assert pack["ranking_effect_of_enrichment"] == "none"


def test_unresolved_x_expression_needs_a_concrete_discovery_shape():
    row = _automatic_row(
        12,
        "모호한 표현",
        lane="review",
        category="unclassified",
        broad_category="other",
    )
    row["latest_source_ranks"] = {"x": 3, "google_trends": None}
    row["context_status"] = "needs_context"

    pack = build_editorial_review_pack({"unified_ranking": [row]})

    assert pack["trends"] == []
    assert pack["selection_audit"][0]["reason"] == "not_main_or_x_discovery"


def test_unresolved_screen_content_title_is_not_mistaken_for_a_specific_work():
    row = _automatic_row(4, "넓은 화면 표현", category="screen_content", broad_category="content")
    row["context_status"] = "needs_context"

    pack = build_editorial_review_pack({"unified_ranking": [row]})

    assert pack["trends"] == []
    assert pack["selection_audit"][0]["reason"] == "content_title_context_not_resolved"


def test_hashtag_discovery_cap_preserves_source_order_and_variety():
    rows = []
    for rank in range(1, 5):
        row = _automatic_row(
            rank,
            f"#ObservedMoment{rank}",
            lane="review",
            category="unclassified",
            broad_category="other",
        )
        row["latest_source_ranks"] = {"x": rank, "google_trends": None}
        row["period_sources"] = ["x"]
        row["context_status"] = "needs_context"
        rows.append(row)
    event = _automatic_row(
        5,
        "도심 불꽃축제",
        lane="review",
        category="unclassified",
        broad_category="other",
    )
    event["latest_source_ranks"] = {"x": 5, "google_trends": None}
    event["period_sources"] = ["x"]
    event["context_status"] = "needs_context"
    rows.append(event)

    pack = build_editorial_review_pack({"unified_ranking": rows})

    assert [item["observed_rank"] for item in pack["trends"]] == [1, 2, 3, 5]
    capped = next(row for row in pack["selection_audit"] if row["observed_rank"] == 4)
    assert capped["reason"] == "hashtag_discovery_diversity_cap"


def test_named_technology_is_classified_by_generic_markers_not_exact_whitelist():
    assert _category("smr") == "unclassified"
    assert _category("삼전닉스") == "unclassified"
    assert _category("휴머노이드 로봇") == "technology_tool"
    assert _category("물류 로봇") == "technology_tool"
