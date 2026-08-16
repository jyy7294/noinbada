from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .source_safety import is_spam_solicitation

KST = timedelta(hours=9)

# Only these source/collector cohorts have the same sampling frame as the
# production ranking contract.  ``trzip_v3`` is retained as the explicit
# deterministic fixture cohort used by unit tests and local replay; arbitrary
# non-null strings must never become ranking-eligible by accident.
APPROVED_COLLECTOR_VERSIONS = {
    "x": frozenset({"x_current_session_kr_v1", "trzip_v3"}),
    "google_trends": frozenset({"google_trending_now_kr_v1", "trzip_v3"}),
}

# Remote/live publications have a narrower trust boundary than local replay.
# Keep ``trzip_v3`` readable for deterministic fixtures, but never let it enter
# a production ranking merely because it shares the same SQLite ledger.
LIVE_COLLECTOR_VERSIONS = {
    "x": frozenset({"x_current_session_kr_v1"}),
    "google_trends": frozenset({"google_trending_now_kr_v1"}),
}

ELIGIBLE_COLLECTOR_SQL = """(
    (source = 'x' AND collector_version IN ('x_current_session_kr_v1','trzip_v3'))
    OR
    (source = 'google_trends' AND collector_version IN ('google_trending_now_kr_v1','trzip_v3'))
)"""

LIVE_COLLECTOR_SQL = """(
    (source = 'x' AND collector_version = 'x_current_session_kr_v1')
    OR
    (source = 'google_trends' AND collector_version = 'google_trending_now_kr_v1')
)"""


def collector_version_is_approved(source: str, collector_version: str | None) -> bool:
    return str(collector_version or "") in APPROVED_COLLECTOR_VERSIONS.get(source, ())


def collector_version_is_live(source: str, collector_version: str | None) -> bool:
    return str(collector_version or "") in LIVE_COLLECTOR_VERSIONS.get(source, ())


@dataclass(frozen=True)
class HourlyObservation:
    observed_at: str
    source: str
    topic: str
    source_rank: int
    value: float
    provenance: str
    seed_observed_at: str | None = None
    source_payload_json: str | None = None
    related_terms_json: str | None = None
    collector_version: str = "trzip_v3"


def default_db_path() -> Path:
    explicit = os.environ.get("TRZIP_DB_PATH", "").strip()
    if explicit:
        return Path(explicit)
    runtime = os.environ.get("TRZIP_RUNTIME_ROOT", "").strip()
    if runtime:
        return Path(runtime) / "data" / "trzip-hourly.sqlite3"
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / "TRZIP" / "data" / "trzip-hourly.sqlite3"


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Open the single local SQLite store and close it after each operation."""
    target = path or default_db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS hourly_observations (
                observed_at TEXT NOT NULL,
                source TEXT NOT NULL CHECK(source IN ('x','google_trends')),
                topic TEXT NOT NULL,
                source_rank INTEGER NOT NULL CHECK(source_rank > 0),
                value REAL NOT NULL CHECK(value >= 0),
                provenance TEXT NOT NULL CHECK(provenance IN ('observed','generated')),
                seed_observed_at TEXT,
                source_payload_json TEXT,
                related_terms_json TEXT,
                collector_version TEXT,
                PRIMARY KEY (observed_at, source, source_rank, topic, provenance)
            );
            CREATE INDEX IF NOT EXISTS hourly_observations_time
              ON hourly_observations(observed_at, source, provenance, source_rank);
            CREATE INDEX IF NOT EXISTS hourly_observations_topic_time
              ON hourly_observations(topic, observed_at);
            CREATE TABLE IF NOT EXISTS collection_audit (
                observed_at TEXT NOT NULL, collector TEXT NOT NULL, status TEXT NOT NULL,
                row_count INTEGER NOT NULL, detail TEXT NOT NULL,
                PRIMARY KEY (observed_at, collector)
            );
        """)
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='hourly_observations'"
        ).fetchone()[0]
        normalized_table_sql = " ".join(table_sql.replace("\n", " ").split()).casefold()
        expected_primary_key = "primary key (observed_at, source, source_rank, topic, provenance)"
        if expected_primary_key not in normalized_table_sql:
            connection.executescript("""
                DROP VIEW IF EXISTS hourly_source_rankings;
                DROP VIEW IF EXISTS source_hour_quality;
                DROP VIEW IF EXISTS daily_source_aggregates;
                DROP INDEX IF EXISTS hourly_observations_time;
                DROP INDEX IF EXISTS hourly_observations_topic_time;
            """)
            connection.executescript("""
                CREATE TABLE hourly_observations_v3 (
                    observed_at TEXT NOT NULL,
                    source TEXT NOT NULL CHECK(source IN ('x','google_trends')),
                    topic TEXT NOT NULL,
                    source_rank INTEGER NOT NULL CHECK(source_rank > 0),
                    value REAL NOT NULL CHECK(value >= 0),
                    provenance TEXT NOT NULL CHECK(provenance IN ('observed','generated')),
                    seed_observed_at TEXT,
                    source_payload_json TEXT,
                    related_terms_json TEXT,
                    collector_version TEXT,
                    PRIMARY KEY (observed_at, source, source_rank, topic, provenance)
                );
                INSERT OR REPLACE INTO hourly_observations_v3
                (observed_at,source,topic,source_rank,value,provenance,seed_observed_at)
                SELECT observed_at,source,topic,source_rank,value,provenance,seed_observed_at
                FROM hourly_observations ORDER BY rowid;
                DROP TABLE hourly_observations;
                ALTER TABLE hourly_observations_v3 RENAME TO hourly_observations;
            """)
        existing_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(hourly_observations)").fetchall()
        }
        for column in ("source_payload_json", "related_terms_json", "collector_version"):
            if column not in existing_columns:
                connection.execute(
                    f"ALTER TABLE hourly_observations ADD COLUMN {column} TEXT"
                )
        # Views are derived contracts. Recreate them on each schema open so an
        # existing runtime database receives revised quality rules immediately.
        connection.executescript(f"""
            DROP VIEW IF EXISTS daily_source_aggregates;
            DROP VIEW IF EXISTS source_hour_quality;
            DROP VIEW IF EXISTS hourly_source_rankings;
        """)
        connection.executescript(f"""
            CREATE INDEX IF NOT EXISTS hourly_observations_time
              ON hourly_observations(observed_at, source, provenance, source_rank);
            CREATE INDEX IF NOT EXISTS hourly_observations_topic_time
              ON hourly_observations(topic, observed_at);
            CREATE VIEW IF NOT EXISTS hourly_source_rankings AS
              SELECT observed_at, source, topic, source_rank, value, provenance,
                     seed_observed_at, source_payload_json, related_terms_json,
                     collector_version,
                     61.0 / (60.0 + source_rank) AS normalized_rrf
              FROM hourly_observations
              WHERE {ELIGIBLE_COLLECTOR_SQL};
            CREATE VIEW IF NOT EXISTS source_hour_quality AS
              WITH counts AS (
                SELECT observed_at, source, provenance,
                       COUNT(*) AS row_count,
                       COUNT(DISTINCT source_rank) AS distinct_rank_count,
                       COUNT(DISTINCT topic) AS distinct_topic_count
                FROM hourly_observations
                WHERE {ELIGIBLE_COLLECTOR_SQL}
                GROUP BY observed_at, source, provenance
              )
              SELECT counts.*,
                     audit.row_count AS audited_row_count,
                     CASE
                       WHEN counts.row_count <> counts.distinct_rank_count
                         THEN 'quarantined_duplicate_rank'
                       WHEN audit.status = 'observed' AND audit.row_count <> counts.row_count
                         THEN 'quarantined_audit_mismatch'
                       ELSE 'eligible'
                     END AS quality_status
              FROM counts
              LEFT JOIN collection_audit AS audit
                ON audit.observed_at = counts.observed_at
               AND audit.collector = CASE counts.source
                    WHEN 'x' THEN 'x_korea_realtime'
                    WHEN 'google_trends' THEN 'google_geo_kr'
                  END;
            CREATE VIEW IF NOT EXISTS daily_source_aggregates AS
              SELECT date(observation.observed_at, '+9 hours') AS kst_date,
                     observation.source, observation.topic, observation.provenance,
                     COUNT(*) AS observation_count,
                     COUNT(DISTINCT observation.observed_at) AS hours_present,
                     MIN(observation.source_rank) AS best_rank,
                     AVG(observation.source_rank) AS mean_rank,
                     MIN(observation.observed_at) AS first_observed_at,
                     MAX(observation.observed_at) AS last_observed_at
              FROM hourly_observations AS observation
              JOIN source_hour_quality AS quality
                USING (observed_at, source, provenance)
              WHERE quality.quality_status = 'eligible'
                AND ((observation.source = 'x' AND observation.collector_version IN ('x_current_session_kr_v1','trzip_v3'))
                  OR (observation.source = 'google_trends' AND observation.collector_version IN ('google_trending_now_kr_v1','trzip_v3')))
              GROUP BY date(observation.observed_at, '+9 hours'),
                       observation.source, observation.topic, observation.provenance;
        """)
        yield connection
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()
    finally:
        connection.close()


def floor_hour(value: datetime | None = None) -> datetime:
    current = value or datetime.now(UTC)
    return current.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def load_local_env() -> None:
    """Load uncommitted local secrets without printing or returning them."""
    env_file = Path(".env")
    raw_lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    for raw_line in raw_lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

    if os.environ.get("TRZIP_DISABLE_USER_SECRET_BRIDGE") == "1":
        return

    # Reuse the existing TRZIP Windows user-level secret inventory. Values are
    # read into this process only and are never copied to files or logs.
    aliases = {"OPENDART_API_KEY": "KIWOOM_TRZIP_DART_API_KEY"}
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as registry:
                for target, source in aliases.items():
                    if os.environ.get(target, "").strip():
                        continue
                    try:
                        value, _ = winreg.QueryValueEx(registry, source)
                    except FileNotFoundError:
                        continue
                    if isinstance(value, str) and value.strip():
                        os.environ[target] = value.strip()
        except OSError:
            pass


def collect_google(at: datetime) -> list[HourlyObservation]:
    """Collect every verified row from Google Trending Now's Korea web UI."""
    from .google_web_collector import collect_google_page

    profile_value = os.environ.get("TRZIP_GOOGLE_CHROME_PROFILE", "").strip()
    profile_dir = Path(profile_value) if profile_value else None
    headed = os.environ.get("TRZIP_GOOGLE_HEADED", "0").strip() == "1"
    minimum_rows = int(os.environ.get("TRZIP_GOOGLE_MINIMUM_ROWS", "100"))
    trends, page_audit = collect_google_page(
        profile_dir=profile_dir,
        headless=not headed,
        minimum_rows=max(1, minimum_rows),
    )
    stamp = floor_hour(at).isoformat()
    return [
        HourlyObservation(
            stamp,
            "google_trends",
            trend.topic,
            trend.rank,
            float(max(1, 101 - trend.rank)),
            "observed",
            source_payload_json=json.dumps(
                {
                    **trend.source_payload,
                    "collection_declared_total": page_audit.get("declared_total"),
                    "collection_page_count": page_audit.get("page_count"),
                    "collection_completion_verified": bool(
                        page_audit.get("completion_verified")
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            related_terms_json=json.dumps(
                list(trend.related_terms),
                ensure_ascii=False,
            ),
            collector_version="google_trending_now_kr_v1",
        )
        for trend in trends
    ]


def collect_x(at: datetime) -> list[HourlyObservation]:
    """Consume the complete Korea realtime list captured by current Chrome."""
    from .x_web_collector import collect_x_page

    minimum_rows = int(os.environ.get("TRZIP_X_MINIMUM_ROWS", "30"))
    topics, collection_audit = collect_x_page(
        minimum_rows=max(30, minimum_rows),
    )
    stamp = floor_hour(at).isoformat()
    evidence = json.dumps(collection_audit, ensure_ascii=False, sort_keys=True)
    return [
        HourlyObservation(
            stamp,
            "x",
            item.topic,
            item.rank,
            float(max(1, 101 - item.rank)),
            "observed",
            source_payload_json=evidence,
            collector_version="x_current_session_kr_v1",
        )
        for item in topics
    ]


def upsert(rows: list[HourlyObservation], path: Path | None = None) -> int:
    if any(row.provenance != "observed" for row in rows):
        raise ValueError("production ledger accepts observed rows only")
    if any(not collector_version_is_approved(row.source, row.collector_version) for row in rows):
        raise ValueError("collector version is not approved for source")
    if any(
        row.source == "x"
        and row.collector_version == "x_current_session_kr_v1"
        and is_spam_solicitation(row.topic)
        for row in rows
    ):
        raise ValueError("live X source snapshot contains solicitation/contact spam")
    with connect(path) as connection:
        connection.executemany("""
            INSERT INTO hourly_observations
            (observed_at, source, topic, source_rank, value, provenance, seed_observed_at,
             source_payload_json, related_terms_json, collector_version)
            VALUES (:observed_at,:source,:topic,:source_rank,:value,:provenance,:seed_observed_at,
                    :source_payload_json,:related_terms_json,:collector_version)
            ON CONFLICT(observed_at, source, source_rank, topic, provenance) DO UPDATE SET
              value=excluded.value, seed_observed_at=excluded.seed_observed_at,
              source_payload_json=excluded.source_payload_json,
              related_terms_json=excluded.related_terms_json,
              collector_version=excluded.collector_version
        """, [asdict(row) for row in rows])
    return len(rows)


def store_verified_source_snapshot(
    rows: list[HourlyObservation],
    *,
    source: str,
    collector: str,
    detail: str,
    path: Path | None = None,
) -> int:
    """Atomically replace one verified source snapshot and its audit row."""
    if not rows:
        raise ValueError("verified source snapshot cannot be empty")
    stamps = {row.observed_at for row in rows}
    if len(stamps) != 1 or any(row.source != source or row.provenance != "observed" for row in rows):
        raise ValueError("snapshot rows must share one hour, source, and observed provenance")
    if any(not collector_version_is_approved(row.source, row.collector_version) for row in rows):
        raise ValueError("collector version is not approved for source")
    if source == "x" and any(is_spam_solicitation(row.topic) for row in rows):
        raise ValueError("live X source snapshot contains solicitation/contact spam")
    ranks = [row.source_rank for row in rows]
    if len(ranks) != len(set(ranks)):
        raise ValueError("snapshot rows must have unique source ranks")
    stamp = next(iter(stamps))
    with connect(path) as connection:
        connection.execute(
            "DELETE FROM hourly_observations WHERE observed_at=? AND source=? AND provenance='observed'",
            (stamp, source),
        )
        connection.executemany(
            """
            INSERT INTO hourly_observations
            (observed_at, source, topic, source_rank, value, provenance, seed_observed_at,
             source_payload_json, related_terms_json, collector_version)
            VALUES (:observed_at,:source,:topic,:source_rank,:value,:provenance,:seed_observed_at,
                    :source_payload_json,:related_terms_json,:collector_version)
            """,
            [asdict(row) for row in rows],
        )
        connection.execute(
            """INSERT INTO collection_audit
               (observed_at, collector, status, row_count, detail) VALUES (?,?,?,?,?)
               ON CONFLICT(observed_at, collector) DO UPDATE SET
                 status=excluded.status, row_count=excluded.row_count, detail=excluded.detail""",
            (stamp, collector, "observed", len(rows), detail),
        )
    return len(rows)


def _first_verified_snapshot_for_hour(
    at: datetime,
    source: str,
    path: Path | None,
) -> tuple[list[HourlyObservation], dict] | None:
    """Return the first complete same-hour snapshot without re-scraping it.

    An hourly ledger is a point-in-time record. Once a source passes its
    completeness gate, a manual retry must not rewrite that hour with a later
    web-page state. A source that was missing or invalid remains collectible.
    """

    stamp = floor_hour(at).isoformat()
    with connect(path) as connection:
        stored = connection.execute(
            """SELECT * FROM hourly_observations
               WHERE observed_at=? AND source=? AND provenance='observed'
                  AND ((source='x' AND collector_version IN ('x_current_session_kr_v1','trzip_v3'))
                    OR (source='google_trends' AND collector_version IN ('google_trending_now_kr_v1','trzip_v3')))
               ORDER BY source_rank""",
            (stamp, source),
        ).fetchall()
    if not stored:
        return None
    ranks = [int(row["source_rank"]) for row in stored]
    if ranks != list(range(1, len(stored) + 1)):
        return None
    rows = [
        HourlyObservation(
            observed_at=row["observed_at"],
            source=row["source"],
            topic=row["topic"],
            source_rank=row["source_rank"],
            value=row["value"],
            provenance=row["provenance"],
            seed_observed_at=row["seed_observed_at"],
            source_payload_json=row["source_payload_json"],
            related_terms_json=row["related_terms_json"],
            collector_version=row["collector_version"],
        )
        for row in stored
    ]
    if source == "x":
        if len(rows) != 30:
            return None
        if any(is_spam_solicitation(row.topic) for row in rows):
            return None
        try:
            evidence = json.loads(rows[0].source_payload_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            evidence = {}
        return rows, {
            "status": "observed",
            "row_count": 30,
            "detail": "first verified same-hour X Korea 1-30 snapshot preserved",
            "collector": evidence.get("collector"),
            "transport": evidence.get("transport"),
            "profile": evidence.get("profile"),
            "region": evidence.get("region"),
            "region_verified": evidence.get("region_verified"),
            "observed_at": evidence.get("observed_at"),
            "scheduled_for": evidence.get("scheduled_for"),
            "schedule_delay_seconds": evidence.get("schedule_delay_seconds"),
        }
    if source == "google_trends":
        if len(rows) < 100:
            return None
        try:
            evidence = json.loads(rows[0].source_payload_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        declared_total = evidence.get("collection_declared_total")
        page_count = evidence.get("collection_page_count")
        complete = evidence.get("collection_completion_verified") is True
        if declared_total != len(rows) or not complete or not isinstance(page_count, int):
            return None
        return rows, {
            "status": "observed",
            "row_count": len(rows),
            "declared_total": declared_total,
            "page_count": page_count,
            "completion_verified": True,
            "detail": "first verified same-hour Google Trending Now KR snapshot preserved",
        }
    return None


def collect_current(path: Path | None = None, now: datetime | None = None) -> dict:
    at = floor_hour(now)
    observed: list[HourlyObservation] = []
    newly_collected: list[HourlyObservation] = []
    errors: dict[str, str] = {}
    load_local_env()
    # Production collection is deliberately limited to the two approved Korea
    # discovery sources. Optional/global trend feeds cannot enter this path.
    audit: dict[str, dict] = {}

    def google_korea(value: datetime) -> list[HourlyObservation]:
        korea_rows = collect_google(value)
        page_evidence: dict = {}
        if korea_rows and korea_rows[0].source_payload_json:
            try:
                page_evidence = json.loads(korea_rows[0].source_payload_json)
            except (TypeError, ValueError, json.JSONDecodeError):
                page_evidence = {}
        audit["google_geo_kr"] = {
            "status": "observed" if korea_rows else "empty",
            "row_count": len(korea_rows),
            "declared_total": page_evidence.get("collection_declared_total"),
            "page_count": page_evidence.get("collection_page_count"),
            "completion_verified": bool(
                page_evidence.get("collection_completion_verified")
            ),
            "detail": "Google Trending Now KR web full-list completion gate",
        }
        return korea_rows

    audit_keys = {"google_trends": "google_geo_kr", "x": "x_korea_realtime"}
    collectors = (("google_trends", google_korea), ("x", collect_x))
    for source, collector in collectors:
        existing = _first_verified_snapshot_for_hour(at, source, path)
        if existing is not None:
            stored_rows, stored_audit = existing
            observed.extend(stored_rows)
            audit[audit_keys[source]] = stored_audit
            continue
        try:
            rows = collector(at)
            observed.extend(rows)
            newly_collected.extend(rows)
            if not rows:
                errors[source] = "approved collector not configured or returned no rows"
        except Exception as exc:  # operational boundary: fallback remains labelled
            errors[source] = f"{type(exc).__name__}: {exc}"
            if source == "google_trends":
                audit["google_geo_kr"] = {
                    "status": getattr(exc, "code", "error"),
                    "row_count": 0,
                    "detail": errors[source],
                }
    x_rows = sum(row.source == "x" for row in observed)
    x_error = errors.get("x", "")
    x_status = "observed" if x_rows else (
        x_error.split(":", 1)[1].strip().split(":", 1)[0]
        if x_error.startswith("XCollectionError:") else "unavailable"
    )
    audit["x_korea_realtime"] = {
        "status": x_status,
        "row_count": x_rows,
        "detail": (
            "Codex-controlled logged-in Chrome; sanitized rank-only snapshot; KR 1-30 completeness verified"
            if x_rows else x_error or "X realtime page returned no rows"
        ),
    }
    with connect(path) as connection:
        # Replace only sources that were collected successfully. A transient
        # failure must not erase a valid snapshot already stored for this hour.
        for source in sorted({row.source for row in newly_collected}):
            connection.execute(
                "DELETE FROM hourly_observations WHERE observed_at=? AND source=? AND provenance='observed'",
                (at.isoformat(), source),
            )
        connection.executemany(
            """
            INSERT INTO hourly_observations
            (observed_at, source, topic, source_rank, value, provenance, seed_observed_at,
             source_payload_json, related_terms_json, collector_version)
            VALUES (:observed_at,:source,:topic,:source_rank,:value,:provenance,:seed_observed_at,
                    :source_payload_json,:related_terms_json,:collector_version)
            ON CONFLICT(observed_at, source, source_rank, topic, provenance) DO UPDATE SET
              value=excluded.value, seed_observed_at=excluded.seed_observed_at,
              source_payload_json=excluded.source_payload_json,
              related_terms_json=excluded.related_terms_json,
              collector_version=excluded.collector_version
            """,
            [asdict(row) for row in newly_collected],
        )
        connection.executemany(
            """INSERT INTO collection_audit
               (observed_at, collector, status, row_count, detail) VALUES (?,?,?,?,?)
               ON CONFLICT(observed_at, collector) DO UPDATE SET
                 status=excluded.status, row_count=excluded.row_count, detail=excluded.detail""",
            [(at.isoformat(), collector, item["status"], item["row_count"], item["detail"])
             for collector, item in audit.items()],
        )
    return {"observed": len(observed), "errors": errors,
            "rank_sources": ["x", "google_trends"],
            "audit": audit,
            "observed_at": at.isoformat()}


def snapshot(
    at: datetime,
    path: Path | None = None,
    *,
    live_only: bool = False,
) -> list[dict]:
    stamp = floor_hour(at).isoformat()
    collector_sql = LIVE_COLLECTOR_SQL if live_only else ELIGIBLE_COLLECTOR_SQL
    with connect(path) as connection:
        rows = connection.execute(
            f"""SELECT * FROM hourly_observations
               WHERE observed_at=? AND provenance='observed'
                  AND {collector_sql}
               ORDER BY source, source_rank""",
            (stamp,),
        ).fetchall()
    if live_only and any(
        row["source"] == "x" and is_spam_solicitation(row["topic"])
        for row in rows
    ):
        rows = [row for row in rows if row["source"] != "x"]
    return [dict(row) for row in rows]


def hourly_rankings(
    at: datetime,
    path: Path | None = None,
) -> list[dict]:
    """Return the complete platform rankings for one UTC hour.

    ``normalized_rrf`` is derived only from the platform rank. ``value`` is
    retained as source payload compatibility but is deliberately not used by
    the combined ranking algorithm.
    """
    stamp = floor_hour(at).isoformat()
    with connect(path) as connection:
        rows = connection.execute(
            """SELECT * FROM hourly_source_rankings
               WHERE observed_at=? AND provenance=?
               ORDER BY source, source_rank""",
            (stamp, "observed"),
        ).fetchall()
    return [dict(row) for row in rows]


def daily_aggregates(
    start: date | datetime,
    path: Path | None = None,
    *,
    end: date | datetime | None = None,
) -> list[dict]:
    """Aggregate the raw ledger by Korea calendar day, source, and raw term."""
    def day(value: date | datetime) -> str:
        if isinstance(value, datetime):
            return (value.astimezone(UTC) + KST).date().isoformat()
        return value.isoformat()

    first_day = day(start)
    last_day = day(end or start)
    if last_day < first_day:
        raise ValueError("end day must not precede start day")
    with connect(path) as connection:
        rows = connection.execute(
            """SELECT * FROM daily_source_aggregates
               WHERE kst_date BETWEEN ? AND ? AND provenance=?
               ORDER BY kst_date, source, best_rank, topic""",
            (first_day, last_day, "observed"),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["mean_rank"] = round(float(item["mean_rank"]), 4)
        result.append(item)
    return result


def source_hour_quality(
    start: datetime,
    end: datetime,
    path: Path | None = None,
    *,
    live_only: bool = False,
) -> list[dict]:
    """Expose source-hour eligibility without mutating or deleting raw rows."""
    if not live_only:
        with connect(path) as connection:
            rows = connection.execute(
                """SELECT * FROM source_hour_quality
                   WHERE observed_at BETWEEN ? AND ? AND provenance=?
                   ORDER BY observed_at, source""",
                (floor_hour(start).isoformat(), floor_hour(end).isoformat(), "observed"),
            ).fetchall()
        return [dict(row) for row in rows]

    # A mixed replay/live hour must be measured from the live cohort alone;
    # the shared compatibility view intentionally includes both cohorts.
    with connect(path) as connection:
        rows = connection.execute(
            f"""WITH counts AS (
                    SELECT observed_at, source, provenance,
                           COUNT(*) AS row_count,
                           COUNT(DISTINCT source_rank) AS distinct_rank_count,
                           COUNT(DISTINCT topic) AS distinct_topic_count
                    FROM hourly_observations
                    WHERE observed_at BETWEEN ? AND ?
                      AND provenance='observed'
                      AND {LIVE_COLLECTOR_SQL}
                    GROUP BY observed_at, source, provenance
                )
                SELECT counts.*,
                       audit.row_count AS audited_row_count,
                       CASE
                         WHEN counts.row_count <> counts.distinct_rank_count
                           THEN 'quarantined_duplicate_rank'
                         WHEN audit.status = 'observed'
                           AND audit.row_count <> counts.row_count
                           THEN 'quarantined_audit_mismatch'
                         ELSE 'eligible'
                       END AS quality_status
                FROM counts
                LEFT JOIN collection_audit AS audit
                  ON audit.observed_at = counts.observed_at
                 AND audit.collector = CASE counts.source
                      WHEN 'x' THEN 'x_korea_realtime'
                      WHEN 'google_trends' THEN 'google_geo_kr'
                    END
                ORDER BY counts.observed_at, counts.source""",
            (floor_hour(start).isoformat(), floor_hour(end).isoformat()),
        ).fetchall()
    result = [dict(row) for row in rows]
    with connect(path) as connection:
        x_topics = connection.execute(
            """SELECT observed_at, topic FROM hourly_observations
               WHERE observed_at BETWEEN ? AND ?
                 AND source='x' AND provenance='observed'
                 AND collector_version='x_current_session_kr_v1'""",
            (floor_hour(start).isoformat(), floor_hour(end).isoformat()),
        ).fetchall()
    spam_hours = {
        str(row["observed_at"])
        for row in x_topics
        if is_spam_solicitation(row["topic"])
    }
    for item in result:
        if item.get("source") == "x" and item.get("observed_at") in spam_hours:
            item["quality_status"] = "quarantined_source_spam"
    return result


def latest_audit(at: datetime, path: Path | None = None) -> dict[str, dict]:
    """Return persisted collector status for one scheduled hour."""
    stamp = floor_hour(at).isoformat()
    with connect(path) as connection:
        rows = connection.execute(
            "SELECT collector,status,row_count,detail FROM collection_audit WHERE observed_at=?",
            (stamp,),
        ).fetchall()
    return {
        str(row["collector"]): {
            "status": row["status"],
            "row_count": row["row_count"],
            "detail": row["detail"],
        }
        for row in rows
    }


def coverage(path: Path | None = None) -> dict:
    with connect(path) as connection:
        row = connection.execute("""
          SELECT MIN(CASE WHEN provenance='observed' AND collector_version IS NOT NULL THEN observed_at END) AS first_hour,
                 MAX(CASE WHEN provenance='observed' AND collector_version IS NOT NULL THEN observed_at END) AS last_hour,
                 COUNT(DISTINCT CASE WHEN provenance='observed' AND collector_version IS NOT NULL THEN observed_at END) AS hours,
                 COALESCE(SUM(CASE WHEN provenance='observed' AND collector_version IS NOT NULL THEN 1 ELSE 0 END), 0) AS rows,
                 COALESCE(SUM(CASE WHEN provenance='observed' AND collector_version IS NOT NULL THEN 1 ELSE 0 END), 0) AS observed_rows,
                 COALESCE(SUM(CASE WHEN provenance='observed' AND collector_version IS NULL THEN 1 ELSE 0 END), 0) AS legacy_observed_rows,
                 COALESCE(SUM(CASE WHEN provenance='generated' THEN 1 ELSE 0 END), 0) AS legacy_generated_rows
          FROM hourly_observations
        """).fetchone()
    return dict(row)
