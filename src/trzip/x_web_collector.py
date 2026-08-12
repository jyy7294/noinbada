from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse


X_TRENDS_URL = "https://x.com/explore/tabs/trending"
RANK_RE = re.compile(r"^\d{1,3}$")
CONTEXT_MARKERS = (
    "대한민국에서 트렌드 중",
    "실시간 트렌드",
    "트렌드 중",
    "trending in south korea",
    "trends in south korea",
    "only on x",
)
KOREA_REGION_MARKERS = (
    "대한민국에서 트렌드 중",
    "대한민국 트렌드",
    "trending in south korea",
    "trends in south korea",
)


@dataclass(frozen=True)
class XTrend:
    rank: int
    topic: str


@dataclass(frozen=True)
class XPageSnapshot:
    """A sanitized DOM sample used by parser unit tests.

    Production collection is controlled by Codex in the user's currently
    logged-in Chrome. Python receives only the sanitized rank/topic snapshot,
    never cookies, full HTML, or post bodies.
    """

    url: str
    body_text: str
    cells: list[str]


class XCollectionError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _windows_downloads_dir() -> Path | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        downloads_guid = "{374DE290-123F-4565-9164-39C4925E467B}"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _kind = winreg.QueryValueEx(key, downloads_guid)
        return Path(os.path.expandvars(str(value))).expanduser()
    except (OSError, ImportError):
        return None


def default_inbox_file() -> Path:
    explicit = os.environ.get("TRZIP_X_INBOX", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    downloads = _windows_downloads_dir()
    if downloads is None:
        downloads = Path.home() / "Downloads"
    return downloads / "TRZIP" / "x-current-session.json"


def parse_trend_cells(cells: list[str]) -> list[XTrend]:
    """Parse numbered X trend cells and ignore promoted/non-ranked cells."""

    parsed: list[XTrend] = []
    seen_topics: set[str] = set()
    seen_ranks: set[int] = set()
    for raw in cells:
        lines = [line.strip() for line in str(raw).splitlines() if line.strip()]
        if not lines or not RANK_RE.fullmatch(lines[0]):
            continue
        rank = int(lines[0])
        if rank < 1 or rank > 100 or rank in seen_ranks:
            continue
        candidates = []
        for line in lines[1:]:
            folded = line.casefold()
            if line == "·" or any(marker in folded for marker in CONTEXT_MARKERS):
                continue
            if folded in {"더 보기", "show more"}:
                continue
            if folded.endswith(" posts") or folded.endswith(" 게시물"):
                continue
            candidates.append(line)
        if not candidates:
            continue
        topic = candidates[-1].strip()
        topic_key = topic.casefold()
        if not topic or topic_key in seen_topics:
            continue
        seen_topics.add(topic_key)
        seen_ranks.add(rank)
        parsed.append(XTrend(rank=rank, topic=topic))
    return sorted(parsed, key=lambda item: item.rank)


def inspect_x_page(
    snapshot: XPageSnapshot, minimum_rows: int = 30
) -> tuple[list[XTrend], dict]:
    """Validate a sanitized page sample without opening or attaching Chrome."""

    folded_url = snapshot.url.casefold()
    if any(marker in folded_url for marker in ("/login", "mode=login", "/onboarding/")):
        raise XCollectionError("auth_required", "the current Chrome profile must be signed in to X")
    trends = parse_trend_cells(snapshot.cells)
    if not snapshot.cells:
        raise XCollectionError("selector_changed", "no data-testid=trend cells were found")
    if not trends:
        raise XCollectionError("empty", "numbered realtime trends were not found")
    region_text = "\n".join([snapshot.body_text, *snapshot.cells]).casefold()
    if not any(marker in region_text for marker in KOREA_REGION_MARKERS):
        raise XCollectionError("region_unverified", "the page did not expose a South Korea marker")
    if len(trends) < max(1, minimum_rows):
        raise XCollectionError(
            "incomplete_scroll",
            f"only {len(trends)} numbered trends were observed; 30 are required",
        )
    return trends, {
        "status": "observed",
        "collector": "codex_chrome_current_session",
        "url": X_TRENDS_URL,
        "region": "KR",
        "region_verified": True,
        "row_count": len(trends),
        "profile": "current_logged_in_chrome",
    }


def _parse_aware_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise XCollectionError("snapshot_invalid", f"{field} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise XCollectionError("snapshot_invalid", f"{field} is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise XCollectionError("snapshot_invalid", f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _validate_bridge_payload(
    payload: object,
    *,
    now: datetime,
    minimum_rows: int,
) -> tuple[list[XTrend], dict]:
    if not isinstance(payload, dict):
        raise XCollectionError("snapshot_invalid", "snapshot root must be an object")
    if payload.get("schema_version") != 1 or payload.get("source") != "x":
        raise XCollectionError("snapshot_invalid", "unsupported X snapshot schema")
    collector = str(payload.get("collector") or "")
    supported_collectors = {
        "codex_chrome_current_session": "codex_browser_snapshot",
    }
    if collector not in supported_collectors:
        raise XCollectionError("snapshot_invalid", "unsupported X snapshot collector")
    url = str(payload.get("url") or "")
    parsed_url = urlparse(url)
    if parsed_url.scheme != "https" or parsed_url.hostname != "x.com" or parsed_url.path != "/explore/tabs/trending":
        raise XCollectionError("snapshot_invalid", "snapshot URL is not the X realtime trends page")
    if payload.get("region") != "KR" or payload.get("region_verified") is not True:
        raise XCollectionError("region_unverified", "the current Chrome snapshot did not verify South Korea")

    observed_at = _parse_aware_datetime(payload.get("observed_at"), "observed_at")
    current_hour = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    observed_hour = observed_at.replace(minute=0, second=0, microsecond=0)
    if observed_hour != current_hour:
        raise XCollectionError(
            "snapshot_stale",
            f"latest X snapshot belongs to {observed_hour.isoformat()}, not {current_hour.isoformat()}",
        )

    raw_trends = payload.get("trends")
    if not isinstance(raw_trends, list):
        raise XCollectionError("snapshot_invalid", "trends must be an array")
    trends: list[XTrend] = []
    seen_topics: set[str] = set()
    seen_ranks: set[int] = set()
    for item in raw_trends:
        if not isinstance(item, dict):
            raise XCollectionError("snapshot_invalid", "each trend must be an object")
        try:
            rank = int(item.get("rank"))
        except (TypeError, ValueError) as exc:
            raise XCollectionError("snapshot_invalid", "trend rank must be an integer") from exc
        topic = str(item.get("topic") or "").strip()
        if rank < 1 or rank > 100 or rank in seen_ranks or not topic or len(topic) > 200:
            raise XCollectionError("snapshot_invalid", "trend ranks/topics are invalid or duplicated")
        topic_key = topic.casefold()
        if topic_key in seen_topics:
            raise XCollectionError("snapshot_invalid", "trend topics are duplicated")
        seen_ranks.add(rank)
        seen_topics.add(topic_key)
        trends.append(XTrend(rank=rank, topic=topic))
    trends.sort(key=lambda item: item.rank)

    required_rows = max(30, minimum_rows)
    required_ranks = set(range(1, required_rows + 1))
    if len(trends) < required_rows or not required_ranks.issubset(seen_ranks):
        raise XCollectionError(
            "incomplete_scroll",
            f"collector observed {len(trends)} rows but ranks 1-{required_rows} are required",
        )
    declared_count = payload.get("row_count")
    if declared_count != len(trends):
        raise XCollectionError("snapshot_invalid", "row_count does not match trends")

    scheduled_for = payload.get("scheduled_for")
    scheduled_at = _parse_aware_datetime(scheduled_for, "scheduled_for") if scheduled_for else None
    delay_seconds = None
    if scheduled_at is not None:
        delay_seconds = max(0.0, (observed_at - scheduled_at).total_seconds())
    return trends, {
        "status": "observed",
        "collector": collector,
        "url": X_TRENDS_URL,
        "region": "KR",
        "region_verified": True,
        "row_count": len(trends),
        "profile": "current_logged_in_chrome",
        "observed_at": observed_at.isoformat(),
        "scheduled_for": scheduled_at.isoformat() if scheduled_at else None,
        "schedule_delay_seconds": delay_seconds,
        "transport": supported_collectors[collector],
    }


def _read_snapshot(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise XCollectionError("current_session_not_ready", f"X inbox does not exist: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise XCollectionError("snapshot_invalid", f"cannot read X inbox: {type(exc).__name__}") from exc


def collect_x_page(
    *,
    profile_dir: Path | None = None,
    headless: bool = True,
    timeout_ms: int = 120_000,
    minimum_rows: int = 30,
    inbox_file: Path | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    pause: Callable[[float], None] = time.sleep,
) -> tuple[list[XTrend], dict]:
    """Consume a fresh snapshot produced inside the current Chrome session.

    ``profile_dir`` and ``headless`` remain in the signature only so the
    existing hourly pipeline does not need a migration.  They are never used
    to launch, attach to, copy, or terminate Chrome.
    """

    del profile_dir, headless
    target = (inbox_file or default_inbox_file()).resolve()
    if not target.exists():
        raise XCollectionError(
            "current_session_not_ready",
            f"X inbox does not exist; the Codex Chrome collection has not completed: {target}",
        )
    deadline = time.monotonic() + max(0.0, timeout_ms / 1_000)
    last_error = XCollectionError("current_session_not_ready", f"waiting for current-hour X snapshot: {target}")
    while True:
        try:
            payload = _read_snapshot(target)
            return _validate_bridge_payload(
                payload,
                now=now(),
                minimum_rows=max(1, minimum_rows),
            )
        except XCollectionError as exc:
            last_error = exc
            if exc.code not in {"current_session_not_ready", "snapshot_stale", "snapshot_invalid"}:
                raise
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise last_error
        pause(min(1.0, remaining))


def wait_for_current_session_snapshot(
    *,
    inbox_file: Path | None = None,
    timeout_seconds: int = 600,
) -> dict:
    deadline = time.monotonic() + max(1, timeout_seconds)
    last_error = XCollectionError("current_session_not_ready", "waiting for the first Codex Chrome snapshot")
    while True:
        try:
            _trends, audit = collect_x_page(
                inbox_file=inbox_file,
                timeout_ms=1_000,
                minimum_rows=30,
            )
            return audit
        except XCollectionError as exc:
            last_error = exc
        if time.monotonic() >= deadline:
            raise last_error
        time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="TRZIP current-Chrome X snapshot consumer")
    parser.add_argument("--setup", action="store_true", help="wait for the first Codex Chrome snapshot")
    parser.add_argument("--setup-timeout-seconds", type=int, default=600)
    parser.add_argument("--inbox", type=Path)
    parser.add_argument("--headed", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.setup:
        print(json.dumps(wait_for_current_session_snapshot(
            inbox_file=args.inbox,
            timeout_seconds=max(1, args.setup_timeout_seconds),
        ), ensure_ascii=False))
        return
    trends, audit = collect_x_page(inbox_file=args.inbox)
    print(json.dumps({
        "observed_at": datetime.now(UTC).isoformat(),
        "audit": audit,
        "trends": [{"rank": item.rank, "topic": item.topic} for item in trends],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
