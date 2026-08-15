from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from .company_roles import COMPANY_ROLE_LABELS
from .hourly_store import ELIGIBLE_COLLECTOR_SQL
from .keyword_policy import keyword_fits_public_label
from .ontology import MINIMUM_FRONTEND_COMPANIES
from .presentation_feed import (
    LOGO_ASSET_VERIFICATION,
    LOGO_QUALITY_POLICY,
    logo_asset_contract_is_valid,
    logo_display_contract_is_valid,
)
from .readiness import MVP_CONSECUTIVE_SOURCE_HOURS


PUBLIC_BROAD_CATEGORIES = {
    "food", "content", "sports", "lifestyle", "culture",
    "consumer", "technology", "market",
}
PUBLIC_RELATION_TIERS = {"direct", "value_chain", "industry_watch"}
HOURLY_VALIDATION_RECEIPT_POLICY = "hourly-local-validation-receipt-v1"
CURRENT_FRONTEND_RESULT_POLICIES = {
    "frontend-result-quality-v7",  # canonical rank-free home_feed
    "frontend-result-quality-v8",  # reviewed presentation_feed frontend
}


def _is_git_or_sha256_hex(value: object, lengths: set[int]) -> bool:
    text = str(value or "").strip().casefold()
    return len(text) in lengths and all(char in "0123456789abcdef" for char in text)


def _valid_public_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _presentation_logo_contract_is_valid(company: dict) -> bool:
    """Validate a v3 logo row without requiring a deliberately blank image URL.

    The display policy has three valid modes: a verified sharp image, a
    browser-probed official-domain icon, or initials when the only reviewed
    raster is too small.  Initials are a quality-preserving result, not a
    missing-logo state.
    """

    company_name = str(company.get("company") or "").strip()
    official_domain = str(company.get("official_domain") or "").strip().casefold()
    mode = str(company.get("logo_render_mode") or "").strip()
    logo_url = str(company.get("logo_url") or "").strip()
    if (
        not company_name
        or not official_domain
        or "." not in official_domain
        or "/" in official_domain
        or not str(company.get("logo_asset_host") or "").strip()
        or company.get("logo_asset_verification") != LOGO_ASSET_VERIFICATION
        or company.get("logo_quality_policy") != LOGO_QUALITY_POLICY
        or not logo_display_contract_is_valid(company)
    ):
        return False
    if mode == "initials":
        return (
            company.get("logo_asset_source") == "initials_fallback"
            and not logo_url
            and _valid_public_url(
                str(company.get("logo_rejected_asset_url") or "").strip()
            )
        )
    if mode == "image":
        expected_source = "official_page_asset"
    elif mode == "runtime_probe":
        expected_source = "official_domain_declared_favicon"
    else:
        return False
    return (
        company.get("logo_asset_source") == expected_source
        and _valid_public_url(logo_url)
        and logo_asset_contract_is_valid(company_name, official_domain, logo_url)
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _normalized_exact_hour(value: str | datetime) -> tuple[datetime, str]:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        raise ValueError("hourly validation time must include a timezone")
    normalized = parsed.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    if parsed.astimezone(UTC) != normalized:
        raise ValueError("hourly validation time must be an exact UTC hour")
    return normalized, normalized.isoformat()


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def _ensure_hourly_validation_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS hourly_validation_receipts (
            observed_at TEXT PRIMARY KEY,
            validated_at TEXT NOT NULL,
            policy_version TEXT NOT NULL,
            publication_id TEXT NOT NULL,
            frontend_manifest_sha256 TEXT NOT NULL,
            source_snapshot_sha256 TEXT NOT NULL,
            contract_json TEXT NOT NULL,
            source_gate_json TEXT NOT NULL,
            receipt_sha256 TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS hourly_validation_triggers (
            observed_at TEXT PRIMARY KEY,
            registered_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS hourly_validation_gaps (
            observed_at TEXT PRIMARY KEY,
            detected_at TEXT NOT NULL,
            detected_by_hour TEXT NOT NULL,
            reason TEXT NOT NULL
        );
        """
    )
    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(hourly_validation_receipts)")
    }
    if "publication_id" not in columns:
        connection.execute(
            "ALTER TABLE hourly_validation_receipts ADD COLUMN publication_id TEXT"
        )
    if "frontend_manifest_sha256" not in columns:
        connection.execute(
            "ALTER TABLE hourly_validation_receipts "
            "ADD COLUMN frontend_manifest_sha256 TEXT"
        )


def _source_snapshot_sha256(path: Path, observed_at: str) -> str:
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            """
            SELECT source, topic, source_rank, value, provenance,
                   COALESCE(source_payload_json, ''),
                   COALESCE(related_terms_json, ''),
                   COALESCE(collector_version, '')
            FROM hourly_observations
            WHERE observed_at=? AND source IN ('x', 'google_trends')
              AND provenance='observed'
              AND {ELIGIBLE_COLLECTOR_SQL}
            ORDER BY source, source_rank, topic
            """.format(ELIGIBLE_COLLECTOR_SQL=ELIGIBLE_COLLECTOR_SQL),
            (observed_at,),
        ).fetchall()
    finally:
        connection.close()
    encoded = _canonical_json([list(row) for row in rows]).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _hourly_receipt_digest(
    *, observed_at: str, publication_id: str,
    frontend_manifest_sha256: str, source_snapshot_sha256: str,
    contract: dict, source_gate: dict,
) -> str:
    payload = {
        "policy_version": HOURLY_VALIDATION_RECEIPT_POLICY,
        "observed_at": observed_at,
        "publication_id": publication_id,
        "frontend_manifest_sha256": frontend_manifest_sha256,
        "source_snapshot_sha256": source_snapshot_sha256,
        "contract": contract,
        "source_gate": source_gate,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def register_hourly_trigger(path: Path, at: datetime) -> dict:
    """Register one invocation and immutably mark skipped exact hours.

    The first invocation uses the latest existing collection audit as its
    baseline, so deploying this monitor does not manufacture historical gaps.
    Later invocations record every absent trigger between the two exact hours.
    """

    normalized, stamp = _normalized_exact_hour(at)
    connection = sqlite3.connect(path)
    try:
        _ensure_hourly_validation_tables(connection)
        connection.commit()
        connection.execute("BEGIN IMMEDIATE")
        previous_row = connection.execute(
            "SELECT MAX(observed_at) FROM hourly_validation_triggers"
        ).fetchone()
        previous_stamp = previous_row[0] if previous_row else None
        if previous_stamp is None:
            candidates: list[str] = []
            for table in ("collection_audit", "hourly_validation_receipts"):
                if _table_exists(connection, table):
                    row = connection.execute(
                        f"SELECT MAX(observed_at) FROM {table}"
                    ).fetchone()
                    if row and row[0]:
                        candidates.append(str(row[0]))
            previous_stamp = max(candidates, default=None)
        previous = (
            datetime.fromisoformat(previous_stamp).astimezone(UTC)
            if previous_stamp else None
        )
        if previous and normalized < previous:
            raise ValueError("hourly trigger precedes the last registered trigger")

        detected_at = datetime.now(UTC).isoformat()
        missed: list[str] = []
        cursor = previous + timedelta(hours=1) if previous else normalized
        while cursor < normalized:
            missing_stamp = cursor.isoformat()
            has_receipt = connection.execute(
                "SELECT 1 FROM hourly_validation_receipts WHERE observed_at=?",
                (missing_stamp,),
            ).fetchone()
            has_audit = (
                _table_exists(connection, "collection_audit")
                and connection.execute(
                    "SELECT 1 FROM collection_audit WHERE observed_at=? LIMIT 1",
                    (missing_stamp,),
                ).fetchone()
            )
            if not has_receipt and not has_audit:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO hourly_validation_gaps(
                        observed_at, detected_at, detected_by_hour, reason
                    ) VALUES (?, ?, ?, 'missed_trigger')
                    """,
                    (missing_stamp, detected_at, stamp),
                )
                missed.append(missing_stamp)
            cursor += timedelta(hours=1)
        connection.execute(
            "INSERT OR IGNORE INTO hourly_validation_triggers(observed_at, registered_at) "
            "VALUES (?, ?)",
            (stamp, detected_at),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {
        "policy_version": "hourly-trigger-gap-monitor-v1",
        "observed_at": stamp,
        "missed_hours": missed,
    }


def record_hourly_validation_receipt(
    path: Path, *, observed_at: str, publication_id: str,
    frontend_manifest_sha256: str, contract: dict, source_gate: dict,
) -> dict:
    """Persist an immutable local proof for one fully validated exact hour."""

    _, stamp = _normalized_exact_hour(observed_at)
    connection = sqlite3.connect(path)
    try:
        _ensure_hourly_validation_tables(connection)
        connection.commit()
        connection.execute("BEGIN IMMEDIATE")
        # Hold the SQLite writer reservation while deriving and inserting the
        # proof so source rows cannot change between validation and hashing.
        actual_source_gate = _source_gate(path, stamp)
        if source_gate != actual_source_gate:
            raise ValueError("hourly validation source gate does not match the ledger")
        if (
            source_gate.get("policy_version") != "hourly-source-proof-v2"
            or source_gate.get("passed") is not True
        ):
            raise ValueError("hourly validation source gate did not pass")
        if (
            contract.get("policy_version") not in CURRENT_FRONTEND_RESULT_POLICIES
            or contract.get("passed") is not True
        ):
            raise ValueError("hourly validation frontend contract did not pass")
        if not str(publication_id).strip():
            raise ValueError("hourly validation publication_id is required")
        if not _is_git_or_sha256_hex(frontend_manifest_sha256, {64}):
            raise ValueError("hourly validation frontend manifest SHA-256 is invalid")

        source_digest = _source_snapshot_sha256(path, stamp)
        contract_json = _canonical_json(contract)
        source_gate_json = _canonical_json(source_gate)
        receipt_digest = _hourly_receipt_digest(
            observed_at=stamp,
            publication_id=publication_id,
            frontend_manifest_sha256=frontend_manifest_sha256,
            source_snapshot_sha256=source_digest,
            contract=contract,
            source_gate=source_gate,
        )
        immutable = (
            HOURLY_VALIDATION_RECEIPT_POLICY,
            publication_id,
            frontend_manifest_sha256,
            source_digest,
            contract_json,
            source_gate_json,
            receipt_digest,
        )
        if connection.execute(
            "SELECT 1 FROM hourly_validation_gaps WHERE observed_at=?",
            (stamp,),
        ).fetchone():
            raise ValueError("cannot validate an hour recorded as a missed trigger")
        existing = connection.execute(
            """
            SELECT policy_version, publication_id, frontend_manifest_sha256,
                   source_snapshot_sha256, contract_json, source_gate_json,
                   receipt_sha256
            FROM hourly_validation_receipts WHERE observed_at=?
            """,
            (stamp,),
        ).fetchone()
        if existing:
            if tuple(existing) != immutable:
                raise ValueError(
                    "an immutable hourly validation receipt already exists for this observed_at"
                )
            connection.commit()
        else:
            connection.execute(
                """
                INSERT INTO hourly_validation_receipts(
                    observed_at, validated_at, policy_version,
                    publication_id, frontend_manifest_sha256,
                    source_snapshot_sha256, contract_json, source_gate_json,
                    receipt_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stamp, datetime.now(UTC).isoformat(),
                    HOURLY_VALIDATION_RECEIPT_POLICY, publication_id,
                    frontend_manifest_sha256, source_digest,
                    contract_json, source_gate_json, receipt_digest,
                ),
            )
            connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return _hourly_validation_receipt(path, stamp)


def _hourly_validation_gap(path: Path, observed_at: str) -> dict | None:
    connection = sqlite3.connect(path)
    try:
        if not _table_exists(connection, "hourly_validation_gaps"):
            return None
        row = connection.execute(
            "SELECT detected_at, detected_by_hour, reason "
            "FROM hourly_validation_gaps WHERE observed_at=?",
            (observed_at,),
        ).fetchone()
    finally:
        connection.close()
    if not row:
        return None
    return {
        "observed_at": observed_at,
        "detected_at": row[0],
        "detected_by_hour": row[1],
        "reason": row[2],
    }


def _hourly_validation_receipt(path: Path, observed_at: str) -> dict:
    connection = sqlite3.connect(path)
    try:
        columns = (
            set()
            if not _table_exists(connection, "hourly_validation_receipts")
            else {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(hourly_validation_receipts)"
                )
            }
        )
        required_columns = {
            "publication_id", "frontend_manifest_sha256",
            "source_snapshot_sha256", "contract_json", "source_gate_json",
            "receipt_sha256",
        }
        if not required_columns.issubset(columns):
            row = None
        else:
            row = connection.execute(
                """
                SELECT validated_at, policy_version, publication_id,
                       frontend_manifest_sha256, source_snapshot_sha256,
                       contract_json, source_gate_json, receipt_sha256
                FROM hourly_validation_receipts WHERE observed_at=?
                """,
                (observed_at,),
            ).fetchone()
    finally:
        connection.close()
    if not row:
        return {
            "passed": False,
            "observed_at": observed_at,
            "failure": "missing_hourly_validation_receipt",
            "contract": None,
            "source_gate": None,
        }
    try:
        contract = json.loads(row[5])
        source_gate = json.loads(row[6])
    except (TypeError, ValueError, json.JSONDecodeError):
        contract, source_gate = None, None
    current_source_digest = _source_snapshot_sha256(path, observed_at)
    expected_receipt_digest = (
        _hourly_receipt_digest(
            observed_at=observed_at,
            publication_id=row[2],
            frontend_manifest_sha256=row[3],
            source_snapshot_sha256=row[4],
            contract=contract,
            source_gate=source_gate,
        )
        if isinstance(contract, dict) and isinstance(source_gate, dict)
        else None
    )
    failures = []
    if row[1] != HOURLY_VALIDATION_RECEIPT_POLICY:
        failures.append("legacy_hourly_validation_receipt_policy")
    if not row[2]:
        failures.append("missing_hourly_publication_id")
    if not _is_git_or_sha256_hex(row[3], {64}):
        failures.append("invalid_frontend_manifest_sha256")
    if row[4] != current_source_digest:
        failures.append("source_snapshot_digest_mismatch")
    if row[7] != expected_receipt_digest:
        failures.append("hourly_validation_receipt_digest_mismatch")
    if not (
        isinstance(contract, dict)
        and contract.get("policy_version") in CURRENT_FRONTEND_RESULT_POLICIES
        and contract.get("passed") is True
    ):
        failures.append("frontend_contract_not_verified")
    if not (
        isinstance(source_gate, dict)
        and source_gate.get("policy_version") == "hourly-source-proof-v2"
        and source_gate.get("passed") is True
    ):
        failures.append("source_gate_not_verified")
    return {
        "passed": not failures,
        "observed_at": observed_at,
        "validated_at": row[0],
        "policy_version": row[1],
        "publication_id": row[2],
        "frontend_manifest_sha256": row[3],
        "source_snapshot_sha256": row[4],
        "receipt_sha256": row[7],
        "contract": contract,
        "source_gate": source_gate,
        "failures": failures,
    }


def hourly_validation_receipt_exists(path: Path, observed_at: str) -> bool:
    return _hourly_validation_receipt(path, observed_at).get("passed") is True


def _ontology_path_reaches_company(path: object, company_name: str) -> bool:
    if not isinstance(path, list) or len(path) < 2:
        return False
    target = " ".join(company_name.casefold().split())
    # A complete listed-company path normally terminates at the stock node,
    # with the company reached by the preceding business edge.  Accept an
    # explicit company node anywhere on the forward path instead of wrongly
    # requiring the terminal stock label to equal the company name.
    for step in path:
        if isinstance(step, str):
            values = [step]
        elif isinstance(step, dict):
            values = [step.get(key) for key in ("to", "target", "label", "name")]
        else:
            continue
        if any(
            " ".join(str(value).casefold().split()) == target
            for value in values if value
        ):
            return True
    return False


def record_publication_receipt(
    path: Path, *, observed_at: str, publication_id: str, remote_sha: str,
    contract: dict | None = None, source_gate: dict | None = None,
    manifest_sha256: str | None = None, remote_manifest_blob: str | None = None,
) -> None:
    """Persist proof that the exact hourly publication reached the remote."""

    if not _is_git_or_sha256_hex(remote_sha, {40, 64}):
        raise ValueError("remote_sha must be a Git object id")
    if not _is_git_or_sha256_hex(manifest_sha256, {64}):
        raise ValueError("manifest_sha256 must be a SHA-256 digest")
    if not _is_git_or_sha256_hex(remote_manifest_blob, {40, 64}):
        raise ValueError("remote_manifest_blob must be a Git object id")

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


def assert_publication_receipt_available(
    path: Path, *, observed_at: str, publication_id: str,
) -> None:
    """Reject a different publication for an hour before any remote mutation."""

    connection = sqlite3.connect(path)
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='publication_receipts'"
        ).fetchone()
        if not table:
            return
        existing = connection.execute(
            "SELECT publication_id FROM publication_receipts WHERE observed_at=?",
            (observed_at,),
        ).fetchone()
    finally:
        connection.close()
    if existing and existing[0] != publication_id:
        raise ValueError(
            "an immutable publication receipt already exists for this observed_at"
        )


def publication_receipt_exists(path: Path, observed_at: str) -> bool:
    """Return whether an exact hour has already completed remote verification."""

    connection = sqlite3.connect(path)
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='publication_receipts'"
        ).fetchone()
        if not table:
            return False
        return connection.execute(
            "SELECT 1 FROM publication_receipts WHERE observed_at=?",
            (observed_at,),
        ).fetchone() is not None
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
            row[0] and _is_git_or_sha256_hex(row[1], {40, 64})
            and contract and contract.get("passed") is True
            and source_gate and source_gate.get("passed") is True
            and _is_git_or_sha256_hex(manifest_sha256, {64})
            and _is_git_or_sha256_hex(remote_manifest_blob, {40, 64})
        ),
        "publication_id": row[0],
        "remote_sha": row[1],
        "verified_at": row[2],
        "contract": contract,
        "source_gate": source_gate,
        "manifest_sha256": manifest_sha256,
        "remote_manifest_blob": remote_manifest_blob,
    }


def _evaluate_canonical_frontend_result(intelligence: dict) -> dict:
    """Evaluate the canonical rank-free home feed without recomputing rank."""

    home_feed = intelligence.get("home_feed") or {}
    using_rank_free_feed = bool(home_feed)
    top = [
        item for group in home_feed.get("groups") or []
        for item in group.get("trends") or []
    ]
    if not home_feed and intelligence.get("home_top10"):
        # Backward-compatible evaluator input only; immutable publications must
        # carry home_feed.
        top = list(intelligence.get("home_top10") or [])
    failures: list[str] = []
    enrichment_warnings: list[str] = []
    expected_home_status = "ready" if top else "empty"
    declared_home_status = intelligence.get("home_status") or (
        intelligence.get("publication_readiness") or {}
    ).get("home_status")
    # Unit callers may pass only the exported arrays.  The immutable
    # publication schema requires the explicit field; treat its absence here
    # as legacy input rather than changing a content-quality result.
    if declared_home_status is not None and declared_home_status != expected_home_status:
        failures.append(
            f"home_status_mismatch:expected_{expected_home_status}:actual_{declared_home_status}"
        )
    if using_rank_free_feed and any(
        {"observed_rank", "home_rank", "publication_rank", "score", "_home_selection_score"}
        & set(item)
        for item in top
    ):
        failures.append("home_feed_exposes_rank_or_selection_score")
    if not using_rank_free_feed and top:
        publication_ranks = [item.get("publication_rank") for item in top]
        if publication_ranks != list(range(1, len(top) + 1)):
            failures.append("publication_rank_not_contiguous")
    event_keys = [str(item.get("event_key") or "") for item in top]
    if not all(event_keys) or len(event_keys) != len(set(event_keys)):
        failures.append("duplicate_or_empty_event_key")
    rising = list(intelligence.get("rising_top10") or [])
    for item in rising:
        name = str(item.get("display_name") or item.get("event_key") or "")
        if item.get("is_current") is not True or item.get("lifecycle") == "expired":
            failures.append(f"{name}:non_current_rising_trend")

    trend_checks = []
    for item in top:
        name = str(item.get("display_name") or item.get("event_key") or "")
        keywords = list(item.get("related_keywords") or item.get("keywords") or [])
        companies = list(item.get("companies") or [])
        unique_codes = {str(company.get("stock_code") or "").strip() for company in companies}
        item_failures = []
        item_warnings = []
        context_research = item.get("context_research") or {}
        context_urls = [
            str(url).strip()
            for url in context_research.get("evidence_urls") or []
            if str(url).strip()
        ]
        if not (
            context_research.get("status") == "ready"
            and str(context_research.get("trigger_title") or "").strip()
            and str(context_research.get("why_now") or "").strip()
            and context_urls
            and all(_valid_public_url(url) for url in context_urls)
        ):
            item_failures.append("trigger_evidence_incomplete")
        if item.get("broad_category") not in PUBLIC_BROAD_CATEGORIES:
            item_failures.append(f"invalid_category:{item.get('broad_category')}")
        definition = str(item.get("trend_definition") or "").strip()
        if not definition:
            item_failures.append("missing_trend_definition")
        elif (
            len(definition) < 30
            or "X와 Google 대한민국 관측값" not in definition
            or any(phrase in definition for phrase in ("투자 추천", "투자 조언", "수익 예측"))
        ):
            item_failures.append("insufficient_trend_definition")
        if not str(item.get("disclaimer") or "").strip():
            item_failures.append("missing_separate_disclaimer")
        if len(keywords) != 5:
            item_failures.append(f"keyword_count:{len(keywords)}")
        keyword_texts = [str(keyword.get("text") or "").strip() for keyword in keywords]
        normalized_keyword_texts = {" ".join(text.casefold().split()) for text in keyword_texts}
        if not all(keyword_texts) or len(normalized_keyword_texts) != len(keyword_texts):
            item_failures.append("empty_or_duplicate_keyword")
        if any(not keyword_fits_public_label(text) for text in keyword_texts):
            item_failures.append("keyword_exceeds_six_characters")
        if any(not list(keyword.get("source") or []) for keyword in keywords):
            item_failures.append("keyword_without_source")
        if len(unique_codes) < MINIMUM_FRONTEND_COMPANIES or "" in unique_codes:
            item_failures.append(f"company_count:{len(unique_codes - {''})}")
        if len(unique_codes - {""}) >= MINIMUM_FRONTEND_COMPANIES:
            if item.get("company_card_status") != "ready":
                item_failures.append("company_card_not_ready")
            if item.get("company_card_reason") != "evidence_backed_ten_or_more":
                item_failures.append("company_card_reason_mismatch")
            company_role_categories = {
                str(company.get("company_role_category") or "").strip()
                for company in companies
                if str(company.get("company_role_category") or "").strip()
            }
            if not 3 <= len(company_role_categories) <= 4:
                item_failures.append(
                    f"company_role_category_count:{len(company_role_categories)}"
                )
        presentation_display_contract = str(
            item.get("selection_origin") or ""
        ).startswith("reviewed_observed_reference")
        if presentation_display_contract:
            visualization = item.get("visualization_series") or {}
            if (
                visualization.get("display_only") is not True
                or visualization.get("ranking_effect") != "none"
                or visualization.get("canonical_series_unchanged") is not True
            ):
                item_failures.append("visualization_series_not_rank_neutral")
            for window_key, expected_count in (("1w", 7), ("1m", 30), ("3m", 13)):
                window = visualization.get(window_key) or {}
                if (
                    len(window.get("labels") or []) != expected_count
                    or any(
                        len(window.get(source_key) or []) != expected_count
                        for source_key in ("x", "google_trends", "combined")
                    )
                    or any(
                        not isinstance(value, (int, float)) or not 0 <= value <= 100
                        for source_key in ("x", "google_trends", "combined")
                        for value in window.get(source_key) or []
                    )
                ):
                    item_failures.append(f"visualization_series_incomplete:{window_key}")
        for company in companies:
            company_name = str(company.get("company") or "").strip()
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
                str(company.get("connection_explanation") or "").strip(),
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
            if any(not _valid_public_url(url) for url in evidence_urls) or not evidence_urls:
                item_failures.append(f"invalid_company_evidence_url:{company_name}")
            if company.get("relation_tier") not in PUBLIC_RELATION_TIERS:
                item_failures.append(f"invalid_relation_tier:{company_name}")
            if not _ontology_path_reaches_company(company.get("ontology_path"), company_name):
                item_failures.append(f"ontology_path_not_to_company:{company_name}")
            if presentation_display_contract:
                snapshot = company.get("market_snapshot") or {}
                if not _presentation_logo_contract_is_valid(company):
                    item_failures.append(f"missing_official_logo:{company_name}")
                if (
                    snapshot.get("display_only") is not True
                    or snapshot.get("ranking_effect") != "none"
                    or len(snapshot.get("price_series") or []) != 30
                    or not all(
                        isinstance(snapshot.get(field), (int, float))
                        for field in ("last_price", "change_percent", "per", "pbr", "roe_percent")
                    )
                    or not all(
                        isinstance(value, (int, float)) and value > 0
                        for value in snapshot.get("price_series") or []
                    )
                ):
                    item_failures.append(f"market_snapshot_incomplete:{company_name}")
        keyword_company_links = list(item.get("keyword_company_links") or [])
        company_by_name = {
            str(company.get("company") or "").strip(): company
            for company in companies
            if str(company.get("company") or "").strip()
        }
        linked_keywords: set[str] = set()
        linked_companies: set[str] = set()
        link_pairs: set[tuple[str, str]] = set()
        invalid_link = False
        for link in keyword_company_links:
            keyword = " ".join(str(link.get("keyword") or "").casefold().split())
            company_name = str(link.get("company") or "").strip()
            evidence_urls = list(link.get("evidence_urls") or [])
            pair = (keyword, company_name)
            company = company_by_name.get(company_name)
            valid_link = bool(
                keyword in normalized_keyword_texts
                and company
                and str(link.get("connection_explanation") or "").strip()
                and evidence_urls
                and all(_valid_public_url(str(url)) for url in evidence_urls)
                and pair not in link_pairs
            )
            if presentation_display_contract and company:
                valid_link = bool(
                    valid_link
                    and link.get("stock_code") == company.get("stock_code")
                    and link.get("company_role_category")
                    == company.get("company_role_category")
                    and link.get("company_role_label")
                    == company.get("company_role_label")
                )
            if not valid_link:
                invalid_link = True
                continue
            link_pairs.add(pair)
            linked_keywords.add(keyword)
            linked_companies.add(company_name)
        if invalid_link:
            item_failures.append("invalid_keyword_company_link")
        if presentation_display_contract:
            if linked_keywords != normalized_keyword_texts:
                item_failures.append(
                    "keyword_company_keyword_coverage:"
                    f"{len(linked_keywords)}/{len(normalized_keyword_texts)}"
                )
            if linked_companies != set(company_by_name):
                item_failures.append(
                    "keyword_company_company_coverage:"
                    f"{len(linked_companies)}/{len(company_by_name)}"
                )
        elif len(linked_keywords) < 2:
            item_failures.append(f"keyword_company_link_count:{len(linked_keywords)}")
        if item.get("frontend_readiness_status") != "ready":
            item_failures.append("frontend_enrichment_pending")
        failures.extend(f"{name}:{reason}" for reason in item_failures)
        enrichment_warnings.extend(f"{name}:{reason}" for reason in item_warnings)
        trend_checks.append({
            "display_name": name,
            "keyword_count": len(keywords),
            "company_count": len(unique_codes - {""}),
            "role_categories": sorted({
                str(company.get("company_role_category") or "") for company in companies
            }),
            "passed": not item_failures,
            "enrichment_ready": not item_warnings,
            "enrichment_warnings": item_warnings,
        })
    return {
        "policy_version": "frontend-result-quality-v7",
        "passed": not failures,
        "trend_count": len(top),
        "target_trend_count": None,
        "home_status": expected_home_status,
        "home_content_ready": bool(top),
        "required_keyword_count": 5,
        "minimum_company_count": MINIMUM_FRONTEND_COMPANIES,
        "failures": failures,
        "enrichment_warnings": enrichment_warnings,
        "enrichment_ready_count": sum(
            1 for row in trend_checks if row["enrichment_ready"]
        ),
        "trends": trend_checks,
        "ranking_effect": "none",
    }


def _presentation_card_display_failures(
    item: dict, *, strict_logo_contract: bool = True
) -> list[str]:
    """Return display-contract failures for one reviewed presentation card."""

    failures: list[str] = []
    companies = list(item.get("companies") or [])
    identities = {
        (
            str(company.get("exchange") or company.get("market") or "").strip(),
            str(company.get("stock_code") or company.get("ticker") or "").strip(),
        )
        for company in companies
    }
    if len(companies) != 10 or len(identities) != 10 or any(not all(key) for key in identities):
        failures.append(f"company_count:{len(companies)}")
    roles = {
        str(company.get("company_role_category") or "").strip()
        for company in companies
        if str(company.get("company_role_category") or "").strip()
    }
    if not 3 <= len(roles) <= 4:
        failures.append(f"company_role_category_count:{len(roles)}")
    for company in companies:
        company_name = str(company.get("company") or "").strip()
        official_domain = str(company.get("official_domain") or "").strip().casefold()
        logo_url = str(company.get("logo_url") or "").strip()
        if strict_logo_contract:
            mode = str(company.get("logo_render_mode") or "").strip()
            identity_missing = (
                not official_domain
                or "." not in official_domain
                or "/" in official_domain
                or mode not in {"image", "runtime_probe", "initials"}
                or (
                    mode in {"image", "runtime_probe"}
                    and not _valid_public_url(logo_url)
                )
                or (
                    mode == "initials"
                    and not _valid_public_url(
                        str(company.get("logo_rejected_asset_url") or "").strip()
                    )
                )
            )
            if identity_missing:
                failures.append(f"missing_official_logo:{company_name}")
            elif not _presentation_logo_contract_is_valid(company):
                failures.append(f"invalid_v3_logo_metadata:{company_name}")
        elif (
            not official_domain
            or "." not in official_domain
            or not _valid_public_url(logo_url)
        ):
            failures.append(f"missing_official_logo:{company_name}")
        snapshot = company.get("market_snapshot") or {}
        if (
            snapshot.get("display_only") is not True
            or snapshot.get("ranking_effect") != "none"
            or len(snapshot.get("price_series") or []) != 30
            or not all(
                isinstance(snapshot.get(field), (int, float))
                and not isinstance(snapshot.get(field), bool)
                for field in ("last_price", "change_percent", "per", "pbr", "roe_percent")
            )
            or not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and value > 0
                for value in snapshot.get("price_series") or []
            )
        ):
            failures.append(f"market_snapshot_incomplete:{company_name}")
    visualization = item.get("visualization_series") or {}
    if (
        visualization.get("display_only") is not True
        or visualization.get("ranking_effect") != "none"
        or visualization.get("canonical_series_unchanged") is not True
    ):
        failures.append("visualization_series_not_rank_neutral")
    for window_key, expected_count in (("1w", 7), ("1m", 30), ("3m", 13)):
        window = visualization.get(window_key) or {}
        if (
            window.get("display_only") is not True
            or window.get("ranking_effect") != "none"
            or len(window.get("labels") or []) != expected_count
            or any(
                len(window.get(source_key) or []) != expected_count
                for source_key in ("x", "google_trends", "combined")
            )
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not 0 <= value <= 100
                for source_key in ("x", "google_trends", "combined")
                for value in window.get(source_key) or []
            )
        ):
            failures.append(f"visualization_series_incomplete:{window_key}")
    return failures


def evaluate_presentation_feed_quality(feed: dict) -> dict:
    """Evaluate the reviewed display projection consumed by the current frontend."""

    from .publication_pipeline import _validate_presentation_feed

    items = list(feed.get("items") or [])
    schema_version = str(feed.get("schema_version") or "")
    legacy_contract = schema_version == "trzip-presentation-feed-v2"
    strict_logo_contract = schema_version == "trzip-presentation-feed-v3"
    contract_failures: list[str] = []
    try:
        _validate_presentation_feed(feed)
    except (TypeError, ValueError) as exc:
        contract_failures.append(str(exc))
    trend_checks = []
    for item in items:
        item_failures = _presentation_card_display_failures(
            item, strict_logo_contract=strict_logo_contract
        )
        companies = list(item.get("companies") or [])
        trend_checks.append({
            "display_name": str(item.get("display_name") or ""),
            "company_count": len(companies),
            "role_categories": sorted({
                str(company.get("company_role_category") or "").strip()
                for company in companies
                if str(company.get("company_role_category") or "").strip()
            }),
            "passed": not item_failures,
            "failures": item_failures,
        })
    company_ready_count = sum(1 for row in trend_checks if row["passed"])
    passed = not contract_failures and len(items) == 10 and company_ready_count == 10
    return {
        "policy_version": "presentation-result-quality-v1",
        "schema_version": schema_version,
        "legacy_contract": legacy_contract,
        "warnings": ["legacy_logo_contract_v2"] if legacy_contract else [],
        "status": str(feed.get("status") or "missing"),
        "frontend_default": feed.get("frontend_default") is True,
        "passed": passed,
        "presentation_count": len(items),
        "company_ready_count": company_ready_count,
        "failures": contract_failures + [
            f"{row['display_name']}:{failure}"
            for row in trend_checks
            for failure in row["failures"]
        ],
        "trends": trend_checks,
        "ranking_effect": "none",
    }


def evaluate_frontend_result(intelligence: dict) -> dict:
    """Evaluate canonical data and the actual frontend-default projection separately."""

    canonical = _evaluate_canonical_frontend_result(intelligence)
    presentation_feed = intelligence.get("presentation_feed")
    if not isinstance(presentation_feed, dict) or not presentation_feed:
        return {
            **canonical,
            "frontend_surface": "canonical_home_feed",
            "home_count": canonical["trend_count"],
            "company_ready_count": sum(
                1 for row in canonical["trends"] if row.get("passed") is True
            ),
            "canonical_home_count": canonical["trend_count"],
            "canonical_home_content_ready": canonical["home_content_ready"],
            "presentation_count": 0,
            "presentation_content_ready": False,
            "presentation_feed_quality": None,
        }

    presentation = evaluate_presentation_feed_quality(presentation_feed)
    presentation_is_default = presentation["frontend_default"]
    presentation_ready = presentation_is_default and presentation["passed"]
    failures = list(canonical["failures"])
    if presentation_is_default:
        failures.extend(
            f"presentation_feed:{failure}" for failure in presentation["failures"]
        )
    return {
        **canonical,
        "policy_version": "frontend-result-quality-v8",
        "passed": not failures and presentation_ready,
        "frontend_surface": "presentation_feed" if presentation_is_default else "canonical_home_feed",
        # Compatibility metrics intentionally describe the surface consumed by
        # the frontend. Canonical counts remain available under explicit names.
        "trend_count": presentation["presentation_count"] if presentation_is_default else canonical["trend_count"],
        "home_count": presentation["presentation_count"] if presentation_is_default else canonical["trend_count"],
        "company_ready_count": (
            presentation["company_ready_count"]
            if presentation_is_default
            else sum(1 for row in canonical["trends"] if row.get("passed") is True)
        ),
        "home_status": "ready" if presentation_ready else canonical["home_status"],
        "home_content_ready": presentation_ready if presentation_is_default else canonical["home_content_ready"],
        "canonical_home_count": canonical["trend_count"],
        "canonical_home_content_ready": canonical["home_content_ready"],
        "presentation_count": presentation["presentation_count"],
        "presentation_content_ready": presentation_ready,
        "presentation_feed_quality": presentation,
        "failures": failures,
        "trends": presentation["trends"] if presentation_is_default else canonical["trends"],
        "enrichment_ready_count": (
            presentation["company_ready_count"]
            if presentation_is_default
            else canonical["enrichment_ready_count"]
        ),
    }


def _source_gate(path: Path, observed_at: str) -> dict:
    connection = sqlite3.connect(path)
    try:
        if not _table_exists(connection, "hourly_observations"):
            return {
                "policy_version": "hourly-source-proof-v2",
                "passed": False,
                "sources": {},
            }
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
    normalized = at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    stamp = normalized.isoformat()
    hourly_receipt = _hourly_validation_receipt(path, stamp)
    gap = _hourly_validation_gap(path, stamp)
    publication = _publication_receipt(path, stamp)
    source_gate = (
        hourly_receipt.get("source_gate")
        or publication.get("source_gate")
        or _source_gate(path, stamp)
    )
    if source_gate.get("policy_version") != "hourly-source-proof-v2":
        source_gate = {
            **source_gate,
            "passed": False,
            "failure": "legacy_source_gate_policy",
        }
    contract = hourly_receipt.get("contract") or publication.get("contract")
    if contract is not None and contract.get("policy_version") not in CURRENT_FRONTEND_RESULT_POLICIES:
        contract = {
            **contract,
            "passed": False,
            "failure": "legacy_frontend_result_policy",
        }
    if contract is None:
        contract = {
            "policy_version": "frontend-result-quality-v8",
            "passed": False,
            "home_content_ready": False,
            "failure": "missing_hourly_validation_receipt",
        }
    local_passed = hourly_receipt.get("passed") is True and gap is None
    return {
        "observed_at": stamp,
        "local_passed": local_passed,
        "content_ready": contract.get("home_content_ready") is True,
        "passed": local_passed and publication["passed"],
        "source_gate": source_gate,
        "contract": contract,
        "hourly_validation_receipt": hourly_receipt,
        "missed_trigger": gap,
        "publication": publication,
    }


def evaluate_local_consecutive_hours(
    path: Path, *, end: datetime, count: int = MVP_CONSECUTIVE_SOURCE_HOURS
) -> dict:
    hours = [end - timedelta(hours=offset) for offset in reversed(range(count))]
    evaluations = [evaluate_actual_hour(path, at) for at in hours]
    current_streak = 0
    for row in reversed(evaluations):
        if not row["local_passed"]:
            break
        current_streak += 1
    return {
        "policy_version": "consecutive-local-result-v2",
        "required_consecutive_hours": count,
        "passed": (
            len(evaluations) == count
            and all(row["local_passed"] for row in evaluations)
        ),
        "current_consecutive_success_count": current_streak,
        "remaining_success_hours": max(0, count - current_streak),
        "content_ready_hour_count": sum(
            1 for row in evaluations if row["content_ready"]
        ),
        "evaluations": evaluations,
        "ranking_effect": "none",
    }


def evaluate_consecutive_hours(
    path: Path, *, end: datetime, count: int = MVP_CONSECUTIVE_SOURCE_HOURS
) -> dict:
    local = evaluate_local_consecutive_hours(path, end=end, count=count)
    end_publication = (
        local["evaluations"][-1]["publication"]
        if local["evaluations"]
        else {"passed": False}
    )
    end_content_ready = bool(
        local["evaluations"]
        and local["evaluations"][-1]["content_ready"]
    )
    integrity_passed = local["passed"] and end_publication["passed"]
    return {
        "policy_version": "consecutive-actual-result-v4",
        "required_consecutive_hours": count,
        "passed": integrity_passed,
        "presentation_ready": integrity_passed and end_content_ready,
        "end_hour_content_ready": end_content_ready,
        "current_consecutive_success_count": local["current_consecutive_success_count"],
        "remaining_success_hours": local["remaining_success_hours"],
        "local_hourly_validation": local,
        "daily_publication_verified": end_publication["passed"],
        "publication": end_publication,
        "evaluations": local["evaluations"],
        "ranking_effect": "none",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit consecutive actual TRZIP frontend results")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--end", type=datetime.fromisoformat, required=True)
    parser.add_argument(
        "--count", type=int, default=MVP_CONSECUTIVE_SOURCE_HOURS
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--record-publication", action="store_true")
    parser.add_argument("--publication-id")
    parser.add_argument("--remote-sha")
    parser.add_argument("--intelligence", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--remote-manifest-blob")
    parser.add_argument("--assert-receipt-available", action="store_true")
    parser.add_argument("--receipt-exists", action="store_true")
    parser.add_argument("--record-hourly-validation", action="store_true")
    parser.add_argument("--hourly-receipt-exists", action="store_true")
    parser.add_argument("--register-trigger", action="store_true")
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="validate same-hour sources and frontend contract before remote publication",
    )
    args = parser.parse_args()
    exact_hour_modes = any((
        args.register_trigger,
        args.hourly_receipt_exists,
        args.receipt_exists,
        args.assert_receipt_available,
        args.preflight,
        args.record_hourly_validation,
        args.record_publication,
    ))
    if exact_hour_modes:
        try:
            _, normalized_end = _normalized_exact_hour(args.end)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        normalized_end = args.end.astimezone(UTC).replace(
            minute=0, second=0, microsecond=0
        ).isoformat()
    hourly_validation_recorded = False
    if args.register_trigger:
        try:
            result = register_hourly_trigger(args.database, args.end)
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.hourly_receipt_exists:
        return 0 if hourly_validation_receipt_exists(
            args.database, normalized_end
        ) else 1
    if args.receipt_exists:
        return 0 if publication_receipt_exists(args.database, normalized_end) else 1
    if args.assert_receipt_available:
        if not args.publication_id:
            parser.error("--assert-receipt-available requires --publication-id")
        assert_publication_receipt_available(
            args.database,
            observed_at=normalized_end,
            publication_id=args.publication_id,
        )
        return 0
    if args.preflight:
        if not args.intelligence:
            parser.error("--preflight requires --intelligence")
        intelligence = json.loads(args.intelligence.read_text(encoding="utf-8"))
        source_gate = _source_gate(args.database, normalized_end)
        contract = evaluate_frontend_result(intelligence)
        result = {
            "policy_version": "hourly-publication-preflight-v1",
            "observed_at": normalized_end,
            "passed": source_gate["passed"] and contract["passed"],
            "source_gate": source_gate,
            "contract": contract,
        }
        encoded = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.output.with_suffix(args.output.suffix + ".tmp")
            temporary.write_bytes(encoded)
            temporary.replace(args.output)
        print(encoded.decode("utf-8"))
        return 0 if result["passed"] else 1
    if args.record_hourly_validation:
        if args.record_publication:
            parser.error(
                "--record-hourly-validation and --record-publication are separate operations"
            )
        if not args.intelligence or not args.manifest:
            parser.error(
                "--record-hourly-validation requires --intelligence and --manifest"
            )
        intelligence = json.loads(args.intelligence.read_text(encoding="utf-8"))
        manifest_bytes = args.manifest.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        if (
            manifest.get("observed_at") != normalized_end
            or not manifest.get("publication_id")
            or manifest.get("publication_id") != intelligence.get("publication_id")
        ):
            parser.error(
                "--manifest and --intelligence do not match the requested exact hour"
            )
        source_gate = _source_gate(args.database, normalized_end)
        contract = evaluate_frontend_result(intelligence)
        try:
            record_hourly_validation_receipt(
                args.database,
                observed_at=normalized_end,
                publication_id=str(manifest["publication_id"]),
                frontend_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                contract=contract,
                source_gate=source_gate,
            )
        except ValueError as exc:
            parser.error(str(exc))
        hourly_validation_recorded = True
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
    if hourly_validation_recorded:
        # A valid local receipt is a successful command even while the separate
        # daily remote-publication proof or eight-hour maturity remains pending.
        return 0
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
