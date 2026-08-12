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


X_TRENDS_URL = "https://x.com/explore/tabs/trending"
RANK_RE = re.compile(r"^\d{1,3}$")
CONTEXT_MARKERS = (
    "대한민국에서 트렌드 중",
    "실시간 트렌드",
    "트렌드 중",
)
KOREA_REGION_MARKERS = (
    "대한민국에서 트렌드 중",
    "대한민국 트렌드",
    "trending in south korea",
    "trends in south korea",
)
AUTH_URL_MARKERS = (
    "/i/flow/login",
    "/i/jf/onboarding/web",
    "/login",
    "/account/access",
    "mode=login",
)
AUTH_BODY_MARKERS = (
    "x에 로그인",
    "계정 만들기",
    "전화번호로 계속",
    "이메일 또는 사용자 이름",
    "sign in to x",
    "log in to x",
    "continue with phone",
)


@dataclass(frozen=True)
class XTrend:
    rank: int
    topic: str


@dataclass(frozen=True)
class XPageSnapshot:
    url: str
    body_text: str
    cells: list[str]


class XCollectionError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def default_profile_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise XCollectionError("profile_unavailable", "LOCALAPPDATA is not available")
    return Path(local_app_data) / "TRZIP" / "chrome-profile"


def ready_marker(profile_dir: Path) -> Path:
    return profile_dir / ".trzip-x-ready"


def _write_ready_marker(profile_dir: Path, row_count: int) -> None:
    payload = {
        "verified_at": datetime.now(UTC).isoformat(),
        "url": X_TRENDS_URL,
        "region": "KR",
        "row_count": row_count,
    }
    ready_marker(profile_dir).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def parse_trend_cells(cells: list[str]) -> list[XTrend]:
    """Parse only numbered X trend cells and ignore promoted content."""
    parsed: list[XTrend] = []
    seen: set[str] = set()
    for raw in cells:
        lines = [line.strip() for line in str(raw).splitlines() if line.strip()]
        if not lines or not RANK_RE.fullmatch(lines[0]):
            continue
        rank = int(lines[0])
        candidates = [
            line
            for line in lines[1:]
            if line != "·"
            and not any(marker in line for marker in CONTEXT_MARKERS)
            and line != "더 보기"
            and not line.endswith("posts")
            and not line.endswith("게시물")
        ]
        if not candidates:
            continue
        topic = candidates[-1].strip()
        key = topic.casefold()
        if not topic or key in seen:
            continue
        seen.add(key)
        parsed.append(XTrend(rank=rank, topic=topic))
    return sorted(parsed, key=lambda item: item.rank)


def _classify_page_failure(url: str, body_text: str, cell_count: int) -> XCollectionError:
    folded_url = url.casefold()
    folded_body = body_text.casefold()
    if any(marker in folded_url for marker in AUTH_URL_MARKERS) or any(
        marker in folded_body for marker in AUTH_BODY_MARKERS
    ):
        return XCollectionError("auth_required", "the dedicated Chrome profile must sign in to X once")
    if cell_count == 0:
        return XCollectionError("selector_changed", "no data-testid=trend cells were found")
    return XCollectionError("empty", "numbered realtime trends were not found")


def inspect_x_page(snapshot: XPageSnapshot, minimum_rows: int = 10) -> tuple[list[XTrend], dict]:
    """Classify authentication, Korea region evidence, and numbered trend rows."""
    auth_failure = _classify_page_failure(
        snapshot.url, snapshot.body_text, len(snapshot.cells)
    )
    if auth_failure.code == "auth_required":
        raise auth_failure

    trends = parse_trend_cells(snapshot.cells)
    if not snapshot.cells:
        raise auth_failure
    if not trends:
        raise XCollectionError("empty", "numbered realtime trends were not found")

    region_text = "\n".join([snapshot.body_text, *snapshot.cells]).casefold()
    if not any(marker in region_text for marker in KOREA_REGION_MARKERS):
        raise XCollectionError(
            "region_unverified",
            "the page did not expose a South Korea trend marker",
        )
    if len(trends) < minimum_rows:
        raise XCollectionError(
            "empty",
            f"only {len(trends)} numbered trends were found; minimum is {minimum_rows}",
        )
    return trends, {
        "status": "observed",
        "collector": "x_chrome_page",
        "url": X_TRENDS_URL,
        "region": "KR",
        "region_verified": True,
        "row_count": len(trends),
        "profile": "dedicated_local_profile",
    }


def wait_for_verified_page(
    snapshot_supplier: Callable[[], XPageSnapshot],
    *,
    timeout_seconds: float,
    minimum_rows: int = 10,
    retry_auth: bool = False,
    pause: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> tuple[list[XTrend], dict]:
    """Poll the live page until it proves auth, KR region, and enough rows."""
    deadline = now() + max(0.0, timeout_seconds)
    last_error = XCollectionError("timeout", "X realtime trends page timed out")
    while True:
        try:
            return inspect_x_page(snapshot_supplier(), minimum_rows=minimum_rows)
        except XCollectionError as exc:
            last_error = exc
            if exc.code == "auth_required" and not retry_auth:
                raise
        remaining = deadline - now()
        if remaining <= 0:
            raise last_error
        pause(min(1.0, remaining))


def _snapshot_from_page(page) -> XPageSnapshot:
    try:
        body = page.locator("body").inner_text(timeout=5_000)
    except Exception:
        body = ""
    try:
        cells = page.locator('[data-testid="trend"]').all_inner_texts()
    except Exception:
        cells = []
    return XPageSnapshot(url=page.url, body_text=body, cells=cells)


def collect_x_page(
    *,
    profile_dir: Path | None = None,
    headless: bool = True,
    timeout_ms: int = 30_000,
    minimum_rows: int = 10,
) -> tuple[list[XTrend], dict]:
    """Read the X realtime trends page through installed Google Chrome.

    The dedicated profile is intentionally outside the repository. Cookies,
    page HTML, and post bodies are never returned or persisted.
    """
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise XCollectionError("browser_dependency_missing", "install the playwright Python package") from exc

    target_profile = (profile_dir or default_profile_dir()).resolve()
    target_profile.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(target_profile),
                channel="chrome",
                headless=headless,
                locale="ko-KR",
                args=["--lang=ko-KR"],
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(X_TRENDS_URL, wait_until="domcontentloaded", timeout=timeout_ms)
                trends, audit = wait_for_verified_page(
                    lambda: _snapshot_from_page(page),
                    timeout_seconds=timeout_ms / 1_000,
                    minimum_rows=max(1, minimum_rows),
                    retry_auth=False,
                    pause=lambda seconds: page.wait_for_timeout(round(seconds * 1_000)),
                )
                # The marker is evidence from a successful page read, never a
                # prerequisite that prevents the collector from opening X.
                try:
                    _write_ready_marker(target_profile, len(trends))
                except OSError:
                    pass
                return trends, audit
            finally:
                context.close()
    except XCollectionError:
        raise
    except PlaywrightTimeoutError as exc:
        raise XCollectionError("timeout", "X realtime trends page timed out") from exc
    except Exception as exc:
        raise XCollectionError("browser_error", f"{type(exc).__name__}: {exc}") from exc


def open_setup_browser(
    profile_dir: Path | None = None,
    *,
    timeout_seconds: int = 600,
    minimum_rows: int = 10,
) -> dict:
    """Open Chrome and automatically detect a ready Korea page for ten minutes."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise XCollectionError("browser_dependency_missing", "install the playwright Python package") from exc
    target_profile = (profile_dir or default_profile_dir()).resolve()
    target_profile.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(target_profile),
            channel="chrome",
            headless=False,
            locale="ko-KR",
            args=["--lang=ko-KR"],
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(X_TRENDS_URL, wait_until="domcontentloaded", timeout=30_000)
            print(
                "X 로그인이 필요하면 브라우저에서 완료해 주세요. "
                "대한민국 트렌드 10개 이상이 보이면 자동으로 저장됩니다."
            )
            trends, audit = wait_for_verified_page(
                lambda: _snapshot_from_page(page),
                timeout_seconds=max(1, timeout_seconds),
                minimum_rows=max(1, minimum_rows),
                retry_auth=True,
                pause=lambda seconds: page.wait_for_timeout(round(seconds * 1_000)),
            )
            _write_ready_marker(target_profile, len(trends))
            return audit
        finally:
            context.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="TRZIP X Chrome page collector")
    parser.add_argument("--setup", action="store_true", help="open the dedicated profile for one-time login")
    parser.add_argument("--setup-timeout-seconds", type=int, default=600)
    parser.add_argument("--headed", action="store_true", help="show Chrome while probing")
    args = parser.parse_args()
    if args.setup:
        audit = open_setup_browser(timeout_seconds=max(1, args.setup_timeout_seconds))
        print(json.dumps(audit, ensure_ascii=False))
        return
    trends, audit = collect_x_page(headless=not args.headed)
    print({"observed_at": datetime.now(UTC).isoformat(), "audit": audit,
           "trends": [{"rank": item.rank, "topic": item.topic} for item in trends]})


if __name__ == "__main__":
    main()
