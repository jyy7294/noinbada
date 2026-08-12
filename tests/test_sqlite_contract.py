import sqlite3

from trzip.hourly_store import connect, default_db_path


def test_runtime_database_path_uses_sqlite_environment(monkeypatch, tmp_path):
    target = tmp_path / "runtime.sqlite3"
    monkeypatch.setenv("TRZIP_DB_PATH", str(target))
    monkeypatch.setenv("VERCEL", "1")

    assert default_db_path() == target
    with connect() as connection:
        connection.execute("SELECT 1").fetchone()

    assert target.is_file()


def test_explicit_sqlite_path_wins_over_runtime_default(monkeypatch, tmp_path):
    configured = tmp_path / "configured.sqlite3"
    explicit = tmp_path / "explicit.sqlite3"
    monkeypatch.setenv("TRZIP_DB_PATH", str(configured))

    with connect(explicit) as connection:
        connection.execute("SELECT 1").fetchone()

    assert explicit.is_file()
    assert not configured.exists()


def test_legacy_sqlite_schema_is_migrated_without_losing_rows(tmp_path):
    target = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(target) as connection:
        connection.executescript("""
            CREATE TABLE hourly_observations (
                observed_at TEXT NOT NULL,
                source TEXT NOT NULL,
                topic TEXT NOT NULL,
                source_rank INTEGER NOT NULL,
                value REAL NOT NULL,
                provenance TEXT NOT NULL,
                seed_observed_at TEXT,
                PRIMARY KEY (observed_at, source, topic)
            );
            INSERT INTO hourly_observations VALUES (
                '2026-08-12T00:00:00+00:00', 'x', '말복', 1, 100, 'observed', NULL
            );
        """)

    with connect(target) as connection:
        row = connection.execute(
            "SELECT topic, provenance FROM hourly_observations"
        ).fetchone()
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='hourly_observations'"
        ).fetchone()[0]

    assert dict(row) == {"topic": "말복", "provenance": "observed"}
    assert "topic, provenance" in table_sql
