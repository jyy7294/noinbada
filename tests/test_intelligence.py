from datetime import UTC, datetime, timedelta

from trzip.company_adapters import integration_status, opendart_company, pykrx_stock
from trzip.hourly_store import HourlyObservation, upsert
from trzip.intelligence import (
    _broad_category,
    _category,
    _frontend_story,
    _home_context_gate,
    _path_relation_tier,
    _provider_issue_context_titles,
    _assign_canonical_topics,
    build_intelligence,
    canonical_topic,
    refresh_frontend_readiness,
)


def test_frontend_refresh_reconciles_company_reason_and_excludes_expired_rising():
    companies = [
        {
            "company": f"Company {index}",
            "stock_code": f"T{index}",
            "market": "NASDAQ",
            "company_description": "evidence-backed listed company",
            "relationship_reason": "documented relationship",
            "evidence_sources": [{"url": f"https://example.com/{index}"}],
            "ontology_complete": True,
        }
        for index in range(10)
    ]
    expired = {
        "event_key": "expired-rising",
        "display_name": "Expired rising",
        "lane": "main",
        "home_eligible": True,
        "broad_category": "content",
        "keyword_status": "ready",
        "related_keywords": [{"text": str(index)} for index in range(5)],
        "companies": companies,
        "company_eligible": True,
        "company_card_status": "enrichment_pending",
        "company_status": "enrichment_pending",
        "company_card_reason": "fewer_than_ten_evidence_backed_companies",
        "ranking_data_readiness": {"momentum_status": "measured"},
        "momentum_delta": 1.0,
        "period_strength": 1.0,
        "observed_rank": 1,
        "is_current": False,
        "lifecycle": "expired",
    }
    intelligence = {
        "unified_ranking": [expired],
        "category_summary": [],
        "ranking_views": {},
        "publication_readiness": {},
    }

    refresh_frontend_readiness(intelligence)

    assert expired["company_card_status"] == "ready"
    assert expired["company_card_reason"] == "evidence_backed_ten_or_more"
    assert intelligence["rising_top10"] == []


def test_aliases_are_normalized_to_events():
    assert canonical_topic("두쫀쿠") == "두쫀쿠"
    assert canonical_topic("말복") == "말복"
    assert canonical_topic("#JIN_IN_BALTIMORE_D2") == "jin in baltimore d2"
    assert canonical_topic("#JIN_LIGHTS_UP_CHARM_CITY") == canonical_topic(
        "JIN LIGHTS UP CHARM CITY"
    )
    assert canonical_topic("볼티모어") == "볼티모어"
    assert canonical_topic("cpi 발표") == "cpi"
    assert canonical_topic("로스앤젤레스 FC 대 케레타로 FC 순위") == canonical_topic(
        "엘에이 FC 대 케레타로"
    )


def test_public_observation_event_is_a_culture_trend_without_a_manual_allowlist():
    assert _category("개기일식") == "public_observation_event"
    assert _broad_category(_category("개기일식")) == "culture"


def test_trend_definition_explains_meaning_and_observed_context():
    from trzip.intelligence import _trend_definition

    definition = _trend_definition(
        "개기일식",
        "문화·밈·참여",
        ["일식", "개기일식 시간"],
    )

    assert "관측·공유·참여" in definition
    assert "일식, 개기일식 시간" in definition
    assert "X와 Google 대한민국 관측값" in definition
    assert "투자 추천을 의미하지 않습니다" in definition


def test_frontend_story_keeps_related_terms_as_context_not_causal_lineage():
    story = _frontend_story({
        "event_key": "두쫀쿠",
        "display_name": "두쫀쿠",
        "observed_representative_term": "두쫀쿠",
        "first_seen_at": "2026-08-14T00:00:00+00:00",
        "age_hours": 28,
        "lifecycle": "rising",
        "lifecycle_baseline": {"observed_hours": 5},
        "related_keywords": [
            {
                "text": "두바이 초콜릿",
                "status": "observed_related_query",
                "evidence_urls": ["https://trends.google.com/trending?geo=KR"],
            },
            {
                "text": "마시멜로",
                "status": "approved_ontology_related_term",
                "evidence_urls": ["https://example.com/ontology"],
            },
        ],
        "context_research": {
            "status": "ready",
            "trigger_title": "신제품 영상 확산",
            "trigger_type": "creator_spread",
            "why_now": "짧은 영상 공유가 늘었다.",
            "evidence_urls": ["https://example.com/trigger"],
        },
        "attention_change": {
            "24h": {"status": "measured", "percent": 38.2},
        },
        "latest_source_ranks": {"x": 3, "google_trends": 7},
        "rank_change_by_source": {"x": 2, "google_trends": None},
    })

    assert story["diffusion"]["phase_label"] == "확산 중"
    assert story["diffusion"]["observed_day_label"] == "관측 2일차"
    assert story["diffusion"]["attention_lift"]["label"] == "24시간 관심 점수 +38.2%"
    assert story["relationship_graph"]["interpretation"] == "observed_context_graph_not_causal_lineage"
    assert story["relationship_graph"]["edges"][0]["relation_type"] == "source_related_query"
    assert story["relationship_graph"]["edges"][0]["causality"] == "not_inferred"
    assert story["diffusion"]["channels"][0]["movement_label"] == "직전 관측 대비 순위 +2"


def test_astronomy_aliases_merge_only_with_source_related_query_context():
    assert canonical_topic("일식") == "일식"
    assert canonical_topic("일식", '["개기일식 시간"]') == "개기일식"
    assert canonical_topic(
        "별똥별", '["유성우 시간", "페르세우스 유성우 시간"]'
    ) == "페르세우스 유성우"
    assert canonical_topic(
        "페르세우스", '["페르세우스 유성우 방향", "오늘 유성우"]'
    ) == "페르세우스 유성우"
    assert canonical_topic("별똥별", '["드라마 별똥별"]') == "별똥별"


def test_same_expression_shares_source_context_within_one_day():
    rows = _assign_canonical_topics([
        {
            "observed_at": "2026-08-13T10:00:00+00:00",
            "topic": "페르세우스",
            "related_terms_json": None,
        },
        {
            "observed_at": "2026-08-13T13:00:00+00:00",
            "topic": "페르세우스",
            "related_terms_json": '["페르세우스 유성우 방향", "오늘 유성우"]',
        },
    ])
    assert {row["event_key"] for row in rows} == {"페르세우스 유성우"}


def test_single_source_market_term_needs_extra_home_context():
    base = {
        "lane": "main",
        "category": "investment_market",
        "broad_category": "market",
        "context_status": "resolved",
        "trend_fit": {"labels": ["named_object"]},
        "period_sources": ["google_trends"],
    }
    assert _home_context_gate(base) == (False, "market_context_evidence_missing")

    consumer_context = {
        **base,
        "trend_fit": {"labels": ["named_object", "consumer_action"]},
        "context_research": {
            "status": "ready", "trigger_title": "공식 발표",
            "why_now": "공식 발표 뒤 관심이 증가했다.",
            "evidence_urls": ["https://example.com/trigger"],
        },
    }
    assert _home_context_gate(consumer_context) == (True, "verified_trigger_event")

    cross_source = {
        **base,
        "period_sources": ["x", "google_trends"],
        "context_research": consumer_context["context_research"],
    }
    assert _home_context_gate(cross_source) == (True, "verified_trigger_event")


def test_listing_edge_alone_never_promotes_a_company_to_direct_relation():
    assert _path_relation_tier([{"relation_type": "listed_as"}]) == "adjacent"
    assert _path_relation_tier([
        {
            "relation_type": "parent_company_exposure_via_broadcaster",
            "metadata": {"relation_tier": "value_chain"},
        },
        {"relation_type": "listed_as"},
    ]) == "value_chain"


def test_product_facing_industry_observation_tier_stays_cautious_in_public_contract():
    assert _path_relation_tier([
        {
            "relation_type": "develops_adjacent_robot",
            "metadata": {"relation_tier": "industry_observation"},
        },
        {"relation_type": "listed_as"},
    ]) == "adjacent"


def test_provider_issue_titles_require_specific_exact_term_match():
    providers = {
        "youtube": {
            "matched": True,
            "evidence": [
                {"title": "삼성증권 유령주식 18억 배상 판결"},
                {"title": "다른 증권사 투자 설명회"},
            ],
        }
    }

    assert _provider_issue_context_titles(providers, "삼성증권") == [
        "삼성증권 유령주식 18억 배상 판결"
    ]
    assert _provider_issue_context_titles(providers, "음식") == []


def test_cpi_release_variant_is_one_event_without_double_counting_source(tmp_path):
    target = tmp_path / "cpi-variant.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(at.isoformat(), "google_trends", "cpi", 1, 100, "observed"),
        HourlyObservation(at.isoformat(), "google_trends", "cpi 발표", 2, 99, "observed"),
    ], target)

    result = build_intelligence(at, hours=1, path=target)

    assert len(result["unified_ranking"]) == 1
    event = result["unified_ranking"][0]
    assert event["topic"] == "cpi"
    assert event["raw_terms"] == ["cpi", "cpi 발표"]
    assert event["latest_source_ranks"] == {"google_trends": 1}
    assert event["current_source_position"] == 0.5


def test_sports_fixture_variants_merge_and_publish_compact_display_name(tmp_path):
    target = tmp_path / "fixture-variants.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(
            at.isoformat(), "google_trends",
            "로스앤젤레스 FC 대 케레타로 FC 순위", 1, 100, "observed"
        ),
        HourlyObservation(
            at.isoformat(), "google_trends",
            "엘에이 FC 대 케레타로", 2, 99, "observed"
        ),
    ], target)

    result = build_intelligence(at, hours=1, path=target)

    assert len(result["unified_ranking"]) == 1
    event = result["unified_ranking"][0]
    assert event["event_key"] == "로스앤젤레스 대 케레타로"
    assert event["display_name"] == "로스앤젤레스 대 케레타로"
    assert event["display_name_policy"] == "normalized_sports_fixture"
    assert event["latest_source_ranks"] == {"google_trends": 1}


def test_company_gold_never_fills_missing_companies_with_templates(tmp_path):
    target = tmp_path / "evidence-only-companies.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(
            at.isoformat(), "google_trends", "아이폰·스마트폰 확산", 1, 100, "observed"
        )
    ], target)
    result = build_intelligence(at, hours=1, path=target)

    trend = result["unified_ranking"][0]
    published = trend["companies"]
    assert len({company["stock_code"] for company in published}) >= 5
    assert all(company["ontology_complete"] for company in published)
    assert all(company["relationship_reason"] for company in published)
    assert all(company["company_summary"] for company in published)
    assert all(company["evidence_sources"] for company in published)
    assert trend["company_resolution"]["publish_status"] == "published"
    assert trend["company_resolution"]["ontology_diagnostics"]["padding_forbidden"] is True
    queue = result["ontology_enrichment_queue"]
    assert len(queue) == 1
    assert queue[0]["missing_company_paths"] == 4
    assert queue[0]["minimum_required"] == 10


def test_three_evidence_backed_companies_are_publishable_gold(tmp_path):
    target = tmp_path / "ontology-incomplete.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(
            at.isoformat(), "google_trends", "두바이 쫀득쿠키", 1, 100, "observed"
        )
    ], target)

    result = build_intelligence(at, hours=1, path=target)
    trend = result["unified_ranking"][0]

    assert len({company["stock_code"] for company in trend["company_candidates"]}) == 3
    assert trend["companies"] == trend["company_candidates"]
    assert trend["company_resolution"]["publish_status"] == "published"
    assert trend["company_resolution"]["minimum_gold_companies"] == 3
    assert trend["company_card_status"] == "enrichment_pending"
    assert trend["company_card_reason"] == "fewer_than_ten_evidence_backed_companies"
    queue = result["ontology_enrichment_queue"]
    assert len(queue) == 1
    assert queue[0]["missing_company_paths"] == 7
    assert queue[0]["minimum_required"] == 10


def test_registered_person_name_stays_ranked_but_manual_reference_does_not_promote_it(tmp_path):
    from trzip.hourly_store import HourlyObservation
    target = tmp_path / "person-issue.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([HourlyObservation(at.isoformat(), "google_trends", "지드래곤", 1, 100, "observed")], target)
    result = build_intelligence(at, hours=1, path=target)
    person = next(item for item in result["unified_ranking"] if item["topic"] == "지드래곤")
    assert person["classification"] == "맥락 확인"
    assert person["lane"] == "review"
    assert person["companies"] == []
    assert person["company_candidates"] == []
    assert person["company_resolution"]["status"] == "ontology_incomplete"


def test_policy_issue_stays_ranked_but_has_no_company_candidates(tmp_path):
    from trzip.hourly_store import HourlyObservation
    target = tmp_path / "issue.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([HourlyObservation(at.isoformat(), "google_trends", "국가장학금", 1, 100, "observed")], target)
    result = build_intelligence(at, hours=1, path=target)
    issue = result["unified_ranking"][0]
    assert issue["classification"] == "이슈·주의"
    assert issue["companies"] == []
    assert issue["company_eligible"] is False


def test_controversy_context_is_ranked_but_never_company_mapped(tmp_path):
    from trzip.hourly_store import HourlyObservation
    target = tmp_path / "controversy.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([HourlyObservation(at.isoformat(), "x", "증조부 친일", 2, 99, "observed")], target)
    item = build_intelligence(at, hours=1, path=target)["unified_ranking"][0]
    assert item["classification"] == "이슈·주의"
    assert item["company_eligible"] is False
    assert item["companies"] == []


def test_intelligence_returns_series_lanes_and_company_evidence(tmp_path):
    target = tmp_path / "intelligence.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(
            at.isoformat(), "google_trends", "아이폰·스마트폰 확산", 1, 100, "observed"
        )
    ], target)
    result = build_intelligence(at, hours=1, path=target)
    assert result["mode"] == "live"
    assert result["is_live"] is True
    assert result["lanes"]["main"]
    item = result["lanes"]["main"][0]
    assert item["series"]
    assert item["broad_category"] in {
        "food", "content", "lifestyle", "sports", "culture",
        "consumer", "technology", "market", "issue", "other",
    }
    assert len(item["companies"]) >= 5
    candidate = item["company_candidates"][0]
    assert candidate["stock_code"]
    assert candidate["ontology_complete"] is True
    assert all(edge["evidence_urls"] for edge in candidate["ontology_path"])


def test_integrations_fail_closed_without_credentials(monkeypatch):
    monkeypatch.setenv("TRZIP_DISABLE_USER_SECRET_BRIDGE", "1")
    for name in ("OPENDART_API_KEY",):
        monkeypatch.delenv(name, raising=False)
    status = integration_status()
    assert status["opendart"]["configured"] is False
    assert status["pykrx"]["configured"] is True
    assert opendart_company("삼양식품")["status"] == "unavailable"
    assert pykrx_stock("bad-code")["status"] == "invalid"


def test_region_name_is_not_misclassified_as_sports_by_substring(tmp_path):
    target = tmp_path / "region-name.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(at.isoformat(), "google_trends", "경기도", 1, 100, "observed")
    ], target)

    trend = build_intelligence(at, hours=1, path=target)["unified_ranking"][0]

    assert trend["category"] == "unclassified"
    assert trend["lane"] == "review"


def test_drama_director_honorific_is_not_misclassified_as_sports(tmp_path):
    target = tmp_path / "director-not-sports.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(
            at.isoformat(), "google_trends", "안판석 감독님", 1, 100, "observed"
        )
    ], target)

    trend = build_intelligence(at, hours=1, path=target)["unified_ranking"][0]

    assert trend["category"] != "sports_participation"
    assert trend["broad_category"] != "sports"


def test_automatic_main_filter_does_not_use_reviewed_brand_or_team_names(tmp_path):
    target = tmp_path / "weak-main-filter.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(at.isoformat(), "google_trends", "삼성증권", 1, 100, "observed"),
        HourlyObservation(at.isoformat(), "google_trends", "티빙", 2, 99, "observed"),
        HourlyObservation(at.isoformat(), "google_trends", "롯데 자이언츠", 3, 98, "observed"),
        HourlyObservation(at.isoformat(), "google_trends", "휴머노이드 로봇", 4, 97, "observed"),
        HourlyObservation(at.isoformat(), "google_trends", "음식", 5, 96, "observed"),
    ], target)

    result = build_intelligence(at, hours=1, path=target)
    by_topic = {item["topic"]: item for item in result["unified_ranking"]}

    assert by_topic["삼성증권"]["broad_category"] == "market"
    assert by_topic["티빙"]["broad_category"] == "other"
    assert by_topic["롯데 자이언츠"]["broad_category"] == "other"
    assert by_topic["휴머노이드 로봇"]["broad_category"] == "technology"
    assert all(by_topic[topic]["lane"] == "main" for topic in (
        "삼성증권", "휴머노이드 로봇",
    ))
    assert all(by_topic[topic]["lane"] == "review" for topic in (
        "티빙", "롯데 자이언츠",
    ))
    assert by_topic["음식"]["lane"] == "review"


def test_broad_raw_word_and_unresolved_title_do_not_enter_home(tmp_path):
    target = tmp_path / "broad-home-guard.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(
            at.isoformat(), "google_trends", "운전", 1, 100, "observed",
            related_terms_json='["블랙박스 리뷰", "교통 영상"]',
        ),
        HourlyObservation(at.isoformat(), "google_trends", "미스코리아", 2, 99, "observed"),
        HourlyObservation(at.isoformat(), "google_trends", "커피믹스", 3, 98, "observed"),
    ], target)

    result = build_intelligence(at, hours=1, path=target)
    by_topic = {item["topic"]: item for item in result["unified_ranking"]}

    assert by_topic["운전"]["lane"] == "review"
    assert by_topic["미스코리아"]["lane"] == "review"
    assert by_topic["커피믹스"]["lane"] == "main"
    assert result["home_top10"] == []
    assert by_topic["커피믹스"]["frontend_readiness_status"] == "enrichment_pending"
    assert result["publication_readiness"]["publication_ready"] is False


def test_intelligence_exposes_lifecycle_and_rank_movement(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert
    target = tmp_path / "movement.sqlite3"
    rows = []
    for hour, rank in ((0, 8), (1, 3)):
        at = datetime(2026, 7, 15, hour, tzinfo=UTC).isoformat()
        rows.append(HourlyObservation(at, "x", "불닭", rank, 101-rank, "observed"))
    upsert(rows, target)
    result = build_intelligence(datetime(2026, 7, 15, 1, tzinfo=UTC), hours=2, path=target)
    buldak = next(item for item in result["lanes"]["main"] if item["topic"] == "불닭")
    assert buldak["rank_change_by_source"]["x"] == 5
    assert buldak["lifecycle"] in {"new", "rising"}
    assert buldak["first_seen_at"].endswith("+00:00")


def test_semantic_reference_aliases_do_not_merge_or_promote_observed_rows(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert
    target = tmp_path / "keyword-evidence.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(at.isoformat(), "x", "#JIN_IN_BALTIMORE_D2", 4, 96, "observed"),
        HourlyObservation(at.isoformat(), "x", "JIN LIGHTS UP CHARM CITY", 9, 91, "observed"),
    ], target)
    result = build_intelligence(at, hours=1, path=target)
    assert {item["event_key"] for item in result["unified_ranking"]} == {
        "jin in baltimore d2", "jin lights up charm city",
    }
    assert all(item["lane"] == "review" for item in result["unified_ranking"])
    assert result["home_top10"] == []


def test_google_related_queries_can_disambiguate_category_without_renaming_term(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert

    target = tmp_path / "related-category.sqlite3"
    at = datetime(2026, 8, 12, 4, tzinfo=UTC)
    upsert([
        HourlyObservation(
            at.isoformat(), "google_trends", "홍길동", 1, 100, "observed",
            related_terms_json='["홍길동 야구 경기", "홍길동 선수"]',
        )
    ], target)

    item = build_intelligence(at, hours=1, path=target)["unified_ranking"][0]

    assert item["display_name"] == "홍길동"
    assert item["category"] == "sports_participation"
    assert item["broad_category"] == "sports"
    assert item["context_status"] == "resolved_by_observed_context"
    assert item["home_context_status"] == "review_required"
    assert item["home_context_reason"] == "trigger_evidence_incomplete"
    assert item["company_card_status"] == "enrichment_pending"


def test_public_top10_keeps_unresolved_non_issue_with_review_state(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert
    target = tmp_path / "public-quality-gate.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(at.isoformat(), "x", "스네즈나", 1, 100, "observed"),
        HourlyObservation(at.isoformat(), "google_trends", "005930", 2, 99, "observed"),
        HourlyObservation(at.isoformat(), "x", "패션 브랜드", 3, 98, "observed"),
    ], target)

    result = build_intelligence(at, hours=1, path=target)

    assert any(item["topic"] == "스네즈나" for item in result["unified_ranking"])
    unresolved = next(item for item in result["unified_ranking"] if item["topic"] == "스네즈나")
    assert unresolved["home_context_status"] == "review_required"
    assert unresolved["selection_layer"] == "review_queue"
    assert unresolved not in result["trend_top10"]
    assert unresolved["companies"] == []
    generic = next(item for item in result["unified_ranking"] if item["topic"] == "패션 브랜드")
    assert generic["lane"] == "review"
    assert generic["home_context_status"] == "review_required"
    assert generic["home_context_reason"] == "not_main_lane"
    assert generic["company_eligible"] is True
    assert generic["companies"] == []
    assert generic not in result["trend_top10"]
    assert generic["company_card_status"] == "enrichment_pending"
    stock = next(item for item in result["unified_ranking"] if item["topic"] == "005930")
    assert stock["resolved_entity_name"] == "삼성전자"
    assert stock["home_context_status"] == "review_required"
    assert stock["home_context_reason"] == "not_main_lane"
    assert stock not in result["trend_top10"]
    assert stock["company_card_status"] == "not_applicable"
    assert stock["companies"] == []


def test_home_subset_holds_needs_context_term_without_any_disambiguation_evidence(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert

    target = tmp_path / "home-context-evidence.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(at.isoformat(), "google_trends", "애니", 1, 100, "observed"),
        HourlyObservation(at.isoformat(), "google_trends", "말복", 2, 99, "observed"),
    ], target)

    result = build_intelligence(at, hours=1, path=target)
    ambiguous = next(item for item in result["unified_ranking"] if item["topic"] == "애니")

    assert ambiguous["lane"] == "review"
    assert ambiguous["context_status"] == "needs_context"
    assert ambiguous["keywords"] == []
    assert ambiguous["company_candidates"] == []
    assert ambiguous["verification_layer"]["status"] == "not_run"
    assert ambiguous["home_context_status"] == "review_required"
    assert ambiguous["home_context_reason"] == "not_main_lane"
    assert ambiguous["selection_layer"] == "review_queue"
    assert ambiguous not in result["trend_top10"]
    assert result["trend_top10"] == []
    assert result["public_top10"] == result["trend_top10"]
    assert result["home_quality_gate"]["ranking_effect"] == "none"
    assert result["home_quality_gate"]["unified_ranking_preserved"] is True
    assert result["home_quality_gate"]["home_excluded_total"] == 1
    assert result["home_quality_gate"]["context_review_reasons"] == {
        "trigger_evidence_incomplete": 1,
    }


def test_investment_terms_do_not_receive_unrelated_generic_companies(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert
    target = tmp_path / "investment-company-guard.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(at.isoformat(), "google_trends", "관리 종목", 1, 100, "observed"),
        HourlyObservation(at.isoformat(), "google_trends", "삼성전자", 2, 99, "observed"),
    ], target)

    result = build_intelligence(at, hours=1, path=target)
    generic = next(item for item in result["unified_ranking"] if item["resolved_entity_name"] == "관리종목")
    samsung = next(item for item in result["unified_ranking"] if item["resolved_entity_name"] == "삼성전자")

    # Manual reference membership cannot change rank or lane. It may only be
    # consulted by the independent enrichment layer.
    assert generic["company_eligible"] is True
    assert generic["companies"] == []
    assert samsung["lane"] == "review"
    assert samsung["company_eligible"] is True
    assert samsung["company_resolution"]["score_independent_of_company_count"] is True


def test_quality_summary_detects_unchanged_source_snapshots(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert
    target = tmp_path / "snapshot-quality.sqlite3"
    rows = []
    for hour in range(3, 6):
        stamp = datetime(2026, 8, 12, hour, tzinfo=UTC).isoformat()
        rows.append(HourlyObservation(stamp, "x", "불꽃축제", 1, 100, "observed"))
    upsert(rows, target)

    result = build_intelligence(datetime(2026, 8, 12, 5, tzinfo=UTC), hours=3, path=target)
    quality = result["quality_summary"]["source_snapshot_quality"]["x"]

    assert quality["snapshot_count"] == 3
    assert quality["unchanged_rate"] == 1.0
    assert quality["status"] == "stale_or_static_feed"


def test_quality_summary_flags_low_churn_top10_even_when_lower_ranks_change(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert
    target = tmp_path / "low-churn.sqlite3"
    rows = []
    for hour in range(3, 6):
        stamp = datetime(2026, 8, 12, hour, tzinfo=UTC).isoformat()
        for rank in range(1, 11):
            rows.append(HourlyObservation(stamp, "x", f"고정{rank}", rank, 101-rank, "observed"))
        rows.append(HourlyObservation(stamp, "x", f"변경{hour}", 11, 80, "observed"))
    upsert(rows, target)

    result = build_intelligence(datetime(2026, 8, 12, 5, tzinfo=UTC), hours=3, path=target)
    quality = result["quality_summary"]["source_snapshot_quality"]["x"]

    assert quality["average_top10_overlap"] == 1.0
    assert quality["status"] == "low_churn_needs_source_review"


def test_source_value_never_changes_score_or_rank(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert

    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    first = tmp_path / "value-a.sqlite3"
    second = tmp_path / "value-b.sqlite3"
    upsert([
        HourlyObservation(at.isoformat(), "x", "주제 A", 1, 1, "observed"),
        HourlyObservation(at.isoformat(), "x", "주제 B", 2, 9999, "observed"),
    ], first)
    upsert([
        HourlyObservation(at.isoformat(), "x", "주제 A", 1, 9999, "observed"),
        HourlyObservation(at.isoformat(), "x", "주제 B", 2, 1, "observed"),
    ], second)

    result_a = build_intelligence(at, hours=1, path=first)
    result_b = build_intelligence(at, hours=1, path=second)

    assert [(item["topic"], item["score"]) for item in result_a["unified_ranking"]] == [
        (item["topic"], item["score"]) for item in result_b["unified_ranking"]
    ]
    assert result_a["score_policy"]["source_values_used"] is False


def test_representative_prefers_repeated_observed_term_before_best_rank(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert

    target = tmp_path / "representative.sqlite3"
    first = datetime(2026, 8, 12, 3, tzinfo=UTC)
    second = datetime(2026, 8, 12, 4, tzinfo=UTC)
    upsert([
        HourlyObservation(first.isoformat(), "x", "#JIN_LIGHTS_UP_CHARM_CITY", 10, 1, "observed"),
        HourlyObservation(second.isoformat(), "x", "#JIN_LIGHTS_UP_CHARM_CITY", 10, 1, "observed"),
        HourlyObservation(second.isoformat(), "x", "JIN LIGHTS UP CHARM CITY", 1, 100, "observed"),
    ], target)

    item = build_intelligence(second, hours=2, path=target)["unified_ranking"][0]

    assert item["event_key"] == "jin lights up charm city"
    assert item["topic"] == "#JIN_LIGHTS_UP_CHARM_CITY"
    assert item["representative_evidence"]["observed_hours"] == 2


def test_reviewed_seasonal_alias_does_not_merge_observed_events(tmp_path):
    target = tmp_path / "current-representative.sqlite3"
    first = datetime(2026, 8, 12, 3, tzinfo=UTC)
    current = datetime(2026, 8, 12, 4, tzinfo=UTC)
    upsert([
        HourlyObservation(first.isoformat(), "x", "삼계탕", 1, 100, "observed"),
        HourlyObservation(current.isoformat(), "x", "말복", 2, 99, "observed"),
    ], target)

    items = build_intelligence(current, hours=2, path=target)["unified_ranking"]

    assert {item["event_key"] for item in items} == {"삼계탕", "말복"}
    current_item = next(item for item in items if item["event_key"] == "말복")
    assert current_item["representative_evidence"]["currently_observed"] is True


def test_future_rows_do_not_leak_into_past_ranking(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert

    target = tmp_path / "no-future.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([HourlyObservation(at.isoformat(), "x", "불닭", 2, 1, "observed")], target)
    before = build_intelligence(at, hours=24, path=target)
    upsert([
        HourlyObservation(
            datetime(2026, 8, 12, 4, tzinfo=UTC).isoformat(),
            "x", "불닭", 1, 10000, "observed",
        )
    ], target)
    after = build_intelligence(at, hours=24, path=target)

    assert before["unified_ranking"] == after["unified_ranking"]


def test_low_history_is_explicit_and_does_not_block_ranking(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert

    target = tmp_path / "low-history.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([HourlyObservation(at.isoformat(), "x", "불닭", 1, 100, "observed")], target)

    result = build_intelligence(at, hours=24, path=target)

    assert result["unified_ranking"]
    assert result["unified_ranking"][0]["data_confidence"]["level"] == "very_low"
    assert result["quality_summary"]["eligible_ledger_hours"] == 1
    assert result["ranking_availability"] == {
        "status": "provisional_single_source",
        "label": "단일출처 잠정 순위",
        "is_combined_rank": False,
        "current_sources": ["x"],
        "missing_sources": ["google_trends"],
        "reason": "X와 Google 중 한 출처만 현재 시간에 관측되어 통합 순위로 확정할 수 없음",
    }
    assert result["unified_ranking"][0]["ranking_availability_status"] == "provisional_single_source"


def test_period_persistence_uses_source_eligible_snapshot_denominator(tmp_path):
    target = tmp_path / "maturity.sqlite3"
    start = datetime(2026, 8, 8, 0, tzinfo=UTC)
    rows = [
        HourlyObservation(
            (start + timedelta(hours=offset)).isoformat(),
            "x",
            "불닭",
            1,
            100,
            "observed",
        )
        for offset in range(96)
    ]
    upsert(rows, target)

    halfway = build_intelligence(start + timedelta(hours=47), hours=48, path=target)
    mature = build_intelligence(start + timedelta(hours=95), hours=96, path=target)

    assert halfway["unified_ranking"][0]["persistence"] == 0.5
    assert halfway["quality_summary"]["ranking_maturity_status"] == "provisional"
    assert mature["unified_ranking"][0]["persistence"] == 0.5
    assert mature["quality_summary"]["ranking_maturity_status"] == "mature"


def test_duplicate_rank_source_hour_is_quarantined_not_deleted(tmp_path):
    from trzip.hourly_store import HourlyObservation, snapshot, upsert

    target = tmp_path / "quarantine.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(at.isoformat(), "x", "불닭", 1, 100, "observed"),
        HourlyObservation(at.isoformat(), "x", "말복", 1, 99, "observed"),
    ], target)

    result = build_intelligence(at, hours=1, path=target)

    assert len(snapshot(at, target)) == 2
    assert result["unified_ranking"] == []
    assert result["quality_summary"]["quarantined_source_hour_count"] == 1


def test_hourly_and_daily_derived_rankings_are_exposed(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert

    target = tmp_path / "derived-rankings.sqlite3"
    first = datetime(2026, 8, 12, 3, tzinfo=UTC)
    second = datetime(2026, 8, 12, 4, tzinfo=UTC)
    upsert([
        HourlyObservation(first.isoformat(), "x", "불닭", 2, 1, "observed"),
        HourlyObservation(second.isoformat(), "x", "불닭", 1, 1, "observed"),
    ], target)

    result = build_intelligence(second, hours=2, path=target)

    assert len(result["hourly_rankings"]) == 2
    assert result["daily_aggregates"][0]["hours_present"] == 2
    assert result["daily_aggregates"][0]["best_rank"] == 1


def test_current_position_is_source_normalized_and_cross_bonus_is_explicit(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert

    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    single = tmp_path / "single-source.sqlite3"
    dual = tmp_path / "dual-source.sqlite3"
    upsert([HourlyObservation(at.isoformat(), "x", "불닭", 1, 1, "observed")], single)
    upsert([
        HourlyObservation(at.isoformat(), "x", "불닭", 1, 1, "observed"),
        HourlyObservation(at.isoformat(), "google_trends", "불닭", 1, 9999, "observed"),
    ], dual)

    single_item = build_intelligence(at, hours=1, path=single)["unified_ranking"][0]
    dual_item = build_intelligence(at, hours=1, path=dual)["unified_ranking"][0]

    assert single_item["current_source_position"] == 0.5
    assert dual_item["current_source_position"] == 1.0
    assert single_item["score_components"]["cross_source_points"] == 0
    assert dual_item["score_components"]["cross_source_points"] == 20
    for item in (single_item, dual_item):
        components = item["score_components"]
        visible_sum = round(sum(
            components[key]
            for key in (
                "period_strength_points", "momentum_points", "persistence_points",
                "recency_points", "cross_source_points",
            )
        ), 2)
        assert item["score"] == components["total_points"] == visible_sum
        assert components["formula_version"] == "spread35_velocity25_breadth20_persistence10_recency10_v2"
        assert components["rounding_policy"] == "each_component_2dp_then_sum_2dp"


def test_unified_ranking_preserves_main_issue_and_review_without_score_calibration(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert

    target = tmp_path / "all-candidates.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(at.isoformat(), "x", "국가장학금", 1, 100, "observed"),
        HourlyObservation(at.isoformat(), "x", "스네즈나", 2, 99, "observed"),
        HourlyObservation(at.isoformat(), "x", "말복", 3, 98, "observed"),
    ], target)

    result = build_intelligence(at, hours=1, path=target)

    assert len(result["unified_ranking"]) == 3
    assert {item["selection_layer"] for item in result["unified_ranking"]} == {
        "context_review_queue", "issue_context", "review_queue",
    }
    assert all(item["trend_fit"]["affects_score"] is False for item in result["unified_ranking"])
    assert result["trend_top10"] == []
    assert result["public_top10"] == result["trend_top10"]


def test_balanced_home_selection_prioritises_current_without_food_quota():
    from trzip.intelligence import select_balanced_home_top10

    def row(key, score, rank, category, current=True, lifecycle="sustained"):
        return {
            "event_key": key,
            "score": score,
            "observed_rank": rank,
            "broad_category": category,
            "is_current": current,
            "lifecycle": lifecycle,
            "publication_rank": None,
        }

    rows = [
        row("food-a", 100, 1, "food"),
        row("food-b", 99, 2, "food"),
        row("tech-a", 98, 3, "technology", lifecycle="rising"),
        row("tech-b", 97, 4, "technology"),
        row("tech-c", 96, 5, "technology"),
        row("content-a", 95, 6, "content"),
        row("culture-a", 94, 7, "culture"),
        row("market-a", 93, 8, "market"),
        row("life-a", 92, 9, "lifestyle"),
        row("sport-a", 91, 10, "sports"),
        row("expired-a", 1000, 11, "consumer", False, "expired"),
    ]

    selected = select_balanced_home_top10(rows)

    assert [item["event_key"] for item in selected] == [
        "food-a", "food-b", "tech-a", "tech-b", "content-a", "culture-a",
        "market-a", "life-a", "sport-a", "tech-c",
    ]
    assert sum(item["broad_category"] == "food" for item in selected) == 2
    assert all(item["event_key"] != "expired-a" for item in selected)
    assert [item["publication_rank"] for item in selected] == list(range(1, 11))


def test_balanced_home_selection_never_uses_expired_to_fill_contract():
    from trzip.intelligence import select_balanced_home_top10

    rows = [
        {
            "event_key": f"current-{index}", "score": 100 - index,
            "observed_rank": index, "broad_category": "content",
            "is_current": True, "lifecycle": "sustained",
        }
        for index in range(1, 9)
    ] + [
        {
            "event_key": f"expired-{index}", "score": 200 - index,
            "observed_rank": 100 + index, "broad_category": "culture",
            "is_current": False, "lifecycle": "expired",
        }
        for index in range(1, 4)
    ]

    selected = select_balanced_home_top10(rows)

    assert [item["event_key"] for item in selected[:8]] == [
        f"current-{index}" for index in range(1, 9)
    ]
    assert len(selected) == 8
    assert all(not item["event_key"].startswith("expired-") for item in selected)


def test_home_selection_can_fill_short_gap_with_recent_resolved_context():
    from trzip.intelligence import select_balanced_home_top10

    rows = [
        {
            "event_key": f"current-{index}", "score": 100 - index,
            "observed_rank": index, "broad_category": "content",
            "is_current": True, "candidate_status": "is_current",
            "lifecycle": "sustained", "source_count": 2,
        }
        for index in range(1, 9)
    ] + [
        {
            "event_key": f"recent-{index}", "score": 80 - index,
            "observed_rank": 20 + index, "broad_category": "culture",
            "is_current": False, "candidate_status": "period_observed",
            "lifecycle": "cooling", "hours_since_last_seen": float(index),
            "source_count": 2,
        }
        for index in range(1, 3)
    ]

    selected = select_balanced_home_top10(rows)

    assert len(selected) == 10
    assert [item["home_mix_bucket"] for item in selected[-2:]] == [
        "recent_context", "recent_context",
    ]


def test_naver_becomes_an_equal_home_platform_only_after_coverage_gate():
    from trzip.intelligence import apply_equal_platform_home_scores

    rows = []
    for index in range(1, 11):
        rows.append({
            "event_key": f"trend-{index}",
            "score": 101 - index,
            "observed_rank": index,
            "latest_source_ranks": {"x": index, "google_trends": 11 - index},
            "verification_layer": {
                "providers": {
                    "naver": {
                        "status": "observed",
                        "matched": True,
                        "metrics": {
                            "news_recent_24h_sample_count": index,
                            "blog_recent_24h_sample_count": index,
                            "news_independent_host_count": min(index, 3),
                            "blog_independent_host_count": 1,
                            "search_trend": {
                                "latest_ratio": index * 10,
                                "growth_percent": index * 5,
                            },
                        },
                    }
                }
            },
        })

    apply_equal_platform_home_scores(rows)

    assert all(item["naver_home_rank_status"] == "active_equal_weight" for item in rows)
    assert all(item["home_platform_weights"] == {
        "x": 0.333333, "google_trends": 0.333333, "naver": 0.333333,
    } for item in rows)
    assert sorted(item["home_rank"] for item in rows) == list(range(1, 11))
    assert all(item["canonical_observed_rank_preserved"] is True for item in rows)


def test_youtube_chart_signal_becomes_equal_home_platform_only_after_coverage_gate():
    from trzip.intelligence import apply_equal_platform_home_scores

    rows = [
        {
            "event_key": f"video-trend-{index}",
            "score": 101 - index,
            "observed_rank": index,
            "latest_source_ranks": {"x": index, "google_trends": 11 - index},
            "verification_layer": {"providers": {}},
            "youtube_chart_signal": {
                "status": "matched_exact_observed_expression",
                "youtube_score": index * 10,
            },
        }
        for index in range(1, 11)
    ]

    apply_equal_platform_home_scores(rows)

    assert all(item["youtube_home_rank_status"] == "active_equal_weight" for item in rows)
    assert all(item["home_platform_weights"] == {
        "x": 0.333333, "google_trends": 0.333333, "youtube": 0.333333,
    } for item in rows)
    assert all(item["naver_home_rank_status"] == "shadow_insufficient_coverage" for item in rows)


def test_home_selection_prioritises_verified_positive_slope():
    from trzip.intelligence import select_balanced_home_top10

    rows = []
    for index in range(1, 9):
        rows.append({
            "event_key": f"established-{index}", "score": 100 - index,
            "observed_rank": index, "broad_category": "content",
            "is_current": True, "lifecycle": "sustained",
            "representative_evidence": {"observed_hours": 4},
        })
    for index in range(1, 7):
        rows.append({
            "event_key": f"emerging-{index}", "score": 120 - index,
            "observed_rank": 20 + index, "broad_category": "culture",
            "is_current": True, "lifecycle": "rising", "source_count": 2,
            "momentum_delta": 0.4,
            "ranking_data_readiness": {"momentum_status": "measured"},
            "representative_evidence": {"observed_hours": 2},
        })

    selected = select_balanced_home_top10(rows)

    assert len(selected) == 10
    assert sum(item["home_mix_bucket"] == "emerging" for item in selected) == 6
    assert sum(item["home_mix_bucket"] == "established" for item in selected) == 4
    assert all(
        item["home_mix_bucket"] == "emerging" for item in selected[:6]
    )


def test_weekly_period_retains_recent_history_with_explicit_stale_status(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert

    target = tmp_path / "active-only.sqlite3"
    previous = datetime(2026, 8, 12, 3, tzinfo=UTC)
    current = datetime(2026, 8, 12, 4, tzinfo=UTC)
    upsert([
        HourlyObservation(previous.isoformat(), "x", "오징어 게임", 1, 100, "observed"),
        HourlyObservation(current.isoformat(), "x", "불닭", 1, 100, "observed"),
    ], target)

    result = build_intelligence(current, hours=2, path=target)

    assert [item["topic"] for item in result["unified_ranking"]] == ["불닭", "오징어 게임"]
    stale = result["unified_ranking"][1]
    assert stale["candidate_status"] == "period_observed"
    assert stale["is_current"] is False
    assert stale["hours_since_last_seen"] == 1.0
    historical = {
        item["representative_term"]
        for snapshot in result["hourly_rankings"][:-1]
        for item in snapshot["ranking"]
    }
    assert "오징어 게임" in historical
    assert result["quality_summary"]["ranking_maturity_status"] == "provisional"


def test_malbok_current_expression_reaches_six_reviewed_listed_companies(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert

    target = tmp_path / "malbok-enrichment.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert(
        [HourlyObservation(at.isoformat(), "google_trends", "말복", 1, 100, "observed")],
        target,
    )

    item = build_intelligence(at, hours=1, path=target)["unified_ranking"][0]

    assert item["display_name"] == "말복"
    assert item["company_resolution"]["publish_status"] == "published"
    assert {company["stock_code"] for company in item["companies"]} == {
        "001680",
        "003680",
        "027740",
        "031440",
        "136480",
        "139480",
    }
    assert all(company["ontology_complete"] for company in item["companies"])
    assert all(
        edge["evidence_urls"]
        for company in item["companies"]
        for edge in company["ontology_path"]
    )


def test_iam_solo_publishes_three_direct_and_two_value_chain_companies(tmp_path):
    target = tmp_path / "iam-solo-enrichment.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert(
        [HourlyObservation(at.isoformat(), "google_trends", "나솔", 1, 100, "observed")],
        target,
    )

    item = build_intelligence(at, hours=1, path=target)["unified_ranking"][0]
    companies = {company["stock_code"]: company for company in item["companies"]}

    assert item["display_name"] == "나솔"
    assert {keyword["text"] for keyword in item["keywords"]} == {
        "나는 SOLO", "나는 솔로", "SBS Plus", "ENA", "TVING",
    }
    assert all(keyword["affects_score"] is False for keyword in item["keywords"])
    assert any(
        keyword["status"] == "approved_ontology_term"
        and keyword["source"] == ["reviewed_ontology"]
        and keyword["evidence_urls"]
        for keyword in item["keywords"]
    )
    assert sum(
        keyword["status"] == "approved_ontology_related_term"
        for keyword in item["keywords"]
    ) == 3
    assert item["company_resolution"]["publish_status"] == "published"
    assert set(companies) == {"030200", "034120", "035760", "053210", "402340"}
    assert {
        stock_code for stock_code, company in companies.items()
        if company["relation_tier"] == "direct"
    } == {"034120", "035760", "053210"}
    assert {
        stock_code for stock_code, company in companies.items()
        if company["relation_tier"] == "value_chain"
    } == {"030200", "402340"}
    assert all(
        company["relation_display_type"] == "직접 관계"
        for company in companies.values()
        if company["relation_tier"] == "direct"
    )
    assert all(
        company["relation_display_type"] == "가치사슬"
        for company in companies.values()
        if company["relation_tier"] == "value_chain"
    )
    assert item["company_resolution"]["direct_count"] == 3
    assert item["company_resolution"]["tier_counts"] == {
        "direct": 3,
        "value_chain": 2,
        "industry_watch": 0,
    }
    assert all(
        "/dst/irReference/" not in source["url"]
        for company in companies.values()
        for source in company["evidence_sources"]
    )
    assert all(
        source["review_status"] == "approved"
        for company in companies.values()
        for source in company["evidence_sources"]
    )
    assert all(
        edge["review_status"] in {"observed", "approved"}
        for company in companies.values()
        for edge in company["ontology_path"]
    )
    assert all(company["relation_type"] != "listed_as" for company in companies.values())


def test_registered_gstar_enrichment_does_not_promote_an_unclassified_observation(tmp_path):
    target = tmp_path / "gstar-enrichment.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert(
        [HourlyObservation(at.isoformat(), "google_trends", "지스타", 1, 100, "observed")],
        target,
    )

    item = build_intelligence(at, hours=1, path=target)["unified_ranking"][0]

    assert {keyword["text"] for keyword in item["keywords"]} == {
        "G-STAR", "G-CON", "팰월드 모바일", "산나비 외전", "오디세이 모니터",
    }
    assert all(keyword["affects_score"] is False for keyword in item["keywords"])
    assert item["lane"] == "review"
    assert item["company_eligible"] is True
    assert item["company_resolution"]["score_independent_of_company_count"] is True
    assert item["company_resolution"]["publish_status"] in {
        "published", "ontology_incomplete",
    }


def test_tving_exposes_five_reviewed_related_keywords_and_five_companies(tmp_path):
    target = tmp_path / "tving-enrichment.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert(
        [HourlyObservation(at.isoformat(), "google_trends", "티빙", 1, 100, "observed")],
        target,
    )

    item = build_intelligence(at, hours=1, path=target)["unified_ranking"][0]

    assert item["lane"] == "review"
    assert [keyword["text"] for keyword in item["keywords"]] == [
        "TVING",
        "KT 시즌",
        "NAVER",
        "삼성 AI TV",
        "웨이브",
    ]
    assert item["keyword_evidence"]["total"] == 5
    assert item["keyword_evidence"]["reviewed_ontology_count"] == 5
    assert all(keyword["affects_score"] is False for keyword in item["keywords"])
    assert all(keyword["evidence_urls"] for keyword in item["keywords"])
    assert {company["stock_code"] for company in item["companies"]} == {
        "005930", "030200", "035420", "035760", "402340",
    }
    assert item["company_resolution"]["tier_counts"] == {
        "direct": 1,
        "value_chain": 4,
        "industry_watch": 0,
    }


def test_humanoid_robot_exposes_five_keywords_and_three_core_two_industry_observations(
    tmp_path,
):
    target = tmp_path / "humanoid-enrichment.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert(
        [
            HourlyObservation(
                at.isoformat(),
                "google_trends",
                "휴머노이드 로봇",
                1,
                100,
                "observed",
            )
        ],
        target,
    )

    item = build_intelligence(at, hours=1, path=target)["unified_ranking"][0]
    companies = {company["stock_code"]: company for company in item["companies"]}

    assert len(item["keywords"]) == 5
    assert {keyword["text"] for keyword in item["keywords"]} <= {
        "휴머노이드",
        "아틀라스",
        "미래로봇",
        "실용적 휴머노이드",
        "LG 클로이드",
        "AMBIDEX",
    }
    assert all(keyword["affects_score"] is False for keyword in item["keywords"])
    assert set(companies) == {"005380", "005930", "035420", "066570", "454910"}
    assert {
        ticker for ticker, company in companies.items() if company["relation_tier"] == "direct"
    } == {"005380", "005930", "454910"}
    assert {
        ticker
        for ticker, company in companies.items()
        if company["relation_tier"] == "industry_watch"
    } == {"035420", "066570"}
    assert all(
        company["relation_display_type"] == "산업 관찰"
        for company in companies.values()
        if company["relation_tier"] == "industry_watch"
    )
    assert item["company_resolution"]["tier_counts"] == {
        "direct": 3,
        "value_chain": 0,
        "industry_watch": 2,
    }


def test_stock_code_reference_data_does_not_promote_or_company_enrich_it(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert

    target = tmp_path / "stock-code-enrichment.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert(
        [HourlyObservation(at.isoformat(), "google_trends", "005930", 1, 100, "observed")],
        target,
    )

    result = build_intelligence(at, hours=1, path=target)
    item = result["unified_ranking"][0]

    assert item["display_name"] == "삼성전자"
    assert item["observed_representative_term"] == "005930"
    assert item["display_name_policy"] == "reviewed_stock_code_to_company_name"
    assert {keyword["text"] for keyword in item["keywords"]} == {
        "삼성전자",
        "삼성전자주식회사",
        "메모리",
        "시스템LSI",
        "파운드리",
    }
    assert all(keyword["affects_score"] is False for keyword in item["keywords"])
    assert item["lane"] == "review"
    assert item["company_candidates"] == []
    assert item["companies"] == []
    assert item["company_resolution"]["publish_status"] == "excluded_by_context"
    assert item["company_resolution"]["published_count"] == 0
    assert not any(
        queue["representative"] == "005930"
        for queue in result["ontology_enrichment_queue"]
    )


def test_frontend_enrichment_queue_reports_ten_company_target(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert

    target = tmp_path / "frontend-enrichment-target.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert(
        [HourlyObservation(at.isoformat(), "google_trends", "개기일식", 1, 100, "observed")],
        target,
    )

    result = build_intelligence(at, hours=1, path=target)
    queue = result["ontology_enrichment_queue"][0]

    assert queue["minimum_required"] == 10
    assert queue["missing_company_paths"] == max(
        0, 10 - queue["evidence_backed_company_count"]
    )


def test_hanbok_shop_company_roles_follow_reviewed_ontology_edges(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert

    target = tmp_path / "hanbok-company-roles.sqlite3"
    at = datetime(2026, 8, 14, 0, tzinfo=UTC)
    upsert(
        [HourlyObservation(at.isoformat(), "google_trends", "한복상점", 1, 100, "observed")],
        target,
    )

    item = build_intelligence(at, hours=1, path=target)["unified_ranking"][0]
    roles = {
        company["stock_code"]: company["company_role_category"]
        for company in item["companies"]
    }

    assert roles == {
        "020000": "retail_sales",
        "105630": "manufacturing_development",
        "111770": "manufacturing_development",
        "120110": "brand_marketing",
        "298020": "raw_materials_components",
        "383220": "brand_marketing",
    }


def test_listed_securities_company_has_self_and_four_reviewed_sector_peers(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert

    target = tmp_path / "listed-company-name-enrichment.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert(
        [HourlyObservation(at.isoformat(), "google_trends", "삼성증권", 1, 100, "observed")],
        target,
    )

    result = build_intelligence(at, hours=1, path=target)
    item = result["unified_ranking"][0]

    assert item["display_name"] == "삼성증권"
    assert {company["stock_code"] for company in item["company_candidates"]} == {
        "003540", "005940", "006800", "016360", "039490"
    }
    assert item["companies"] == item["company_candidates"]
    assert item["company_resolution"]["publish_status"] == "published"
    assert item["company_resolution"]["published_count"] == 5
    assert [keyword["text"] for keyword in item["keywords"]] == [
        "금융상품",
        "펀드",
        "주식",
        "트레이딩",
        "자산관리",
    ]
    assert all(
        keyword["status"] == "approved_ontology_related_term"
        and keyword["affects_score"] is False
        and keyword["evidence_urls"]
        for keyword in item["keywords"]
    )
    assert next(
        company for company in item["companies"] if company["stock_code"] == "016360"
    )["relation_tier"] == "direct"
    assert {
        company["relation_tier"]
        for company in item["companies"]
        if company["stock_code"] != "016360"
    } == {"industry_watch"}


def test_unresearched_person_expression_stays_zero_candidate_and_review_only(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert

    target = tmp_path / "person-no-filler.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert(
        [HourlyObservation(at.isoformat(), "google_trends", "지드래곤", 1, 100, "observed")],
        target,
    )

    result = build_intelligence(at, hours=1, path=target)
    item = result["unified_ranking"][0]

    assert item["display_name"] == "지드래곤"
    assert item["company_candidates"] == []
    assert item["companies"] == []
    assert item["lane"] == "review"
    assert result["ontology_enrichment_queue"] == []


def test_intelligence_exposes_daily_weekly_monthly_period_aggregate_views(tmp_path):
    target = tmp_path / "period-ranking-views.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    rows = []
    for age in range(30):
        stamp = (at - timedelta(hours=age)).isoformat()
        rows.extend([
            HourlyObservation(stamp, "x", "말복", 1, 100, "observed"),
            HourlyObservation(stamp, "google_trends", "말복", 1, 100, "observed"),
        ])
    upsert(rows, target)

    result = build_intelligence(at, hours=1, path=target)

    assert result["ranking_default_period"] == "daily"
    assert [period["key"] for period in result["ranking_periods"]] == [
        "daily", "weekly", "monthly",
    ]
    assert [period["window"]["hours"] for period in result["ranking_periods"]] == [
        24, 168, 720,
    ]
    assert set(result["ranking_views"]) == {"daily", "weekly", "monthly"}
    for key, view in result["ranking_views"].items():
        assert view["key"] == key
        assert view["company_count_affects_rank"] is False
        assert view["company_detail_policy"] == "shared_by_detail_event_key"
        assert view["unified_ranking"][0]["detail_event_key"] == "말복"
        assert "companies" not in view["unified_ranking"][0]
        assert view["period_top10"] == []
    daily = result["ranking_views"]["daily"]
    assert [item["event_key"] for item in daily["unified_ranking"]] == [
        item["event_key"] for item in result["unified_ranking"]
    ]
    assert [item["score"] for item in daily["unified_ranking"]] == [
        item["score"] for item in result["unified_ranking"]
    ]
    assert result["ranking_views"]["daily"]["data_readiness"]["status"] == "ready"
    assert result["ranking_views"]["monthly"]["data_readiness"]["status"] == "provisional"


def test_monthly_only_event_is_period_summary_without_entering_weekly_alias(tmp_path):
    target = tmp_path / "monthly-only-period.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(at.isoformat(), "x", "말복", 1, 100, "observed"),
        HourlyObservation(
            (at - timedelta(days=20)).isoformat(),
            "x",
            "오징어 게임",
            1,
            100,
            "observed",
        ),
    ], target)

    result = build_intelligence(at, hours=1, path=target)

    assert [item["event_key"] for item in result["unified_ranking"]] == ["말복"]
    monthly = result["ranking_views"]["monthly"]["unified_ranking"]
    monthly_old = next(item for item in monthly if item["event_key"] == "오징어 게임")
    assert monthly_old["candidate_status"] == "period_observed"
    assert monthly_old["detail_status"] == "period_summary_only"
    assert monthly_old["company_card_status"] == "enrichment_pending"
    assert monthly_old["last_seen_at"] == (at - timedelta(days=20)).isoformat()
    assert monthly_old["freshness"]["half_life_hours"] == 360.0
    assert all(
        item["event_key"] != "오징어 게임"
        for item in result["ranking_views"]["weekly"]["unified_ranking"]
    )
