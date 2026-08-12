from pathlib import Path

from trzip.hourly_store import _postgres_url


def test_explicit_sqlite_path_wins_over_database_url(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/trzip")
    assert _postgres_url(tmp_path / "test.sqlite3") is None


def test_database_url_is_used_without_explicit_path(monkeypatch):
    url = "postgresql://user:password@example.invalid/trzip"
    monkeypatch.setenv("DATABASE_URL", url)
    assert _postgres_url(None) == url
