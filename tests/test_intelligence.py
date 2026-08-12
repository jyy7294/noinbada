from datetime import UTC, datetime, timedelta

from trzip.company_adapters import integration_status, opendart_company, pykrx_stock
from trzip.hourly_store import HourlyObservation, upsert
from trzip.intelligence import (
    _path_relation_tier,
    _provider_issue_context_titles,
    build_intelligence,
    canonical_topic,
)


def test_aliases_are_normalized_to_events():
    assert canonical_topic("두쫀쿠") == "두쫀쿠"
    assert canonical_topic("말복") == "말복"
    assert canonical_topic("#JIN_IN_BALTIMORE_D2") == "BTS 진 볼티모어 공연"
    assert canonical_topic("볼티모어") == "볼티모어"
    assert canonical_topic("cpi 발표") == "cpi"


def test_listing_edge_alone_never_promotes_a_company_to_direct_relation():
    assert _path_relation_tier([{"relation_type": "listed_as"}]) == "adjacent"
    assert _path_relation_tier([
        {
            "relation_type": "parent_company_exposure_via_broadcaster",
            "metadata": {"relation_tier": "value_chain"},
        },
        {"relation_type": "listed_as"},
    ]) == "value_chain"


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
    assert event["rrf"] == 1.0


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
    assert result["ontology_enrichment_queue"] == []


def test_three_evidence_backed_companies_remain_candidates_but_gold_is_hidden(tmp_path):
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
    assert trend["companies"] == []
    assert trend["company_resolution"]["publish_status"] == "ontology_incomplete"
    queued = result["ontology_enrichment_queue"][0]
    assert queued["representative_term"] == "두바이 쫀득쿠키"
    assert queued["evidence_backed_company_count"] == 3
    assert queued["missing_company_paths"] == 2
    assert queued["padding_forbidden"] is True
    assert queued["affects_score"] is False


def test_person_name_is_ranked_and_can_expose_verified_business_relation(tmp_path):
    from trzip.hourly_store import HourlyObservation
    target = tmp_path / "person-issue.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([HourlyObservation(at.isoformat(), "google_trends", "지드래곤", 1, 100, "observed")], target)
    result = build_intelligence(at, hours=1, path=target)
    person = next(item for item in result["unified_ranking"] if item["topic"] == "지드래곤")
    assert person["classification"] == "일반 트렌드"
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


def test_weak_main_filter_covers_typed_market_content_sports_and_technology(tmp_path):
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
    assert by_topic["티빙"]["broad_category"] == "content"
    assert by_topic["롯데 자이언츠"]["broad_category"] == "sports"
    assert by_topic["휴머노이드 로봇"]["broad_category"] == "technology"
    assert all(by_topic[topic]["lane"] == "main" for topic in (
        "삼성증권", "티빙", "롯데 자이언츠", "휴머노이드 로봇",
    ))
    assert by_topic["음식"]["lane"] == "review"


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


def test_representative_and_related_terms_use_observed_source_expressions_only(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert
    target = tmp_path / "keyword-evidence.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(at.isoformat(), "x", "#JIN_IN_BALTIMORE_D2", 4, 96, "observed"),
        HourlyObservation(at.isoformat(), "x", "JIN LIGHTS UP CHARM CITY", 9, 91, "observed"),
    ], target)
    result = build_intelligence(at, hours=1, path=target)
    event = next(
        item for item in result["lanes"]["main"]
        if item["event_key"] == "BTS 진 볼티모어 공연"
    )
    assert event["topic"] == "#JIN_IN_BALTIMORE_D2"
    assert event["display_name"] == "#JIN_IN_BALTIMORE_D2"
    assert event["resolved_entity_name"] == "BTS 진 볼티모어 공연"
    observed = [item for item in event["keywords"] if item["status"] == "observed_ranked_term"]
    assert {item["text"] for item in observed} == {"JIN LIGHTS UP CHARM CITY"}
    assert all(item["source"] == ["x"] for item in observed)
    assert all(item["role_status"] == "deterministic_draft" for item in observed)
    assert all(item["affects_score"] is False for item in observed)
    assert event["company_resolution"]["status"] == "ontology_incomplete"
    assert event["company_candidates"] == []
    assert event["latest_source_ranks"]["x"] == 4
    assert event["rank_change_by_source"]["x"] is None


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
    assert item["home_context_reason"] == "company_ontology_incomplete"


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
    assert unresolved not in result["public_top10"]
    assert unresolved["companies"] == []
    generic = next(item for item in result["unified_ranking"] if item["topic"] == "패션 브랜드")
    assert generic["home_context_status"] == "review_required"
    assert generic["home_context_reason"] == "context_evidence_missing"
    assert generic["company_eligible"] is True
    assert generic["companies"] == []
    assert generic not in result["public_top10"]
    stock = next(item for item in result["unified_ranking"] if item["topic"] == "005930")
    assert stock["resolved_entity_name"] == "삼성전자"
    assert stock["home_context_status"] == "resolved"
    assert stock["home_context_reason"] == "context_resolved"
    assert stock in result["public_top10"]
    assert {company["stock_code"] for company in stock["companies"]} == {
        "000660",
        "005930",
        "006400",
        "009150",
        "066570",
    }
    assert next(
        company for company in stock["companies"] if company["stock_code"] == "005930"
    )["relation_tier"] == "core"
    assert {
        company["relation_tier"]
        for company in stock["companies"]
        if company["stock_code"] != "005930"
    } == {"adjacent"}


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

    assert ambiguous["lane"] == "main"
    assert ambiguous["context_status"] == "needs_context"
    assert ambiguous["keywords"] == []
    assert ambiguous["company_candidates"] == []
    assert ambiguous["verification_layer"]["status"] == "not_run"
    assert ambiguous["home_context_status"] == "review_required"
    assert ambiguous["home_context_reason"] == "context_evidence_missing"
    assert ambiguous["selection_layer"] == "context_review_queue"
    assert ambiguous not in result["public_top10"]
    assert [item["topic"] for item in result["public_top10"]] == ["말복"]
    assert result["home_quality_gate"]["ranking_effect"] == "none"
    assert result["home_quality_gate"]["unified_ranking_preserved"] is True
    assert result["home_quality_gate"]["home_excluded_total"] == 1
    assert result["home_quality_gate"]["exclusion_reasons"] == {
        "context_evidence_missing": 1
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

    # A generic market term receives no companies.  A reviewed company term
    # may expose its own stock plus clearly-labelled industry observations.
    assert generic["company_eligible"] is True
    assert generic["companies"] == []
    assert {company["stock_code"] for company in samsung["companies"]} == {
        "000660", "005930", "006400", "009150", "066570"
    }
    assert samsung["company_resolution"]["publish_status"] == "published"
    assert samsung["company_resolution"]["published_count"] == 5


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
        HourlyObservation(first.isoformat(), "x", "#JIN_IN_BALTIMORE_D2", 10, 1, "observed"),
        HourlyObservation(second.isoformat(), "x", "#JIN_IN_BALTIMORE_D2", 10, 1, "observed"),
        HourlyObservation(second.isoformat(), "x", "JIN LIGHTS UP CHARM CITY", 1, 100, "observed"),
    ], target)

    item = build_intelligence(second, hours=2, path=target)["unified_ranking"][0]

    assert item["event_key"] == "BTS 진 볼티모어 공연"
    assert item["topic"] == "#JIN_IN_BALTIMORE_D2"
    assert item["representative_evidence"]["observed_hours"] == 2


def test_current_observed_expression_beats_expired_historical_alias(tmp_path):
    target = tmp_path / "current-representative.sqlite3"
    first = datetime(2026, 8, 12, 3, tzinfo=UTC)
    current = datetime(2026, 8, 12, 4, tzinfo=UTC)
    upsert([
        HourlyObservation(first.isoformat(), "x", "삼계탕", 1, 100, "observed"),
        HourlyObservation(current.isoformat(), "x", "말복", 2, 99, "observed"),
    ], target)

    item = build_intelligence(current, hours=2, path=target)["unified_ranking"][0]

    assert item["event_key"] == "말복"
    assert item["topic"] == "말복"
    assert item["representative_evidence"]["currently_observed"] is True


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


def test_persistence_matures_linearly_until_96_eligible_hours(tmp_path):
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
    assert mature["unified_ranking"][0]["persistence"] == 1.0
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


def test_rrf_is_normalized_for_available_sources_and_cross_bonus_is_explicit(tmp_path):
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

    assert single_item["rrf"] == dual_item["rrf"] == 1.0
    assert single_item["score_components"]["cross_source_points"] == 0
    assert dual_item["score_components"]["cross_source_points"] == 5
    for item in (single_item, dual_item):
        components = item["score_components"]
        visible_sum = round(sum(
            components[key]
            for key in (
                "rrf_points", "momentum_points", "persistence_points",
                "cross_source_points",
            )
        ) * components["calibration"], 2)
        assert item["score"] == components["total_points"] == visible_sum
        assert components["formula_version"] == "rrf60_momentum20_persistence15_cross5_v1"
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
        "main_subset", "issue_context", "review_queue",
    }
    assert all(item["trend_fit"]["affects_score"] is False for item in result["unified_ranking"])
    assert [item["topic"] for item in result["public_top10"]] == ["말복"]


def test_window_only_history_cannot_reenter_current_ranking(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert

    target = tmp_path / "active-only.sqlite3"
    previous = datetime(2026, 8, 12, 3, tzinfo=UTC)
    current = datetime(2026, 8, 12, 4, tzinfo=UTC)
    upsert([
        HourlyObservation(previous.isoformat(), "x", "오징어 게임", 1, 100, "observed"),
        HourlyObservation(current.isoformat(), "x", "불닭", 1, 100, "observed"),
    ], target)

    result = build_intelligence(current, hours=2, path=target)

    assert [item["topic"] for item in result["unified_ranking"]] == ["불닭"]
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
        if company["relation_tier"] == "core"
    } == {"034120", "035760", "053210"}
    assert {
        stock_code for stock_code, company in companies.items()
        if company["relation_tier"] == "value_chain"
    } == {"030200", "402340"}
    assert all(
        company["relation_display_type"] == "직접 관계"
        for company in companies.values()
        if company["relation_tier"] == "core"
    )
    assert all(
        company["relation_display_type"] == "가치사슬"
        for company in companies.values()
        if company["relation_tier"] == "value_chain"
    )
    assert item["company_resolution"]["direct_count"] == 3
    assert item["company_resolution"]["tier_counts"] == {
        "core": 3,
        "value_chain": 2,
        "adjacent": 0,
        "excluded": 0,
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


def test_gstar_exposes_five_reviewed_keywords_and_five_companies(tmp_path):
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
    assert {company["stock_code"] for company in item["companies"]} == {
        "005930", "036570", "095660", "251270", "259960",
    }
    assert item["company_resolution"]["publish_status"] == "published"
    assert item["company_resolution"]["direct_count"] == 4
    assert item["company_resolution"]["tier_counts"] == {
        "core": 4,
        "value_chain": 1,
        "adjacent": 0,
        "excluded": 0,
    }
    assert all(
        source["review_status"] == "approved" and source["url"].startswith("https://")
        for company in item["companies"]
        for source in company["evidence_sources"]
    )


def test_tving_exposes_five_reviewed_related_keywords_and_five_companies(tmp_path):
    target = tmp_path / "tving-enrichment.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert(
        [HourlyObservation(at.isoformat(), "google_trends", "티빙", 1, 100, "observed")],
        target,
    )

    item = build_intelligence(at, hours=1, path=target)["unified_ranking"][0]

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
        "core": 1,
        "value_chain": 4,
        "adjacent": 0,
        "excluded": 0,
    }


def test_stock_code_has_reviewed_company_and_four_labelled_industry_peers(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert

    target = tmp_path / "stock-code-enrichment.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert(
        [HourlyObservation(at.isoformat(), "google_trends", "005930", 1, 100, "observed")],
        target,
    )

    result = build_intelligence(at, hours=1, path=target)
    item = result["unified_ranking"][0]

    assert item["display_name"] == "005930"
    assert {keyword["text"] for keyword in item["keywords"]} == {
        "삼성전자",
        "삼성전자주식회사",
        "메모리",
        "시스템LSI",
        "파운드리",
    }
    assert all(keyword["affects_score"] is False for keyword in item["keywords"])
    assert {company["stock_code"] for company in item["company_candidates"]} == {
        "000660", "005930", "006400", "009150", "066570"
    }
    assert item["companies"] == item["company_candidates"]
    assert item["company_resolution"]["publish_status"] == "published"
    assert item["company_resolution"]["published_count"] == 5
    assert not any(
        queue["representative"] == "005930"
        for queue in result["ontology_enrichment_queue"]
    )


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
    )["relation_tier"] == "core"
    assert {
        company["relation_tier"]
        for company in item["companies"]
        if company["stock_code"] != "016360"
    } == {"adjacent"}


def test_unresearched_person_expression_stays_zero_candidate_and_enters_queue(tmp_path):
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
    queue = result["ontology_enrichment_queue"][0]
    assert queue["lookup_status"] == "no_reviewed_ontology_match"
    assert queue["research_stages"][-1] == "team_review"
