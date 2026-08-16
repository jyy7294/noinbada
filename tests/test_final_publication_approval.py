from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import json

import pytest

from trzip.final_publication_approval import (
    build_final_publication_review,
    verify_approval,
    write_approval,
)


OBSERVED_AT = "2026-08-16T00:00:00+00:00"


def _intelligence() -> dict:
    ready_checks = {
        "main_lane": True,
        "observed_within_24h": True,
        "context_ready": True,
        "related_keywords_exactly_five": True,
        "evidence_backed_listed_companies_at_least_ten": True,
        "company_role_categories_between_three_and_four": True,
        "related_keywords_linked_to_companies_at_least_two": True,
    }
    blocked_checks = {**ready_checks, "context_ready": False}
    return {
        "window": {"to": OBSERVED_AT},
        "unified_ranking": [
            {
                "event_key": "ready-event",
                "display_name": "승인 가능",
                "rank": 2,
                "main_rank": 1,
                "score": 80,
                "lane": "main",
                "category_label": "문화",
                "home_eligible": True,
                "trend_fit": {"selection": "main"},
                "series": [{
                    "at": OBSERVED_AT,
                    "source": "google_trends",
                    "rank": 10,
                    "provenance": "observed",
                }],
            },
            {
                "event_key": "blocked-event",
                "display_name": "보강 필요",
                "rank": 1,
                "score": 90,
                "lane": "review",
                "category_label": "검토",
                "trend_fit": {"hard_issue": True},
                "series": [{
                    "at": OBSERVED_AT,
                    "source": "x",
                    "rank": 3,
                    "provenance": "observed",
                }],
            },
        ],
        "processing_cycle": {
            "complete_card_gates": {
                "ready-event": {
                    "ready": True,
                    "checks": ready_checks,
                    "missing": [],
                    "projected_company_count": 10,
                    "role_category_count": 3,
                    "valid_keyword_company_link_count": 10,
                },
                "blocked-event": {
                    "ready": False,
                    "checks": blocked_checks,
                    "missing": ["context_ready"],
                    "projected_company_count": 0,
                    "role_category_count": 0,
                    "valid_keyword_company_link_count": 0,
                },
            }
        },
    }


def test_review_is_deterministic_and_exposes_every_filter_result():
    review = build_final_publication_review(_intelligence())

    assert review == build_final_publication_review(_intelligence())
    assert review["candidate_count"] == 2
    assert review["automatic_filter_passed_count"] == 1
    assert [row["event_key"] for row in review["candidates"]] == [
        "ready-event",
        "blocked-event",
    ]
    assert review["candidates"][0]["manual_approval_eligible"] is True
    assert set(review["candidates"][1]["missing"]) == {
        "recognized_concrete_trend",
        "not_hard_issue",
    }
    assert review["candidates"][0]["enrichment_ready"] is True


def test_named_trend_is_approval_eligible_while_company_enrichment_is_pending():
    intelligence = _intelligence()
    intelligence["unified_ranking"][0].update({
        "display_name": "둠스데이",
        "lane": "review",
        "trend_fit": {"selection": "main", "reviewed_named_trend": True},
        "companies": [],
        "related_keywords": [],
    })
    intelligence["processing_cycle"]["complete_card_gates"]["ready-event"] = {
        "ready": False,
        "checks": {},
        "missing": ["exactly_five_public_keywords", "at_least_ten_evidence_backed_companies"],
        "projected_company_count": 0,
    }

    row = next(
        candidate
        for candidate in build_final_publication_review(intelligence)["candidates"]
        if candidate["event_key"] == "ready-event"
    )

    assert row["display_name"] == "둠스데이"
    assert row["automatic_filter_passed"] is True
    assert row["manual_approval_eligible"] is True
    assert row["enrichment_ready"] is False
    assert "at_least_ten_evidence_backed_companies" in row["enrichment_missing"]


def test_unknown_unclassified_word_stays_visible_for_owner_review_without_being_recommended():
    intelligence = _intelligence()
    intelligence["unified_ranking"][0].update({
        "display_name": "수건",
        "lane": "review",
        "trend_fit": {"selection": "review"},
    })

    row = next(
        candidate
        for candidate in build_final_publication_review(intelligence)["candidates"]
        if candidate["event_key"] == "ready-event"
    )

    assert row["automatic_filter_passed"] is False
    assert row["manual_approval_eligible"] is True
    assert row["review_tier"] == "owner_review"
    assert "recognized_concrete_trend" in row["missing"]


def test_full_ledger_review_keeps_an_older_observed_named_trend_without_enrichment():
    intelligence = _intelligence()
    item = intelligence["unified_ranking"][0]
    item.update({
        "display_name": "말복",
        "lane": "review",
        "trend_fit": {"selection": "main"},
        "series": [{
            "at": "2026-08-12T02:00:00+00:00",
            "source": "google_trends",
            "rank": 1,
            "provenance": "observed",
        }],
        "companies": [],
        "related_keywords": [],
    })
    intelligence["full_ledger_demo_ranking"] = {
        "formula_version": "peak25_mean40_persistence20_breadth15_v1",
        "window": {
            "from": "2026-08-12T02:00:00+00:00",
            "to": "2026-08-16T00:00:00+00:00",
        },
        "ranking": [{
            "event_key": "ready-event",
            "rank": 6,
            "score": 79.11,
            "observed_hour_count": 13,
        }],
    }
    intelligence["processing_cycle"]["complete_card_gates"]["ready-event"] = {
        "ready": False,
        "checks": {},
        "missing": ["exactly_five_public_keywords", "at_least_ten_evidence_backed_companies"],
        "projected_company_count": 0,
    }

    row = next(
        candidate
        for candidate in build_final_publication_review(intelligence)["candidates"]
        if candidate["event_key"] == "ready-event"
    )

    assert row["review_ranking_mode"] == "full_ledger_demo_no_recency"
    assert row["review_rank"] == 6
    assert row["review_score"] == 79.11
    assert row["automatic_filter_passed"] is True
    assert row["manual_approval_eligible"] is True
    assert row["enrichment_ready"] is False


def test_only_highest_ranked_fixture_is_recommended_but_owner_can_choose_another():
    intelligence = _intelligence()
    football = intelligence["unified_ranking"][0]
    football.update({
        "event_key": "football-first",
        "display_name": "밀란 대 맨유",
        "rank": 5,
        "lane": "main",
        "category": "sports_participation",
        "trend_fit": {"selection": "main", "plain_sports_fixture": True},
    })
    second = deepcopy(football)
    second.update({
        "event_key": "football-second",
        "display_name": "수원 대 수원FC",
        "rank": 13,
    })
    intelligence["unified_ranking"].insert(1, second)
    intelligence["processing_cycle"]["complete_card_gates"]["football-first"] = (
        intelligence["processing_cycle"]["complete_card_gates"].pop("ready-event")
    )
    intelligence["processing_cycle"]["complete_card_gates"]["football-second"] = {
        "ready": False,
        "checks": {},
        "missing": ["company_enrichment_pending"],
        "projected_company_count": 0,
    }

    review = build_final_publication_review(intelligence)
    by_key = {row["event_key"]: row for row in review["candidates"]}

    assert by_key["football-first"]["manual_approval_eligible"] is True
    assert by_key["football-first"]["sports_slot_selected"] is True
    assert by_key["football-second"]["automatic_filter_passed"] is False
    assert by_key["football-second"]["manual_approval_eligible"] is True
    assert by_key["football-second"]["superseded_by_event_key"] == "football-first"
    assert "one_fixture_per_sports_discipline" in by_key["football-second"]["missing"]


def test_approval_rejects_two_fixtures_from_the_same_sport(tmp_path):
    intelligence = _intelligence()
    football = intelligence["unified_ranking"][0]
    football.update({
        "event_key": "football-first",
        "display_name": "밀란 대 맨유",
        "rank": 5,
        "lane": "main",
        "category": "sports_participation",
        "trend_fit": {"selection": "main", "plain_sports_fixture": True},
    })
    second = deepcopy(football)
    second.update({"event_key": "football-second", "display_name": "수원 대 수원FC", "rank": 13})
    intelligence["unified_ranking"].insert(1, second)
    gate = intelligence["processing_cycle"]["complete_card_gates"].pop("ready-event")
    intelligence["processing_cycle"]["complete_card_gates"]["football-first"] = gate
    intelligence["processing_cycle"]["complete_card_gates"]["football-second"] = gate
    review = build_final_publication_review(intelligence)

    with pytest.raises(ValueError, match="one fixture per sports discipline"):
        write_approval(
            review,
            approval_root=tmp_path,
            approved_event_keys=["football-first", "football-second"],
            approved_by="이찬희",
        )


def test_overseas_fixture_needs_strong_korean_source_salience():
    intelligence = _intelligence()
    row = intelligence["unified_ranking"][0]
    row.update({
        "display_name": "인도 대 스리랑카",
        "lane": "main",
        "category": "sports_participation",
        "trend_fit": {"selection": "main", "plain_sports_fixture": True},
    })
    row["series"][0]["rank"] = 104

    filtered = next(
        item for item in build_final_publication_review(intelligence)["candidates"]
        if item["event_key"] == "ready-event"
    )

    assert filtered["sports_discipline"] == "cricket"
    assert filtered["sports_korean_interest"] is False
    assert filtered["manual_approval_eligible"] is False
    assert "korean_product_sports_interest" in filtered["missing"]

    row["display_name"] = "밀란 대 맨유"
    row["series"][0]["rank"] = 1
    retained = next(
        item for item in build_final_publication_review(intelligence)["candidates"]
        if item["event_key"] == "ready-event"
    )
    assert retained["sports_discipline"] == "football"
    assert retained["sports_korean_interest"] is True
    assert retained["manual_approval_eligible"] is True


def test_liberation_day_aliases_collapse_to_one_top_ranked_review_candidate():
    intelligence = _intelligence()
    first = intelligence["unified_ranking"][0]
    first.update({
        "event_key": "independence-activist",
        "display_name": "독립운동가",
        "rank": 1,
        "lane": "review",
        "trend_fit": {"selection": "review"},
    })
    alias = deepcopy(first)
    alias.update({
        "event_key": "liberation-hashtag",
        "display_name": "#광복절",
        "rank": 20,
    })
    intelligence["unified_ranking"].insert(1, alias)
    gate = intelligence["processing_cycle"]["complete_card_gates"].pop("ready-event")
    intelligence["processing_cycle"]["complete_card_gates"]["independence-activist"] = gate
    intelligence["processing_cycle"]["complete_card_gates"]["liberation-hashtag"] = gate

    review = build_final_publication_review(intelligence)
    by_key = {row["event_key"]: row for row in review["candidates"]}

    assert by_key["independence-activist"]["display_name"] == "광복절·독립운동가"
    assert by_key["independence-activist"]["manual_approval_eligible"] is True
    assert by_key["liberation-hashtag"]["manual_approval_eligible"] is False
    assert "one_candidate_per_normalized_trend_group" in by_key["liberation-hashtag"]["missing"]


def test_only_an_exact_eligible_review_can_receive_final_approval(tmp_path):
    review = build_final_publication_review(_intelligence())
    approval_root = tmp_path / "approvals"
    write_approval(
        review,
        approval_root=approval_root,
        approved_event_keys=["ready-event"],
        approved_by="이찬희",
        approved_at=datetime(2026, 8, 16, 1, tzinfo=UTC),
    )

    verified = verify_approval(review, approval_root=approval_root)
    assert verified["verified"] is True
    assert verified["approved_event_keys"] == ["ready-event"]
    assert verified["approved_by"] == "이찬희"

    with pytest.raises(ValueError, match="owner-review safety filters"):
        write_approval(
            review,
            approval_root=approval_root,
            approved_event_keys=["blocked-event"],
            approved_by="이찬희",
        )


def test_review_or_receipt_tampering_fails_closed(tmp_path):
    review = build_final_publication_review(_intelligence())
    approval_root = tmp_path / "approvals"
    path = write_approval(
        review,
        approval_root=approval_root,
        approved_event_keys=["ready-event"],
        approved_by="이찬희",
    )

    tampered_review = deepcopy(review)
    tampered_review["candidate_count"] = 999
    assert verify_approval(tampered_review, approval_root=approval_root)["status"] == "invalid_final_review"
    with pytest.raises(ValueError, match="review hash"):
        write_approval(
            tampered_review,
            approval_root=approval_root,
            approved_event_keys=[],
            approved_by="이찬희",
        )

    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["approved_event_keys"] = ["blocked-event"]
    path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
    assert verify_approval(review, approval_root=approval_root)["verified"] is False
