from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .company_roles import COMPANY_ROLE_LABELS
from .hourly_store import ELIGIBLE_COLLECTOR_SQL
from .ontology import MINIMUM_FRONTEND_COMPANIES


PUBLIC_BROAD_CATEGORIES = {
    "food", "content", "sports", "lifestyle", "culture",
    "consumer", "technology", "market",
}


def record_publication_receipt(
    path: Path, *, observed_at: str, publication_id: str, remote_sha: str,
    contract: dict | None = None, source_gate: dict | None = None,
    manifest_sha256: str | None = None, remote_manifest_blob: str | None = None,
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
                source_gate_json TEXT,
                manifest_sha256 TEXT,
                remote_manifest_blob TEXT
            )
            """
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(publication_receipts)")}
        if "contract_json" not in columns:
            connection.execute("ALTER TABLE publication_receipts ADD COLUMN contract_json TEXT")
        if "source_gate_json" not in columns:
            connection.execute("ALTER TABLE publication_receipts ADD COLUMN source_gate_json TEXT")
        if "manifest_sha256" not in columns:
            connection.execute("ALTER TABLE publication_receipts ADD COLUMN manifest_sha256 TEXT")
        if "remote_manifest_blob" not in columns:
            connection.execute("ALTER TABLE publication_receipts ADD COLUMN remote_manifest_blob TEXT")
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
                contract_json, source_gate_json, manifest_sha256, remote_manifest_blob
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observed_at,
                publication_id,
                remote_sha,
                datetime.now(UTC).isoformat(),
                json.dumps(contract, ensure_ascii=False, separators=(",", ":")) if contract else None,
                json.dumps(source_gate, ensure_ascii=False, separators=(",", ":"))
                if source_gate else None,
                manifest_sha256,
                remote_manifest_blob,
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
        manifest_expression = "manifest_sha256" if "manifest_sha256" in columns else "NULL"
        blob_expression = "remote_manifest_blob" if "remote_manifest_blob" in columns else "NULL"
        row = None if not exists else connection.execute(
            f"SELECT publication_id, remote_sha, verified_at, {contract_expression}, "
            f"{source_expression}, {manifest_expression}, {blob_expression} "
            "FROM publication_receipts WHERE observed_at=?",
            (observed_at,),
        ).fetchone()
    finally:
        connection.close()
    if not row:
        return {"passed": False, "publication_id": None, "remote_sha": None, "verified_at": None}
    contract = json.loads(row[3]) if row[3] else None
    source_gate = json.loads(row[4]) if row[4] else None
    manifest_sha256 = row[5]
    remote_manifest_blob = row[6]
    return {
        "passed": bool(
            row[0] and row[1]
            and contract and contract.get("passed") is True
            and source_gate and source_gate.get("passed") is True
            and isinstance(manifest_sha256, str) and len(manifest_sha256) == 64
            and isinstance(remote_manifest_blob, str) and len(remote_manifest_blob) in {40, 64}
        ),
        "publication_id": row[0],
        "remote_sha": row[1],
        "verified_at": row[2],
        "contract": contract,
        "source_gate": source_gate,
        "manifest_sha256": manifest_sha256,
        "remote_manifest_blob": remote_manifest_blob,
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
        if item.get("broad_category") not in PUBLIC_BROAD_CATEGORIES:
            item_failures.append(f"invalid_category:{item.get('broad_category')}")
        if not str(item.get("trend_definition") or "").strip():
            item_failures.append("missing_trend_definition")
        if len(keywords) != 5:
            item_failures.append(f"keyword_count:{len(keywords)}")
        keyword_texts = [str(keyword.get("text") or "").strip() for keyword in keywords]
        normalized_keyword_texts = {" ".join(text.casefold().split()) for text in keyword_texts}
        if not all(keyword_texts) or len(normalized_keyword_texts) != len(keyword_texts):
            item_failures.append("empty_or_duplicate_keyword")
        if any(not list(keyword.get("source") or []) for keyword in keywords):
            item_failures.append("keyword_without_source")
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
                isinstance(company.get("ontology_path"), list)
                and len(company.get("ontology_path")) >= 2,
                str(company.get("relation_tier") or "").strip(),
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
        "policy_version": "frontend-result-quality-v2",
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
    with sqlite3.connect(path) as evidence_connection:
        x_payload_rows = evidence_connection.execute(
            "SELECT source_payload_json FROM hourly_observations "
            "WHERE observed_at=? AND source='x' AND provenance='observed' "
            f"AND {ELIGIBLE_COLLECTOR_SQL} ORDER BY source_rank",
            (observed_at,),
        ).fetchall()
    evidence_payloads = []
    for payload_row in x_payload_rows:
        try:
            evidence_payloads.append(json.loads(payload_row[0]) if payload_row[0] else {})
        except (TypeError, ValueError, json.JSONDecodeError):
            evidence_payloads.append({})
    x_evidence = evidence_payloads[0] if evidence_payloads else {}
    x["collection_evidence"] = {
        key: x_evidence.get(key)
        for key in (
            "collector", "transport", "profile", "region", "region_verified",
            "observed_at", "scheduled_for", "schedule_delay_seconds",
        )
    }
    try:
        scheduled_at = datetime.fromisoformat(str(x_evidence.get("scheduled_for")))
        actually_observed_at = datetime.fromisoformat(str(x_evidence.get("observed_at")))
        reported_delay = float(x_evidence.get("schedule_delay_seconds"))
        actual_delay = (actually_observed_at - scheduled_at).total_seconds()
        timing_passed = (
            scheduled_at.tzinfo is not None
            and actually_observed_at.tzinfo is not None
            and 0 <= actual_delay <= 900
            and abs(reported_delay - actual_delay) <= 1
        )
    except (TypeError, ValueError, OverflowError):
        timing_passed = False
    evidence_consistent = (
        len(evidence_payloads) == 30
        and all(payload == x_evidence for payload in evidence_payloads)
    )
    x_evidence_passed = (
        x_evidence.get("collector") == "codex_chrome_current_session"
        and x_evidence.get("transport") == "codex_browser_snapshot"
        and x_evidence.get("profile") == "current_logged_in_chrome"
        and x_evidence.get("region") == "KR"
        and x_evidence.get("region_verified") is True
        and x_evidence.get("scheduled_for") == observed_at
        and timing_passed
        and evidence_consistent
    )
    x["collection_evidence"]["evidence_row_count"] = len(evidence_payloads)
    x["collection_evidence"]["evidence_consistent"] = evidence_consistent
    x["collection_evidence"]["timing_verified"] = timing_passed
    passed = (
        x.get("row_count") == 30
        and x.get("unique_topics") == 30
        and x.get("unique_ranks") == 30
        and x.get("minimum_rank") == 1
        and x.get("maximum_rank") == 30
        and x.get("observed_rows") == 30
        and x_evidence_passed
        and int(google.get("row_count") or 0) > 0
        and google.get("row_count") == google.get("unique_topics") == google.get("observed_rows")
        and google.get("unique_ranks") == google.get("row_count")
        and google.get("minimum_rank") == 1
        and google.get("maximum_rank") == google.get("row_count")
    )
    return {
        "policy_version": "hourly-source-proof-v2",
        "passed": passed,
        "sources": sources,
    }


def evaluate_actual_hour(path: Path, at: datetime) -> dict:
    from .editorial_review import apply_frontend_enrichment_cache
    from .intelligence import build_intelligence, refresh_frontend_readiness

    normalized = at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    stamp = normalized.isoformat()
    publication = _publication_receipt(path, stamp)
    source_gate = publication.get("source_gate") or _source_gate(path, stamp)
    if source_gate.get("policy_version") != "hourly-source-proof-v2":
        source_gate = {
            **source_gate,
            "passed": False,
            "failure": "legacy_source_gate_policy",
        }
    contract = publication.get("contract")
    if contract is not None and contract.get("policy_version") != "frontend-result-quality-v2":
        contract = {
            **contract,
            "passed": False,
            "failure": "legacy_frontend_result_policy",
        }
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
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--remote-manifest-blob")
    args = parser.parse_args()
    if args.record_publication:
        if not args.publication_id or not args.remote_sha:
            parser.error("--record-publication requires --publication-id and --remote-sha")
        if not args.intelligence or not args.manifest or not args.remote_manifest_blob:
            parser.error(
                "--record-publication requires --intelligence, --manifest, and --remote-manifest-blob"
            )
        if len(args.remote_manifest_blob) not in {40, 64} or any(
            char not in "0123456789abcdef" for char in args.remote_manifest_blob.lower()
        ):
            parser.error("--remote-manifest-blob must be a Git object id")
        intelligence = json.loads(args.intelligence.read_text(encoding="utf-8"))
        if intelligence.get("publication_id") != args.publication_id:
            parser.error("--intelligence publication_id does not match --publication-id")
        manifest_bytes = args.manifest.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        normalized_end = args.end.astimezone(UTC).replace(
            minute=0, second=0, microsecond=0
        ).isoformat()
        if (
            manifest.get("publication_id") != args.publication_id
            or manifest.get("observed_at") != normalized_end
        ):
            parser.error("--manifest does not match publication id and observed hour")
        contract = evaluate_frontend_result(intelligence)
        source_gate = _source_gate(args.database, normalized_end)
        record_publication_receipt(
            args.database,
            observed_at=args.end.astimezone(UTC).replace(minute=0, second=0, microsecond=0).isoformat(),
            publication_id=args.publication_id,
            remote_sha=args.remote_sha,
            contract=contract,
            source_gate=source_gate,
            manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            remote_manifest_blob=args.remote_manifest_blob.lower(),
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
