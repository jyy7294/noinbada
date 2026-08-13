"""Build the deterministic TRZIP ontology seed from extracted workbook values.

This is an offline build tool.  The production runtime loads
``data/ontology_seed.json`` and has no XLSX or spreadsheet-library dependency.
The source workbooks describe historical cases and value-chain research; their
contents are explicitly excluded from trend observations and ranking.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "trzip-ontology-v1"
TREND_WORKBOOK = "trend-meme-stock-cases (2).xlsx"
BUSINESS_WORKBOOK = "business-relationship-kospi-value-chain-FINAL (1).xlsx"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "ontology_seed.json"

ALLOWED_TYPES = {
    "trend",
    "term",
    "entity",
    "product_service",
    "person_place",
    "industry",
    "company",
    "stock",
    "evidence",
}


def normalize_label(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(normalized.casefold().split())


def stable_token(value: Any, length: int = 16) -> str:
    return hashlib.sha256(normalize_label(value).encode("utf-8")).hexdigest()[:length]


def text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def split_ids(value: Any) -> list[str]:
    return [part.strip() for part in re.split(r"[;,]", text(value)) if part.strip()]


def excel_date(value: Any) -> str | None:
    """Convert an Excel serial or pass through an explicit date-like value."""

    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return (date(1899, 12, 30) + timedelta(days=int(value))).isoformat()
    raw = text(value)
    try:
        return datetime.fromisoformat(raw).date().isoformat()
    except ValueError:
        return raw


def padded_ticker(value: Any) -> str:
    raw = re.sub(r"\D", "", text(value))
    return raw.zfill(6) if raw else ""


def parse_company_ticker(value: Any) -> tuple[str, str] | None:
    match = re.match(r"^\s*(.*?)\s*\((\d{6})\)\s*$", text(value))
    if not match:
        return None
    return match.group(1).strip(), match.group(2)


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _sheet(workbook: Mapping[str, Any], name: str) -> list[list[Any]]:
    for sheet in workbook.get("sheets") or []:
        if sheet.get("name") == name:
            return list(sheet.get("values") or [])
    raise ValueError(f"required sheet is missing: {name}")


def _records(
    workbook: Mapping[str, Any],
    sheet_name: str,
    *,
    header_row: int,
    required: Iterable[str],
) -> list[dict[str, Any]]:
    values = _sheet(workbook, sheet_name)
    if len(values) < header_row:
        raise ValueError(f"header row is missing: {sheet_name}!{header_row}")
    headers = [text(value) for value in values[header_row - 1]]
    missing = [name for name in required if name not in headers]
    if missing:
        raise ValueError(f"missing columns in {sheet_name}: {missing}")

    records: list[dict[str, Any]] = []
    for excel_row, row in enumerate(values[header_row:], start=header_row + 1):
        if not row or not text(row[0] if row else None):
            continue
        padded = [*row, *([None] * max(0, len(headers) - len(row)))]
        record = {header: padded[index] for index, header in enumerate(headers) if header}
        record["__row__"] = excel_row
        records.append(record)
    return records


class SeedBuilder:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, Any]] = {}
        self.evidence: dict[str, dict[str, Any]] = {}
        self.stats: Counter[str] = Counter()

    def add_node(
        self,
        node_id: str,
        node_type: str,
        label: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        if node_type not in ALLOWED_TYPES:
            raise ValueError(f"unsupported node type: {node_type}")
        label = text(label)
        if not label:
            raise ValueError(f"node label is required: {node_id}")
        item = {
            "id": node_id,
            "type": node_type,
            "label": label,
            "normalized_label": normalize_label(label),
            "metadata": deepcopy(dict(metadata or {})),
        }
        existing = self.nodes.get(node_id)
        if existing is None:
            self.nodes[node_id] = item
            return node_id
        if existing["type"] != node_type:
            raise ValueError(f"node type conflict: {node_id}")
        if existing["label"] != label:
            aliases = set(existing["metadata"].get("aliases") or [])
            aliases.add(label)
            existing["metadata"]["aliases"] = sorted(aliases, key=normalize_label)
        for key, value in item["metadata"].items():
            existing["metadata"].setdefault(key, value)
        return node_id

    def add_evidence(
        self,
        evidence_id: str,
        *,
        source_id: str,
        title: str,
        publisher: str,
        url: str,
        evidence_type: str,
        summary: str,
        published_at: str | None,
        review_status: str,
        provenance: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
    ) -> str | None:
        if not text(url):
            self.stats["evidence_without_url_skipped"] += 1
            return None
        record = {
            "id": evidence_id,
            "source_id": source_id,
            "title": text(title) or source_id,
            "publisher": text(publisher),
            "url": text(url),
            "evidence_type": text(evidence_type),
            "summary": text(summary),
            "published_at": published_at,
            "review_status": review_status,
            "provenance": deepcopy(dict(provenance)),
            "metadata": deepcopy(dict(metadata or {})),
        }
        existing = self.evidence.get(evidence_id)
        if existing is not None and existing != record:
            raise ValueError(f"evidence conflict: {evidence_id}")
        self.evidence[evidence_id] = record
        self.add_node(
            evidence_id,
            "evidence",
            record["title"],
            metadata={"source_id": source_id, "url": record["url"]},
        )
        return evidence_id

    def add_edge(
        self,
        edge_id: str,
        start: str,
        end: str,
        relation_type: str,
        *,
        evidence_ids: Iterable[str],
        review_status: str,
        provenance: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
    ) -> str | None:
        resolved = sorted(
            {value for value in evidence_ids if value and value in self.evidence}
        )
        if not resolved:
            self.stats["edges_without_resolved_evidence_skipped"] += 1
            return None
        if start not in self.nodes or end not in self.nodes:
            raise ValueError(f"edge endpoint is missing: {edge_id}")
        item = {
            "id": edge_id,
            "from_node": start,
            "to_node": end,
            "relation_type": relation_type,
            "evidence_ids": resolved,
            "review_status": review_status,
            "provenance": deepcopy(dict(provenance)),
            "metadata": deepcopy(dict(metadata or {})),
        }
        existing = self.edges.get(edge_id)
        if existing is not None and existing != item:
            raise ValueError(f"edge conflict: {edge_id}")
        self.edges[edge_id] = item
        return edge_id

    def company(self, label: str, ticker: str, market: str) -> tuple[str, str]:
        ticker = padded_ticker(ticker)
        market_key = normalize_label(market).replace(" ", "-") or "unknown"
        company_id = f"company:kr:{market_key}:{ticker}"
        stock_id = f"stock:kr:{market_key}:{ticker}"
        self.add_node(
            company_id,
            "company",
            label,
            metadata={"ticker": ticker, "market": market},
        )
        self.add_node(
            stock_id,
            "stock",
            f"{ticker} ({market})",
            metadata={"ticker": ticker, "market": market},
        )
        return company_id, stock_id

    def payload(self) -> dict[str, Any]:
        nodes = sorted(self.nodes.values(), key=lambda item: item["id"])
        edges = sorted(self.edges.values(), key=lambda item: item["id"])
        evidence = sorted(self.evidence.values(), key=lambda item: item["id"])
        node_counts = Counter(item["type"] for item in nodes)
        edge_counts = Counter(item["relation_type"] for item in edges)
        return {
            "schema_version": SCHEMA_VERSION,
            "metadata": {
                "title": "TRZIP historical ontology seed",
                "language": "ko-KR",
                "source_workbooks": [TREND_WORKBOOK, BUSINESS_WORKBOOK],
                "usage": {
                    "historical_seed": True,
                    "ranking_input": False,
                    "current_trend_claim": False,
                    "description": (
                        "과거 유행 사례와 산업·기업 관계 조사 자료입니다. "
                        "현재 X·Google 관측, 점수 또는 순위를 생성하지 않습니다."
                    ),
                },
                "publication_gate": {
                    "minimum_unique_evidence_backed_companies": 3,
                    "insufficient_status": "ontology_incomplete",
                    "padding_forbidden": True,
                },
                "node_type_counts": dict(sorted(node_counts.items())),
                "edge_type_counts": dict(sorted(edge_counts.items())),
                "build_stats": dict(sorted(self.stats.items())),
            },
            "nodes": nodes,
            "edges": edges,
            "evidence": evidence,
        }


def _workbooks(extracted: Any) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if not isinstance(extracted, list):
        raise ValueError("extracted workbook JSON must be a list")
    by_name = {Path(text(book.get("path"))).name: book for book in extracted}
    try:
        return by_name[TREND_WORKBOOK], by_name[BUSINESS_WORKBOOK]
    except KeyError as exc:
        raise ValueError(f"required workbook is missing: {exc.args[0]}") from exc


def _review_status(value: Any, *, historical: bool = False) -> str:
    raw = text(value)
    if historical:
        return "historical_reference"
    if any(token in raw for token in ("승인", "공개", "완료")) and "대기" not in raw:
        return "approved"
    return "review_required"


def _source_provenance(workbook: str, sheet: str, row: int) -> dict[str, Any]:
    return {"workbook": workbook, "sheet": sheet, "row": row}


def _parse_relation_parties(value: Any, ticker_value: Any) -> tuple[list[tuple[str, str]], list[tuple[str, str]], str] | None:
    relation = text(value)
    tickers = text(ticker_value)
    arrow = "↔" if "↔" in relation and "↔" in tickers else "→" if "→" in relation and "→" in tickers else ""
    if not arrow:
        return None
    left_names_raw, right_names_raw = (part.strip() for part in relation.split(arrow, 1))
    left_tickers_raw, right_tickers_raw = (part.strip() for part in tickers.split(arrow, 1))

    def pair(names_raw: str, codes_raw: str) -> list[tuple[str, str]] | None:
        codes = [padded_ticker(item) for item in codes_raw.split("·") if padded_ticker(item)]
        if len(codes) == 1:
            names = [names_raw]
        else:
            names = [item.strip() for item in names_raw.split("·") if item.strip()]
        if len(names) != len(codes):
            return None
        if any("파트너" in name for name in names):
            return None
        return list(zip(names, codes, strict=True))

    left = pair(left_names_raw, left_tickers_raw)
    right = pair(right_names_raw, right_tickers_raw)
    if not left or not right:
        return None
    return left, right, "bidirectional" if arrow == "↔" else "directed"


def build_seed(extracted: Any) -> dict[str, Any]:
    trend_book, business_book = _workbooks(extracted)
    builder = SeedBuilder()

    trend_sources = _records(
        trend_book,
        "03_출처",
        header_row=4,
        required=("출처ID", "발행처", "제목·활용 내용", "URL", "유형"),
    )
    trend_evidence_by_source: dict[str, str] = {}
    for row in trend_sources:
        source_id = text(row["출처ID"])
        evidence_id = f"evidence:trend:{source_id.casefold()}"
        added = builder.add_evidence(
            evidence_id,
            source_id=source_id,
            title=text(row["제목·활용 내용"]),
            publisher=text(row["발행처"]),
            url=text(row["URL"]),
            evidence_type=text(row["유형"]),
            summary=text(row["제목·활용 내용"]),
            published_at=excel_date(row.get("발행일(최신순)")),
            review_status="historical_reference",
            provenance=_source_provenance(TREND_WORKBOOK, "03_출처", row["__row__"]),
        )
        if added:
            trend_evidence_by_source[source_id] = added

    business_evidence_rows = _records(
        business_book,
        "03_근거원장",
        header_row=5,
        required=(
            "근거ID",
            "근거구분",
            "KOSPI업종ID",
            "기업·관계",
            "티커",
            "URL",
            "근거 문장·요약",
            "검수 상태",
        ),
    )
    business_evidence_by_source: dict[str, str] = {}
    for row in business_evidence_rows:
        source_id = text(row["근거ID"])
        evidence_id = f"evidence:business:{source_id.casefold()}"
        added = builder.add_evidence(
            evidence_id,
            source_id=source_id,
            title=text(row.get("문서·페이지 제목")) or source_id,
            publisher=text(row.get("기업·관계")),
            url=text(row["URL"]),
            evidence_type=text(row.get("출처 유형")) or text(row["근거구분"]),
            summary=text(row["근거 문장·요약"]),
            published_at=excel_date(row.get("기준 시점")),
            review_status=_review_status(row["검수 상태"]),
            provenance=_source_provenance(BUSINESS_WORKBOOK, "03_근거원장", row["__row__"]),
            metadata={
                "proof_scope": text(row.get("증명 범위")),
                "review_note": text(row.get("검수 메모")),
            },
        )
        if added:
            business_evidence_by_source[source_id] = added

    industry_rows = _records(
        business_book,
        "01_업종마스터",
        header_row=5,
        required=("업종ID", "KRX 세부업종", "대표 검색어", "대표 근거ID"),
    )
    for row in industry_rows:
        industry_id = text(row["업종ID"])
        builder.add_node(
            f"industry:{industry_id.casefold()}",
            "industry",
            text(row["KRX 세부업종"]),
            metadata={
                "industry_id": industry_id,
                "krx_group": text(row.get("KRX 상위분류")),
                "ksic": text(row.get("KSIC 대응")),
                "representative_terms": text(row.get("대표 검색어")),
                "outputs": text(row.get("핵심 산출물")),
                "description": text(row.get("산업 설명")),
                "examples": text(row.get("실제 상품·서비스 예시")),
                "review_status": _review_status(row.get("검수 상태")),
                "public_status": text(row.get("공개 상태")),
                "representative_evidence_ids": split_ids(row.get("대표 근거ID")),
            },
        )

    industry_relation_rows = _records(
        business_book,
        "02_관계원장",
        header_row=5,
        required=(
            "관계ID",
            "공급업종ID",
            "수요업종ID",
            "관계유형",
            "분류 근거 URL",
            "검수 상태",
        ),
    )
    for row in industry_relation_rows:
        relation_id = text(row["관계ID"])
        evidence_id = builder.add_evidence(
            f"evidence:industry:{relation_id.casefold()}",
            source_id=relation_id,
            title=f"{text(row.get('공급업종'))} → {text(row.get('수요업종'))} 산업 구조",
            publisher="KRX 분류 기반 팀 분석",
            url=text(row["분류 근거 URL"]),
            evidence_type="industry_structure_analysis",
            summary=text(row.get("근거 수준·주의")),
            published_at=None,
            review_status=_review_status(row["검수 상태"]),
            provenance=_source_provenance(BUSINESS_WORKBOOK, "02_관계원장", row["__row__"]),
            metadata={"specific_company_transaction": False},
        )
        builder.add_edge(
            f"edge:industry:{relation_id.casefold()}",
            f"industry:{text(row['공급업종ID']).casefold()}",
            f"industry:{text(row['수요업종ID']).casefold()}",
            "industry_structure_supply",
            evidence_ids=(evidence_id,) if evidence_id else (),
            review_status=_review_status(row["검수 상태"]),
            provenance=_source_provenance(BUSINESS_WORKBOOK, "02_관계원장", row["__row__"]),
            metadata={
                "relation_label": text(row["관계유형"]),
                "transferred_object": text(row.get("전달 대상")),
                "layer": text(row.get("관계 레이어")),
                "structure_only": True,
                "company_transaction": False,
                "public_status": text(row.get("공개 상태")),
            },
        )

    trend_rows = _records(
        trend_book,
        "01_유행이벤트",
        header_row=5,
        required=("이벤트ID", "유행·트렌드·밈", "출처ID"),
    )
    term_by_event: dict[str, str] = {}
    for row in trend_rows:
        event_id = text(row["이벤트ID"])
        label = text(row["유행·트렌드·밈"])
        trend_id = f"trend:historical:{event_id.casefold()}"
        term_id = f"term:{stable_token(label)}"
        builder.add_node(
            trend_id,
            "trend",
            label,
            metadata={
                "event_id": event_id,
                "year": row.get("연도"),
                "category": text(row.get("대분류")),
                "subcategory": text(row.get("소분류")),
                "why_spread": text(row.get("왜 유행했나")),
                "platform_context": text(row.get("주요 플랫폼·확산권역")),
                "historical_only": True,
                "ranking_input": False,
            },
        )
        builder.add_node(
            term_id,
            "term",
            label,
            metadata={"observed_as_written": True, "historical_only": True},
        )
        term_by_event[event_id] = term_id
        evidence_ids = [
            trend_evidence_by_source[source_id]
            for source_id in split_ids(row["출처ID"])
            if source_id in trend_evidence_by_source
        ]
        builder.add_edge(
            f"edge:trend-term:{event_id.casefold()}",
            trend_id,
            term_id,
            "represented_by",
            evidence_ids=evidence_ids,
            review_status="historical_reference",
            provenance=_source_provenance(TREND_WORKBOOK, "01_유행이벤트", row["__row__"]),
            metadata={"representative_term_is_source_label": True},
        )

    reaction_rows = _records(
        trend_book,
        "02_종목반응",
        header_row=5,
        required=("사례ID", "이벤트ID", "기업·티커", "시장", "출처ID", "판정"),
    )
    for row in reaction_rows:
        parsed = parse_company_ticker(row["기업·티커"])
        event_id = text(row["이벤트ID"])
        term_id = term_by_event.get(event_id)
        if parsed is None or term_id is None:
            builder.stats["historical_company_rows_unparsed"] += 1
            continue
        evidence_ids = [
            trend_evidence_by_source[source_id]
            for source_id in split_ids(row["출처ID"])
            if source_id in trend_evidence_by_source
        ]
        if not evidence_ids:
            builder.stats["historical_company_rows_without_evidence"] += 1
            continue
        company_label, ticker = parsed
        company_id, stock_id = builder.company(company_label, ticker, text(row["시장"]))
        case_id = text(row["사례ID"]).casefold()
        edge_case_id = f"{case_id}:row-{row['__row__']}"
        provenance = _source_provenance(TREND_WORKBOOK, "02_종목반응", row["__row__"])
        builder.add_edge(
            f"edge:term-company:{edge_case_id}",
            term_id,
            company_id,
            "historical_business_link",
            evidence_ids=evidence_ids,
            review_status="historical_reference",
            provenance=provenance,
            metadata={
                "event_id": event_id,
                "case_id": text(row["사례ID"]),
                "business_connection": text(row.get("기업 연결")),
                "relation_note": text(row.get("기업 연결·경계 메모")),
                "verdict": text(row["판정"]),
                "price_direction": text(row.get("방향")),
                "not_a_buy_signal": True,
            },
        )
        builder.add_edge(
            f"edge:company-stock:historical:{edge_case_id}",
            company_id,
            stock_id,
            "listed_as",
            evidence_ids=evidence_ids,
            review_status="historical_reference",
            provenance=provenance,
            metadata={"market": text(row["시장"])},
        )

    # Official company-business evidence establishes company-to-industry scope,
    # but remains review_required because the workbook marks it 2nd-review pending.
    for row in business_evidence_rows:
        source_id = text(row["근거ID"])
        if not source_id.startswith("SRC-"):
            continue
        evidence_id = business_evidence_by_source.get(source_id)
        ticker = padded_ticker(row.get("티커"))
        company_label = text(row.get("기업·관계"))
        industry_id = text(row.get("KOSPI업종ID"))
        if not evidence_id or not ticker or not company_label or not industry_id:
            builder.stats["company_business_rows_unusable"] += 1
            continue
        company_id, stock_id = builder.company(company_label, ticker, "KOSPI")
        status = _review_status(row.get("검수 상태"))
        provenance = _source_provenance(BUSINESS_WORKBOOK, "03_근거원장", row["__row__"])
        builder.add_edge(
            f"edge:company-industry:{source_id.casefold()}",
            company_id,
            f"industry:{industry_id.casefold()}",
            "operates_in_industry",
            evidence_ids=(evidence_id,),
            review_status=status,
            provenance=provenance,
            metadata={"proof_scope": text(row.get("증명 범위"))},
        )
        builder.add_edge(
            f"edge:company-stock:business:{source_id.casefold()}",
            company_id,
            stock_id,
            "listed_as",
            evidence_ids=(evidence_id,),
            review_status=status,
            provenance=provenance,
        )

    # Only parse explicit company-company evidence.  Ambiguous generic parties
    # stay as evidence records and never become inferred company nodes or edges.
    for row in business_evidence_rows:
        source_id = text(row["근거ID"])
        if not source_id.startswith("REL-"):
            continue
        evidence_id = business_evidence_by_source.get(source_id)
        parsed = _parse_relation_parties(row.get("기업·관계"), row.get("티커"))
        if not evidence_id or parsed is None:
            builder.stats["company_relationship_rows_unparsed"] += 1
            continue
        left, right, direction = parsed
        status = _review_status(row.get("검수 상태"))
        provenance = _source_provenance(BUSINESS_WORKBOOK, "03_근거원장", row["__row__"])
        pair_index = 0
        for left_name, left_ticker in left:
            left_company, left_stock = builder.company(left_name, left_ticker, "KOSPI")
            builder.add_edge(
                f"edge:company-stock:relation:{source_id.casefold()}:left:{pair_index}",
                left_company,
                left_stock,
                "listed_as",
                evidence_ids=(evidence_id,),
                review_status=status,
                provenance=provenance,
            )
            for right_name, right_ticker in right:
                right_company, right_stock = builder.company(right_name, right_ticker, "KOSPI")
                builder.add_edge(
                    f"edge:company-stock:relation:{source_id.casefold()}:right:{pair_index}",
                    right_company,
                    right_stock,
                    "listed_as",
                    evidence_ids=(evidence_id,),
                    review_status=status,
                    provenance=provenance,
                )
                builder.add_edge(
                    f"edge:company-company:{source_id.casefold()}:{pair_index}",
                    left_company,
                    right_company,
                    "documented_business_relationship",
                    evidence_ids=(evidence_id,),
                    review_status=status,
                    provenance=provenance,
                    metadata={
                        "direction": direction,
                        "proof_scope": text(row.get("증명 범위")),
                        "relationship_label": text(row.get("기업·관계")),
                    },
                )
                pair_index += 1

    builder.stats["historical_trend_rows"] = len(trend_rows)
    builder.stats["historical_stock_reaction_rows"] = len(reaction_rows)
    builder.stats["trend_source_rows"] = len(trend_sources)
    builder.stats["industry_rows"] = len(industry_rows)
    builder.stats["industry_structure_rows"] = len(industry_relation_rows)
    builder.stats["business_evidence_rows"] = len(business_evidence_rows)
    return builder.payload()


def build_seed_from_file(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return build_seed(json.load(handle))


def write_seed(payload: Mapping[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_json(payload), encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-json",
        type=Path,
        required=True,
        help="Path to the reviewed, workbook-derived ontology source JSON.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_seed_from_file(args.source_json)
    target = write_seed(payload, args.output)
    print(
        json.dumps(
            {
                "output": str(target),
                "nodes": len(payload["nodes"]),
                "edges": len(payload["edges"]),
                "evidence": len(payload["evidence"]),
                "build_stats": payload["metadata"]["build_stats"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
