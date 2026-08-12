from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


X_TRENDS_URL = "https://x.com/explore/tabs/trending"
RANK_RE = re.compile(r"^\d{1,3}$")
CONTEXT_MARKERS = (
    "대한민국에서 트렌드 중",
    "실시간 트렌드",
    "트렌드 중",
)


@dataclass(frozen=True)
class XTrend:
    rank: int
    topic: str


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
    if "/login" in folded_url or "로그인" in body_text or "sign in" in folded_body:
        return XCollectionError("auth_required", "the dedicated Chrome profile must sign in to X once")
    if cell_count == 0:
        return XCollectionError("selector_changed", "no data-testid=trend cells were found")
    return XCollectionError("empty", "numbered realtime trends were not found")


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
    if not ready_marker(target_profile).exists():
        raise XCollectionError(
            "auth_required",
            "run scripts/setup-x-chrome.ps1 and verify the Korea realtime page once",
        )
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
                try:
                    page.locator('[data-testid="trend"]').first.wait_for(
                        state="visible", timeout=timeout_ms
                    )
                except PlaywrightTimeoutError:
                    body = page.locator("body").inner_text(timeout=5_000)
                    raise _classify_page_failure(page.url, body, 0)

                cells = page.locator('[data-testid="trend"]').all_inner_texts()
                body = page.locator("body").inner_text(timeout=5_000)
                trends = parse_trend_cells(cells)
                region_verified = "대한민국에서 트렌드 중" in body
                if not region_verified:
                    raise XCollectionError(
                        "region_unverified",
                        "the page did not expose the South Korea trend marker",
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
            finally:
                context.close()
    except XCollectionError:
        raise
    except PlaywrightTimeoutError as exc:
        raise XCollectionError("timeout", "X realtime trends page timed out") from exc
    except Exception as exc:
        raise XCollectionError("browser_error", f"{type(exc).__name__}: {exc}") from exc


def open_setup_browser(profile_dir: Path | None = None) -> None:
    """Open the dedicated Chrome profile for the one-time user login."""
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
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(X_TRENDS_URL, wait_until="domcontentloaded", timeout=30_000)
        input("X에 로그인하고 실시간 트렌드 탭이 보이면 이 창에서 Enter를 누르세요: ")
        cells = page.locator('[data-testid="trend"]').all_inner_texts()
        body = page.locator("body").inner_text(timeout=5_000)
        trends = parse_trend_cells(cells)
        if "대한민국에서 트렌드 중" not in body or len(trends) < 10:
            raise XCollectionError(
                "region_unverified",
                "대한민국 실시간 트렌드 10개 이상을 확인하지 못했습니다",
            )
        ready_marker(target_profile).write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
        context.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="TRZIP X Chrome page collector")
    parser.add_argument("--setup", action="store_true", help="open the dedicated profile for one-time login")
    parser.add_argument("--headed", action="store_true", help="show Chrome while probing")
    args = parser.parse_args()
    if args.setup:
        open_setup_browser()
        return
    trends, audit = collect_x_page(headless=not args.headed)
    print({"observed_at": datetime.now(UTC).isoformat(), "audit": audit,
           "trends": [{"rank": item.rank, "topic": item.topic} for item in trends]})


if __name__ == "__main__":
    main()
