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
    )

    receipt = _publication_receipt(database, stamp)
    assert receipt["passed"] is True
    assert receipt["publication_id"] == "pub-example"
    assert receipt["remote_sha"] == "a" * 40
