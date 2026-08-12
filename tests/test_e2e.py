from trzip.e2e import run_e2e, to_markdown


def test_markdown_contains_top10_and_company_tables():
    result = {
        "run": {"ranking_at": "2026-08-12T04:00:00+00:00", "mode": "live", "hours": 24},
        "top10": [{"rank": 1, "topic": "야구 직관", "score": 80.0, "lifecycle": "rising",
                   "source_ranks": {"x": 3, "google_trends": 5}, "persistence": .5,
                   "keywords": [{"text": "유니폼"}], "company_count": 1}],
        "companies": [{"trend": "야구 직관", "relation_category": "시설·현장·주변소비", "company": "이마트", "stock_code": "139480",
                       "role": "공간·운영", "relation_tier": "핵심 사업자",
                       "opportunity_status": "confirmed_relationship", "dart_status": "verified",
                       "market_status": "observed", "reason": "구단 운영 연결"}],
    }
    report = to_markdown(result)
    assert "트렌드 통합 전체 순위" in report
    assert "관련기업·가치사슬" in report
    assert "이마트" in report


def test_e2e_top10_uses_public_quality_gate(monkeypatch):
    monkeypatch.setattr("trzip.e2e.collect_current", lambda **kwargs: {
        "observed_at": "2026-08-12T04:00:00+00:00", "observed": 2, "generated": 0,
    })
    monkeypatch.setattr("trzip.e2e.coverage", lambda: {})
    monkeypatch.setattr("trzip.e2e.integration_status", lambda: {})
    monkeypatch.setattr("trzip.e2e.build_intelligence", lambda *args, **kwargs: {
        "mode": "live", "sources": ["x", "google_trends"], "score_formula": "test",
        "quality_summary": {}, "lanes": {"issue": [], "review": []},
        "unified_ranking": [
            {"rank": 1, "topic": "미해결", "display_name": "미해결", "phenomenon_summary": "-", "raw_terms": ["미해결"],
             "category": "unclassified", "classification": "맥락 확인", "company_eligible": False,
             "persistence_rank": 1, "momentum_rank": 1, "age_hours": 1, "score": 99.0, "lifecycle": "new",
             "data_confidence": {}, "latest_source_ranks": {"x": 1}, "persistence": 1.0,
             "selection_reason": "검토", "keywords": [], "companies": [], "company_categories": [],
             "company_resolution": {"minimum_category_met": False}},
            {"rank": 2, "topic": "말복", "display_name": "말복", "phenomenon_summary": "-", "raw_terms": ["말복"],
             "category": "food", "classification": "일반 트렌드", "company_eligible": True,
             "persistence_rank": 2, "momentum_rank": 2, "age_hours": 1, "score": 90.0, "lifecycle": "new",
             "data_confidence": {}, "latest_source_ranks": {"google_trends": 1}, "persistence": 1.0,
             "selection_reason": "공개", "keywords": [], "companies": [], "company_categories": [],
             "company_resolution": {"minimum_category_met": False}},
        ],
        "public_top10": [{"topic": "말복"}],
    })

    result = run_e2e(collect=True, verify_companies=False, live_keywords=False)

    assert [item["topic"] for item in result["ranking"]] == ["미해결", "말복"]
    assert [item["topic"] for item in result["top10"]] == ["말복"]
