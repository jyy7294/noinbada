import json
from collections import Counter
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "research-reconstructed-60d"


def _rows():
    return [
        json.loads(line)
        for line in (DATA / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_reconstructed_seed_manifest_matches_rows():
    rows = _rows()
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))

    assert len(rows) == manifest["event_count"]
    assert Counter(row["category"] for row in rows) == manifest["category_counts"]
    assert len({row["event_id"] for row in rows}) == len(rows)
    assert len({row["representative_term"] for row in rows}) == len(rows)


def test_reconstructed_rows_are_evidence_backed_and_not_measured():
    start = date.fromisoformat("2026-06-01")
    end = date.fromisoformat("2026-07-31")

    for row in _rows():
        assert row["schema_version"] == "trzip-reconstructed-event-v1"
        assert row["provenance"] == "research_reconstructed"
        assert row["measurement_status"] == "event_timing_evidence_only"
        assert row["rank_eligible"] is False
        assert 0.0 <= row["confidence"] <= 1.0
        assert 1 <= len(row["representative_term"]) <= 40
        assert 1 <= len(row["aliases"]) <= 5
        assert len({alias.casefold() for alias in row["aliases"]}) == len(row["aliases"])
        assert row["evidence"]
        assert all(item["url"].startswith("https://") for item in row["evidence"])
        assert all(item["publisher"] and item["evidence_type"] for item in row["evidence"])
        assert all(item["claim"] for item in row["evidence"])
        assert all(date.fromisoformat(item["published_at"]) for item in row["evidence"])
        assert len({item["url"] for item in row["evidence"]}) == len(row["evidence"])
        active_from = date.fromisoformat(row["active_from"])
        active_to = date.fromisoformat(row["active_to"])
        peak = date.fromisoformat(row["peak_hint"])
        assert active_from <= peak <= active_to
        assert active_from <= end and active_to >= start
        assert not ({"search_volume", "platform_rank", "attention_index"} & row.keys())


def test_reconstructed_seed_has_product_scope_and_time_coverage():
    rows = _rows()
    categories = {row["category"] for row in rows}

    assert {"소비", "문화·생활", "콘텐츠", "음식·식품", "게임", "스포츠", "K-pop", "주식·기업"} <= categories
    assert any(row["active_from"].startswith("2026-06") for row in rows)
    assert any(row["active_from"].startswith("2026-07") for row in rows)
    assert not any("synthetic" in json.dumps(row, ensure_ascii=False).casefold() for row in rows)
