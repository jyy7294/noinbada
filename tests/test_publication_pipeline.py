import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from trzip.publication_pipeline import (
    _attach_provider_context_research,
    _attach_youtube_chart_signals,
    _annotate_x_collection_provenance,
    _collection_health,
    _domestic_reference_needs_fundamentals,
    _complete_market_price_series,
    _enrich_market_references,
    _failure_class,
    _fresh_market_reference,
    _public_market_reference,
    _merge_domestic_market_references,
    _verification_references,
    _hourly_verification_term_limit,
    _period_detail_items,
    _previous_published_presentation,
    _prune_observations,
    _refresh_verification_layer,
    _sanitize_collection_for_public,
    _validate_contract,
    _validate_frontend_delivery,
    run,
)
from trzip.hourly_store import HourlyObservation
from trzip.presentation_feed import build_presentation_feed, build_reference_demo_feed


@pytest.fixture(autouse=True)
def enable_auxiliary_path_for_legacy_provider_tests(monkeypatch):
    """Exercise the NAVER News path explicitly in provider unit fixtures."""

    monkeypatch.setenv("TRZIP_AUXILIARY_RESEARCH_ENABLED", "1")


def test_local_cli_is_canonical():
    from trzip.local_pipeline import run as local_run

    assert local_run is run


def test_period_detail_items_include_monthly_only_summary_after_weekly_details():
    weekly = {"event_key": "weekly", "detail_status": "shared_full_detail"}
    monthly_only = {"event_key": "monthly", "detail_status": "period_summary_only"}
    intelligence = {
        "unified_ranking": [weekly],
        "ranking_views": {
            "daily": {"unified_ranking": [weekly]},
            "weekly": {"unified_ranking": [weekly]},
            "monthly": {"unified_ranking": [weekly, monthly_only]},
        },
    }

    assert _period_detail_items(intelligence) == [weekly, monthly_only]


def test_youtube_chart_signal_requires_exact_observed_event_alias():
    intelligence = {
        "youtube_content_ranking": [
            {
                "event_key": "youtube:오디세이",
                "display_topic": "오디세이",
                "best_video_rank": 2,
                "youtube_score": 98.0,
                "supporting_video_count": 2,
                "youtube_trend_rank_change": 3,
                "rank_change_status": "measured",
                "source_evidence": [{"url": "https://www.youtube.com/watch?v=one"}],
                "ranking_source": "youtube_videos_most_popular_kr",
            }
        ],
        "unified_ranking": [
            {
                "event_key": "오디세이",
                "display_name": "오디세이",
                "observed_representative_term": "오디세이",
                "raw_terms": ["오디세이 영화"],
            },
            {
                "event_key": "오디세이아님",
                "display_name": "오디세이아님",
                "observed_representative_term": "오디세이아님",
                "raw_terms": ["오디세이아님"],
            },
        ],
    }

    result = _attach_youtube_chart_signals(intelligence)

    signal = result["unified_ranking"][0]["youtube_chart_signal"]
    assert signal["status"] == "matched_exact_observed_expression"
    assert signal["best_video_rank"] == 2
    assert signal["affects_canonical_observed_rank"] is False
    assert result["unified_ranking"][1]["youtube_chart_signal"] is None


def test_provider_context_research_uses_only_naver_title_with_observed_alias():
    ready_candidate = {
        "event_key": "오디세이",
        "display_name": "오디세이",
        "observed_representative_term": "오디세이",
        "raw_terms": ["오디세이 영화"],
        "context_research": {"status": "incomplete"},
        "verification_layer": {
            "providers": {
                "naver": {
                    "status": "observed",
                    "matched": True,
                    "evidence": [{
                            "item_type": "naver_news",
                        "title": "오디세이 공식 예고편 공개",
                        "url": "https://news.example/odyssey",
                        "published_at": "2026-08-14T00:00:00+00:00",
                        "publisher": "Example News",
                    }],
                }
            }
        },
    }
    unrelated_candidate = {
        **ready_candidate,
        "event_key": "다른영화",
        "display_name": "다른 영화",
        "observed_representative_term": "다른 영화",
        "raw_terms": ["다른 영화"],
        "context_research": {"status": "incomplete"},
    }

    result = _attach_provider_context_research({
        "unified_ranking": [ready_candidate, unrelated_candidate]
    })

    context = result["unified_ranking"][0]["context_research"]
    assert context["status"] == "ready"
    assert context["trigger_title"] == "오디세이 공식 예고편 공개"
    assert context["ranking_source"] is False
    assert result["unified_ranking"][1]["context_research"]["status"] == "incomplete"


def test_provider_context_research_ignores_historical_youtube_record():
    candidate = {
        "event_key": "오디세이",
        "display_name": "오디세이",
        "observed_representative_term": "오디세이",
        "raw_terms": ["오디세이 영화"],
        "context_research": {"status": "incomplete"},
        "verification_layer": {
            "providers": {
                "youtube": {
                    "status": "observed",
                    "matched": True,
                    "evidence": [{
                        "item_type": "youtube_video",
                        "title": "오디세이 공식 예고편",
                        "url": "https://www.youtube.com/watch?v=odyssey",
                    }],
                }
            }
        },
    }

    result = _attach_provider_context_research({"unified_ranking": [candidate]})

    assert result["unified_ranking"][0]["context_research"] == {"status": "incomplete"}


def _verified_live_data_fixture(tmp_path):
    runtime = tmp_path / "runtime"
    publication = runtime / "publication"
    latest = runtime / "live-data" / "latest"
    database = runtime / "data" / "trzip-hourly.sqlite3"
    publication.mkdir(parents=True)
    database.parent.mkdir(parents=True)
    publication_id = "pub-" + "a" * 32
    observed_at = "2026-08-14T18:00:00+00:00"
    generated_at = "2026-08-14T18:05:00+00:00"
    feed = build_reference_demo_feed({"unified_ranking": []})
    presentation_path = latest / "delivery" / publication_id / "presentation.json"
    presentation_path.parent.mkdir(parents=True)
    presentation_path.write_text(json.dumps({
        "schema_version": "trzip-presentation-payload-v1",
        "publication_id": publication_id,
        "generated_at": generated_at,
        "observed_at": observed_at,
        "mode": "live",
        "unified_ranking": [],
        "presentation_feed": feed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {
        "schema_version": "trzip-frontend-delivery-v1",
        "publication_id": publication_id,
        "generated_at": generated_at,
        "observed_at": observed_at,
        "mode": "live",
        "bundle": {
            "presentation": {
                "path": f"delivery/{publication_id}/presentation.json",
            },
        },
    }
    manifest_path = latest / "manifest.json"
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    blob = hashlib.new("sha1", usedforsecurity=False)
    blob.update(f"blob {len(manifest_bytes)}\0".encode("ascii"))
    blob.update(manifest_bytes)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TABLE publication_receipts (
                   observed_at TEXT PRIMARY KEY,
                   publication_id TEXT NOT NULL,
                   remote_sha TEXT NOT NULL,
                   verified_at TEXT NOT NULL,
                   contract_json TEXT,
                   source_gate_json TEXT,
                   manifest_sha256 TEXT,
                   remote_manifest_blob TEXT
               )"""
        )
        connection.execute(
            "INSERT INTO publication_receipts VALUES (?,?,?,?,?,?,?,?)",
            (
                observed_at,
                publication_id,
                "b" * 40,
                "2026-08-14T18:06:00+00:00",
                json.dumps({"passed": True}),
                json.dumps({"passed": True}),
                hashlib.sha256(manifest_bytes).hexdigest(),
                blob.hexdigest(),
            ),
        )
    return publication, database, feed


def test_first_v4_publication_ignores_verified_legacy_v3_feed(tmp_path, monkeypatch):
    publication, database, previous_feed = _verified_live_data_fixture(tmp_path)
    monkeypatch.setattr(
        "trzip.publication_pipeline._validate_frontend_delivery",
        lambda latest, manifest: None,
    )

    loaded = _previous_published_presentation(
        publication,
        database,
        before=datetime(2026, 8, 15, 2, tzinfo=UTC),
    )
    current = build_presentation_feed({"unified_ranking": []}, previous_feed=loaded)

    assert previous_feed["schema_version"] == "trzip-presentation-feed-v3"
    assert loaded is None
    assert current["schema_version"] == "trzip-presentation-feed-v4"
    assert current["status"] == "empty"
    assert current["items"] == []


def test_invalid_live_data_receipt_keeps_new_rank_fallback(tmp_path, monkeypatch):
    publication, database, _ = _verified_live_data_fixture(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE publication_receipts SET manifest_sha256=?",
            ("0" * 64,),
        )
    monkeypatch.setattr(
        "trzip.publication_pipeline._validate_frontend_delivery",
        lambda latest, manifest: None,
    )

    loaded = _previous_published_presentation(
        publication,
        database,
        before=datetime(2026, 8, 15, 2, tzinfo=UTC),
    )
    current = build_presentation_feed({"unified_ranking": []}, previous_feed=loaded)

    assert loaded is None
    assert current["status"] == "empty"
    assert current["items"] == []


def test_pipeline_writes_frontend_contract(tmp_path, monkeypatch):
    at = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    stamp = at.isoformat()

    monkeypatch.setattr("trzip.publication_pipeline.floor_hour", lambda value: at)
    monkeypatch.setattr(
        "trzip.hourly_store.collect_google",
        lambda value: [
            HourlyObservation(
                stamp, "google_trends",
                "말복" if rank == 1 else f"구글-{rank}",
                rank, 101 - rank, "observed",
                source_payload_json=json.dumps({
                    "collection_declared_total": 100,
                    "collection_page_count": 4,
                    "collection_completion_verified": True,
                }),
                collector_version="google_trending_now_kr_v1",
            )
            for rank in range(1, 101)
        ],
    )
    monkeypatch.setattr(
        "trzip.hourly_store.collect_x",
        lambda value: [
            HourlyObservation(
                stamp, "x", "말복" if rank == 1 else f"엑스-{rank}",
                rank, 101 - rank, "observed",
                collector_version="x_current_session_kr_v1",
            )
            for rank in range(1, 31)
        ],
    )
    monkeypatch.setattr(
        "trzip.publication_pipeline.pykrx_stock",
        lambda code, base_date, lookback_days=21: {
             "status": "observed",
             "provider": "pykrx",
             "source_url": "https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd",
             "stock_code": code,
             "summary": {
                 "as_of": at.date().isoformat(),
                 "close": 10000,
                 "close_krw": 10000,
                 "daily_change_pct": 1.25,
                 "volume": 123456,
                 "currency": "KRW",
                 "market_cap": 1_000_000_000,
                 "market_cap_krw": 1_000_000_000,
             },
             "valuation": {
                 "market_cap_as_of": at.date().isoformat(),
                 "per": 10.0,
                 "per_status": "observed",
                 "per_as_of": at.date().isoformat(),
                 "pbr": 1.0,
                 "pbr_as_of": at.date().isoformat(),
                 "roe_pct": 10.0,
                 "roe_numerator": {"as_of": at.date().isoformat()},
             },
             "fx_reference": {
                 "status": "observed", "provider": "identity", "rate": 1.0,
                 "as_of": at.date().isoformat(),
                 "source_url": "https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd",
             },
             "daily_ohlcv": [],
        },
    )
    def unexpected_yahoo(*_args, **_kwargs):
        raise AssertionError("complete pykrx fixture must not call Yahoo")

    monkeypatch.setattr(
        "trzip.publication_pipeline.yahoo_finance_fundamentals", unexpected_yahoo
    )
    monkeypatch.setattr(
        "trzip.publication_pipeline.yahoo_finance_stock", unexpected_yahoo
    )
    monkeypatch.setattr("trzip.publication_pipeline.verify_terms", lambda *args, **kwargs: [])

    result = run(tmp_path)

    assert result["collection"]["observed"] == 130
    assert result["daily_file"].startswith("observations/")
    assert result["pruned_observation_files"] == 0
    assert result["retention_policy"] == "indefinite"
    assert result["retention_days"] is None
    intelligence = json.loads((tmp_path / "latest" / "intelligence.json").read_text(encoding="utf-8"))
    assert intelligence["mode"] == "live"
    assert intelligence["unified_ranking"][0]["display_name"] == "말복"
    assert intelligence["market_data_status"]["provider"] == "pykrx"
    assert intelligence["collection_status"]["partial"] is False
    assert intelligence["collection_status"]["source_status"] == {
        "x": "observed", "google_trends": "observed"
    }
    trend = intelligence["unified_ranking"][0]
    assert trend["companies"] == []
    assert len({company["stock_code"] for company in trend["company_candidates"]}) == 6
    assert all(company["ontology_complete"] is True for company in trend["company_candidates"])
    assert trend["company_resolution"]["publish_status"] == "not_published"
    assert trend["company_resolution"]["reason"] == "fewer_than_ten_evidence_backed_companies"
    assert len(trend["company_candidates"]) == 6
    assert list((tmp_path / "observations").glob("*.json"))
    status = json.loads((tmp_path / "latest" / "status.json").read_text(encoding="utf-8"))
    assert status["partial"] is False
    assert result["storage"] == "local-sqlite-published-to-live-data"
    assert intelligence["publication_id"] == status["publication_id"] == result["publication_id"]
    assert intelligence["generated_at"] == status["generated_at"] == result["generated_at"]
    assert intelligence["window"]["to"] == status["observed_at"] == result["observed_at"]
    assert result["schema_version"] == "trzip-live-data-v3"
    assert intelligence["verification_run"]["ranking_effect"] == "none"
    manifest = json.loads(
        (tmp_path / "latest" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["publication_id"] == result["publication_id"]
    assert manifest["generated_at"] == result["generated_at"]
    assert manifest["observed_at"] == result["observed_at"]
    assert manifest["bundle"]["trend_count"] == len(intelligence["unified_ranking"])
    rankings_path = tmp_path / "latest" / manifest["bundle"]["rankings"]["path"]
    rankings = json.loads(rankings_path.read_text(encoding="utf-8"))
    assert [item["event_key"] for item in rankings["unified_ranking"]] == [
        item["event_key"] for item in intelligence["unified_ranking"]
    ]
    assert rankings["ranking_default_period"] == "daily"
    assert [period["key"] for period in rankings["ranking_periods"]] == [
        "daily", "weekly", "monthly",
    ]
    assert set(rankings["ranking_views"]) == {"daily", "weekly", "monthly"}
    assert [
        item["event_key"] for item in rankings["ranking_views"]["daily"]["unified_ranking"]
    ] == [item["event_key"] for item in rankings["unified_ranking"]]
    assert rankings["all_observed_ranking"] == rankings["unified_ranking"]
    assert rankings["home_top10"] == rankings["trend_top10"] == rankings["public_top10"]
    assert rankings["home_feed"] == intelligence["home_feed"]
    assert rankings["home_feed"]["status"] in {"ready", "empty"}
    assert "youtube_content_discovery" not in rankings
    assert isinstance(rankings["rising_top10"], list)
    assert len(rankings["category_summary"]) == 8
    assert intelligence["publishable"] is True
    assert status["publishable"] is True
    assert all(
        "companies" not in item
        for view in rankings["ranking_views"].values()
        for item in view["unified_ranking"]
    )
    assert all("period_top10" in view for view in rankings["ranking_views"].values())
    assert b"\r\n" not in (tmp_path / "latest" / "status.json").read_bytes()
    assert b"\r\n" not in rankings_path.read_bytes()
    assert b"\r\n" not in (tmp_path / "latest" / "manifest.json").read_bytes()
    _validate_frontend_delivery(tmp_path / "latest", manifest)
    presentation_path = tmp_path / "latest" / manifest["bundle"]["presentation"]["path"]
    presentation_payload = json.loads(presentation_path.read_text(encoding="utf-8"))
    presentation_payload["presentation_feed"]["observed_at"] = "2000-01-01T00:00:00+00:00"
    presentation_path.write_text(
        json.dumps(presentation_payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    tampered_manifest = json.loads(json.dumps(manifest))
    tampered_manifest["bundle"]["presentation"]["sha256"] = hashlib.sha256(
        presentation_path.read_bytes()
    ).hexdigest()
    with pytest.raises(ValueError, match="differs between published documents"):
        _validate_frontend_delivery(tmp_path / "latest", tampered_manifest)
    assert intelligence["news_discovery_queue"][0]["observed_term"] == "양즈깐루"

    second = run(tmp_path)
    daily = json.loads((tmp_path / second["daily_file"]).read_text(encoding="utf-8"))
    assert len(daily) == 130
    assert second["coverage"]["rows"] == 130
    assert second["publication_id"] != result["publication_id"]


def test_nonpositive_retention_preserves_all_published_daily_files(tmp_path):
    observations = tmp_path / "observations"
    observations.mkdir()
    old_file = observations / "2025-01-01.json"
    old_file.write_text("[]", encoding="utf-8")

    assert _prune_observations(tmp_path, datetime(2026, 8, 12, tzinfo=UTC), 0) == 0
    assert old_file.exists()


def _public_rows(count=5):
    rows = [
            {
                "rank": index,
                "event_key": f"event:{index}",
                "display_name": f"term {index}",
                "score": 100 - index,
                "lane": "main",
                "latest_source_ranks": {"google_trends": index},
            }
            for index in range(1, count + 1)
        ]
    return {
        "unified_ranking": rows,
        "public_top10": list(rows),
        "collection_status": {"partial": False, "errors": {}},
    }


def test_hourly_verification_uses_twenty_term_capacity_and_reuses_ledger(
    tmp_path, monkeypatch
):
    from trzip.provider_verification import (
        ProviderCredentials,
        read_verification_ledger,
        verify_terms as actual_verify_terms,
    )

    at = datetime(2026, 8, 12, 13, tzinfo=UTC)
    database = tmp_path / "runtime.sqlite3"
    intelligence = _public_rows()
    selected = _verification_references(intelligence, limit=3)
    assert [item.trend_key for item in selected] == ["event:1", "event:2", "event:3"]
    assert _hourly_verification_term_limit({"TRZIP_PROVIDER_VERIFICATION_TERM_LIMIT": "99"}) == 20

    calls = []

    def offline_verify(references, **kwargs):
        calls.append([item.trend_key for item in references])
        return actual_verify_terms(
            references,
            path=kwargs["path"],
            at=kwargs["at"],
            credentials=ProviderCredentials(),
            youtube_term_limit=kwargs["youtube_term_limit"],
        )

    monkeypatch.setattr("trzip.publication_pipeline.verify_terms", offline_verify)
    before = [
        (item["rank"], item["score"])
        for item in intelligence["unified_ranking"]
    ]
    first = _refresh_verification_layer(intelligence, database, at)

    assert calls == [["event:1", "event:2", "event:3", "event:4", "event:5"]]
    assert len(read_verification_ledger(database)) == 5
    assert first["verification_run"] == {
        "status": "completed",
        "requested_terms": 5,
        "attempted_terms": 5,
        "hourly_term_limit": 20,
        "selection_policy": "never_verified_then_oldest_verified_then_current_rank",
        "candidate_count": 5,
        "selection_scope": "current_non_issue_candidates_including_review_lane",
            "providers": ["naver"],
            "configured": True,
            "ranking_effect": "none",
            "new_provider_calls_allowed_this_run": True,
        "home_ranking_effect": "none_context_only",
        "affects_collection_partial": False,
        "blocks_publication": False,
        "error": None,
    }
    assert before == [
        (item["rank"], item["score"])
        for item in first["unified_ranking"]
    ]
    assert first["collection_status"]["partial"] is False

    second = _refresh_verification_layer(first, database, at)

    assert calls == [["event:1", "event:2", "event:3", "event:4", "event:5"]]
    assert len(read_verification_ledger(database)) == 5
    assert second["verification_run"]["status"] == "skipped_already_recorded_for_hour"
    assert second["verification_run"]["attempted_terms"] == 0


def test_verification_layer_exposes_only_active_naver_provider(monkeypatch, tmp_path):
    intelligence = _public_rows(1)
    at = datetime(2026, 8, 12, 13, tzinfo=UTC)
    monkeypatch.setattr(
        "trzip.publication_pipeline.verification_trend_keys_at",
        lambda path, observed_at: {"event:1"},
    )
    monkeypatch.setattr(
        "trzip.publication_pipeline.latest_verification_by_trend",
        lambda path: {
            "event:1": {
                "providers": {
                    "naver": {
                        "status": "observed",
                        "matched": True,
                        "evidence": [{
                            "item_type": "naver_news",
                            "title": "후보 1 공식 공개",
                            "url": "https://example.com/news/1",
                        }],
                    },
                    "youtube": {"status": "observed", "matched": True},
                }
            }
        },
    )

    result = _refresh_verification_layer(
        intelligence,
        tmp_path / "runtime.sqlite3",
        at,
    )

    layer = result["unified_ranking"][0]["verification_layer"]
    assert list(layer["providers"]) == ["naver"]
    assert layer["observed_platforms"] == ["naver"]
    assert result["verification_run"]["providers"] == ["naver"]


def test_naver_news_defaults_active_with_credentials_but_explicit_zero_disables(
    monkeypatch, tmp_path
):
    from trzip.provider_verification import ProviderCredentials

    at = datetime(2026, 8, 12, 13, tzinfo=UTC)
    database = tmp_path / "runtime.sqlite3"
    calls = []
    monkeypatch.setattr(
        "trzip.publication_pipeline.resolve_provider_credentials",
        lambda: ProviderCredentials("id", "secret", "", ""),
    )
    monkeypatch.setattr(
        "trzip.publication_pipeline.verification_trend_keys_at", lambda *args: set()
    )
    monkeypatch.setattr(
        "trzip.publication_pipeline.latest_verification_by_trend", lambda *args: {}
    )
    monkeypatch.setattr(
        "trzip.publication_pipeline.verify_terms",
        lambda references, **kwargs: calls.append(list(references)) or [],
    )

    monkeypatch.delenv("TRZIP_AUXILIARY_RESEARCH_ENABLED", raising=False)
    active = _refresh_verification_layer(_public_rows(1), database, at)
    assert active["verification_run"]["status"] == "completed"
    assert active["verification_run"]["providers"] == ["naver"]
    assert len(calls) == 1

    monkeypatch.setenv("TRZIP_AUXILIARY_RESEARCH_ENABLED", "0")
    disabled = _refresh_verification_layer(_public_rows(1), database, at)
    assert disabled["verification_run"]["status"] == "disabled_by_runtime_policy"
    assert disabled["verification_run"]["providers"] == []
    assert len(calls) == 1


def test_hourly_verification_refreshes_public_ten_each_hour(
    tmp_path, monkeypatch
):
    from datetime import timedelta
    from trzip.provider_verification import ProviderCredentials, verify_terms as actual_verify_terms

    database = tmp_path / "runtime.sqlite3"
    intelligence = _public_rows(10)
    at = datetime(2026, 8, 12, 13, tzinfo=UTC)
    batches = []

    def offline_verify(references, **kwargs):
        batches.append([item.trend_key for item in references])
        return actual_verify_terms(
            references,
            path=kwargs["path"],
            at=kwargs["at"],
            credentials=ProviderCredentials(),
            youtube_term_limit=kwargs["youtube_term_limit"],
        )

    monkeypatch.setattr("trzip.publication_pipeline.verify_terms", offline_verify)
    for offset in range(4):
        _refresh_verification_layer(intelligence, database, at + timedelta(hours=offset))

    assert batches == [
        [f"event:{index}" for index in range(1, 11)],
        [f"event:{index}" for index in range(1, 11)],
        [f"event:{index}" for index in range(1, 11)],
        [f"event:{index}" for index in range(1, 11)],
    ]


def test_verification_failure_is_separate_and_never_marks_core_partial(
    tmp_path, monkeypatch
):
    at = datetime(2026, 8, 12, 13, tzinfo=UTC)
    intelligence = _public_rows(1)

    def fail_verification(*args, **kwargs):
        raise RuntimeError("provider temporarily unavailable")

    monkeypatch.setattr("trzip.publication_pipeline.verify_terms", fail_verification)
    result = _refresh_verification_layer(intelligence, tmp_path / "runtime.sqlite3", at)

    assert result["verification_run"]["status"] == "failed_non_blocking"
    assert result["verification_run"]["error"] == "provider_verification_failed"
    assert result["verification_run"]["blocks_publication"] is False
    assert result["verification_run"]["affects_collection_partial"] is False
    assert result["collection_status"]["partial"] is False


def test_provider_verification_uses_unified_main_candidates_but_skips_issue_lane():
    hidden = {
        "rank": 1,
        "event_key": "hidden-issue",
        "display_name": "hidden issue",
        "latest_source_ranks": {"google_trends": 1},
        "lane": "issue",
    }
    visible = {
        "rank": 9,
        "event_key": "visible-main",
        "display_name": "visible main",
        "latest_source_ranks": {"google_trends": 9},
        "lane": "main",
    }
    selected = _verification_references(
        {"unified_ranking": [hidden, visible], "public_top10": [visible]},
        limit=3,
    )
    assert [item.trend_key for item in selected] == ["visible-main"]


def test_market_reference_public_contract_removes_provider_exception_text():
    sanitized = _public_market_reference(
        {
            "status": "error",
            "stock_code": "005930",
            "reason": "RuntimeError: C:\\Users\\name\\secret.txt?token=abc",
        },
        "005930",
    )
    assert sanitized == {
        "status": "error",
        "stock_code": "005930",
        "reason": "market_reference_error",
    }


def test_market_reference_public_contract_nulls_invalid_ratios_but_keeps_negative_roe():
    sanitized = _public_market_reference(
        {
            "status": "observed",
            "provider": "pykrx",
            "source_url": "https://data.krx.co.kr/",
            "stock_code": "005930",
            "summary": {
                "market_cap": float("inf"),
                "market_cap_krw": 0,
                "currency": "KRW",
            },
            "valuation": {
                "per": 0,
                "pbr": float("nan"),
                "roe_pct": -4.5,
            },
        },
        "005930",
    )

    assert sanitized["summary"]["market_cap"] is None
    assert sanitized["summary"]["market_cap_krw"] is None
    assert sanitized["market_cap"] is None
    assert sanitized["valuation"]["per"] is None
    assert sanitized["valuation"]["pbr"] is None
    assert sanitized["valuation"]["roe_pct"] == -4.5


def test_market_enrichment_routes_domestic_and_overseas_actual_providers(monkeypatch):
    at = datetime(2026, 8, 15, 0, tzinfo=UTC)
    daily = [
        {"date": f"2026-07-{index:02d}", "close": 100 + index}
        for index in range(1, 31)
    ]
    calls = []

    def fake_pykrx(code, base_date, lookback_days=45):
        calls.append(("pykrx", code, base_date, lookback_days))
        return {
            "status": "observed", "provider": "pykrx", "stock_code": code,
            "source_url": "https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd",
            "daily_ohlcv": daily,
            "summary": {
                "as_of": "2026-08-14", "currency": "KRW", "close": 130,
                "market_cap": 1_000, "market_cap_krw": 1_000,
            },
            "valuation": {
                "market_cap_as_of": "2026-08-14",
                "per": 10.0, "per_status": "observed", "per_as_of": "2026-08-14",
                "pbr": 1.2, "pbr_as_of": "2026-08-14", "roe_pct": 8.0,
                "roe_numerator": {"as_of": "2026-06-30"},
            },
        }

    def fake_yahoo(code, exchange, as_of=None):
        calls.append(("yahoo_finance", code, exchange, as_of))
        return {
            "status": "observed", "provider": "yahoo_finance", "ticker": code,
            "exchange": exchange, "source_url": f"https://finance.yahoo.com/quote/{code}",
            "daily_ohlcv": daily,
            "summary": {"as_of": "2026-07-30", "currency": "USD", "close": 130, "market_cap": 2_000},
            "valuation": {"per": 20.0, "pbr": 2.2, "roe_pct": 18.0},
        }

    monkeypatch.setattr("trzip.publication_pipeline.pykrx_stock", fake_pykrx)
    monkeypatch.setattr("trzip.publication_pipeline.yahoo_finance_stock", fake_yahoo)
    intelligence = {"unified_ranking": [{"company_candidates": [
        {"stock_code": "005930", "market": "KRX"},
        {"stock_code": "AAPL", "market": "NASDAQ"},
    ]}]}

    result = _enrich_market_references(intelligence, {}, at)
    domestic, overseas = result["unified_ranking"][0]["company_candidates"]

    assert [call[0] for call in calls] == ["pykrx", "yahoo_finance"]
    assert domestic["market_reference"]["currency"] == "KRW"
    assert overseas["market_reference"]["currency"] == "USD"
    assert overseas["market_reference"]["market_cap"] == 2_000
    assert overseas["market_reference"]["valuation"]["roe_pct"] == 18.0
    assert result["market_data_status"]["provider"] == "multi_market_actual"
    assert result["market_data_status"]["provider_request_count"] == {
        "pykrx": 1, "yahoo_finance": 1,
    }


def test_market_cache_rejects_incomplete_price_series_without_padding():
    at = datetime(2026, 8, 15, 0, tzinfo=UTC)
    market = {
        "summary": {"as_of": "2026-08-14"},
        "daily_ohlcv": [
            {"date": f"2026-07-{index + 1:02d}", "close": 100 + index}
            for index in range(28)
        ],
    }

    assert _fresh_market_reference(market, at) is True
    assert _complete_market_price_series(market) is False
    market["daily_ohlcv"].extend([
        {"date": "2026-07-29", "close": 128},
        {"date": "2026-07-30", "close": 129},
    ])
    assert _complete_market_price_series(market) is True
    market["daily_ohlcv"].append({"date": "2026-07-31", "close": 130})
    assert _complete_market_price_series(market) is False
    market["daily_ohlcv"] = market["daily_ohlcv"][:30]
    market["daily_ohlcv"][-1]["date"] = market["daily_ohlcv"][-2]["date"]
    assert _complete_market_price_series(market) is False


def test_market_enrichment_fails_closed_on_reviewed_inactive_krx_security(monkeypatch):
    at = datetime(2026, 8, 15, 16, tzinfo=UTC)
    def unexpected_pykrx(*_args, **_kwargs):
        raise AssertionError("inactive reviewed security must not reach a quote provider")

    monkeypatch.setattr("trzip.publication_pipeline.pykrx_stock", unexpected_pykrx)
    monkeypatch.setattr(
        "trzip.publication_pipeline.yahoo_finance_fundamentals",
        lambda *_args, **_kwargs: {"status": "unavailable", "provider": "yahoo_finance"},
    )
    intelligence = {
        "unified_ranking": [{
            "company_candidates": [{"company": "신세계푸드", "stock_code": "031440", "market": "KRX"}]
        }]
    }

    result = _enrich_market_references(intelligence, {}, at)
    market = result["unified_ranking"][0]["company_candidates"][0]["market_reference"]

    assert {key: market[key] for key in ("status", "stock_code", "reason")} == {
        "status": "not_found", "stock_code": "031440",
        "reason": "market_reference_not_found",
    }
    assert market["listing_verification"]["current_listed"] is False
    assert result["market_data_status"]["newly_observed"] == 0
    assert result["market_data_status"]["provider_request_count"]["pykrx"] == 0


def test_market_enrichment_rejects_fresh_cached_inactive_krx_security(monkeypatch):
    at = datetime(2026, 8, 15, 16, tzinfo=UTC)

    def unexpected_provider(*_args, **_kwargs):
        raise AssertionError("inactive reviewed security must bypass cache and providers")

    monkeypatch.setattr("trzip.publication_pipeline.pykrx_stock", unexpected_provider)
    monkeypatch.setattr(
        "trzip.publication_pipeline.yahoo_finance_fundamentals",
        unexpected_provider,
    )
    cached_market = {
        "status": "observed",
        "provider": "pykrx",
        "source_url": "https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd",
        "summary": {"as_of": "2026-08-14", "currency": "KRW", "close": 50_000},
        "valuation": {"per": 10.0, "pbr": 1.0, "roe_pct": 10.0},
        "daily_ohlcv": [
            {"date": f"2026-07-{index:02d}", "close": 50_000 + index}
            for index in range(1, 31)
        ],
    }
    previous = {
        "unified_ranking": [{
            "company_candidates": [{
                "company": "신세계푸드",
                "stock_code": "031440",
                "market": "KRX",
                "market_reference": cached_market,
            }]
        }]
    }
    intelligence = {
        "unified_ranking": [{
            "company_candidates": [{
                "company": "신세계푸드",
                "stock_code": "031440",
                "market": "KRX",
            }]
        }]
    }

    result = _enrich_market_references(intelligence, previous, at)
    market = result["unified_ranking"][0]["company_candidates"][0]["market_reference"]

    assert {key: market[key] for key in ("status", "stock_code", "reason")} == {
        "status": "not_found", "stock_code": "031440",
        "reason": "market_reference_not_found",
    }
    assert market["listing_verification"]["current_listed"] is False
    assert result["market_data_status"]["reused_company_rows"] == 0
    assert result["market_data_status"]["provider_request_count"] == {
        "pykrx": 0,
        "yahoo_finance": 0,
    }


def test_domestic_market_enrichment_supplements_only_missing_actual_facts(monkeypatch):
    at = datetime(2026, 8, 15, 0, tzinfo=UTC)
    daily = [
        {"date": f"2026-07-{index:02d}", "close": 70_000 + index}
        for index in range(1, 31)
    ]
    calls = []

    def fake_pykrx(code, base_date, lookback_days=45):
        calls.append(("pykrx", code))
        return {
            "status": "observed",
            "provider": "pykrx",
            "stock_code": code,
            "source_url": "https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd",
            "daily_ohlcv": daily,
            "summary": {
                "as_of": "2026-07-30",
                "currency": "KRW",
                "close": 70_030,
                "close_krw": 70_030,
                "market_cap": None,
                "market_cap_krw": None,
            },
            "fx_reference": {
                "status": "observed",
                "provider": "identity",
                "rate": 1.0,
                "as_of": "2026-07-30",
                "source_url": "https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd",
            },
            "valuation": {"per": 11.0, "pbr": 1.4},
        }

    def fake_yahoo(code, exchange, as_of=None):
        calls.append(("yahoo_finance", code, exchange))
        return {
            "status": "observed",
            "provider": "yahoo_finance",
            "ticker": code,
            "exchange": exchange,
            "source_url": f"https://finance.yahoo.com/quote/{code}.KS",
            "daily_ohlcv": [{"date": "2026-07-30", "close": 70_030}],
            "summary": {
                "as_of": "2026-07-30",
                "currency": "KRW",
                "close": 70_030,
                "close_krw": 70_030,
                "market_cap": 420_000_000_000_000,
                "market_cap_krw": 420_000_000_000_000,
            },
            "valuation": {"per": 12.0, "pbr": 1.5, "roe_pct": 13.0},
            "fx_reference": {
                "status": "observed",
                "provider": "identity",
                "rate": 1.0,
                "as_of": "2026-07-30",
                "source_url": "https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd",
            },
        }

    monkeypatch.setattr("trzip.publication_pipeline.pykrx_stock", fake_pykrx)
    monkeypatch.setattr("trzip.publication_pipeline.yahoo_finance_fundamentals", fake_yahoo)
    intelligence = {
        "unified_ranking": [{"company_candidates": [{"stock_code": "005930", "market": "KOSPI"}]}]
    }

    result = _enrich_market_references(intelligence, {}, at)
    market = result["unified_ranking"][0]["company_candidates"][0]["market_reference"]

    assert calls == [("pykrx", "005930"), ("yahoo_finance", "005930", "KOSPI")]
    assert market["provider"] == "pykrx+yahoo_finance"
    assert len(market["daily_ohlcv"]) == 30  # primary KRX price series is preserved
    assert market["summary"]["market_cap_krw"] == 420_000_000_000_000
    assert market["valuation"] == {"per": 11.0, "pbr": 1.4, "roe_pct": 13.0}
    assert result["market_data_status"]["provider_request_count"] == {
        "pykrx": 1,
        "yahoo_finance": 1,
    }


def test_domestic_market_metric_validity_replaces_sentinels_but_keeps_real_roe():
    at = datetime(2026, 8, 15, 0, tzinfo=UTC)
    primary = {
        "status": "observed",
        "provider": "pykrx",
        "source_url": "https://data.krx.co.kr/",
        "summary": {"market_cap": float("nan"), "market_cap_krw": 0},
        "valuation": {"per": 0.0, "pbr": float("inf"), "roe_pct": -4.5},
    }
    supplement = {
        "status": "observed",
        "provider": "yahoo_finance",
        "source_url": "https://finance.yahoo.com/quote/005930.KS",
        "summary": {"market_cap": 1000.0, "market_cap_krw": 1000.0},
        "valuation": {"per": 9.0, "pbr": 1.2, "roe_pct": 8.0},
    }

    assert _domestic_reference_needs_fundamentals(primary, at) is True
    merged = _merge_domestic_market_references(primary, supplement)

    assert merged["summary"]["market_cap_krw"] == 1000.0
    assert merged["valuation"] == {"per": 9.0, "pbr": 1.2, "roe_pct": -4.5}
    assert merged["provider"] == "pykrx+yahoo_finance"

    zero_roe = {
        **primary,
        "summary": {
            "as_of": "2026-08-15", "market_cap": 1000.0,
            "market_cap_krw": 1000.0,
        },
        "valuation": {
            "market_cap_as_of": "2026-08-15",
            "per": 9.0, "per_status": "observed", "per_as_of": "2026-08-15",
            "pbr": 1.2, "pbr_as_of": "2026-08-15", "roe_pct": 0.0,
            "roe_numerator": {"as_of": "2026-06-30"},
        },
    }
    assert _domestic_reference_needs_fundamentals(zero_roe, at) is False


def test_market_status_separates_attempts_from_observed_contributors(monkeypatch):
    monkeypatch.setattr(
        "trzip.publication_pipeline.pykrx_stock",
        lambda *_args, **_kwargs: {
            "status": "observed",
            "provider": "pykrx",
            "source_url": "https://data.krx.co.kr/",
            "daily_ohlcv": [{"date": "2026-08-14", "close": 100}],
            "summary": {"as_of": "2026-08-14", "currency": "KRW", "close": 100},
            "valuation": {},
        },
    )
    monkeypatch.setattr(
        "trzip.publication_pipeline.yahoo_finance_fundamentals",
        lambda *_args, **_kwargs: {"status": "unavailable", "provider": "yahoo_finance"},
    )
    intelligence = {
        "unified_ranking": [{"company_candidates": [{"stock_code": "005930", "market": "KOSPI"}]}]
    }

    result = _enrich_market_references(
        intelligence, {}, datetime(2026, 8, 15, 0, tzinfo=UTC)
    )
    status = result["market_data_status"]

    assert status["provider"] == "pykrx"
    assert status["providers"] == ["pykrx"]
    assert status["attempted_providers"] == ["pykrx", "yahoo_finance"]
    assert status["observed_provider_row_count"] == {"pykrx": 1, "yahoo_finance": 0}
    assert status["provider_request_count"] == {"pykrx": 1, "yahoo_finance": 1}


def test_domestic_market_enrichment_never_fills_missing_values_when_both_providers_fail(monkeypatch):
    monkeypatch.setattr(
        "trzip.publication_pipeline.pykrx_stock",
        lambda *_args, **_kwargs: {"status": "unavailable", "reason": "krx_down"},
    )
    monkeypatch.setattr(
        "trzip.publication_pipeline.yahoo_finance_stock",
        lambda *_args, **_kwargs: {"status": "unavailable", "reason": "yahoo_down"},
    )
    intelligence = {
        "unified_ranking": [{"company_candidates": [{"stock_code": "005930", "market": "KRX"}]}]
    }

    result = _enrich_market_references(
        intelligence, {}, datetime(2026, 8, 15, 0, tzinfo=UTC)
    )
    market = result["unified_ranking"][0]["company_candidates"][0]["market_reference"]

    assert market["status"] == "unavailable"
    assert "summary" not in market
    assert result["market_data_status"]["provider_request_count"] == {
        "pykrx": 1,
        "yahoo_finance": 2,
    }
    assert result["market_data_status"]["provider"] == "unavailable"
    assert result["market_data_status"]["providers"] == []
    assert result["market_data_status"]["attempted_providers"] == [
        "pykrx",
        "yahoo_finance",
    ]


def test_scheduled_publication_verifies_only_automatic_main_terms_once_per_hour(
    tmp_path, monkeypatch
):
    from trzip.provider_verification import (
        ProviderCredentials,
        read_verification_ledger,
        verify_terms as actual_verify_terms,
    )

    at = datetime(2026, 8, 12, 13, tzinfo=UTC)
    stamp = at.isoformat()
    database = tmp_path / "runtime.sqlite3"
    topics = ["업비트", "네이마르", "지드래곤", "말복"]
    monkeypatch.setattr("trzip.publication_pipeline.floor_hour", lambda value: at)
    monkeypatch.setattr(
        "trzip.hourly_store.collect_google",
        lambda value: [
            HourlyObservation(stamp, "google_trends", topic, index, 101 - index, "observed")
            for index, topic in enumerate(topics, start=1)
        ],
    )
    monkeypatch.setattr(
        "trzip.hourly_store.collect_x",
        lambda value: [
            HourlyObservation(stamp, "x", topic, index, 101 - index, "observed")
            for index, topic in enumerate(topics, start=1)
        ],
    )
    monkeypatch.setattr(
        "trzip.publication_pipeline.pykrx_stock",
        lambda *args, **kwargs: {"status": "unavailable", "reason": "test"},
    )

    def offline_verify(references, **kwargs):
        return actual_verify_terms(
            references,
            path=kwargs["path"],
            at=kwargs["at"],
            credentials=ProviderCredentials(),
            youtube_term_limit=kwargs["youtube_term_limit"],
        )

    monkeypatch.setattr("trzip.publication_pipeline.verify_terms", offline_verify)
    run(tmp_path / "publication", database_path=database, now=at)
    first_payload = json.loads(
        (tmp_path / "publication" / "latest" / "intelligence.json").read_text(
            encoding="utf-8"
        )
    )

    # The candidate pass includes review-lane candidates. Each optional
    # NAVER News writes one auditable result for every candidate.
    assert len(read_verification_ledger(database)) == 4
    assert first_payload["verification_run"]["status"] == "completed"
    assert first_payload["verification_run"]["requested_terms"] == 4
    assert first_payload["verification_run"]["ranking_effect"] == "none"

    run(tmp_path / "publication", database_path=database, now=at)
    second_payload = json.loads(
        (tmp_path / "publication" / "latest" / "intelligence.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(read_verification_ledger(database)) == 4
    assert second_payload["verification_run"]["status"] == "skipped_already_recorded_for_hour"


def test_news_discovery_becomes_context_only_after_core_source_observation(tmp_path, monkeypatch):
    at = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    stamp = at.isoformat()
    monkeypatch.setattr("trzip.publication_pipeline.floor_hour", lambda value: at)
    monkeypatch.setattr(
        "trzip.hourly_store.collect_google",
        lambda value: [
            HourlyObservation(stamp, "google_trends", "양즈깐루", 1, 100, "observed")
        ],
    )
    monkeypatch.setattr("trzip.hourly_store.collect_x", lambda value: [])
    monkeypatch.setattr("trzip.publication_pipeline.verify_terms", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "trzip.publication_pipeline.pykrx_stock",
        lambda *args, **kwargs: {"status": "unavailable", "reason": "test"},
    )

    run(tmp_path)

    intelligence = json.loads(
        (tmp_path / "latest" / "intelligence.json").read_text(encoding="utf-8")
    )
    status = json.loads(
        (tmp_path / "latest" / "status.json").read_text(encoding="utf-8")
    )
    assert intelligence["publishable"] is False
    assert status["publishable"] is False
    trend = intelligence["unified_ranking"][0]
    news = next(
        item for item in intelligence["news_discovery_queue"]
        if item["observed_term"] == "양즈깐루"
    )
    assert news["core_source_gate"] == "satisfied_by_x_or_google"
    assert news["ranking_insertion_performed"] is False
    assert trend["news_context"]["status"] == "observed"
    assert trend["news_context"]["claim_types"] == ["consumer_behavior"]
    assert trend["news_context"]["affects_score"] is False


@pytest.mark.parametrize(
    ("changed_document", "field", "value", "message"),
    [
        ("status", "publication_id", "pub-other", "publication_id"),
        ("metadata", "generated_at", "2026-08-12T03:00:01+00:00", "generated_at"),
        ("status", "observed_at", "2026-08-12T04:00:00+00:00", "observation window"),
    ],
)
def test_publication_contract_rejects_mixed_document_bundle(
    changed_document, field, value, message
):
    observed_at = "2026-08-12T03:00:00+00:00"
    generated_at = "2026-08-12T03:00:05+00:00"
    intelligence = {
        "mode": "live",
        "publication_id": "pub-one",
        "generated_at": generated_at,
        "window": {"to": observed_at},
        "unified_ranking": [],
    }
    metadata = {
        "mode": "live",
        "publication_id": "pub-one",
        "generated_at": generated_at,
        "observed_at": observed_at,
        "collection": {"rank_sources": ["x", "google_trends"]},
    }
    status = {
        "mode": "live",
        "publication_id": "pub-one",
        "generated_at": generated_at,
        "observed_at": observed_at,
    }
    {"intelligence": intelligence, "metadata": metadata, "status": status}[
        changed_document
    ][field] = value

    with pytest.raises(ValueError, match=message):
        _validate_contract(intelligence, metadata, status)


def test_collection_health_deduplicates_hour_and_classifies_source_failures(tmp_path):
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    collection = {
        "observed": 10,
        "errors": {"x": "HTTP Error 401: Unauthorized"},
        "audit": {
            "x_korea_realtime": {"status": "unavailable", "detail": "token rejected"},
            "google_geo_kr": {"status": "observed", "detail": "geo=KR"},
        },
    }
    first = _collection_health(tmp_path, at, collection, at, at)
    second = _collection_health(tmp_path, at, collection, at, at)
    history = json.loads((tmp_path / "monitoring" / "run_history.json").read_text(encoding="utf-8"))
    assert len(history) == 1
    assert history[0]["contract_version"] == "trzip-v3-hourly"
    assert first["status"] == second["status"] == "collecting_baseline"
    assert second["source_failure_counts"]["x"]["api_authentication"] == 1
    assert second["remaining_runs_for_3d"] == 71
    assert second["source_targets_met"] == {"x": False, "google_trends": False}


def test_collection_health_preserves_first_scheduler_timing_on_manual_retry(tmp_path):
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    collection = {
        "observed": 100,
        "errors": {"x": "current_session_not_ready"},
        "audit": {
            "x_korea_realtime": {"status": "current_session_not_ready", "row_count": 0},
            "google_geo_kr": {"status": "observed", "row_count": 100},
        },
    }
    first = _collection_health(
        tmp_path, at, collection, at + timedelta(seconds=2), at + timedelta(seconds=10)
    )
    recovered_collection = {
        "observed": 130,
        "errors": {},
        "audit": {
            "x_korea_realtime": {"status": "observed", "row_count": 30},
            "google_geo_kr": {"status": "observed", "row_count": 100},
        },
    }
    second = _collection_health(
        tmp_path,
        at,
        recovered_collection,
        at + timedelta(minutes=20),
        at + timedelta(minutes=21),
    )

    assert first["latest_delay_seconds"] == second["latest_delay_seconds"] == 2
    assert second["recorded_runs"] == 1
    assert second["successful_runs"] == 0
    assert second["success_rate"] == 0.0
    assert first["current_publication_status"] == "scheduled_partial"
    assert first["current_publication_success"] is False
    assert second["current_publication_attempt_type"] == "recovery"
    assert second["current_publication_status"] == "recovered_complete"
    assert second["current_publication_success"] is True
    assert second["current_schedule_initial_attempt_success"] is False
    assert second["latest_scheduled_attempt_success"] is False
    assert second["recovered_from_scheduled_failure"] is True
    assert second["current_publication_source_success"] == {
        "x": True,
        "google_trends": True,
    }


def test_collection_health_complete_republication_does_not_claim_recovery(tmp_path):
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    collection = {
        "observed": 130,
        "errors": {},
        "audit": {
            "x_korea_realtime": {"status": "observed", "row_count": 30},
            "google_geo_kr": {"status": "observed", "row_count": 100},
        },
    }

    first = _collection_health(tmp_path, at, collection, at, at)
    second = _collection_health(
        tmp_path, at, collection, at + timedelta(minutes=5), at + timedelta(minutes=6)
    )

    assert first["current_publication_status"] == "scheduled_complete"
    assert second["current_publication_status"] == "republished_complete"
    assert second["current_schedule_initial_attempt_success"] is True
    assert second["latest_scheduled_attempt_success"] is True
    assert second["recovered_from_scheduled_failure"] is False
    assert second["recorded_runs"] == 1
    assert second["successful_runs"] == 1


def test_collection_health_drops_unversioned_legacy_success_rows(tmp_path):
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    monitoring = tmp_path / "monitoring"
    monitoring.mkdir()
    (monitoring / "run_history.json").write_text(
        json.dumps([{
            "scheduled_at": "2026-08-12T02:00:00+00:00",
            "success": True,
            "source_success": {"x": True, "google_trends": True},
        }]),
        encoding="utf-8",
    )
    collection = {
        "observed": 193,
        "errors": {"x": "current_session_not_ready"},
        "audit": {
            "x_korea_realtime": {"status": "current_session_not_ready", "row_count": 0},
            "google_geo_kr": {"status": "observed", "row_count": 193},
        },
    }

    health = _collection_health(tmp_path, at, collection, at, at)

    assert health["recorded_runs"] == 1
    assert health["successful_runs"] == 0
    assert health["source_success_rate"] == {"x": 0.0, "google_trends": 1.0}


def test_public_collection_and_monitoring_redact_local_paths_urls_and_credentials(tmp_path):
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    secret_detail = (
        r"XCollectionError: current_session_not_ready: X inbox does not exist: "
        r"C:\\Users\\person\\Desktop\\TRZIP\\x.json?token=super-secret"
    )
    collection = {
        "observed": 185,
        "observed_at": at.isoformat(),
        "rank_sources": ["x", "google_trends"],
        "errors": {"x": secret_detail},
        "audit": {
            "x_korea_realtime": {
                "status": "current_session_not_ready",
                "row_count": 0,
                "detail": secret_detail,
            },
            "google_geo_kr": {
                "status": "observed",
                "row_count": 185,
                "declared_total": 185,
                "page_count": 8,
                "completion_verified": True,
                "detail": "https://trends.google.com/trending?geo=KR&key=super-secret",
            },
        },
    }

    public = _sanitize_collection_for_public(collection)
    monitoring = tmp_path / "monitoring"
    monitoring.mkdir()
    (monitoring / "run_history.json").write_text(
        json.dumps([
            {
                "scheduled_at": "2026-08-12T02:00:00+00:00",
                "started_at": "2026-08-12T02:00:00+00:00",
                "finished_at": "2026-08-12T02:00:01+00:00",
                "delay_seconds": 0,
                "duration_seconds": 1,
                "success": False,
                "source_success": {"x": False, "google_trends": True},
                "observed_rows": 185,
                "errors": {"x": secret_detail},
                "source_failures": {
                    "x": {"class": "unknown", "detail": secret_detail}
                },
            }
        ]),
        encoding="utf-8",
    )
    health = _collection_health(tmp_path, at, collection, at, at)
    run_history = (tmp_path / "monitoring" / "run_history.json").read_text(encoding="utf-8")
    latest = (tmp_path / "monitoring" / "latest.json").read_text(encoding="utf-8")
    serialized = json.dumps({"collection": public, "health": health}) + run_history + latest

    assert public["errors"] == {"x": "current_session_not_ready"}
    assert public["audit"]["x_korea_realtime"]["detail"] == "current_session_not_ready"
    assert public["audit"]["google_geo_kr"]["detail"] == "verified_current_hour_snapshot"
    assert public["audit"]["google_geo_kr"]["declared_total"] == 185
    assert public["audit"]["google_geo_kr"]["page_count"] == 8
    assert public["audit"]["google_geo_kr"]["completion_verified"] is True
    assert "C:\\Users" not in serialized
    assert "https://" not in serialized
    assert "super-secret" not in serialized
    assert "token=" not in serialized


def test_codex_logged_in_chrome_provenance_is_not_relabelled_as_extension(
    tmp_path, monkeypatch
):
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    inbox = tmp_path / "x-current-session.json"
    inbox.write_text(
        json.dumps({
            "schema_version": 1,
            "source": "x",
            "collector": "codex_chrome_current_session",
            "url": "https://x.com/explore/tabs/trending",
            "region": "KR",
            "region_verified": True,
            "observed_at": at.isoformat(),
            "row_count": 30,
            "trends": [
                {"rank": index, "topic": f"term {index}"}
                for index in range(1, 31)
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("TRZIP_X_INBOX", str(inbox))
    collection = {
        "observed": 30,
        "observed_at": at.isoformat(),
        "errors": {},
        "audit": {
            "x_korea_realtime": {
                "status": "observed",
                "row_count": 30,
                "detail": "current logged-in Chrome extension",
            },
            "google_geo_kr": {"status": "unavailable", "row_count": 0},
        },
    }

    annotated = _annotate_x_collection_provenance(collection, at)
    public = _sanitize_collection_for_public(annotated)
    x_audit = public["audit"]["x_korea_realtime"]

    assert x_audit["collector"] == "codex_chrome_current_session"
    assert x_audit["transport"] == "codex_browser_snapshot"
    assert x_audit["profile"] == "current_logged_in_chrome"
    assert "extension" not in x_audit["detail"]


def test_pipeline_uses_preserved_same_hour_source_after_retry_failure(tmp_path, monkeypatch):
    at = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    stamp = at.isoformat()
    database = tmp_path / "runtime.sqlite3"
    from trzip.hourly_store import collect_current

    monkeypatch.setattr("trzip.publication_pipeline.floor_hour", lambda value: at)
    monkeypatch.setattr(
        "trzip.hourly_store.collect_google",
        lambda value: [HourlyObservation(stamp, "google_trends", "말복", 1, 100, "observed")],
    )
    monkeypatch.setattr(
        "trzip.hourly_store.collect_x",
        lambda value: [HourlyObservation(stamp, "x", "불꽃축제", 1, 100, "observed")],
    )
    collect_current(database, at)

    monkeypatch.setattr(
        "trzip.hourly_store.collect_x",
        lambda value: (_ for _ in ()).throw(RuntimeError("browser temporarily unavailable")),
    )
    monkeypatch.setattr(
        "trzip.publication_pipeline.pykrx_stock",
        lambda *args, **kwargs: {"status": "unavailable", "reason": "test"},
    )
    monkeypatch.setattr("trzip.publication_pipeline.verify_terms", lambda *args, **kwargs: [])
    result = run(tmp_path / "publication", database_path=database, now=at)

    assert result["collection"]["errors"] == {}
    assert result["collection"]["audit"]["x_korea_realtime"]["status"] == "observed"
    assert result["collection"]["audit"]["x_korea_realtime"]["detail"] == "verified_current_hour_snapshot"
    assert result["collection"]["observed"] == 2
    status = json.loads(
        (tmp_path / "publication" / "latest" / "status.json").read_text(encoding="utf-8")
    )
    assert status["partial"] is False


def test_failure_class_has_required_operational_buckets():
    assert _failure_class("429 quota exceeded") == "quota_or_rate_limit"
    assert _failure_class("TimeoutError") == "network"
    assert _failure_class("XML parser failed") == "parser_change"
    assert _failure_class("auth_required: login once") == "browser_authentication"
    assert _failure_class("region_unverified") == "region_configuration"
    assert _failure_class("selector_changed") == "browser_page_change"
