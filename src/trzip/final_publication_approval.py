"""Human-controlled final release approval for public TRZIP trends.

Enrichment review proves that evidence was checked.  It does not grant
permission to publish a trend.  This module creates a deterministic final
review pack and validates a separate approval receipt owned by the product
owner.  Ranking values are never changed by an approval decision.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from .trend_fit import sports_discipline_for_name


REVIEW_SCHEMA_VERSION = "trzip-final-publication-review-v2"
APPROVAL_SCHEMA_VERSION = "trzip-final-publication-approval-v1"
MAX_PUBLIC_ITEMS = 10
OVERSEAS_SPORTS_SALIENCE_MAX_SOURCE_RANK = 20
DIRECT_KOREAN_SPORTS_MARKERS = {
    "한국", "대한민국", "한일전",
    "수원", "수원fc", "제주", "안양", "fc 서울", "서울", "대전",
    "한화", "삼성", "두산", "kia", "ssg", "lg", "키움", "kt", "nc", "롯데",
}
LIBERATION_EVENT_MARKERS = {
    "광복", "독립", "독립운동가", "독립유공자", "순국선열", "대한독립만세",
    "koreanliberationday", "national liberation day",
}


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def approval_path(root: Path, observed_at: str) -> Path:
    token = hashlib.sha256(observed_at.encode("utf-8")).hexdigest()[:24]
    return root / f"approval-{token}.json"


def _best_observed_source_rank(item: dict) -> int | None:
    ranks = [
        int(row.get("rank") or row.get("source_rank"))
        for row in item.get("series") or []
        if row.get("provenance") == "observed"
        and row.get("source") in {"x", "google_trends"}
        and isinstance(row.get("rank") or row.get("source_rank"), int)
        and not isinstance(row.get("rank") or row.get("source_rank"), bool)
        and int(row.get("rank") or row.get("source_rank")) > 0
    ]
    return min(ranks) if ranks else None


def _sports_has_direct_korean_interest(display_name: str) -> bool:
    normalized = " ".join(str(display_name or "").casefold().split())
    return any(
        bool(re.search(
            rf"(?<![a-z0-9]){re.escape(marker.casefold())}(?![a-z0-9])",
            normalized,
        ))
        if marker.isascii()
        else marker.casefold() in normalized
        for marker in DIRECT_KOREAN_SPORTS_MARKERS
    )


def _review_trend_group(display_name: str) -> tuple[str | None, str | None]:
    normalized = " ".join(str(display_name or "").casefold().split())
    if any(marker in normalized for marker in LIBERATION_EVENT_MARKERS):
        return "public_event:liberation_day", "광복절·독립운동가"
    return None, None


def build_final_publication_review(intelligence: dict) -> dict:
    """Summarise every current candidate and its deterministic release gates."""

    from .processing_cycle import complete_card_gate, trend_candidate_gate

    observed_at = str((intelligence.get("window") or {}).get("to") or "")
    try:
        observed_at_value = datetime.fromisoformat(observed_at).astimezone(UTC)
    except (TypeError, ValueError):
        observed_at_value = datetime.now(UTC)
    gates = (intelligence.get("processing_cycle") or {}).get("complete_card_gates") or {}
    full_period_contract = intelligence.get("full_ledger_demo_ranking") or {}
    full_period_by_key = {
        str(row.get("event_key") or ""): row
        for row in full_period_contract.get("ranking") or []
        if str(row.get("event_key") or "").strip()
    }
    review_ranking_mode = (
        "full_ledger_demo_no_recency"
        if full_period_by_key
        else "canonical_24h"
    )
    candidates = []
    ranking = list(intelligence.get("unified_ranking") or [])
    hydrated_keys = {
        str(item.get("event_key") or "").strip()
        for item in ranking
    }
    # The operational DTO hydrates the current-period cohort.  The showcase
    # review must still expose older events from the complete observed ledger;
    # enrichment is attached later and is never a prerequisite for review.
    for full_period_row in full_period_contract.get("ranking") or []:
        event_key = str(full_period_row.get("event_key") or "").strip()
        if not event_key or event_key in hydrated_keys:
            continue
        ranking.append({
            "event_key": event_key,
            "display_name": event_key,
            "rank": 0,
            "score": 0.0,
            "lane": "review",
            "category": "unclassified",
            "series": [],
            "companies": [],
            "related_keywords": [],
            "trend_fit": {},
            "showcase_enrichment_status": "pending",
        })
    for item in ranking:
        event_key = str(item.get("event_key") or "").strip()
        if not event_key:
            continue
        enrichment_gate = gates.get(event_key) or complete_card_gate(
            item,
            observed_at=observed_at_value,
        )
        candidate_gate = trend_candidate_gate(item, observed_at=observed_at_value)
        full_period_row = full_period_by_key.get(event_key)
        context = item.get("context_research") or {}
        keywords = list(item.get("related_keywords") or item.get("keywords") or [])
        companies = list(item.get("companies") or [])
        checks = dict(candidate_gate.get("checks") or {})
        strict_missing = list(candidate_gate.get("missing") or [])
        owner_review_missing = list(candidate_gate.get("owner_review_missing") or [])
        # The showcase review consumes the complete observed ledger.  A row
        # need not still be present in the latest 24 hours, but all other
        # lexical and safety checks remain unchanged.
        if full_period_row is not None:
            checks["observed_in_full_ledger"] = True
            strict_missing = [
                value for value in strict_missing
                if value != "observed_within_24h"
            ]
            owner_review_missing = [
                value for value in owner_review_missing
                if value != "observed_within_24h"
            ]
        display_name = str(item.get("display_name") or event_key)
        review_group, normalized_display_name = _review_trend_group(display_name)
        sports_discipline = sports_discipline_for_name(display_name)
        best_source_rank = _best_observed_source_rank(item)
        if best_source_rank is None and full_period_row is not None:
            full_period_best = full_period_row.get("best_source_rank")
            best_source_rank = int(full_period_best) if full_period_best is not None else None
        sports_korean_interest = bool(
            sports_discipline is None
            or _sports_has_direct_korean_interest(display_name)
            or (
                best_source_rank is not None
                and best_source_rank <= OVERSEAS_SPORTS_SALIENCE_MAX_SOURCE_RANK
            )
        )
        candidates.append({
            "event_key": event_key,
            "display_name": display_name,
            "source_display_name": display_name,
            "review_group": review_group,
            "normalized_display_name": normalized_display_name or display_name,
            "canonical_rank": int(item.get("rank") or 0),
            "review_rank": int(
                (full_period_row or {}).get("rank") or item.get("rank") or 0
            ),
            "review_score": float(
                (full_period_row or {}).get("score") or item.get("score") or 0.0
            ),
            "review_ranking_mode": review_ranking_mode,
            "full_period_observed_hour_count": int(
                (full_period_row or {}).get("observed_hour_count") or 0
            ),
            "main_rank": item.get("main_rank"),
            "score": float(item.get("score") or 0.0),
            "lane": str(item.get("lane") or ""),
            "category": str(item.get("category_label") or item.get("broad_category") or ""),
            "sports_discipline": sports_discipline,
            "best_observed_source_rank": best_source_rank,
            "sports_korean_interest": sports_korean_interest,
            "observed_within_24h": bool(checks.get("observed_within_24h")),
            "filter_checks": checks,
            "missing": strict_missing,
            "enrichment_ready": bool(enrichment_gate.get("ready")),
            "enrichment_missing": list(enrichment_gate.get("missing") or []),
            "context_summary": str(context.get("summary") or context.get("why_now") or ""),
            "context_evidence_urls": [
                str(url) for url in context.get("evidence_urls") or []
                if str(url).startswith(("http://", "https://"))
            ],
            "keyword_count": len(keywords),
            "company_count": int(enrichment_gate.get("projected_company_count") or len(companies)),
            "role_category_count": int(enrichment_gate.get("role_category_count") or 0),
            "valid_keyword_company_link_count": int(
                enrichment_gate.get("valid_keyword_company_link_count") or 0
            ),
            "automatic_filter_passed": not strict_missing,
            "manual_approval_eligible": not owner_review_missing,
            "review_tier": (
                "recommended"
                if not strict_missing
                else "owner_review"
                if not owner_review_missing
                else "excluded"
            ),
            "owner_review_missing": owner_review_missing,
            "ranking_effect": "none",
        })
    # Collapse alternate observed expressions of one event before manual
    # approval.  The highest canonical rank owns the group; no score changes.
    selected_groups: dict[str, str] = {}
    for row in sorted(candidates, key=lambda value: (
        value["review_rank"] or 10**9,
        value["event_key"],
    )):
        group = row.get("review_group")
        if not group or row.get("manual_approval_eligible") is not True:
            continue
        selected_event_key = selected_groups.get(group)
        if selected_event_key is None:
            selected_groups[group] = row["event_key"]
            row["display_name"] = row["normalized_display_name"]
            row["trend_group_selected"] = True
            continue
        row["trend_group_selected"] = False
        row["automatic_filter_passed"] = False
        row["manual_approval_eligible"] = False
        row["review_tier"] = "deduplicated"
        row["filter_checks"]["one_candidate_per_normalized_trend_group"] = False
        row["missing"].append("one_candidate_per_normalized_trend_group")
        row["superseded_by_event_key"] = selected_event_key

    # A foreign fixture is still eligible when Korean source users push it
    # into the top 20.  Low-salience overseas fixtures are retained in the
    # canonical ledger but do not enter the product-owner approval surface.
    for row in candidates:
        if (
            row.get("sports_discipline")
            and row.get("sports_korean_interest") is not True
            and row.get("manual_approval_eligible") is True
        ):
            row["automatic_filter_passed"] = False
            row["manual_approval_eligible"] = False
            row["review_tier"] = "excluded"
            row["filter_checks"]["korean_product_sports_interest"] = False
            row["missing"].append("korean_product_sports_interest")

    # Preserve the canonical rank, but prevent sports fixtures from consuming
    # the whole approval surface.  The highest-ranked eligible fixture in each
    # sport remains selectable; later fixtures stay visible as filtered rows.
    selected_sports: dict[str, str] = {}
    for row in sorted(candidates, key=lambda value: (
        value["review_rank"] or 10**9,
        value["event_key"],
    )):
        discipline = row.get("sports_discipline")
        if not discipline or row.get("manual_approval_eligible") is not True:
            continue
        selected_event_key = selected_sports.get(discipline)
        if selected_event_key is None:
            selected_sports[discipline] = row["event_key"]
            row["sports_slot_selected"] = True
            continue
        row["sports_slot_selected"] = False
        row["automatic_filter_passed"] = False
        # Keep the lower fixture selectable. The approval receipt, not this
        # recommendation pass, enforces one approved event per sport.
        row["review_tier"] = "owner_review"
        row["filter_checks"]["one_fixture_per_sports_discipline"] = False
        row["missing"].append("one_fixture_per_sports_discipline")
        row["superseded_by_event_key"] = selected_event_key
    candidates.sort(key=lambda row: (
        not row["automatic_filter_passed"],
        row["review_rank"] or 10**9,
        row["event_key"],
    ))
    body = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "observed_at": observed_at,
        "ranking_policy": (
            "python_full_ledger_demo_rank_no_recency"
            if full_period_by_key
            else "python_canonical_rank_unchanged"
        ),
        "review_ranking_mode": review_ranking_mode,
        "review_ranking_formula_version": str(
            full_period_contract.get("formula_version") or ""
        ),
        "review_ranking_window": full_period_contract.get("window"),
        "approval_policy": "explicit_product_owner_approval_required_for_remote_publication",
        "candidate_count": len(candidates),
        "automatic_filter_passed_count": sum(
            bool(row["automatic_filter_passed"]) for row in candidates
        ),
        "candidates": candidates,
    }
    return {**body, "review_sha256": _sha256(body)}


def write_approval(
    review: dict,
    *,
    approval_root: Path,
    approved_event_keys: Iterable[str],
    approved_by: str,
    approved_at: datetime | None = None,
) -> Path:
    """Persist an atomic approval receipt for one exact immutable review pack."""

    review_body = dict(review)
    supplied_review_hash = str(review_body.pop("review_sha256", ""))
    if not supplied_review_hash or supplied_review_hash != _sha256(review_body):
        raise ValueError("final publication review hash is invalid")
    eligible = {
        str(row.get("event_key") or "")
        for row in review.get("candidates") or []
        if row.get("manual_approval_eligible") is True
    }
    approved = list(dict.fromkeys(str(key).strip() for key in approved_event_keys if str(key).strip()))
    unexpected = sorted(set(approved) - eligible)
    if unexpected:
        raise ValueError("cannot approve candidates that failed owner-review safety filters: " + ", ".join(unexpected))
    if len(approved) > MAX_PUBLIC_ITEMS:
        raise ValueError(f"cannot approve more than {MAX_PUBLIC_ITEMS} candidates")
    candidate_by_key = {
        str(row.get("event_key") or ""): row
        for row in review.get("candidates") or []
    }
    approved_sports = [
        str((candidate_by_key.get(key) or {}).get("sports_discipline") or "")
        for key in approved
    ]
    approved_sports = [value for value in approved_sports if value]
    if len(approved_sports) != len(set(approved_sports)):
        raise ValueError("cannot approve more than one fixture per sports discipline")
    owner = str(approved_by or "").strip()
    if not owner:
        raise ValueError("approved_by is required")
    receipt = {
        "schema_version": APPROVAL_SCHEMA_VERSION,
        "review_sha256": supplied_review_hash,
        "observed_at": str(review.get("observed_at") or ""),
        "decision": "approved",
        "approved_event_keys": approved,
        "approved_by": owner,
        "approved_at": (approved_at or datetime.now(UTC)).astimezone(UTC).isoformat(),
        "ranking_effect": "none",
    }
    receipt["receipt_sha256"] = _sha256(receipt)
    path = approval_path(approval_root, receipt["observed_at"])
    approval_root.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def verify_approval(review: dict, *, approval_root: Path) -> dict:
    """Return a public-safe status; any mismatch fails closed without mutation."""

    path = approval_path(approval_root, str(review.get("observed_at") or ""))
    base = {
        "policy_version": APPROVAL_SCHEMA_VERSION,
        "required": True,
        "review_sha256": str(review.get("review_sha256") or ""),
        "approval_receipt_key": path.name,
        "ranking_effect": "none",
    }
    review_body = dict(review)
    supplied_review_hash = str(review_body.pop("review_sha256", ""))
    if not supplied_review_hash or supplied_review_hash != _sha256(review_body):
        return {
            **base,
            "status": "invalid_final_review",
            "verified": False,
            "approved_event_keys": [],
            "approved_count": 0,
        }
    if not path.is_file():
        return {**base, "status": "pending_product_owner_approval", "verified": False, "approved_event_keys": []}
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {**base, "status": "invalid_approval_receipt", "verified": False, "approved_event_keys": []}
    receipt_hash = str(receipt.pop("receipt_sha256", ""))
    eligible = {
        str(row.get("event_key") or "")
        for row in review.get("candidates") or []
        if row.get("manual_approval_eligible") is True
    }
    approved = list(receipt.get("approved_event_keys") or [])
    valid = bool(
        receipt.get("schema_version") == APPROVAL_SCHEMA_VERSION
        and receipt.get("review_sha256") == review.get("review_sha256")
        and receipt.get("observed_at") == review.get("observed_at")
        and receipt.get("decision") == "approved"
        and str(receipt.get("approved_by") or "").strip()
        and receipt.get("ranking_effect") == "none"
        and len(approved) == len(set(approved))
        and len(approved) <= MAX_PUBLIC_ITEMS
        and set(approved).issubset(eligible)
        and receipt_hash == _sha256(receipt)
    )
    return {
        **base,
        "status": "verified" if valid else "invalid_approval_receipt",
        "verified": valid,
        "approved_event_keys": approved if valid else [],
        "approved_count": len(approved) if valid else 0,
        "approved_by": str(receipt.get("approved_by") or "") if valid else "",
        "approved_at": str(receipt.get("approved_at") or "") if valid else "",
        "receipt_sha256": receipt_hash if valid else "",
    }
