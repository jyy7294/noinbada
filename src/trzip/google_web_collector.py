from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


GOOGLE_TRENDS_URL = "https://trends.google.com/trending?geo=KR&hl=ko"


class GoogleCollectionError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class GoogleTrend:
    rank: int
    topic: str
    volume_text: str
    growth_text: str
    started_text: str
    related_terms: tuple[str, ...]
    source_payload: dict[str, Any]


def default_profile_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise GoogleCollectionError("profile_unavailable", "LOCALAPPDATA is not available")
    return Path(local_app_data) / "TRZIP" / "google-chrome-profile"


def normalize_row(raw: dict[str, Any], rank: int) -> GoogleTrend:
    topic = str(raw.get("topic") or "").strip()
    volume = str(raw.get("volume_text") or "").strip()
    growth = str(raw.get("growth_text") or "").strip()
    started = str(raw.get("started_text") or "").strip()
    raw_related = raw.get("related_terms") or []
    if not isinstance(raw_related, list):
        raise GoogleCollectionError("row_invalid", "related_terms must be an array")
    related: list[str] = []
    seen: set[str] = set()
    for value in raw_related:
        term = str(value).strip()
        key = term.casefold()
        if term and key not in seen and key != topic.casefold():
            related.append(term)
            seen.add(key)
    if not topic or not volume or not started:
        raise GoogleCollectionError("row_invalid", "topic, volume, and start time are required")
    return GoogleTrend(
        rank=rank,
        topic=topic,
        volume_text=volume,
        growth_text=growth,
        started_text=started,
        related_terms=tuple(related),
        source_payload={
            "volume_text": volume,
            "growth_text": growth,
            "started_text": started,
            "status_text": str(raw.get("status_text") or "").strip(),
            "page": int(raw.get("page") or 1),
            "row_on_page": int(raw.get("row_on_page") or 1),
        },
    )


def validate_complete_rows(
    raw_rows: list[dict[str, Any]],
    *,
    declared_total: int | None,
    minimum_rows: int = 100,
) -> list[GoogleTrend]:
    if declared_total is None or declared_total < 1:
        raise GoogleCollectionError("total_unverified", "Google page total was not found")
    if len(raw_rows) != declared_total:
        raise GoogleCollectionError(
            "incomplete_pages",
            f"collected {len(raw_rows)} rows but page declared {declared_total}",
        )
    if len(raw_rows) < max(1, minimum_rows):
        raise GoogleCollectionError(
            "too_few_rows",
            f"only {len(raw_rows)} Google trends were observed",
        )
    rows = [normalize_row(raw, rank) for rank, raw in enumerate(raw_rows, 1)]
    keys = [(row.topic.casefold(), row.started_text.casefold(), row.volume_text.casefold()) for row in rows]
    if len(keys) != len(set(keys)):
        raise GoogleCollectionError("duplicate_rows", "duplicate Google table rows were observed")
    return rows


def _extract_page(page, page_number: int) -> dict[str, Any]:
    return page.evaluate(
        r"""(pageNumber) => {
          const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
          const rows = [...document.querySelectorAll('[role="row"][data-row-id]')].map((row, index) => {
            const topicCell = row.querySelector('td.jvkLtd');
            const metricsCell = row.querySelector('td.dQOTjf');
            const startedCell = row.querySelector('td.WirRge');
            const relatedCell = row.querySelector('td.xm9Xec');
            const topic = clean(topicCell?.querySelector('.mZ3RIc')?.textContent || topicCell?.innerText);
            const volume = clean(metricsCell?.querySelector('.lqv0Cb')?.textContent);
            const growth = clean(metricsCell?.querySelector('.TXt85b')?.textContent);
            const started = clean(startedCell?.querySelector('.vdw3Ld')?.childNodes?.[0]?.textContent || startedCell?.innerText?.split('\n')[0]);
            const status = clean(startedCell?.querySelector('.FmJEKe div:last-child')?.textContent);
            const related = [...(relatedCell?.querySelectorAll('.d15Ppf') || [])]
              .map((item) => clean(item.textContent)).filter(Boolean);
            return {
              topic, volume_text: volume, growth_text: growth,
              started_text: started, status_text: status,
              related_terms: related, page: pageNumber, row_on_page: index + 1,
            };
          }).filter((row) => row.topic);
          const body = document.body?.innerText || '';
          const pagination = body.match(/([\d,]+)\s*중\s*([\d,]+)[–-]([\d,]+)/);
          const declaredTotal = pagination ? Number(pagination[1].replace(/,/g, '')) : null;
          const next = document.querySelector('button[aria-label="다음 페이지로 이동"]');
          return {
            url: location.href,
            title: document.title,
            rows,
            declaredTotal,
            nextDisabled: !next || next.disabled || next.getAttribute('aria-disabled') === 'true',
          };
        }""",
        page_number,
    )


def collect_google_page(
    *,
    profile_dir: Path | None = None,
    headless: bool = True,
    timeout_ms: int = 120_000,
    minimum_rows: int = 100,
    pause: Callable[[float], None] = time.sleep,
) -> tuple[list[GoogleTrend], dict[str, Any]]:
    """Collect every paginated row from Google Trending Now for Korea.

    This collector uses a separate cookie-free Chrome profile because the
    public Google page does not require login. It does not use RSS, MCP, or a
    private endpoint. The page's own declared total is the completion gate, so
    a changing count (for example 181 vs 182) is preserved rather than fixed.
    """

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise GoogleCollectionError("browser_dependency_missing", "install playwright") from exc

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
                page.goto(GOOGLE_TRENDS_URL, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_selector('[role="row"][data-row-id]', timeout=timeout_ms)
                all_rows: list[dict[str, Any]] = []
                declared_total: int | None = None
                page_number = 1
                while True:
                    snapshot = _extract_page(page, page_number)
                    if snapshot["url"] != GOOGLE_TRENDS_URL:
                        raise GoogleCollectionError("unexpected_url", snapshot["url"])
                    if snapshot["declaredTotal"]:
                        if declared_total not in (None, snapshot["declaredTotal"]):
                            raise GoogleCollectionError("total_changed", "Google total changed during pagination")
                        declared_total = int(snapshot["declaredTotal"])
                    page_rows = list(snapshot["rows"])
                    if not page_rows:
                        raise GoogleCollectionError("selector_changed", f"page {page_number} had no rows")
                    all_rows.extend(page_rows)
                    if snapshot["nextDisabled"]:
                        break
                    if page_number >= 20:
                        raise GoogleCollectionError("pagination_loop", "more than 20 pages were encountered")
                    first_topic = page_rows[0]["topic"]
                    page.locator('button[aria-label="다음 페이지로 이동"]').click()
                    page.wait_for_function(
                        """previous => {
                          const current = document.querySelector('[role="row"][data-row-id] td.jvkLtd .mZ3RIc');
                          return current && current.textContent.trim() !== previous;
                        }""",
                        arg=first_topic,
                        timeout=15_000,
                    )
                    pause(0.25)
                    page_number += 1

                rows = validate_complete_rows(
                    all_rows,
                    declared_total=declared_total,
                    minimum_rows=minimum_rows,
                )
                return rows, {
                    "status": "observed",
                    "collector": "google_trending_now_kr_page",
                    "url": GOOGLE_TRENDS_URL,
                    "region": "KR",
                    "row_count": len(rows),
                    "declared_total": declared_total,
                    "page_count": page_number,
                    "completion_verified": True,
                }
            finally:
                context.close()
    except GoogleCollectionError:
        raise
    except PlaywrightTimeoutError as exc:
        raise GoogleCollectionError("timeout", "Google Trending Now page timed out") from exc
    except Exception as exc:
        raise GoogleCollectionError("browser_error", f"{type(exc).__name__}: {exc}") from exc
