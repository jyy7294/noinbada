"""Import the reviewed TRZIP reconstruction workbook without live-rank leakage.

The workbook is a research asset, not an observed X/Google ranking.  This
module converts it into a deterministic, non-ranking JSONL catalog while
preserving source URLs, source keywords and company relationship reasons.  The
public keyword projection is limited to six non-whitespace characters without
silently truncating a reviewed source term.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .keyword_policy import keyword_fits_public_label


SCHEMA_VERSION = "trzip-reconstructed-event-v1"
IMPORT_VERSION = "reviewed-workbook-import-v2-six-character-keywords"
AS_OF_DATE = "2026-08-14"

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL_NS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
_DOC_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"

PUBLIC_CATEGORY_MAP = {
    "food": "food",
    "content": "content",
    "music": "content",
    "game": "content",
    "sports": "sports",
    "fashion_beauty_life": "lifestyle",
    "travel_life": "lifestyle",
    "culture_meme": "culture",
    "product_brand": "consumer",
}

COMPANY_ROLE_MAP = {
    "제조·개발": ("manufacturing_development", "제조·개발", True),
    "원재료·부품": ("raw_materials_components", "원재료·핵심부품", True),
    "콘텐츠 제작": ("content_production", "콘텐츠 제작", True),
    "유통": ("distribution", "배급·유통", True),
    "판매": ("retail_sales", "판매·리테일", True),
    "브랜드·마케팅": ("brand_marketing", "브랜드·마케팅", True),
    "플랫폼": ("platform_service", "플랫폼·서비스", True),
    "투자·소유": ("ownership_investment", "투자·소유", True),
    "행사 운영": ("event_sponsorship", "행사 후원·운영", True),
    # The old catch-all label is preserved for audit but cannot become public.
    "산업 연관": ("unclassified", "역할 미확정", False),
}

RELATION_GRADE_MAP = {
    "direct": "direct",
    "indirect": "value_chain",
    "value_chain": "value_chain",
    "industry_watch": "industry_watch",
}

_DEFINITION_METHOD_PHRASES = (
    "투자 조언",
    "투자 추천",
    "실시간 순위",
    "전체 언급량",
    "단순 언급량",
)


def _cell_column(reference: str) -> int:
    letters = "".join(character for character in reference if character.isalpha())
    value = 0
    for character in letters.upper():
        value = value * 26 + ord(character) - ord("A") + 1
    return value - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    values: list[str] = []
    for item in root.findall("m:si", _NS):
        values.append("".join(node.text or "" for node in item.findall(".//m:t", _NS)))
    return values


def _sheet_targets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        item.attrib["Id"]: item.attrib["Target"]
        for item in relationships.findall("r:Relationship", _REL_NS)
    }
    output = []
    for sheet in workbook.findall("m:sheets/m:sheet", _NS):
        target = targets[sheet.attrib[_DOC_REL]].replace("\\", "/")
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = "xl/" + target.removeprefix("../")
        output.append((sheet.attrib["name"], path))
    return output


def _sheet_rows(
    archive: zipfile.ZipFile,
    path: str,
    shared: list[str],
) -> list[list[Any]]:
    root = ET.fromstring(archive.read(path))
    rows: list[list[Any]] = []
    for row in root.findall("m:sheetData/m:row", _NS):
        values: dict[int, Any] = {}
        for cell in row.findall("m:c", _NS):
            column = _cell_column(cell.attrib.get("r", "A1"))
            cell_type = cell.attrib.get("t")
            if cell_type == "inlineStr":
                value: Any = "".join(
                    node.text or "" for node in cell.findall(".//m:t", _NS)
                )
            else:
                value_node = cell.find("m:v", _NS)
                raw = value_node.text if value_node is not None else None
                if raw is None:
                    value = None
                elif cell_type == "s":
                    value = shared[int(raw)]
                elif cell_type == "b":
                    value = raw == "1"
                elif cell_type in {"str", "e"}:
                    value = raw
                else:
                    numeric = float(raw)
                    value = int(numeric) if numeric.is_integer() else numeric
            values[column] = value
        width = max(values, default=-1) + 1
        rows.append([values.get(column) for column in range(width)])
    return rows


def read_workbook(path: Path) -> dict[str, list[list[Any]]]:
    with zipfile.ZipFile(path) as archive:
        shared = _shared_strings(archive)
        return {
            name: _sheet_rows(archive, target, shared)
            for name, target in _sheet_targets(archive)
        }


def _records(rows: list[list[Any]]) -> list[dict[str, Any]]:
    if len(rows) < 4:
        return []
    headers = [str(value or "").strip() for value in rows[2]]
    output = []
    for row in rows[3:]:
        if not any(value not in (None, "") for value in row):
            continue
        padded = row + [None] * max(0, len(headers) - len(row))
        output.append(dict(zip(headers, padded)))
    return output


def _excel_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return (datetime(1899, 12, 30) + timedelta(days=float(value))).date().isoformat()
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _aliases(value: Any, fallback: str) -> list[str]:
    parsed: list[str] = []
    if isinstance(value, str) and value.strip():
        try:
            loaded = json.loads(value)
            if isinstance(loaded, list):
                parsed = [str(item).strip() for item in loaded if str(item).strip()]
        except json.JSONDecodeError:
            parsed = [item.strip() for item in value.split(",") if item.strip()]
    return list(dict.fromkeys([fallback, *parsed]))[:5]


def _clean_definition(value: Any) -> str:
    """Keep only the user-facing description of what the trend is.

    The reviewed workbook also contains methodology and investment caveats.
    Those remain available in the dedicated disclaimer/provenance fields and
    must not leak into the concise definition displayed by the frontend.
    """

    definition = " ".join(str(value or "").split())
    definition = re.sub(r"\b사후\s*재구성\s*", "", definition)
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", definition)
        if sentence.strip()
    ]
    descriptive = [
        sentence
        for sentence in sentences
        if not any(phrase in sentence for phrase in _DEFINITION_METHOD_PHRASES)
    ]
    return " ".join(descriptive).strip()


def _evidence(candidate: dict[str, Any], completed: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    for number in (1, 2):
        url = str(candidate.get(f"source{number}_url") or completed.get(f"evidence_{number}_url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        output.append({
            "url": url,
            "published_at": _excel_date(candidate.get(f"source{number}_date"))
            or _excel_date(candidate.get("first_observed_date"))
            or AS_OF_DATE,
            "publisher": str(candidate.get(f"source{number}_publisher") or "unknown").strip(),
            "evidence_type": str(candidate.get(f"source{number}_type") or "public_source").strip(),
            "claim": str(candidate.get(f"source{number}_title") or completed.get("trigger_event") or "event context").strip(),
        })
    return output


def _matched_keywords(company: dict[str, Any], keywords: list[dict[str, Any]]) -> list[str]:
    haystack = " ".join(
        str(company.get(field) or "")
        for field in ("connection_reason", "ontology_path", "company_description")
    ).casefold()
    return [
        str(item["text"])
        for item in keywords
        if len(str(item["text"]).strip()) >= 2
        and str(item["text"]).casefold() in haystack
    ]


def build_catalog(
    workbook: dict[str, list[list[Any]]],
    source_sha256: str,
    *,
    source_name: str = "source.xlsx",
) -> list[dict[str, Any]]:
    candidate_rows = _records(workbook["후보_원장"])
    completed_rows = _records(workbook["완성_트렌드"])
    keyword_rows = _records(workbook["키워드_5개"])
    company_rows = _records(workbook["기업연결"])
    candidates = {str(row["trend_id"]): row for row in candidate_rows}
    keywords_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    companies_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in keyword_rows:
        keywords_by_id[str(row["trend_id"])].append({
            "text": str(row.get("keyword") or "").strip(),
            "source_urls": [str(row.get("source_url") or "").strip()],
            "verification_note": str(row.get("verification_note") or "").strip(),
            "source_status": "researched",
            "affects_live_rank": False,
        })

    for row in company_rows:
        role_key, role_label, role_public = COMPANY_ROLE_MAP.get(
            str(row.get("role_category") or "").strip(),
            ("unclassified", "역할 미확정", False),
        )
        evidence_url = str(row.get("evidence_url") or "").strip()
        company = {
            "company": str(row.get("company_name") or "").strip(),
            "stock_code": str(row.get("symbol") or "").strip(),
            "market": str(row.get("exchange") or "").strip(),
            "company_description": str(row.get("company_description") or "").strip(),
            "company_role_category": role_key,
            "company_role_label": role_label,
            "company_role_public": role_public,
            "relationship_reason": str(row.get("connection_reason") or "").strip(),
            "connection_explanation": str(row.get("connection_reason") or "").strip(),
            "relation_tier": RELATION_GRADE_MAP.get(
                str(row.get("relation_grade") or "").strip(), "industry_watch"
            ),
            "source_relation_grade": str(row.get("relation_grade") or "").strip(),
            "evidence_sources": ([{"url": evidence_url, "source_status": "researched"}] if evidence_url else []),
            "ontology_path": [
                part.strip()
                for part in str(row.get("ontology_path") or "").split(">")
                if part.strip()
            ],
            "verified_in_workbook": str(row.get("verified") or "").strip().upper() == "Y",
            "provenance": "research_reconstructed",
            "affects_live_rank": False,
        }
        companies_by_id[str(row["trend_id"])].append(company)

    output = []
    for completed in completed_rows:
        trend_id = str(completed["trend_id"])
        candidate = candidates.get(trend_id, {})
        title = str(completed.get("title") or candidate.get("title") or trend_id).strip()
        source_keyword_items = sorted(
            keywords_by_id.get(trend_id, []),
            key=lambda item: item["text"].casefold(),
        )
        keyword_items = [
            item for item in source_keyword_items
            if keyword_fits_public_label(item["text"])
        ]
        company_items = companies_by_id.get(trend_id, [])
        for company in company_items:
            company["matched_keywords"] = _matched_keywords(company, keyword_items)
        evidence = _evidence(candidate, completed)
        evidence_dates = sorted(
            item["published_at"] for item in evidence if item.get("published_at")
        )
        first_observed = _excel_date(candidate.get("first_observed_date"))
        active_from = first_observed or (evidence_dates[0] if evidence_dates else AS_OF_DATE)
        active_to = max([active_from, *evidence_dates])
        peak_hint = active_to
        period_tokens = {
            token.strip() for token in str(completed.get("periods") or "").split(",")
            if token.strip()
        }
        period_presence = {
            "1w": "7d" in period_tokens,
            "1m": "30d" in period_tokens,
            "3m": "90d" in period_tokens,
        }
        public_companies = [row for row in company_items if row["company_role_public"]]
        role_categories = sorted({row["company_role_category"] for row in public_companies})
        linked_keywords = sorted({
            keyword
            for company in public_companies
            for keyword in company.get("matched_keywords") or []
        })
        missing = []
        if len(keyword_items) != len(source_keyword_items):
            missing.append("related_keywords_max_six_characters")
        if len(keyword_items) != 5:
            missing.append("related_keywords_exactly_five")
        if len(public_companies) < 10:
            missing.append("evidence_backed_listed_companies_at_least_ten")
        if not 2 <= len(role_categories) <= 4:
            missing.append("company_role_categories_between_two_and_four")
        if len(linked_keywords) < 2:
            missing.append("related_keywords_linked_to_companies_at_least_two")
        broad_category = PUBLIC_CATEGORY_MAP.get(
            str(completed.get("category") or candidate.get("category") or "").strip(),
            "culture",
        )
        aliases = _aliases(candidate.get("aliases"), title)
        output.append({
            "schema_version": SCHEMA_VERSION,
            "event_id": trend_id,
            "representative_term": title,
            "aliases": aliases,
            "category": broad_category,
            "source_category": str(completed.get("category") or "").strip(),
            "subcategories": [
                value.strip()
                for value in str(candidate.get("subcategories") or "").split(",")
                if value.strip()
            ],
            "definition": _clean_definition(completed.get("definition")),
            "why_now": str(candidate.get("why_now") or "").strip(),
            "trigger_event": str(completed.get("trigger_event") or candidate.get("trigger_event") or "").strip(),
            "active_from": active_from,
            "active_to": active_to,
            "peak_hint": peak_hint,
            "period_presence": period_presence,
            "attention_windows": [
                {
                    "key": key,
                    "label": label,
                    "status": "researched_presence" if period_presence[key] else "not_researched_in_window",
                    "percent": None,
                    "is_absolute_mention_count": False,
                }
                for key, label in (("1w", "1주"), ("1m", "1개월"), ("3m", "3개월"))
            ],
            "related_keywords": keyword_items,
            "source_related_keywords": source_keyword_items,
            "companies": company_items,
            "keyword_company_links": [
                {
                    "keyword": keyword,
                    "company": company["company"],
                    "stock_code": company["stock_code"],
                    "company_role_category": company["company_role_category"],
                    "company_role_label": company["company_role_label"],
                    "relationship_reason": company["relationship_reason"],
                    "connection_explanation": company["connection_explanation"],
                    "evidence_urls": [
                        source["url"] for source in company["evidence_sources"]
                    ],
                }
                for company in public_companies
                for keyword in company.get("matched_keywords") or []
            ],
            "disclaimer": str(completed.get("disclaimer") or "").strip(),
            "stock_impact_hypothesis": {
                "direction": str(completed.get("stock_impact_direction") or "uncertain").strip(),
                "pathway": str(completed.get("pathway") or "").strip(),
                "status": "research_hypothesis_only",
            },
            "provenance": "research_reconstructed",
            "measurement_status": "event_timing_evidence_only",
            "rank_eligible": False,
            "ranking_eligible": False,
            "mode": "demo_replay",
            "live_eligible": False,
            "ranking_effect": "none",
            "reference_kind": "research_event_timing_catalog",
            "confidence": 1.0 if len(evidence) >= 2 else 0.6,
            "evidence": evidence,
            "frontend_readiness_status": "ready" if not missing else "enrichment_pending",
            "frontend_readiness_missing": missing,
            "frontend_keyword_count": len(keyword_items),
            "frontend_company_count": len(public_companies),
            "frontend_company_role_category_count": len(role_categories),
            "linked_keyword_count": len(linked_keywords),
            "source_workbook": {
                "file_name": source_name,
                "sha256": source_sha256,
                "import_version": IMPORT_VERSION,
                "review_status": str(completed.get("publication_status") or "").strip(),
                "editor_notes": str(completed.get("editor_notes") or "").strip(),
            },
        })
    return sorted(output, key=lambda item: item["event_id"])


def import_workbook(source: Path, output_dir: Path) -> dict[str, Any]:
    source = Path(source)
    output_dir = Path(output_dir)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    workbook = read_workbook(source)
    catalog = build_catalog(workbook, source_hash, source_name=source.name)
    output_dir.mkdir(parents=True, exist_ok=True)
    events_path = output_dir / "events.ndjson"
    events_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in catalog),
        encoding="utf-8",
    )
    missing_counts = Counter(
        reason for item in catalog for reason in item["frontend_readiness_missing"]
    )
    manifest = {
        "schema_version": "trzip-reconstructed-workbook-manifest-v1",
        "dataset_id": "trzip-final-50-20260814",
        "source_file": source.name,
        "source_sha256": source_hash,
        "import_version": IMPORT_VERSION,
        "data_mode": "reconstructed",
        "live_eligible": False,
        "ranking_eligible": False,
        "ranking_effect": "none",
        "event_count": len(catalog),
        # Keep the reviewed workbook count for audit and publish only terms
        # that satisfy the six-character frontend label contract.
        "keyword_count": sum(len(item["source_related_keywords"]) for item in catalog),
        "source_keyword_count": sum(
            len(item["source_related_keywords"]) for item in catalog
        ),
        "public_keyword_count": sum(len(item["related_keywords"]) for item in catalog),
        "company_link_count": sum(len(item["companies"]) for item in catalog),
        "frontend_ready_count": sum(
            item["frontend_readiness_status"] == "ready" for item in catalog
        ),
        "frontend_missing_counts": dict(sorted(missing_counts.items())),
        "events_path": events_path.name,
    }
    manifest["events_sha256"] = hashlib.sha256(events_path.read_bytes()).hexdigest()
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
