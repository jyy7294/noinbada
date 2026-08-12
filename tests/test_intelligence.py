from datetime import UTC, datetime

from trzip.company_adapters import integration_status, opendart_company, pykrx_stock
from trzip.hourly_store import HourlyObservation, upsert
from trzip.intelligence import build_intelligence, canonical_topic


def test_aliases_are_normalized_to_events():
    assert canonical_topic("두쫀쿠") == "두쫀쿠"
    assert canonical_topic("말복") == "말복"
    assert canonical_topic("#JIN_IN_BALTIMORE_D2") == "BTS 진 볼티모어 공연"
    assert canonical_topic("볼티모어") == "볼티모어"


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
    assert generic["home_context_status"] == "resolved"
    assert generic["company_eligible"] is True
    assert generic["companies"] == []
    assert any(item["topic"] == "005930" for item in result["public_top10"])
    stock = next(item for item in result["public_top10"] if item["topic"] == "005930")
    assert stock["resolved_entity_name"] == "삼성전자"


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

    assert generic["company_eligible"] is False
    assert generic["companies"] == []
    assert samsung["companies"] == []
    assert samsung["company_candidates"] == []
    assert samsung["candidate_company_categories"] == []


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


def test_unified_ranking_preserves_main_issue_and_review_without_score_calibration(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert

    target = tmp_path / "all-candidates.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(at.isoformat(), "x", "국가장학금", 1, 100, "observed"),
        HourlyObservation(at.isoformat(), "x", "스네즈나", 2, 99, "observed"),
        HourlyObservation(at.isoformat(), "x", "불닭", 3, 98, "observed"),
    ], target)

    result = build_intelligence(at, hours=1, path=target)

    assert len(result["unified_ranking"]) == 3
    assert {item["selection_layer"] for item in result["unified_ranking"]} == {
        "main_subset", "issue_context", "review_queue",
    }
    assert all(item["trend_fit"]["affects_score"] is False for item in result["unified_ranking"])
    assert [item["topic"] for item in result["public_top10"]] == ["불닭"]


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
