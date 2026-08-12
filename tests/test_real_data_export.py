from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from trzip.real_data_export import ExportInputs, build_real_data_export


def _current_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE hourly_observations (
          observed_at TEXT, source TEXT, topic TEXT, source_rank INTEGER,
          value REAL, provenance TEXT, seed_observed_at TEXT,
          source_payload_json TEXT, related_terms_json TEXT,
          collector_version TEXT
        );
        CREATE TABLE keyword_candidate_evidence (
          event_key TEXT, candidate_key TEXT, provider TEXT, title TEXT,
          url TEXT, published_at TEXT, observed_at TEXT
        );
        INSERT INTO hourly_observations VALUES
          ('2026-08-12T23:00:00+00:00','x','실제 X',1,100,'observed',NULL,NULL,NULL,'x_current_session_kr_v1'),
          ('2026-08-12T23:00:00+00:00','google_trends','실제 Google',1,100,'observed',NULL,'{}','["연관어"]','google_trending_now_kr_v1'),
          ('2026-08-01T00:00:00+00:00','x','합성 금지',1,100,'generated','2026-08-12T23:00:00+00:00',NULL,NULL,'trzip_v3');
        INSERT INTO keyword_candidate_evidence VALUES
          ('event:1','keyword:1','youtube','공개 영상','https://youtube.com/watch?v=1',
           '2026-08-12T00:00:00+00:00','2026-08-12T23:00:00+00:00');
        """
    )
    connection.commit()
    connection.close()


def test_export_excludes_generated_and_marks_only_current_collectors_rank_eligible(
    tmp_path: Path,
) -> None:
    database = tmp_path / "current.sqlite3"
    _current_db(database)
    output = tmp_path / "export"

    result = build_real_data_export(
        ExportInputs(current_db=database), output, create_zip=True
    )

    rows = [json.loads(line) for line in (output / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {row["topic"] for row in rows if row["record_type"] == "trend_observation"} == {
        "실제 X",
        "실제 Google",
    }
    assert all(row["provenance"] != "generated" for row in rows)
    assert sum(bool(row["live_rank_eligible"]) for row in rows) == 2
    assert result["zip_path"].exists()


def test_manifest_contains_no_absolute_paths_and_preserves_asset_hash(tmp_path: Path) -> None:
    database = tmp_path / "current.sqlite3"
    _current_db(database)
    output = tmp_path / "export"

    result = build_real_data_export(ExportInputs(current_db=database), output)
    manifest_text = (output / "manifest.json").read_text(encoding="utf-8")
    manifest = result["manifest"]

    assert str(tmp_path) not in manifest_text
    assert manifest["source_assets"][0]["source_asset_id"] == "current_runtime_sqlite"
    assert len(manifest["source_assets"][0]["sha256"]) == 64
    assert manifest["hard_exclusions"][:4] == [
        "generated",
        "synthetic",
        "fixture",
        "static_demo",
    ]


def test_reviewed_ontology_uses_base_node_catalog_for_company_names(tmp_path: Path) -> None:
    base = tmp_path / "base.json"
    overlay = tmp_path / "overlay.json"
    base.write_text(
        json.dumps(
            {
                "nodes": [
                    {"id": "company:1", "label": "회사 1", "type": "company"}
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    overlay.write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "metadata": {"reviewed_at": "2026-08-13"},
                "nodes": [{"id": "term:1", "label": "트렌드", "type": "term"}],
                "evidence": [
                    {
                        "id": "evidence:1",
                        "title": "공식 근거",
                        "publisher": "기업",
                        "url": "https://example.com/fact",
                        "review_status": "approved",
                    }
                ],
                "edges": [
                    {
                        "id": "edge:1",
                        "from_node": "term:1",
                        "to_node": "company:1",
                        "relation_type": "related_to",
                        "evidence_ids": ["evidence:1"],
                        "review_status": "approved",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output = tmp_path / "export"
    build_real_data_export(
        ExportInputs(ontology_files=(base, overlay)), output, create_zip=False
    )
    rows = [json.loads(line) for line in (output / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    edge = next(row for row in rows if row["record_type"] == "ontology_edge")
    assert edge["topic"] == "트렌드"
    assert edge["query"] == "회사 1"
