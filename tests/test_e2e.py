from trzip.e2e import to_markdown


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
