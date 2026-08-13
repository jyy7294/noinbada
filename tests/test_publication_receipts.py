from datetime import UTC, datetime
from pathlib import Path

from trzip.result_quality import _publication_receipt, record_publication_receipt


def test_remote_publication_receipt_is_required_and_persisted(tmp_path: Path):
    database = tmp_path / "runtime.sqlite3"
    stamp = "2026-08-13T16:00:00+00:00"

    assert _publication_receipt(database, stamp)["passed"] is False

    record_publication_receipt(
        database,
        observed_at=stamp,
        publication_id="pub-example",
        remote_sha="a" * 40,
        contract={"passed": True, "trends": [{"display_name": "당시 결과"}]},
        source_gate={"passed": True, "sources": {"x": {"row_count": 30}}},
    )

    receipt = _publication_receipt(database, stamp)
    assert receipt["passed"] is True
    assert receipt["publication_id"] == "pub-example"
    assert receipt["remote_sha"] == "a" * 40
    assert receipt["contract"]["trends"][0]["display_name"] == "당시 결과"
    assert receipt["source_gate"]["sources"]["x"]["row_count"] == 30


def test_legacy_receipt_without_contract_cannot_pass(tmp_path: Path):
    database = tmp_path / "legacy.sqlite3"
    connection = __import__("sqlite3").connect(database)
    connection.execute(
        "CREATE TABLE publication_receipts (observed_at TEXT PRIMARY KEY, "
        "publication_id TEXT NOT NULL, remote_sha TEXT NOT NULL, verified_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO publication_receipts VALUES (?, ?, ?, ?)",
        ("2026-08-13T15:00:00+00:00", "pub-old", "b" * 40, "2026-08-13T15:01:00+00:00"),
    )
    connection.commit()
    connection.close()

    receipt = _publication_receipt(database, "2026-08-13T15:00:00+00:00")
    assert receipt["passed"] is False
    assert receipt["contract"] is None


def test_receipt_is_immutable_for_the_same_hour(tmp_path: Path):
    database = tmp_path / "immutable.sqlite3"
    kwargs = {
        "observed_at": "2026-08-13T16:00:00+00:00",
        "publication_id": "pub-first",
        "remote_sha": "a" * 40,
        "contract": {"passed": True},
        "source_gate": {"passed": True},
    }
    record_publication_receipt(database, **kwargs)
    record_publication_receipt(database, **kwargs)

    import pytest
    with pytest.raises(ValueError, match="immutable publication receipt"):
        record_publication_receipt(
            database,
            **{**kwargs, "publication_id": "pub-replacement", "remote_sha": "b" * 40},
        )
