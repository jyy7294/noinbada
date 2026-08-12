import sqlite3
from datetime import UTC, datetime

from trzip.keyword_candidates import (
    extract_review_candidates,
    sync_provider_keyword_candidates,
)
from trzip.provider_verification import initialize_verification_ledger


def _seed_provider_title(path, *, title: str, url: str, provider: str = "youtube"):
    initialize_verification_ledger(path)
    with sqlite3.connect(path) as connection:
        cursor = connection.execute(
            """INSERT INTO provider_verification_runs
               (observed_at,trend_key,representative_term,provider,status,matched,
                endpoint,attempt_count,error_code,error_detail,metrics_json,
                provenance_json,ranking_effect,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "2026-08-12T12:00:00+00:00", "두쫀쿠", "두쫀쿠", provider,
                "observed", 1, None, 0, None, None, "{}", "{}", "none",
                "2026-08-12T12:00:01+00:00",
            ),
        )
        connection.execute(
            """INSERT INTO provider_evidence_items
               (run_id,item_order,item_type,provider_item_id,title,url,published_at,
                publisher,metrics_json,provenance_json)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                int(cursor.lastrowid), 1, "video", url.rsplit("/", 1)[-1], title,
                url, "2026-08-12", "채널", "{}", "{}",
            ),
        )


def _intelligence():
    return {
        "unified_ranking": [{
            "rank": 1,
            "event_key": "두쫀쿠",
            "display_name": "두쫀쿠",
            "raw_terms": ["두쫀쿠"],
            "keywords": [],
        }]
    }


def test_extractor_keeps_explicit_hashtag_and_alias_behavior_only():
    result = extract_review_candidates(
        "#두쫀쿠맛집 두쫀쿠 먹방과 무관한 일반 문장",
        ["두쫀쿠"],
    )

    assert result == ["두쫀쿠맛집", "두쫀쿠 먹방"]


def test_provider_candidates_are_persistent_review_only_and_idempotent(tmp_path):
    target = tmp_path / "candidates.sqlite3"
    _seed_provider_title(
        target,
        title="#두쫀쿠맛집 두쫀쿠 먹방 후기",
        url="https://www.youtube.com/watch?v=one",
    )
    _seed_provider_title(
        target,
        title="두쫀쿠 먹방과 #두쫀쿠맛집 솔직 리뷰",
        url="https://www.youtube.com/watch?v=two",
    )
    at = datetime(2026, 8, 12, 12, tzinfo=UTC)

    first = sync_provider_keyword_candidates(_intelligence(), path=target, at=at)
    second = sync_provider_keyword_candidates(_intelligence(), path=target, at=at)
    later = sync_provider_keyword_candidates(
        _intelligence(),
        path=target,
        at=datetime(2026, 8, 12, 13, tzinfo=UTC),
    )

    assert first == second
    assert first["pending_total"] == 2
    assert first["building_total"] == 0
    assert {item["display_text"] for item in first["pending"]} == {
        "두쫀쿠맛집", "두쫀쿠 먹방",
    }
    assert all(item["publishable"] is False for item in first["pending"])
    assert all(item["affects_score"] is False for item in first["pending"])
    assert {item["last_seen_at"] for item in later["pending"]} == {
        "2026-08-12T12:00:00+00:00"
    }
    with sqlite3.connect(target) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM keyword_candidate_evidence"
        ).fetchone()[0] == 4


def test_unrelated_search_result_and_single_document_do_not_enter_review_queue(tmp_path):
    target = tmp_path / "noise.sqlite3"
    _seed_provider_title(
        target,
        title="#무관키워드 검색 결과 노이즈",
        url="https://www.youtube.com/watch?v=noise",
    )
    _seed_provider_title(
        target,
        title="두쫀쿠 #단일후보",
        url="https://www.youtube.com/watch?v=single",
    )

    result = sync_provider_keyword_candidates(
        _intelligence(),
        path=target,
        at=datetime(2026, 8, 12, 12, tzinfo=UTC),
    )

    assert result["pending_total"] == 0
    assert result["building_total"] == 1
    assert result["pending"] == []
