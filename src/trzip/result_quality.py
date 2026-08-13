from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .company_roles import COMPANY_ROLE_LABELS
from .hourly_store import ELIGIBLE_COLLECTOR_SQL
from .ontology import MINIMUM_FRONTEND_COMPANIES


def record_publication_receipt(
    path: Path, *, observed_at: str, publication_id: str, remote_sha: str,
    contract: dict | None = None, source_gate: dict | None = None,
) -> None:
    """Persist proof that the exact hourly publication reached the remote."""

    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS publication_receipts (
                observed_at TEXT PRIMARY KEY,
                publication_id TEXT NOT NULL,
                remote_sha TEXT NOT NULL,
                verified_at TEXT NOT NULL,
                contract_json TEXT,
                source_gate_json TEXT
            )
            """
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(publication_receipts)")}
        if "contract_json" not in columns:
            connection.execute("ALTER TABLE publication_receipts ADD COLUMN contract_json TEXT")
        if "source_gate_json" not in columns:
            connection.execute("ALTER TABLE publication_receipts ADD COLUMN source_gate_json TEXT")
        existing = connection.execute(
            "SELECT publication_id, remote_sha FROM publication_receipts WHERE observed_at=?",
            (observed_at,),
        ).fetchone()
        if existing:
            if existing != (publication_id, remote_sha):
                raise ValueError(
                    "an immutable publication receipt already exists for this observed_at"
                )
            return
        connection.execute(
            """
            INSERT INTO publication_receipts(
                observed_at, publication_id, remote_sha, verified_at,
                contract_json, source_gate_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                observed_at,
                publication_id,
                remote_sha,
                datetime.now(UTC).isoformat(),
                json.dumps(contract, ensure_ascii=False, separators=(",", ":")) if contract else None,
                json.dumps(source_gate, ensure_ascii=False, separators=(",", ":"))
                if source_gate else None,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _publication_receipt(path: Path, observed_at: str) -> dict:
    connection = sqlite3.connect(path)
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='publication_receipts'"
        ).fetchone()
        columns = set() if not exists else {
            column[1] for column in connection.execute("PRAGMA table_info(publication_receipts)")
        }
        contract_expression = "contract_json" if "contract_json" in columns else "NULL"
        source_expression = "source_gate_json" if "source_gate_json" in columns else "NULL"
        row = None if not exists else connection.execute(
            f"SELECT publication_id, remote_sha, verified_at, {contract_expression}, "
            f"{source_expression} "
            "FROM publication_receipts WHERE observed_at=?",
            (observed_at,),
        ).fetchone()
    finally:
        connection.close()
    if not row:
        return {"passed": False, "publication_id": None, "remote_sha": None, "verified_at": None}
    contract = json.loads(row[3]) if row[3] else None
    source_gate = json.loads(row[4]) if row[4] else None
    return {
        "passed": bool(
            row[0] and row[1]
            and contract and contract.get("passed") is True
            and source_gate and source_gate.get("passed") is True
        ),
        "publication_id": row[0],
        "remote_sha": row[1],
        "verified_at": row[2],
        "contract": contract,
        "source_gate": source_gate,
    }


def evaluate_frontend_result(intelligence: dict) -> dict:
    """Evaluate the completed frontend contract without recomputing rank."""

    top = list(intelligence.get("home_top10") or [])
    failures: list[str] = []
    if len(top) != 10:
        failures.append(f"home_top10_count:{len(top)}")
    if [item.get("publication_rank") for item in top] != list(range(1, len(top) + 1)):
        failures.append("publication_rank_not_contiguous")
    event_keys = [str(item.get("event_key") or "") for item in top]
    if not all(event_keys) or len(event_keys) != len(set(event_keys)):
        failures.append("duplicate_or_empty_event_key")
    food_count = sum(item.get("broad_category") == "food" for item in top)
    if food_count > 1:
        failures.append(f"food_category_count:{food_count}")

    trend_checks = []
    for item in top:
        name = str(item.get("display_name") or item.get("event_key") or "")
        keywords = list(item.get("related_keywords") or item.get("keywords") or [])
        companies = list(item.get("companies") or [])
        unique_codes = {str(company.get("stock_code") or "").strip() for company in companies}
        item_failures = []
        if len(keywords) != 5:
            item_failures.append(f"keyword_count:{len(keywords)}")
        if len(unique_codes) < MINIMUM_FRONTEND_COMPANIES or "" in unique_codes:
            item_failures.append(f"company_count:{len(unique_codes - {''})}")
        for company in companies:
            evidence_urls = [
                str(source.get("url") or "").strip()
                for source in company.get("evidence_sources") or []
                if isinstance(source, dict)
            ]
            if not all((
                str(company.get("company") or "").strip(),
                str(company.get("stock_code") or "").strip(),
                str(company.get("market") or "").strip(),
                str(company.get("company_description") or "").strip(),
                str(company.get("relationship_reason") or "").strip(),
                str(company.get("company_role_category") or "").strip(),
                str(company.get("company_role_label") or "").strip(),
                any(evidence_urls),
                company.get("ontology_complete") is True,
            )):
                item_failures.append(f"incomplete_company:{company.get('company')}")
            role_category = str(company.get("company_role_category") or "")
            if COMPANY_ROLE_LABELS.get(role_category) != company.get("company_role_label"):
                item_failures.append(f"invalid_company_role:{company.get('company')}")
        if item.get("frontend_readiness_status") != "ready":
            item_failures.append("frontend_not_ready")
        failures.extend(f"{name}:{reason}" for reason in item_failures)
        trend_checks.append({
            "publication_rank": item.get("publication_rank"),
            "display_name": name,
            "observed_rank": item.get("observed_rank"),
            "keyword_count": len(keywords),
            "company_count": len(unique_codes - {""}),
            "role_categories": sorted({
                str(company.get("company_role_category") or "") for company in companies
            }),
            "passed": not item_failures,
        })
    return {
        "policy_version": "frontend-result-quality-v1",
        "passed": not failures,
        "trend_count": len(top),
        "required_trend_count": 10,
        "required_keyword_count": 5,
        "minimum_company_count": MINIMUM_FRONTEND_COMPANIES,
        "failures": failures,
        "trends": trend_checks,
        "ranking_effect": "none",
    }


def _source_gate(path: Path, observed_at: str) -> dict:
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            """
            SELECT source, COUNT(*) AS row_count,
                   COUNT(DISTINCT topic) AS unique_topics,
                   COUNT(DISTINCT source_rank) AS unique_ranks,
                   MIN(source_rank) AS minimum_rank,
                   MAX(source_rank) AS maximum_rank,
                   SUM(CASE WHEN provenance='observed' THEN 1 ELSE 0 END) AS observed_rows
            FROM hourly_observations
            WHERE observed_at=? AND source IN ('x', 'google_trends')
              AND provenance='observed'
              AND {ELIGIBLE_COLLECTOR_SQL}
            GROUP BY source
            """.format(ELIGIBLE_COLLECTOR_SQL=ELIGIBLE_COLLECTOR_SQL),
            (observed_at,),
        ).fetchall()
    finally:
        connection.close()
    sources = {
        source: {
            "row_count": row_count,
            "unique_topics": unique_topics,
            "unique_ranks": unique_ranks,
            "minimum_rank": minimum_rank,
            "maximum_rank": maximum_rank,
            "observed_rows": observed_rows,
        }
        for source, row_count, unique_topics, unique_ranks,
        minimum_rank, maximum_rank, observed_rows in rows
    }
    x = sources.get("x") or {}
    google = sources.get("google_trends") or {}
    passed = (
        x.get("row_count") == 30
        and x.get("unique_topics") == 30
        and x.get("unique_ranks") == 30
        and x.get("minimum_rank") == 1
        and x.get("maximum_rank") == 30
        and x.get("observed_rows") == 30
        and int(google.get("row_count") or 0) > 0
        and google.get("row_count") == google.get("unique_topics") == google.get("observed_rows")
        and google.get("unique_ranks") == google.get("row_count")
        and google.get("minimum_rank") == 1
        and google.get("maximum_rank") == google.get("row_count")
    )
    return {"passed": passed, "sources": sources}


def evaluate_actual_hour(path: Path, at: datetime) -> dict:
    from .editorial_review import apply_frontend_enrichment_cache
    from .intelligence import build_intelligence, refresh_frontend_readiness

    normalized = at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    stamp = normalized.isoformat()
    publication = _publication_receipt(path, stamp)
    source_gate = publication.get("source_gate") or _source_gate(path, stamp)
    contract = publication.get("contract")
    if contract is None:
        intelligence = build_intelligence(normalized, hours=24, path=path)
        apply_frontend_enrichment_cache(intelligence, verified_at=stamp)
        refresh_frontend_readiness(intelligence)
        contract = evaluate_frontend_result(intelligence)
    return {
        "observed_at": stamp,
        "passed": source_gate["passed"] and contract["passed"] and publication["passed"],
        "source_gate": source_gate,
        "contract": contract,
        "publication": publication,
    }


def evaluate_consecutive_hours(path: Path, *, end: datetime, count: int = 3) -> dict:
    hours = [end - timedelta(hours=offset) for offset in reversed(range(count))]
    evaluations = [evaluate_actual_hour(path, at) for at in hours]
    current_streak = 0
    for row in reversed(evaluations):
        if not row["passed"]:
            break
        current_streak += 1
    return {
        "policy_version": "consecutive-actual-result-v1",
        "required_consecutive_hours": count,
        "passed": len(evaluations) == count and all(row["passed"] for row in evaluations),
        "current_consecutive_success_count": current_streak,
        "remaining_success_hours": max(0, count - current_streak),
        "evaluations": evaluations,
        "ranking_effect": "none",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit consecutive actual TRZIP frontend results")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--end", type=datetime.fromisoformat, required=True)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--record-publication", action="store_true")
    parser.add_argument("--publication-id")
    parser.add_argument("--remote-sha")
    parser.add_argument("--intelligence", type=Path)
    args = parser.parse_args()
    if args.record_publication:
        if not args.publication_id or not args.remote_sha:
            parser.error("--record-publication requires --publication-id and --remote-sha")
        if not args.intelligence:
            parser.error("--record-publication requires --intelligence")
        intelligence = json.loads(args.intelligence.read_text(encoding="utf-8"))
        if intelligence.get("publication_id") != args.publication_id:
            parser.error("--intelligence publication_id does not match --publication-id")
        contract = evaluate_frontend_result(intelligence)
        source_gate = _source_gate(args.database, args.end.astimezone(UTC).replace(
            minute=0, second=0, microsecond=0
        ).isoformat())
        record_publication_receipt(
            args.database,
            observed_at=args.end.astimezone(UTC).replace(minute=0, second=0, microsecond=0).isoformat(),
            publication_id=args.publication_id,
            remote_sha=args.remote_sha,
            contract=contract,
            source_gate=source_gate,
        )
    result = evaluate_consecutive_hours(args.database, end=args.end, count=args.count)
    encoded = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_bytes(encoded)
        temporary.replace(args.output)
    print(encoded.decode("utf-8"))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
