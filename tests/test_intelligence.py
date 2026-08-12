from datetime import UTC, datetime

from trzip.company_adapters import integration_status, opendart_company, pykrx_stock
from trzip.hourly_store import backfill, generated_hour, upsert
from trzip.intelligence import COMPANY_REGISTRY, build_intelligence, canonical_topic
from trzip.curation import lane_for_raw_term, observed_lane


def test_aliases_are_normalized_to_events():
    assert canonical_topic("두쫀쿠") == "두바이 초콜릿"
    assert canonical_topic("말복") == "말복"
    assert canonical_topic("#JIN_IN_BALTIMORE_D2") == "진"


def test_baseball_company_map_covers_multiple_spending_touchpoints():
    companies = COMPANY_REGISTRY["야구 직관"]
    roles = {company["relation_type"] for company in companies}

    assert {"venue_operator", "merchandise_apparel", "venue_food_retail"} <= roles
    assert any(company["strength"] == "direct" for company in companies)
    assert any(company["strength"] == "sector_watch" for company in companies)


def test_every_public_trend_has_three_business_categories(tmp_path):
    target = tmp_path / "three-categories.sqlite3"
    at = datetime(2026, 7, 15, 0, tzinfo=UTC)
    upsert(generated_hour(at), target)
    result = build_intelligence(at, hours=1, path=target)

    for trend in result["public_top10"]:
        assert len(trend["company_categories"]) >= 3
        assert all(category["candidate_count"] >= 1 for category in trend["company_categories"])
        assert trend["company_resolution"]["minimum_category_met"] is True


def test_main_scope_covers_broad_consumption_life_and_culture():
    for term in ("롤 패치 노트", "유리동물원", "코난 극장판"):
        assert lane_for_raw_term(term)[0] == "main"
    for term in ("국가장학금", "거제경찰서"):
        assert lane_for_raw_term(term)[0] == "issue"
    for term in ("지드래곤", "nct 시온"):
        assert lane_for_raw_term(term)[0] == "main"


def test_generic_terms_require_persistence_or_cross_source():
    for term in ("쿠우쿠우", "테니스", "블루레이"):
        assert observed_lane(term, observed_hours=1, source_count=1)[0] == "main"
        assert observed_lane(term, observed_hours=2, source_count=1)[0] == "main"
        assert observed_lane(term, observed_hours=1, source_count=2)[0] == "main"


def test_person_name_is_ranked_and_can_expose_verified_business_relation(tmp_path):
    from trzip.hourly_store import HourlyObservation
    target = tmp_path / "person-issue.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([HourlyObservation(at.isoformat(), "google_trends", "지드래곤", 1, 100, "observed")], target)
    result = build_intelligence(at, hours=1, path=target)
    person = next(item for item in result["unified_ranking"] if item["topic"] == "지드래곤")
    assert person["classification"] == "일반 트렌드"
    assert person["companies"]
    assert person["company_resolution"]["status"] == "mapped"


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
    at = datetime(2026, 7, 15, 0, tzinfo=UTC)
    backfill(at, target)
    result = build_intelligence(at, hours=24, path=target)
    assert result["mode"] == "reconstructed_demo"
    assert result["is_live"] is False
    assert result["lanes"]["main"]
    buldak = next(row for row in result["lanes"]["main"] if row["topic"] == "불닭")
    assert buldak["series"]
    assert buldak["companies"][0]["stock_code"] == "003230"
    assert buldak["companies"][0]["strength"] == "direct"
    assert buldak["companies"][0]["company_role"] == "제조"
    assert buldak["companies"][0]["relation_tier"] == "core"
    assert buldak["companies"][0]["opportunity_status"] == "confirmed_relationship"


def test_integrations_fail_closed_without_credentials(monkeypatch):
    monkeypatch.setenv("TRZIP_DISABLE_USER_SECRET_BRIDGE", "1")
    for name in ("OPENDART_API_KEY",):
        monkeypatch.delenv(name, raising=False)
    status = integration_status()
    assert status["opendart"]["configured"] is False
    assert status["pykrx"]["configured"] is True
    assert opendart_company("삼양식품")["status"] == "unavailable"
    assert pykrx_stock("bad-code")["status"] == "invalid"


def test_intelligence_exposes_lifecycle_and_rank_movement(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert
    target = tmp_path / "movement.sqlite3"
    rows = []
    for hour, rank in ((0, 8), (1, 3)):
        at = datetime(2026, 7, 15, hour, tzinfo=UTC).isoformat()
        rows.append(HourlyObservation(at, "x", "불닭", rank, 101-rank, "generated"))
    upsert(rows, target)
    result = build_intelligence(datetime(2026, 7, 15, 1, tzinfo=UTC), hours=2, path=target)
    buldak = next(item for item in result["lanes"]["main"] if item["topic"] == "불닭")
    assert buldak["rank_change_by_source"]["x"] == 5
    assert buldak["lifecycle"] in {"new", "rising"}
    assert buldak["first_seen_at"].endswith("+00:00")


def test_live_intelligence_never_mixes_generated_rows(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert
    target = tmp_path / "live.sqlite3"
    cutoff = datetime(2026, 8, 12, 2, tzinfo=UTC)
    upsert([HourlyObservation(cutoff.isoformat(), "x", "불닭", 1, 100, "generated"),
            HourlyObservation(datetime(2026, 8, 12, 3, tzinfo=UTC).isoformat(), "google_trends", "말복", 1, 100, "observed")], target)
    result = build_intelligence(datetime(2026, 8, 12, 3, tzinfo=UTC), hours=24, path=target)
    assert result["mode"] == "live"
    assert all(item["provenance"] == ["observed"] for lane in result["lanes"].values() for item in lane)
    assert all(item["topic"] != "불닭" for lane in result["lanes"].values() for item in lane)


def test_observed_related_expression_is_distinguished_from_operator_candidate(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert
    target = tmp_path / "keyword-evidence.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(at.isoformat(), "x", "#JIN_IN_BALTIMORE_D2", 4, 96, "observed"),
        HourlyObservation(at.isoformat(), "x", "JIN LIGHTS UP CHARM CITY", 9, 91, "observed"),
    ], target)
    result = build_intelligence(at, hours=1, path=target)
    event = next(item for item in result["lanes"]["main"] if item["topic"] == "진")
    observed = [item for item in event["keywords"] if item["status"] == "observed_source_expression"]
    assert {item["text"] for item in observed} == {"#JIN_IN_BALTIMORE_D2", "JIN LIGHTS UP CHARM CITY"}
    assert all(item["source"] == ["x"] for item in observed)
    assert event["company_resolution"]["status"] == "mapped"
    assert event["latest_source_ranks"]["x"] == 4
    assert event["rank_change_by_source"]["x"] is None


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
    unresolved = next(item for item in result["public_top10"] if item["topic"] == "스네즈나")
    assert unresolved["home_context_status"] == "review_required"
    assert unresolved["companies"] == []
    generic = next(item for item in result["public_top10"] if item["topic"] == "패션 브랜드")
    assert generic["home_context_status"] == "review_required"
    assert generic["company_eligible"] is False
    assert generic["companies"] == []
    assert any(item["display_name"] == "삼성전자" for item in result["public_top10"])


def test_investment_terms_do_not_receive_unrelated_generic_companies(tmp_path):
    from trzip.hourly_store import HourlyObservation, upsert
    target = tmp_path / "investment-company-guard.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(at.isoformat(), "google_trends", "관리 종목", 1, 100, "observed"),
        HourlyObservation(at.isoformat(), "google_trends", "삼성전자", 2, 99, "observed"),
    ], target)

    result = build_intelligence(at, hours=1, path=target)
    generic = next(item for item in result["unified_ranking"] if item["display_name"] == "관리종목")
    samsung = next(item for item in result["unified_ranking"] if item["display_name"] == "삼성전자")

    assert generic["company_eligible"] is False
    assert generic["companies"] == []
    assert [company["company"] for company in samsung["companies"]] == ["삼성전자"]
    assert samsung["company_categories"][0]["name"] == "직접 기업·종목"


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
