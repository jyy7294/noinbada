from trzip.intelligence import apply_equal_platform_home_scores, refresh_frontend_readiness


def _company(index: int, role: str) -> dict:
    return {
        "company": f"Company {index}", "stock_code": f"C{index:03d}", "market": "NYSE",
        "company_description": "Listed company description", "relationship_reason": "Evidence-backed relation",
        "connection_explanation": "키워드0 맥락에서 확인된 기업 역할입니다.",
        "matched_keywords": ["키워드0", "키워드1"],
        "company_role_category": role, "company_role_label": role,
        "relation_tier": "direct", "ontology_complete": True,
        "ontology_path": [{"to": "industry"}, {"to": f"Company {index}"}],
        "evidence_sources": [{"url": f"https://example.com/{index}"}],
    }


def test_home_feed_is_rank_free_and_groups_positive_cross_platform_candidate():
    item = {
        "event_key": "event-a", "display_name": "테스트 트렌드", "lane": "main",
        "home_eligible": True, "is_current": True, "lifecycle": "rising",
        "broad_category": "consumer", "category_label": "제품·브랜드",
        "latest_source_ranks": {"x": 2, "google_trends": 3}, "score": 70,
        "observed_rank": 1, "momentum_delta": 0.5,
        "series": [{
            "at": "2026-08-15T04:00:00+00:00", "source": "x",
            "rank": 2, "value": 99, "provenance": "observed",
        }],
        "ranking_data_readiness": {"momentum_status": "measured"},
        "persistence": 0.5, "freshness": 1.0, "keyword_status": "ready",
        "related_keywords": [{"text": f"키워드{i}", "source": ["x"]} for i in range(5)],
        "companies": [
            _company(
                i,
                "platform_service"
                if i < 4
                else "brand_marketing"
                if i < 7
                else "distribution",
            )
            for i in range(10)
        ],
        "company_eligible": True, "trend_definition": "테스트 대상은 X와 Google 대한민국 관측값에서 함께 확인된 제품 관심 흐름입니다.",
        "disclaimer": "투자 추천이나 수익 예측이 아닙니다.",
        "context_research": {"status": "ready", "trigger_title": "테스트 트렌드 확산", "why_now": "NAVER 뉴스의 최근 기사 제목으로 맥락을 확인했습니다.", "evidence_urls": ["https://example.com/news"]},
        "stock_impact_hypothesis": {"direction": "uncertain", "path": "trend to industry", "evidence": ["https://example.com/news"], "confidence": "low"},
        "verification_layer": {"providers": {"naver": {"status": "observed", "matched": True, "metrics": {"news_recent_24h_sample_count": 2, "news_independent_host_count": 2}}}},
    }
    intelligence = {"unified_ranking": [item], "category_summary": [], "ranking_views": {}}

    refresh_frontend_readiness(intelligence)

    feed = intelligence["home_feed"]
    assert feed["status"] == "ready"
    assert feed["groups"][0]["key"] == "spreading"
    card = feed["groups"][0]["trends"][0]
    assert not {"observed_rank", "home_rank", "publication_rank", "score"} & set(card)
    assert card["disclaimer"] == item["disclaimer"]
    assert card["keyword_company_links"] == item["keyword_company_links"]
    assert card["platform_observation_summary"]["x"]["observed"] is True
    assert card["platform_observation_summary"]["naver_news"]["selection_input"] is False
    # The new feed stays rank-free, while the one-release compatibility array
    # keeps a numbered Top10 for the current frontend.
    assert [row["event_key"] for row in intelligence["home_top10"]] == [card["event_key"]]
    assert intelligence["home_top10"][0]["publication_rank"] == 1


def test_naver_news_is_context_only_and_never_changes_x_google_weights():
    rows = [
        {"event_key": f"e{i}", "score": 100-i, "observed_rank": i,
         "latest_source_ranks": {"x": i, "google_trends": i},
         "verification_layer": {"providers": {"naver": {"status": "observed", "matched": True,
             "metrics": {"news_recent_24h_sample_count": 1, "news_independent_host_count": 1}}}}}
        for i in range(1, 10)
    ]
    apply_equal_platform_home_scores(rows)
    assert all(
        row["naver_home_rank_status"] == "context_only_not_comparable_rank_signal"
        for row in rows
    )
    assert all(row["home_rank_input_sources"] == ["x", "google_trends"] for row in rows)


def test_home_score_accepts_period_freshness_record():
    rows = [{
        "event_key": "period-freshness",
        "score": 80,
        "observed_rank": 1,
        "latest_source_ranks": {"x": 1, "google_trends": 2},
        "momentum_delta": 0.4,
        "persistence": 0.5,
        "freshness": {
            "signal": 0.5,
            "half_life_hours": 12.0,
            "hours_since_last_seen": 12.0,
        },
    }]

    apply_equal_platform_home_scores(rows)

    assert rows[0]["_home_selection_components"]["recency"] == 50.0
