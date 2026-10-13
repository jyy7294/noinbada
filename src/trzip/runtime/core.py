from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import gzip
import json
import os
from pathlib import Path
import sqlite3
import unicodedata
import time

ROOT = Path(__file__).resolve().parents[3]


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone required")
    return result.astimezone(UTC)


def key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().strip().lstrip("#").split())


def event_id(value: str) -> str:
    return "evt_" + hashlib.sha256(key(value).encode()).hexdigest()[:20]


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def decode(value):
    return json.loads(gzip.decompress(value) if isinstance(value,bytes) else value)


def atomic_bytes(path: Path, value: bytes):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+".tmp")
    with temp.open("wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def home() -> Path:
    return Path(os.environ.get("TRZIP_RUNTIME_HOME", ROOT / "work" / "runtime")).resolve()


def connect(root: Path | None = None) -> sqlite3.Connection:
    root = root or home()
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "runtime.sqlite3", timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=15000")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS runs (
      id INTEGER PRIMARY KEY, slot TEXT UNIQUE NOT NULL, started_at TEXT NOT NULL,
      finished_at TEXT, status TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '{}');
    CREATE TABLE IF NOT EXISTS receipts (
      id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES runs(id),
      source TEXT NOT NULL, sampling_frame TEXT NOT NULL, observed_at TEXT NOT NULL,
      status TEXT NOT NULL, row_count INTEGER NOT NULL, detail TEXT NOT NULL,
      UNIQUE(run_id,source));
    CREATE TABLE IF NOT EXISTS observations (
      id INTEGER PRIMARY KEY, receipt_id INTEGER NOT NULL REFERENCES receipts(id),
      event_id TEXT NOT NULL, source TEXT NOT NULL, sampling_frame TEXT NOT NULL,
      observed_at TEXT NOT NULL, position INTEGER NOT NULL, payload TEXT NOT NULL,
      UNIQUE(receipt_id,event_id));
    CREATE INDEX IF NOT EXISTS observations_event_time ON observations(event_id,observed_at);
    CREATE TABLE IF NOT EXISTS enrichment (
      event_id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS publications (
      id TEXT PRIMARY KEY, published_at TEXT NOT NULL, observed_at TEXT NOT NULL,
      payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS jobs (
      event_id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
      attempts INTEGER NOT NULL DEFAULT 0, next_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    """)
    return db


@contextmanager
def writer_lock(root: Path, wait_seconds: float = 90):
    root.mkdir(parents=True, exist_ok=True)
    stream = (root / "writer.lock").open("a+b")
    deadline=time.monotonic()+wait_seconds
    while True:
        try:
            if os.name == "nt":
                import msvcrt
                if stream.tell() == 0:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.monotonic()>=deadline:
                stream.close()
                raise RuntimeError("another TRZIP writer is running") from None
            time.sleep(0.25)
    try:
        yield
    finally:
        stream.close()


def atomic_json(path: Path, payload: object):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(encode(payload))
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
