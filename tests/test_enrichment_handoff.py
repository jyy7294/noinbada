from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from trzip.enrichment_handoff import (
    export_candidate_batch,
    import_reviewed_batch,
    review_template,
    run_handoff,
)
from trzip.publication_pipeline import _daily_review_cutoff


AT = datetime(2026, 8, 15, 4, tzinfo=UTC)


def _candidate(index: int, *, lane: str = "review", ready: bool = False) -> dict:
    return {
        "event_key": f"event-{index}",
        "display_name": f"후보 {index}",
        "lane": lane,
        "broad_category": "other",
        "observed_rank": index,
        "rank": index,
        "score": 100 - index,
        "latest_source_ranks": {"x": index},
        "raw_terms": [f"후보 {index}"],
        "series": [{
            "at": AT.isoformat(), "source": "x", "rank": index,
            "value": 100 - index, "provenance": "observed",
        }],
        "frontend_readiness_status": "ready" if ready else "enrichment_pending",
        "frontend_readiness_missing": [] if ready else ["trigger_evidence_incomplete"],
    }


def test_handoff_exports_only_top_twelve_incomplete_non_issue_candidates(tmp_path):
    intelligence = {
        "unified_ranking": [
            _candidate(0, lane="issue"),
            _candidate(1, ready=True),
            *[_candidate(index) for index in range(2, 30)],
        ]
    }

    result = run_handoff(
        intelligence, handoff_root=tmp_path / "handoff", at=AT, enabled=True
    )
    batch = json.loads(
        (tmp_path / "handoff" / "pending" / f"{result['batch_id']}.json").read_text(
            encoding="utf-8"
        )
    )

    assert result["status"] == "exported_waiting_review"
    assert len(batch["candidates"]) == 12
    assert [row["event_key"] for row in batch["candidates"]] == [
        f"event-{index}" for index in range(2, 14)
    ]
    assert "observed_rank" in batch["candidates"][0]
    assert "observed_rank" in batch["prohibited_authority"]


def test_handoff_prioritizes_actionable_main_candidates_without_changing_rank(tmp_path):
    review_item = _candidate(2)
    main_item = _candidate(20, lane="main")
    main_item["broad_category"] = "food"
    intelligence = {"unified_ranking": [review_item, main_item]}

    batch, _ = export_candidate_batch(
        intelligence, handoff_root=tmp_path / "handoff", at=AT, limit=2
    )

    assert [row["event_key"] for row in batch["candidates"]] == [
        "event-20", "event-2",
    ]
    assert batch["candidates"][0]["observed_rank"] == 20
    assert batch["candidates"][0]["score"] == 80


def test_review_import_cannot_change_rank_or_score(tmp_path):
    intelligence = {"unified_ranking": [_candidate(2)]}
    batch, _ = export_candidate_batch(
        intelligence, handoff_root=tmp_path / "handoff", at=AT
    )
    review = review_template(batch)
    review["decisions"] = [{"event_key": "event-2", "score": 999}]
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")

    with pytest.raises(ValueError, match="cannot alter ranking fields"):
        import_reviewed_batch(
            intelligence, batch=batch, review_path=review_path
        )


def test_valid_review_changes_semantics_only_and_preserves_observations(tmp_path):
    intelligence = {"unified_ranking": [_candidate(2)]}
    batch, _ = export_candidate_batch(
        intelligence, handoff_root=tmp_path / "handoff", at=AT
    )
    review = review_template(batch)
    review["decisions"] = [{
        "event_key": "event-2",
        "lane": "main",
        "broad_category": "consumer",
        "context_research": {
            "status": "ready",
            "trigger_title": "후보 2 공개 행사",
            "why_now": "공식 행사가 공개됐습니다.",
            "evidence_urls": ["https://example.com/event-2"],
        },
    }]
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    before = (
        intelligence["unified_ranking"][0]["observed_rank"],
        intelligence["unified_ranking"][0]["score"],
        list(intelligence["unified_ranking"][0]["series"]),
    )

    result = import_reviewed_batch(
        intelligence, batch=batch, review_path=review_path
    )
    item = intelligence["unified_ranking"][0]

    assert result["status"] == "reviewed_imported"
    assert item["lane"] == "main"
    assert item["broad_category"] == "consumer"
    assert (item["observed_rank"], item["score"], item["series"]) == before
    assert item["llm_review_handoff"]["ranking_effect"] == "none"


def test_run_handoff_rejects_invalid_review_without_losing_hourly_candidates(tmp_path):
    intelligence = {"unified_ranking": [_candidate(2)]}
    batch, _ = export_candidate_batch(
        intelligence, handoff_root=tmp_path / "handoff", at=AT
    )
    reviewed = tmp_path / "handoff" / "reviewed" / f"{batch['batch_id']}.json"
    reviewed.parent.mkdir(parents=True)
    reviewed.write_text('{"invalid": true}', encoding="utf-8")

    before = json.loads(json.dumps(intelligence))
    result = run_handoff(
        intelligence, handoff_root=tmp_path / "handoff", at=AT, enabled=True
    )

    assert result["status"] == "reviewed_rejected"
    assert result["error_code"] == "reviewed_enrichment_validation_failed"
    assert intelligence == before


def test_next_checkpoint_imports_latest_unconsumed_review_once(tmp_path):
    handoff_root = tmp_path / "handoff"
    first = {"unified_ranking": [_candidate(2)]}
    exported = run_handoff(
        first, handoff_root=handoff_root, at=AT, enabled=True
    )
    batch = json.loads(
        (handoff_root / "pending" / f"{exported['batch_id']}.json").read_text(
            encoding="utf-8"
        )
    )
    review = review_template(batch)
    review["decisions"] = [{
        "event_key": "event-2",
        "lane": "main",
        "broad_category": "consumer",
        "context_research": {
            "status": "ready",
            "trigger_title": "후보 2 공개 행사",
            "why_now": "공식 행사가 공개됐습니다.",
            "evidence_urls": ["https://example.com/event-2"],
        },
    }]
    reviewed_path = handoff_root / "reviewed" / f"{batch['batch_id']}.json"
    reviewed_path.parent.mkdir(parents=True)
    reviewed_path.write_text(json.dumps(review), encoding="utf-8")

    current_item = _candidate(2)
    current_item["observed_rank"] = 7
    current_item["rank"] = 7
    current_item["score"] = 42
    second = {"unified_ranking": [current_item, _candidate(3)]}
    imported = run_handoff(
        second, handoff_root=handoff_root, at=AT + timedelta(hours=4), enabled=True
    )

    assert imported["status"] == "reviewed_imported_previous"
    assert imported["imported_batch_id"] == batch["batch_id"]
    assert current_item["lane"] == "main"
    assert (current_item["observed_rank"], current_item["rank"], current_item["score"]) == (
        7, 7, 42,
    )
    receipt = handoff_root / "receipts" / f"{batch['batch_id']}.json"
    assert json.loads(receipt.read_text(encoding="utf-8"))["status"] == "consumed"

    rebuilt_item = _candidate(2)
    rebuilt_item["observed_rank"] = 9
    rebuilt = {"unified_ranking": [rebuilt_item]}
    deferred = run_handoff(
        rebuilt,
        handoff_root=handoff_root,
        at=AT + timedelta(hours=5),
        enabled=False,
    )
    assert deferred["status"] == "deferred_to_enrichment_checkpoint"
    assert deferred["approved_cache"]["reapplied_count"] == 1
    assert rebuilt_item["lane"] == "main"
    assert rebuilt_item["context_research"]["status"] == "ready"
    assert rebuilt_item["observed_rank"] == 9

    third = run_handoff(
        second, handoff_root=handoff_root, at=AT + timedelta(hours=8), enabled=True
    )
    assert third["status"] == "exported_waiting_review"
    assert third["imported_batch_id"] is None


def test_daily_cutoff_defers_late_review_without_deleting_queue(tmp_path):
    handoff_root = tmp_path / "handoff"
    first = {"unified_ranking": [_candidate(2)]}
    exported = run_handoff(
        first, handoff_root=handoff_root, at=AT, enabled=True
    )
    batch_path = handoff_root / "pending" / f"{exported['batch_id']}.json"
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    cutoff = AT + timedelta(hours=1)
    review = review_template(batch)
    review["reviewed_at"] = (cutoff + timedelta(minutes=1)).isoformat()
    review["decisions"] = [{
        "event_key": "event-2",
        "lane": "main",
        "broad_category": "consumer",
        "context_research": {
            "status": "ready",
            "trigger_title": "Documented event",
            "why_now": "An official page documents the event.",
            "evidence_urls": ["https://example.com/event-2"],
        },
    }]
    review_path = handoff_root / "reviewed" / f"{batch['batch_id']}.json"
    review_path.parent.mkdir(parents=True)
    review_path.write_text(json.dumps(review), encoding="utf-8")
    late_timestamp = (cutoff + timedelta(minutes=2)).timestamp()
    os.utime(review_path, (late_timestamp, late_timestamp))

    current = {"unified_ranking": [_candidate(2), _candidate(3)]}
    frozen = run_handoff(
        current,
        handoff_root=handoff_root,
        at=AT + timedelta(hours=4),
        enabled=True,
        review_cutoff_at=cutoff,
    )

    assert frozen["status"] == "exported_waiting_review"
    assert frozen["deferred_after_cutoff_count"] == 1
    assert not (handoff_root / "receipts" / f"{batch['batch_id']}.json").exists()
    assert current["unified_ranking"][0]["lane"] == "review"

    next_checkpoint = run_handoff(
        current,
        handoff_root=handoff_root,
        at=AT + timedelta(hours=8),
        enabled=True,
    )
    assert next_checkpoint["status"] == "reviewed_imported_previous"
    assert current["unified_ranking"][0]["lane"] == "main"


def test_0445_cutoff_blocks_late_review_and_late_approved_cache_until_next_checkpoint(
    tmp_path,
):
    handoff_root = tmp_path / "handoff"
    checkpoint_at = datetime(2026, 8, 15, 19, tzinfo=UTC)  # 04:00 KST
    cutoff = checkpoint_at + timedelta(minutes=45)
    late_at = cutoff + timedelta(minutes=5)
    publish_at = checkpoint_at + timedelta(hours=2)  # 06:00 KST

    assert _daily_review_cutoff(
        checkpoint_at, daily_publish_hour_kst=6
    ) == cutoff
    assert _daily_review_cutoff(late_at, daily_publish_hour_kst=6) == cutoff
    assert _daily_review_cutoff(
        publish_at, daily_publish_hour_kst=6
    ) == cutoff

    first = {"unified_ranking": [_candidate(2)]}
    exported = run_handoff(
        first,
        handoff_root=handoff_root,
        at=checkpoint_at,
        enabled=True,
        review_cutoff_at=cutoff,
    )
    batch = json.loads(
        (handoff_root / "pending" / f"{exported['batch_id']}.json").read_text(
            encoding="utf-8"
        )
    )
    review = review_template(batch)
    review["reviewed_at"] = late_at.isoformat()
    review["decisions"] = [{
        "event_key": "event-2",
        "lane": "main",
        "broad_category": "consumer",
        "context_research": {
            "status": "ready",
            "trigger_title": "Late documented event",
            "why_now": "A public page documents the event after cutoff.",
            "evidence_urls": ["https://example.com/event-2"],
        },
    }]
    review_path = handoff_root / "reviewed" / f"{batch['batch_id']}.json"
    review_path.parent.mkdir(parents=True)
    review_path.write_text(json.dumps(review), encoding="utf-8")
    os.utime(review_path, (late_at.timestamp(), late_at.timestamp()))

    frozen_item = _candidate(2)
    frozen_ranking = (
        frozen_item["observed_rank"], frozen_item["rank"], frozen_item["score"]
    )
    frozen = run_handoff(
        {"unified_ranking": [frozen_item]},
        handoff_root=handoff_root,
        at=late_at,
        enabled=True,
        review_cutoff_at=_daily_review_cutoff(
            late_at, daily_publish_hour_kst=6
        ),
    )
    assert frozen["status"] == "exported_waiting_review"
    assert frozen["deferred_after_cutoff_count"] == 1
    assert frozen_item["lane"] == "review"
    assert (
        frozen_item["observed_rank"], frozen_item["rank"], frozen_item["score"]
    ) == frozen_ranking
    assert not (handoff_root / "receipts" / f"{batch['batch_id']}.json").exists()

    # Model the pre-fix state in which the same late review had already been
    # consumed into the approved cache.  The 06:00 defense must still reject it.
    legacy_item = _candidate(2)
    legacy_import = run_handoff(
        {"unified_ranking": [legacy_item]},
        handoff_root=handoff_root,
        at=late_at,
        enabled=True,
        review_cutoff_at=None,
    )
    assert legacy_import["status"] == "reviewed_imported"
    assert legacy_item["lane"] == "main"
    receipt_path = handoff_root / "receipts" / f"{batch['batch_id']}.json"
    receipt_before_publish = receipt_path.read_bytes()

    publish_item = _candidate(2)
    publish_ranking = (
        publish_item["observed_rank"], publish_item["rank"], publish_item["score"]
    )
    publish = run_handoff(
        {"unified_ranking": [publish_item]},
        handoff_root=handoff_root,
        at=publish_at,
        enabled=True,
        review_cutoff_at=_daily_review_cutoff(
            publish_at, daily_publish_hour_kst=6
        ),
    )
    assert publish["approved_cache"]["reapplied_count"] == 0
    assert publish["approved_cache"]["deferred_after_cutoff_count"] == 1
    assert publish_item["lane"] == "review"
    assert (
        publish_item["observed_rank"], publish_item["rank"], publish_item["score"]
    ) == publish_ranking
    assert receipt_path.read_bytes() == receipt_before_publish

    next_item = _candidate(2)
    next_checkpoint = run_handoff(
        {"unified_ranking": [next_item]},
        handoff_root=handoff_root,
        at=checkpoint_at + timedelta(hours=4),  # 08:00 KST
        enabled=True,
        review_cutoff_at=None,
    )
    assert next_checkpoint["approved_cache"]["reapplied_count"] == 1
    assert next_item["lane"] == "main"
