from __future__ import annotations

import hashlib
import json
from pathlib import Path

from trzip.demo_replay import default_asset_paths
from trzip.keyword_policy import keyword_fits_public_label
from trzip.reconstructed_workbook import import_workbook


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT / "data" / "reconstructed" / "trzip-final-50-20260814"
    / "source.xlsx"
)


def test_reviewed_workbook_import_is_deterministic_and_never_live_ranked(tmp_path):
    first = import_workbook(SOURCE, tmp_path / "first")
    second = import_workbook(SOURCE, tmp_path / "second")

    assert first["event_count"] == 50
    assert first["keyword_count"] == 250
    assert first["source_keyword_count"] == 250
    assert first["public_keyword_count"] < first["source_keyword_count"]
    assert first["company_link_count"] == 150
    assert first["frontend_ready_count"] == 0
    assert first["events_sha256"] == second["events_sha256"]
    assert first["live_eligible"] is False
    assert first["ranking_eligible"] is False
    assert first["ranking_effect"] == "none"


def test_reviewed_workbook_keeps_definition_and_disclaimer_separate(tmp_path):
    output = tmp_path / "imported"
    manifest = import_workbook(SOURCE, output)
    rows = [
        json.loads(line)
        for line in (output / manifest["events_path"]).read_text(encoding="utf-8").splitlines()
    ]

    assert len(rows) == 50
    assert all(set(row["period_presence"]) == {"1w", "1m", "3m"} for row in rows)
    assert all([window["label"] for window in row["attention_windows"]] == ["1주", "1개월", "3개월"] for row in rows)
    assert all("투자 조언" not in row["definition"] for row in rows)
    assert all(row["disclaimer"] for row in rows)
    assert all(len(row["source_related_keywords"]) == 5 for row in rows)
    assert all(
        keyword_fits_public_label(keyword["text"])
        for row in rows
        for keyword in row["related_keywords"]
    )
    assert any(len(row["related_keywords"]) < 5 for row in rows)
    assert all(row["ranking_effect"] == "none" for row in rows)
    assert all(row["frontend_readiness_status"] == "enrichment_pending" for row in rows)
    assert all(
        company["relationship_reason"]
        and company["connection_explanation"]
        and company["evidence_sources"]
        for row in rows
        for company in row["companies"]
    )
    assert not any(
        company["company_role_category"] == "industry_adjacent"
        for row in rows
        for company in row["companies"]
    )


def test_default_demo_asset_points_to_reviewed_non_live_catalog():
    path = default_asset_paths()["research_reconstruction_jsonl"]

    assert path is not None and Path(path).is_file()
    manifest = json.loads(
        (Path(path).parent / "manifest.json").read_text(encoding="utf-8")
    )
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == manifest["events_sha256"]
    assert manifest["data_mode"] == "reconstructed"
    assert manifest["live_eligible"] is False
