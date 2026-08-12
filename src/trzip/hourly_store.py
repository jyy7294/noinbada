from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

KST = timedelta(hours=9)
BACKFILL_START = datetime(2026, 5, 1, tzinfo=UTC) - KST
BACKFILL_END = datetime(2026, 8, 12, 11, tzinfo=UTC) - KST


@dataclass(frozen=True)
class HourlyObservation:
    observed_at: str
    source: str
    topic: str
    source_rank: int
    value: float
    provenance: str
    seed_observed_at: str | None = None


def default_db_path() -> Path:
    if os.environ.get("VERCEL"):
        return Path("/tmp/trzip-hourly.sqlite3")
    return Path(os.environ.get("TRZIP_DB_PATH", "data/trzip-hourly.sqlite3"))


def _postgres_url(path: Path | None) -> str | None:
    if path is not None:
        return None
    value = os.environ.get("DATABASE_URL", "").strip()
    return value or None


class DatabaseConnection:
    """Small compatibility layer for SQLite locally and PostgreSQL on Render."""

    def __init__(self, raw: Any, dialect: str):
        self.raw = raw
        self.dialect = dialect

    def __enter__(self) -> "DatabaseConnection":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if exc_type is None:
            self.raw.commit()
        else:
            self.raw.rollback()
        self.raw.close()

    def _sql(self, sql: str) -> str:
        if self.dialect == "sqlite":
            return sql
        # The project uses SQLite qmark and named parameters internally.
        converted = sql.replace("?", "%s")
        import re
        return re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", r"%(\1)s", converted)

    def execute(self, sql: str, params: Any = None):
        return self.raw.execute(self._sql(sql), params or ())

    def executemany(self, sql: str, params: Any):
        if self.dialect == "sqlite":
            return self.raw.executemany(sql, params)
        cursor = self.raw.cursor()
        cursor.executemany(self._sql(sql), params)
        return cursor

    def executescript(self, sql: str) -> None:
        if self.dialect != "sqlite":
            raise RuntimeError("executescript is only used for SQLite migrations")
        self.raw.executescript(sql)


def _initialize_postgres(connection: DatabaseConnection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS hourly_observations (
            observed_at TEXT NOT NULL,
            source TEXT NOT NULL CHECK(source IN ('x','google_trends')),
            topic TEXT NOT NULL,
            source_rank INTEGER NOT NULL CHECK(source_rank > 0),
            value DOUBLE PRECISION NOT NULL CHECK(value >= 0),
            provenance TEXT NOT NULL CHECK(provenance IN ('observed','generated')),
            seed_observed_at TEXT,
            PRIMARY KEY (observed_at, source, topic, provenance)
        )
    """)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS hourly_observations_time ON hourly_observations(observed_at)"
    )
    connection.execute("""
        CREATE TABLE IF NOT EXISTS collection_audit (
            observed_at TEXT NOT NULL,
            collector TEXT NOT NULL,
            status TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            detail TEXT NOT NULL,
            PRIMARY KEY (observed_at, collector)
        )
    """)


def connect(path: Path | None = None) -> DatabaseConnection:
    postgres_url = _postgres_url(path)
    if postgres_url:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL requires psycopg[binary]") from exc
        raw = psycopg.connect(postgres_url, row_factory=dict_row)
        connection = DatabaseConnection(raw, "postgres")
        _initialize_postgres(connection)
        raw.commit()
        return connection

    target = path or default_db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(target)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA journal_mode=WAL")
    connection = DatabaseConnection(raw, "sqlite")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS hourly_observations (
            observed_at TEXT NOT NULL,
            source TEXT NOT NULL CHECK(source IN ('x','google_trends')),
            topic TEXT NOT NULL,
            source_rank INTEGER NOT NULL CHECK(source_rank > 0),
            value REAL NOT NULL CHECK(value >= 0),
            provenance TEXT NOT NULL CHECK(provenance IN ('observed','generated')),
            seed_observed_at TEXT,
            PRIMARY KEY (observed_at, source, topic, provenance)
        );
        CREATE INDEX IF NOT EXISTS hourly_observations_time ON hourly_observations(observed_at);
        CREATE TABLE IF NOT EXISTS collection_audit (
            observed_at TEXT NOT NULL, collector TEXT NOT NULL, status TEXT NOT NULL,
            row_count INTEGER NOT NULL, detail TEXT NOT NULL,
            PRIMARY KEY (observed_at, collector)
        );
    """)
    table_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='hourly_observations'"
    ).fetchone()[0]
    if "topic, provenance" not in table_sql:
        connection.executescript("""
            CREATE TABLE hourly_observations_v2 (
                observed_at TEXT NOT NULL,
                source TEXT NOT NULL CHECK(source IN ('x','google_trends')),
                topic TEXT NOT NULL,
                source_rank INTEGER NOT NULL CHECK(source_rank > 0),
                value REAL NOT NULL CHECK(value >= 0),
                provenance TEXT NOT NULL CHECK(provenance IN ('observed','generated')),
                seed_observed_at TEXT,
                PRIMARY KEY (observed_at, source, topic, provenance)
            );
            INSERT OR IGNORE INTO hourly_observations_v2
            SELECT observed_at,source,topic,source_rank,value,provenance,seed_observed_at
            FROM hourly_observations;
            DROP TABLE hourly_observations;
            ALTER TABLE hourly_observations_v2 RENAME TO hourly_observations;
            CREATE INDEX hourly_observations_time ON hourly_observations(observed_at);
        """)
    return connection


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
    aliases = {
        "X_BEARER_TOKEN": "KIWOOM_TRZIP_X_BEARER_TOKEN",
        "OPENDART_API_KEY": "KIWOOM_TRZIP_DART_API_KEY",
    }
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


def _stable_unit(*parts: str) -> float:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / (2**64 - 1)


DEMO_TOPICS = (
    "두바이 초콜릿", "불닭", "오징어 게임", "리센느", "러닝크루",
    "성수 팝업", "말차 디저트", "꾸미기 챌린지", "폴더블폰", "여름 정주행",
    "AI 가상 피팅", "야구 직관", "캐릭터 키링", "저속노화", "홈카페",
)


def demo_topics(at: datetime) -> tuple[str, ...]:
    """Return only topics plausibly active at that historical KST date."""
    day = (at + KST).date()
    active = [
        "불닭", "러닝크루", "성수 팝업", "말차 디저트", "꾸미기 챌린지",
        "여름 정주행", "AI 가상 피팅", "야구 직관", "캐릭터 키링", "저속노화", "홈카페",
    ]
    if day <= datetime(2026, 6, 15).date():
        active += ["오징어 게임", "두바이 초콜릿"]
    if datetime(2026, 5, 15).date() <= day <= datetime(2026, 7, 20).date():
        active += ["리센느"]
    if day >= datetime(2026, 7, 1).date():
        active += ["폴더블폰"]
    if day >= datetime(2026, 8, 1).date():
        active += ["말복", "삼계탕", "보양식"]
    return tuple(active)


def generated_hour(at: datetime, *, seed_topics: tuple[str, ...] = DEMO_TOPICS) -> list[HourlyObservation]:
    if seed_topics is DEMO_TOPICS:
        seed_topics = demo_topics(at)
    stamp = floor_hour(at).isoformat()
    rows: list[HourlyObservation] = []
    for source in ("x", "google_trends"):
        scored = []
        for topic in seed_topics:
            daily = _stable_unit(at.date().isoformat(), source, topic)
            hourly = _stable_unit(stamp, source, topic)
            persistence = _stable_unit(at.strftime("%Y-%m"), topic)
            value = round(35 + daily * 35 + hourly * 20 + persistence * 10, 3)
            scored.append((value, topic))
        scored.sort(reverse=True)
        rows.extend(HourlyObservation(stamp, source, topic, rank, value, "generated")
                    for rank, (value, topic) in enumerate(scored[:10], 1))
    return rows


def collect_google(at: datetime) -> list[HourlyObservation]:
    request = urllib.request.Request(
        "https://trends.google.com/trending/rss?geo=KR",
        headers={"User-Agent": "TRZIP/0.1 (+hourly trend collector)"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        root = ET.fromstring(response.read())
    stamp = floor_hour(at).isoformat()
    titles = [node.text.strip() for node in root.findall(".//item/title") if node.text and node.text.strip()]
    return [HourlyObservation(stamp, "google_trends", title, rank, max(1, 101 - rank), "observed")
            for rank, title in enumerate(dict.fromkeys(titles), 1)]


def collect_trends_mcp(at: datetime, feed_type: str, source: str) -> list[HourlyObservation]:
    load_local_env()
    token = os.environ.get("TRENDS_MCP_API_KEY", "").strip()
    if not token:
        return []
    body = json.dumps({"mode": "get_top_trends", "type": feed_type, "limit": 25}).encode("utf-8")
    request = urllib.request.Request(
        "https://api.trendsmcp.ai/api", data=body, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "TRZIP/0.1"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    if isinstance(payload, dict) and isinstance(payload.get("body"), str):
        payload = json.loads(payload["body"])
    if isinstance(payload, dict) and int(payload.get("statusCode", 200)) >= 400:
        raise ValueError(str(payload.get("body") or payload))
    data = payload.get("data", payload if isinstance(payload, list) else [])
    stamp = floor_hour(at).isoformat()
    parsed: list[tuple[int, str]] = []
    for fallback_rank, item in enumerate(data, 1):
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            rank, name = int(item[0]), str(item[1])
        elif isinstance(item, dict):
            rank = int(item.get("rank", fallback_rank))
            name = str(item.get("name") or item.get("title") or item.get("query") or "")
        else:
            rank, name = fallback_rank, str(item)
        if name.strip():
            parsed.append((rank, name.strip()))
    return [HourlyObservation(stamp, source, name, rank, max(1, 101 - rank), "observed")
            for rank, name in parsed[:25]]


def collect_x(at: datetime) -> list[HourlyObservation]:
    load_local_env()
    token = os.environ.get("X_BEARER_TOKEN", "").strip()
    if not token:
        return []
    # South Korea country WOEID. The override exists only for explicit tests.
    korea_woeid = os.environ.get("X_KOREA_WOEID", "23424868").strip()
    if not korea_woeid.isdigit():
        return []
    query = urllib.parse.urlencode({"max_trends": 50, "trend.fields": "trend_name,tweet_count"})
    endpoint = f"https://api.x.com/2/trends/by/woeid/{korea_woeid}?{query}"
    request = urllib.request.Request(endpoint, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.load(response)
    stamp = floor_hour(at).isoformat()
    topics = payload.get("data", payload.get("topics", []))
    return [HourlyObservation(stamp, "x", str(item.get("trend_name") or item.get("name")), rank,
                              float(item.get("tweet_count") or item.get("value") or 101 - rank), "observed")
            for rank, item in enumerate(topics, 1)]


def upsert(rows: list[HourlyObservation], path: Path | None = None) -> int:
    with connect(path) as connection:
        connection.executemany("""
            INSERT INTO hourly_observations
            (observed_at, source, topic, source_rank, value, provenance, seed_observed_at)
            VALUES (:observed_at,:source,:topic,:source_rank,:value,:provenance,:seed_observed_at)
            ON CONFLICT(observed_at, source, topic, provenance) DO UPDATE SET
              source_rank=excluded.source_rank, value=excluded.value,
              seed_observed_at=excluded.seed_observed_at
        """, [asdict(row) for row in rows])
    return len(rows)


def backfill(until: datetime | None = None, path: Path | None = None) -> int:
    end = min(floor_hour(until), BACKFILL_END)
    cursor, total = BACKFILL_START, 0
    while cursor <= end:
        total += upsert(generated_hour(cursor), path)
        cursor += timedelta(hours=1)
    return total


def purge_generated_outside_demo_window(path: Path | None = None) -> int:
    """Keep reconstructed demo rows strictly inside the requested May-August window."""
    with connect(path) as connection:
        cursor = connection.execute(
            "DELETE FROM hourly_observations WHERE provenance='generated' AND (observed_at < ? OR observed_at > ?)",
            (BACKFILL_START.isoformat(), BACKFILL_END.isoformat()),
        )
    return cursor.rowcount


def collect_current(path: Path | None = None, now: datetime | None = None, *, use_trends_mcp: bool = False) -> dict:
    at = floor_hour(now)
    observed: list[HourlyObservation] = []
    errors: dict[str, str] = {}
    load_local_env()
    # Production collection remains Korea-only. The explicit MCP probe is stored
    # separately because its live feeds have no documented KR geo parameter.
    audit: dict[str, dict] = {}

    def google_korea(value: datetime) -> list[HourlyObservation]:
        korea_rows = collect_google(value)
        audit["google_geo_kr"] = {"status": "observed" if korea_rows else "empty",
                                  "row_count": len(korea_rows), "detail": "Google Trends RSS geo=KR publication gate"}
        if use_trends_mcp and os.environ.get("TRENDS_MCP_API_KEY", "").strip():
            try:
                # MCP is a freshness sensor; geo=KR remains the publication gate.
                mcp_rows = collect_trends_mcp(value, "Google Trends", "google_trends")
                audit["google_trends_mcp"] = {"status": "observed" if mcp_rows else "empty",
                                              "row_count": len(mcp_rows), "detail": "freshness only; not KR publication evidence"}
            except Exception as exc:
                audit["google_trends_mcp"] = {"status": "error", "row_count": 0,
                                              "detail": f"{type(exc).__name__}: {exc}"}
        elif use_trends_mcp:
            audit["google_trends_mcp"] = {"status": "unconfigured", "row_count": 0,
                                          "detail": "TRENDS_MCP_API_KEY not configured"}
        else:
            audit["google_trends_mcp"] = {"status": "disabled", "row_count": 0,
                                          "detail": "one-time probe completed; automatic MCP use disabled"}
        return korea_rows

    collectors = (("google_trends", google_korea), ("x", collect_x))
    for source, collector in collectors:
        try:
            rows = collector(at)
            observed.extend(rows)
            if not rows:
                errors[source] = "approved collector not configured or returned no rows"
        except Exception as exc:  # operational boundary: fallback remains labelled
            errors[source] = f"{type(exc).__name__}: {exc}"
    audit["x_korea_realtime"] = {"status": "observed" if any(row.source == "x" for row in observed) else "unavailable",
                                 "row_count": sum(row.source == "x" for row in observed),
                                 "detail": "Korea realtime trends only; no generated fallback after cutoff"}
    by_source = {row.source for row in observed}
    inside_demo_window = BACKFILL_START <= at <= BACKFILL_END
    generated = generated_hour(at) if inside_demo_window else []
    upsert(generated + observed, path)
    with connect(path) as connection:
        connection.executemany(
            """INSERT INTO collection_audit
               (observed_at, collector, status, row_count, detail) VALUES (?,?,?,?,?)
               ON CONFLICT(observed_at, collector) DO UPDATE SET
                 status=excluded.status, row_count=excluded.row_count, detail=excluded.detail""",
            [(at.isoformat(), collector, item["status"], item["row_count"], item["detail"])
             for collector, item in audit.items()],
        )
    return {"observed": len(observed), "generated": len(generated), "errors": errors,
            "trends_mcp_used": use_trends_mcp and bool(os.environ.get("TRENDS_MCP_API_KEY", "").strip()),
            "audit": audit,
            "observed_at": at.isoformat()}


def snapshot(at: datetime, path: Path | None = None) -> list[dict]:
    stamp = floor_hour(at).isoformat()
    with connect(path) as connection:
        rows = connection.execute(
            "SELECT * FROM hourly_observations WHERE observed_at=? ORDER BY source, source_rank", (stamp,)
        ).fetchall()
    return [dict(row) for row in rows]


def coverage(path: Path | None = None) -> dict:
    with connect(path) as connection:
        row = connection.execute("""
          SELECT MIN(observed_at) AS first_hour, MAX(observed_at) AS last_hour,
                 COUNT(DISTINCT observed_at) AS hours, COUNT(*) AS rows,
                 SUM(CASE WHEN provenance='observed' THEN 1 ELSE 0 END) AS observed_rows,
                 SUM(CASE WHEN provenance='generated' THEN 1 ELSE 0 END) AS generated_rows
          FROM hourly_observations
        """).fetchone()
    return dict(row)
