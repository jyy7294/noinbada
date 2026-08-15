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


def test_daily_period_top10_uses_same_selection_signals_as_top_level_alias():
    def candidate(key: str, *, score: float, source_rank: int) -> dict:
        roles = ["platform_service", "brand_marketing", "distribution"]
        item = {
            "event_key": key,
            "display_name": key,
            "lane": "main",
            "home_eligible": True,
            "is_current": True,
            "lifecycle": "sustained",
            "broad_category": "consumer",
            "category_label": "제품·브랜드",
            "latest_source_ranks": {
                "x": source_rank,
                "google_trends": source_rank,
            },
            "score": score,
            "observed_rank": source_rank,
            "rank": source_rank,
            "momentum_delta": 0.0,
            "series": [{
                "at": "2026-08-15T14:00:00+00:00",
                "source": "x",
                "rank": source_rank,
                "value": 1,
                "provenance": "observed",
            }],
            "ranking_data_readiness": {"momentum_status": "unavailable"},
            "candidate_status": "is_current",
            "period_sources": ["x", "google_trends"],
            "hours_since_last_seen": 0.0,
            "persistence": 0.0,
            "freshness": 0.0,
            "keyword_status": "ready",
            "related_keywords": [
                {"text": f"키워드{i}", "source": ["x"]} for i in range(5)
            ],
            "companies": [
                _company(i, roles[i % len(roles)]) for i in range(10)
            ],
            "company_eligible": True,
            "trend_definition": "동일 선발 계약 검증용 트렌드입니다.",
            "context_research": {
                "status": "ready",
                "trigger_title": "검증된 현재 촉발 사건",
                "why_now": "공개 근거로 현재 맥락을 확인했습니다.",
                "evidence_urls": ["https://example.com/news"],
            },
        }
        return item

    # Canonical score prefers A, while current X/Google position prefers B.
    # The daily period rows intentionally omit the private selection-score
    # cache, matching the public schema used by the real pipeline.
    a = candidate("event-a", score=90.0, source_rank=10)
    b = candidate("event-b", score=80.0, source_rank=1)
    daily_rows = [dict(a), dict(b)]
    intelligence = {
        "unified_ranking": [a, b],
        "category_summary": [],
        "ranking_views": {
            "daily": {"unified_ranking": daily_rows, "period_top10": []},
        },
    }

    refresh_frontend_readiness(intelligence)

    top_keys = [item["event_key"] for item in intelligence["trend_top10"]]
    daily_keys = [
        item["event_key"]
        for item in intelligence["ranking_views"]["daily"]["period_top10"]
    ]
    assert top_keys == ["event-b", "event-a"]
    assert daily_keys == top_keys
    assert all("_home_selection_score" not in item for item in daily_rows)


def test_daily_period_summary_keeps_recent_observed_card_without_series_payload():
    roles = ["platform_service", "brand_marketing", "distribution"]
    item = {
        "event_key": "삼계탕",
        "display_name": "삼계탕",
        "lane": "main",
        "home_eligible": True,
        "is_current": False,
        "candidate_status": "period_observed",
        "period_sources": ["google_trends"],
        "hours_since_last_seen": 9.0,
        "lifecycle": "cooling",
        "broad_category": "food",
        "category_label": "음식",
        "latest_source_ranks": {"google_trends": 12},
        "score": 70.0,
        "observed_rank": 1,
        "rank": 1,
        "momentum_delta": 0.0,
        "series": [{
            "at": "2026-08-15T05:00:00+00:00",
            "source": "google_trends",
            "rank": 12,
            "value": 1,
            "provenance": "observed",
        }],
        "ranking_data_readiness": {"momentum_status": "unavailable"},
        "persistence": 0.2,
        "freshness": {"signal": 0.6},
        "keyword_status": "ready",
        "related_keywords": [
            {"text": f"키워드{i}", "source": ["google_trends"]}
            for i in range(5)
        ],
        "companies": [
            _company(i, roles[i % len(roles)]) for i in range(10)
        ],
        "company_eligible": True,
        "trend_definition": "복날 소비 맥락에서 관측된 음식 트렌드입니다.",
        "context_research": {
            "status": "ready",
            "trigger_title": "말복 삼계탕 수요",
            "why_now": "공개 기사로 복날 소비 맥락을 확인했습니다.",
            "evidence_urls": ["https://example.com/samgyetang"],
        },
    }
    # Real period summaries retain candidate_status, period_sources and
    # freshness but intentionally do not duplicate the full observed series.
    daily_summary = dict(item)
    daily_summary.pop("series")
    intelligence = {
        "unified_ranking": [item],
        "category_summary": [],
        "ranking_views": {
            "daily": {"unified_ranking": [daily_summary], "period_top10": []},
        },
    }

    refresh_frontend_readiness(intelligence)

    assert [row["event_key"] for row in intelligence["trend_top10"]] == ["삼계탕"]
    assert [
        row["event_key"]
        for row in intelligence["ranking_views"]["daily"]["period_top10"]
    ] == ["삼계탕"]
    assert "series" not in daily_summary


def test_final_enrichment_recomputes_company_resolution_without_changing_rank():
    roles = ["platform_service", "brand_marketing", "distribution"]
    companies = [_company(i, roles[i % len(roles)]) for i in range(10)]
    item = {
        "event_key": "삼계탕",
        "display_name": "삼계탕",
        "lane": "main",
        "home_eligible": True,
        "home_context_status": "resolved",
        "is_current": True,
        "lifecycle": "sustained",
        "broad_category": "food",
        "category_label": "음식",
        "latest_source_ranks": {"google_trends": 3},
        "score": 81.5,
        "observed_rank": 4,
        "rank": 4,
        "momentum_delta": 0.0,
        "series": [{
            "at": "2026-08-15T14:00:00+00:00",
            "source": "google_trends",
            "rank": 3,
            "value": 100,
            "provenance": "observed",
        }],
        "ranking_data_readiness": {"momentum_status": "unavailable"},
        "persistence": 0.2,
        "freshness": 1.0,
        "keyword_status": "ready",
        "related_keywords": [
            {"text": f"키워드{i}", "source": ["google_trends"]}
            for i in range(5)
        ],
        # Reproduces an approved handoff attached after the initial pass:
        # the evidence is complete while the initial resolution is stale.
        "companies": companies,
        "company_candidates": [],
        "company_eligible": False,
        "company_resolution": {
            "status": "not_published",
            "publish_status": "not_published",
            "published_count": 0,
        },
        "trend_definition": "복날 소비 맥락에서 관측된 음식 트렌드입니다.",
        "context_research": {
            "status": "ready",
            "trigger_title": "말복 삼계탕 수요",
            "why_now": "공개 기사로 복날 소비 맥락을 확인했습니다.",
            "evidence_urls": ["https://example.com/samgyetang"],
        },
    }
    observed_state = (
        item["observed_rank"], item["rank"], item["score"],
        dict(item["latest_source_ranks"]), list(item["series"]),
    )
    intelligence = {
        "unified_ranking": [item],
        "category_summary": [],
        "ranking_views": {},
    }

    refresh_frontend_readiness(intelligence)

    assert item["company_eligible"] is True
    assert item["company_resolution"]["publish_status"] == "published"
    assert item["company_resolution"]["published_count"] == 10
    assert item["company_resolution"]["category_count"] == 3
    assert len(item["companies"]) == 10
    assert item["frontend_readiness_status"] == "ready"
    assert (
        item["observed_rank"], item["rank"], item["score"],
        item["latest_source_ranks"], item["series"],
    ) == observed_state


def test_final_company_state_fails_closed_for_ineligible_or_incomplete_rows():
    roles = ["platform_service", "brand_marketing", "distribution"]

    def row(key: str, *, lane: str, company_count: int) -> dict:
        return {
            "event_key": key,
            "display_name": key,
            "lane": lane,
            "home_eligible": lane == "main",
            "is_current": True,
            "lifecycle": "sustained",
            "broad_category": "consumer",
            "category_label": "제품·브랜드",
            "latest_source_ranks": {"x": 1},
            "score": 70,
            "observed_rank": 1,
            "rank": 1,
            "momentum_delta": 0.0,
            "series": [{
                "at": "2026-08-15T14:00:00+00:00", "source": "x",
                "rank": 1, "value": 1, "provenance": "observed",
            }],
            "ranking_data_readiness": {"momentum_status": "unavailable"},
            "persistence": 0.1,
            "freshness": 1.0,
            "keyword_status": "ready",
            "related_keywords": [
                {"text": f"키워드{i}", "source": ["x"]} for i in range(5)
            ],
            "companies": [
                _company(i, roles[i % len(roles)]) for i in range(company_count)
            ],
            "company_eligible": True,
            "company_resolution": {"publish_status": "published"},
            "trend_definition": "검증용 트렌드입니다.",
            "context_research": {
                "status": "ready", "trigger_title": "검증 근거",
                "why_now": "공개 근거를 확인했습니다.",
                "evidence_urls": ["https://example.com/evidence"],
            },
        }

    issue = row("정치 이슈", lane="issue", company_count=10)
    incomplete = row("기업 여덟", lane="main", company_count=8)
    missing_relation_grade = row("관계 미확정", lane="main", company_count=10)
    for company in missing_relation_grade["companies"]:
        company.pop("relation_tier", None)
    intelligence = {
        "unified_ranking": [issue, incomplete, missing_relation_grade],
        "category_summary": [],
        "ranking_views": {},
    }

    refresh_frontend_readiness(intelligence)

    for item in (issue, incomplete, missing_relation_grade):
        assert item["companies"] == []
        assert item["company_resolution"]["publish_status"] == "not_published"
        assert item["company_resolution"]["published_count"] == 0
        assert item["frontend_readiness_status"] == "enrichment_pending"
