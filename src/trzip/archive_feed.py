"""Build the non-ranking TRZIP historical research archive.

The reviewed reconstruction workbook is useful as a product research asset,
but it is not an observed X/Google ranking.  This module projects that catalog
into a small frontend contract while preserving the hard boundary from the
live ranking engine.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from .keyword_policy import keyword_fits_public_label


SCHEMA_VERSION = "trzip-archive-feed-v1"

CATEGORY_LABELS = {
    "culture": "문화·밈",
    "content": "콘텐츠",
    "lifestyle": "라이프",
    "consumer": "제품·브랜드",
    "food": "음식",
    "sports": "스포츠",
}

# Historical records can grow later.  Keep the same product-safety boundary as
# the live feed instead of assuming every future workbook row is publishable.
_UNSAFE_TOPIC = re.compile(
    r"정치|선거|정당|대통령|국회의원|범죄|살인|성범죄|사망|참사|재난|"
    r"사생활|폭로|혐오|비하",
    re.IGNORECASE,
)


def _public_urls(values: Iterable[Any]) -> list[str]:
    urls: list[str] = []
    for value in values:
        url = str(value or "").strip()
        if url.startswith(("https://", "http://")) and url not in urls:
            urls.append(url)
    return urls


def _keyword_texts(event: dict[str, Any]) -> list[str]:
    output: list[str] = []
    for row in event.get("related_keywords") or []:
        text = str(row.get("text") if isinstance(row, dict) else row).strip()
        if text and keyword_fits_public_label(text) and text not in output:
            output.append(text)
    return output[:5]


def _companies(event: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in event.get("companies") or []:
        if not isinstance(row, dict) or row.get("company_role_public") is False:
            continue
        name = str(row.get("company") or row.get("name") or "").strip()
        reason = str(
            row.get("connection_explanation")
            or row.get("relationship_reason")
            or ""
        ).strip()
        if not name or not reason:
            continue
        evidence_urls = _public_urls(
            source.get("url")
            for source in (row.get("evidence_sources") or [])
            if isinstance(source, dict)
        )
        output.append(
            {
                "name": name,
                "stock_code": str(row.get("stock_code") or "").strip(),
                "exchange": str(row.get("market") or row.get("exchange") or "").strip(),
                "role": str(row.get("company_role_label") or "기업 역할").strip(),
                "connection_context": reason,
                "evidence_urls": evidence_urls,
            }
        )
    return output[:3]


def _archive_item(event: dict[str, Any]) -> dict[str, Any] | None:
    name = str(event.get("representative_term") or "").strip()
    why_now = str(event.get("why_now") or "").strip()
    review_status = str((event.get("source_workbook") or {}).get("review_status") or "").strip()
    evidence_urls = _public_urls(
        row.get("url")
        for row in (event.get("evidence") or [])
        if isinstance(row, dict)
    )
    if (
        not name
        or not why_now
        or review_status != "ready"
        or _UNSAFE_TOPIC.search(name)
        or not evidence_urls
        or event.get("live_eligible") is not False
        or event.get("rank_eligible") is not False
        or event.get("ranking_effect") != "none"
    ):
        return None

    category = str(event.get("category") or "culture").strip()
    active_from = str(event.get("active_from") or "").strip()
    active_to = str(event.get("active_to") or active_from).strip()
    companies = _companies(event)
    return {
        "id": str(event.get("event_id") or name).strip(),
        "display_name": name,
        "category": category,
        "category_label": CATEGORY_LABELS.get(category, "문화·밈"),
        "active_from": active_from,
        "active_to": active_to,
        "peak_hint": str(event.get("peak_hint") or active_to).strip(),
        "definition": str(event.get("definition") or "").strip(),
        "why_now": why_now,
        "trigger_event": str(event.get("trigger_event") or "").strip(),
        "keywords": _keyword_texts(event),
        "companies": companies,
        "company_count": len(companies),
        "evidence_urls": evidence_urls,
        "source_mode": "reviewed_research_reference",
    }


def build_archive_feed(events: Iterable[dict[str, Any]], *, dataset_id: str) -> dict[str, Any]:
    items = [item for event in events if (item := _archive_item(event)) is not None]
    items.sort(
        key=lambda item: (
            item["peak_hint"],
            item["active_to"],
            item["display_name"].casefold(),
        ),
        reverse=True,
    )
    categories = [
        {"key": key, "label": label, "count": sum(item["category"] == key for item in items)}
        for key, label in CATEGORY_LABELS.items()
        if any(item["category"] == key for item in items)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "data_mode": "reconstructed_reference",
        "display_mode": "historical_research_archive",
        "live_eligible": False,
        "ranking_eligible": False,
        "ranking_effect": "none",
        "ordering": "peak_hint_desc_then_name",
        "item_count": len(items),
        "categories": categories,
        "items": items,
    }


def load_archive_source(events_path: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8-sig"))
    if manifest.get("data_mode") != "reconstructed":
        raise ValueError("archive source must be a reconstructed dataset")
    if manifest.get("live_eligible") is not False or manifest.get("ranking_effect") != "none":
        raise ValueError("archive source must not affect the live ranking")
    events = [
        json.loads(line)
        for line in Path(events_path).read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    if len(events) != int(manifest.get("event_count") or -1):
        raise ValueError("archive event count does not match its manifest")
    return build_archive_feed(events, dataset_id=str(manifest.get("dataset_id") or "archive"))


def write_archive_feed(events_path: Path, manifest_path: Path, output_path: Path) -> dict[str, Any]:
    feed = load_archive_source(events_path, manifest_path)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(
        json.dumps(feed, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return feed
