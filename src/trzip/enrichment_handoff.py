"""API-free four-hour LLM/Codex enrichment handoff.

Python exports immutable observed candidates.  A reviewer may add bounded
semantic/context/keyword/company suggestions in a separate JSON file.  Python
then validates those suggestions and applies them without granting any
authority over observed ranks, numerical scores, or source measurements.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from .hourly_store import floor_hour
from .keyword_policy import keyword_fits_public_label
from .public_company_contract import keyword_company_link_coverage


SCHEMA_VERSION = "trzip-enrichment-handoff-v1"
REVIEW_SCHEMA_VERSION = "trzip-reviewed-enrichment-v1"
RECEIPT_SCHEMA_VERSION = "trzip-reviewed-enrichment-receipt-v1"
APPROVED_SCHEMA_VERSION = "trzip-approved-enrichment-v1"
BATCH_ID_PATTERN = re.compile(r"^\d{8}T\d{6}Z$")
PROHIBITED_FIELDS = {
    "rank", "observed_rank", "home_rank", "main_rank", "publication_rank",
    "rising_rank", "score", "score_components", "period_strength",
    "momentum", "momentum_delta", "persistence", "latest_source_ranks",
    "series", "source_metrics", "source_count", "raw_terms",
}


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(_canonical_bytes(value))
    temporary.replace(path)


def _public_url(value: object) -> bool:
    return str(value or "").startswith(("http://", "https://"))


def _candidate_projection(item: dict) -> dict:
    return {
        "event_key": item.get("event_key"),
        "display_name": item.get("display_name"),
        "lane": item.get("lane"),
        "broad_category": item.get("broad_category"),
        "observed_rank": item.get("observed_rank"),
        "score": item.get("score"),
        "latest_source_ranks": item.get("latest_source_ranks") or {},
        "raw_terms": list(item.get("raw_terms") or []),
        "representative_evidence": item.get("representative_evidence"),
        "context_research": item.get("context_research") or {},
        "related_keywords": item.get("related_keywords") or [],
        "companies": item.get("companies") or [],
        "keyword_company_links": item.get("keyword_company_links") or [],
        "frontend_readiness_missing": item.get("frontend_readiness_missing") or [],
    }


def export_candidate_batch(
    intelligence: dict,
    *,
    handoff_root: Path,
    at: datetime,
    limit: int = 12,
) -> tuple[dict, Path]:
    """Write actionable, then ambiguous incomplete non-issue candidates atomically."""

    at = floor_hour(at)
    # Import locally to keep the handoff schema independent while ensuring an
    # approved cache that already satisfies the production gate is not queued
    # for redundant LLM review at every four-hour checkpoint.
    from .processing_cycle import complete_card_gate

    eligible = [
        item for item in intelligence.get("unified_ranking") or []
        if item.get("lane") != "issue"
        and item.get("frontend_readiness_status") != "ready"
        and not complete_card_gate(item, observed_at=at)["ready"]
    ]
    # This is a work-queue priority only.  Prefer candidates that deterministic
    # Python has already accepted into a public category, because they can be
    # completed by the bounded context/company review contract.  Ambiguous
    # review-lane terms remain in the queue after those actionable candidates.
    # The immutable observed rank/score carried in every row is never changed.
    candidates = sorted(
        eligible,
        key=lambda item: (
            0 if (
                item.get("lane") == "main"
                and item.get("broad_category") not in {None, "", "other"}
            ) else 1,
        ),
    )[: max(0, min(int(limit), 20))]
    rows = [_candidate_projection(item) for item in candidates]
    batch_id = at.strftime("%Y%m%dT%H0000Z")
    immutable = {
        "observed_at": at.isoformat(),
        "candidates": rows,
        "ranking_authority": "python_x_google_only",
        "review_authority": [
            "alias_merge_suggestion", "lane_suggestion_for_non_issue",
            "broad_category_suggestion", "context_research", "related_keywords",
            "companies", "keyword_company_links",
        ],
        "prohibited_authority": sorted(PROHIBITED_FIELDS),
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "batch_id": batch_id,
        **immutable,
        "immutable_sha256": _sha256(immutable),
        "review_path": f"reviewed/{batch_id}.json",
        "instructions": (
            "Copy the review template to review_path. Never alter rank, score, "
            "source observations, or hard issue safety exclusions."
        ),
    }
    path = handoff_root / "pending" / f"{batch_id}.json"
    _atomic_json(path, payload)
    return payload, path


def review_template(batch: dict) -> dict:
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "batch_id": batch["batch_id"],
        "immutable_sha256": batch["immutable_sha256"],
        "reviewed_at": datetime.now(UTC).isoformat(),
        "reviewer": "codex_or_human_reviewer",
        "decisions": [],
    }


def _validate_review(batch: dict, review: dict) -> list[dict]:
    if review.get("schema_version") != REVIEW_SCHEMA_VERSION:
        raise ValueError("review schema version is invalid")
    if (
        review.get("batch_id") != batch.get("batch_id")
        or review.get("immutable_sha256") != batch.get("immutable_sha256")
    ):
        raise ValueError("review does not match the immutable candidate batch")
    batch_by_key = {
        str(row.get("event_key") or ""): row for row in batch.get("candidates") or []
    }
    decisions = list(review.get("decisions") or [])
    seen = set()
    for decision in decisions:
        forbidden = PROHIBITED_FIELDS & set(decision)
        if forbidden:
            raise ValueError(f"review cannot alter ranking fields: {sorted(forbidden)}")
        event_key = str(decision.get("event_key") or "")
        if not event_key or event_key not in batch_by_key or event_key in seen:
            raise ValueError("review decision event_key is invalid or duplicated")
        seen.add(event_key)
        original = batch_by_key[event_key]
        lane = str(decision.get("lane") or original.get("lane") or "review")
        if original.get("lane") == "issue" and lane != "issue":
            raise ValueError("review cannot promote a hard issue lane")
        if lane not in {"main", "review", "issue"}:
            raise ValueError("review lane is invalid")
        aliases = list(decision.get("merge_event_keys") or [])
        if any(str(alias) not in batch_by_key for alias in aliases):
            raise ValueError("alias merge must reference this immutable batch")
        context = decision.get("context_research")
        if context is not None:
            urls = list(context.get("evidence_urls") or [])
            if not (
                context.get("status") == "ready"
                and str(context.get("trigger_title") or "").strip()
                and str(context.get("why_now") or "").strip()
                and urls and all(_public_url(url) for url in urls)
            ):
                raise ValueError("review context requires title, why-now, and public evidence")
        keywords = decision.get("related_keywords")
        if keywords is not None:
            texts = [
                str(row.get("text") if isinstance(row, dict) else row).strip()
                for row in keywords
            ]
            if len(texts) != 5 or len(set(texts)) != 5 or not all(
                keyword_fits_public_label(text) for text in texts
            ):
                raise ValueError("review requires exactly five unique short keywords")
        companies = decision.get("companies")
        if companies is not None and len(companies) < 10:
            raise ValueError("review requires at least ten companies when companies are supplied")
        for company in companies or []:
            urls = [
                row.get("url") for row in company.get("evidence_sources") or []
                if _public_url(row.get("url"))
            ]
            if not (
                str(company.get("company") or "").strip()
                and str(company.get("stock_code") or "").strip()
                and str(company.get("market") or "").strip()
                and str(company.get("company_description") or "").strip()
                and str(company.get("relationship_reason") or "").strip()
                and urls
                and company.get("ontology_complete") is True
            ):
                raise ValueError("review company lacks listed identity or trend evidence")
        if any(
            field in decision
            for field in ("related_keywords", "companies", "keyword_company_links")
        ):
            effective_keywords = decision.get("related_keywords") or original.get(
                "related_keywords"
            ) or []
            effective_companies = decision.get("companies") or original.get(
                "companies"
            ) or []
            effective_links = decision.get("keyword_company_links") or original.get(
                "keyword_company_links"
            ) or []
            coverage = keyword_company_link_coverage(
                keywords=effective_keywords,
                companies=effective_companies,
                links=effective_links,
            )
            if not coverage["ready"]:
                raise ValueError(
                    "review keyword-company links must cover every supplied "
                    "keyword and company with exact matched_keywords and public evidence"
                )
    return decisions


def import_reviewed_batch(
    intelligence: dict,
    *,
    batch: dict,
    review_path: Path,
) -> dict:
    """Validate and apply suggestions while proving ranks/scores are unchanged."""

    if not review_path.is_file():
        return {"status": "exported_waiting_review", "review_path": str(review_path)}
    review = json.loads(review_path.read_text(encoding="utf-8"))
    decisions = _validate_review(batch, review)
    before = {
        str(item.get("event_key") or ""): (
            item.get("observed_rank"), item.get("rank"), item.get("score"),
            item.get("latest_source_ranks"), item.get("series"),
        )
        for item in intelligence.get("unified_ranking") or []
    }
    by_key = {
        str(item.get("event_key") or ""): item
        for item in intelligence.get("unified_ranking") or []
    }
    missing_current = [
        str(decision.get("event_key") or "")
        for decision in decisions
        if str(decision.get("event_key") or "") not in by_key
    ]
    if missing_current:
        raise ValueError(
            "reviewed events are no longer in the current candidate set: "
            f"{sorted(missing_current)}"
        )
    for decision in decisions:
        item = by_key[str(decision["event_key"])]
        for field in (
            "lane", "broad_category", "context_research", "related_keywords",
            "companies", "keyword_company_links",
        ):
            if field in decision:
                item[field] = decision[field]
        item["llm_review_handoff"] = {
            "batch_id": batch["batch_id"],
            "reviewed_at": review.get("reviewed_at"),
            "reviewer": review.get("reviewer"),
            "merge_event_keys": list(decision.get("merge_event_keys") or []),
            "ranking_effect": "none",
        }
    after = {
        key: (
            item.get("observed_rank"), item.get("rank"), item.get("score"),
            item.get("latest_source_ranks"), item.get("series"),
        )
        for key, item in by_key.items()
    }
    if before != after:
        raise ValueError("review import attempted to mutate observed ranking state")
    return {
        "status": "reviewed_imported" if decisions else "reviewed_empty",
        "review_path": str(review_path),
        "decision_count": len(decisions),
        "review_sha256": _sha256(review),
        "ranking_effect": "none",
    }


def _latest_unconsumed_review(
    handoff_root: Path,
    *,
    current_batch_id: str,
    review_cutoff_at: datetime | None = None,
) -> tuple[dict, Path] | None:
    """Return the newest review at or before this checkpoint without a receipt."""

    reviewed_root = handoff_root / "reviewed"
    pending_root = handoff_root / "pending"
    receipt_root = handoff_root / "receipts"
    if not reviewed_root.is_dir():
        return None
    candidates = []
    for review_path in reviewed_root.glob("*.json"):
        batch_id = review_path.stem
        if (
            not BATCH_ID_PATTERN.fullmatch(batch_id)
            or batch_id > current_batch_id
            or (receipt_root / f"{batch_id}.json").exists()
            or not (pending_root / f"{batch_id}.json").is_file()
        ):
            continue
        if not _review_is_within_cutoff(review_path, review_cutoff_at):
            continue
        candidates.append((batch_id, review_path))
    if not candidates:
        return None
    batch_id, review_path = max(candidates, key=lambda row: row[0])
    pending_path = pending_root / f"{batch_id}.json"
    batch = json.loads(pending_path.read_text(encoding="utf-8"))
    if (
        batch.get("schema_version") != SCHEMA_VERSION
        or batch.get("batch_id") != batch_id
    ):
        raise ValueError("pending enrichment batch identity is invalid")
    return batch, review_path


def _review_is_within_cutoff(
    review_path: Path,
    review_cutoff_at: datetime | None,
) -> bool:
    """Require both the claimed review time and filesystem arrival by cutoff.

    A late review is not deleted or marked consumed.  It remains in the queue
    for the next checkpoint, while the current daily publication stays frozen
    to the declared editorial cutoff.
    """

    if review_cutoff_at is None:
        return True
    cutoff = review_cutoff_at.astimezone(UTC)
    try:
        arrived_at = datetime.fromtimestamp(review_path.stat().st_mtime, tz=UTC)
    except OSError:
        return False
    if arrived_at > cutoff:
        return False
    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
        reviewed_at = datetime.fromisoformat(str(review.get("reviewed_at") or ""))
        if reviewed_at.tzinfo is None:
            return False
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        # Malformed files that arrived before the cutoff are still selected so
        # the normal validation path can record a reviewed_rejected outcome.
        return True
    return reviewed_at.astimezone(UTC) <= cutoff


def _deferred_after_cutoff_count(
    handoff_root: Path,
    *,
    current_batch_id: str,
    review_cutoff_at: datetime | None,
) -> int:
    if review_cutoff_at is None:
        return 0
    reviewed_root = handoff_root / "reviewed"
    pending_root = handoff_root / "pending"
    receipt_root = handoff_root / "receipts"
    if not reviewed_root.is_dir():
        return 0
    count = 0
    for review_path in reviewed_root.glob("*.json"):
        batch_id = review_path.stem
        if (
            BATCH_ID_PATTERN.fullmatch(batch_id)
            and batch_id <= current_batch_id
            and not (receipt_root / f"{batch_id}.json").exists()
            and (pending_root / f"{batch_id}.json").is_file()
            and not _review_is_within_cutoff(review_path, review_cutoff_at)
        ):
            count += 1
    return count


def _record_consumed_review(
    handoff_root: Path,
    *,
    batch: dict,
    result: dict,
    at: datetime,
) -> Path:
    """Write an immutable success receipt so one review is never applied twice."""

    receipt_path = handoff_root / "receipts" / f"{batch['batch_id']}.json"
    payload = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "batch_id": batch["batch_id"],
        "immutable_sha256": batch["immutable_sha256"],
        "review_sha256": result["review_sha256"],
        "imported_at": floor_hour(at).isoformat(),
        "decision_count": int(result.get("decision_count") or 0),
        "ranking_effect": "none",
        "status": "consumed",
    }
    if receipt_path.exists():
        existing = json.loads(receipt_path.read_text(encoding="utf-8"))
        if existing != payload:
            raise ValueError("review receipt already exists with different content")
        return receipt_path
    _atomic_json(receipt_path, payload)
    return receipt_path


def _approved_event_path(handoff_root: Path, event_key: str) -> Path:
    digest = hashlib.sha256(event_key.encode("utf-8")).hexdigest()[:24]
    return handoff_root / "approved" / f"event-{digest}.json"


def _persist_approved_decisions(
    handoff_root: Path,
    *,
    batch: dict,
    review_path: Path,
    at: datetime,
) -> list[Path]:
    """Persist validated semantic fields by event so later builds can reapply them."""

    review = json.loads(review_path.read_text(encoding="utf-8"))
    decisions = _validate_review(batch, review)
    paths = []
    for decision in decisions:
        event_key = str(decision["event_key"])
        path = _approved_event_path(handoff_root, event_key)
        payload = {
            "schema_version": APPROVED_SCHEMA_VERSION,
            "event_key": event_key,
            "source_batch_id": batch["batch_id"],
            "immutable_sha256": batch["immutable_sha256"],
            "review_sha256": _sha256(review),
            "approved_at": floor_hour(at).isoformat(),
            "reviewed_at": review.get("reviewed_at"),
            "reviewer": review.get("reviewer"),
            "decision": decision,
            "ranking_effect": "none",
        }
        _atomic_json(path, payload)
        paths.append(path)
    return paths


def _reapply_approved_cache(
    intelligence: dict,
    *,
    handoff_root: Path,
    review_cutoff_at: datetime | None = None,
) -> dict:
    """Reapply validated prior decisions without granting ranking authority."""

    approved_root = handoff_root / "approved"
    if not approved_root.is_dir():
        return {
            "status": "empty",
            "reapplied_count": 0,
            "rejected_count": 0,
            "deferred_after_cutoff_count": 0,
        }
    by_key = {
        str(item.get("event_key") or ""): item
        for item in intelligence.get("unified_ranking") or []
    }
    before = {
        key: (
            item.get("observed_rank"), item.get("rank"), item.get("score"),
            item.get("latest_source_ranks"), item.get("series"),
        )
        for key, item in by_key.items()
    }
    reapplied = 0
    rejected = 0
    deferred_after_cutoff = 0
    for path in sorted(approved_root.glob("event-*.json")):
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            event_key = str(cached.get("event_key") or "")
            batch_id = str(cached.get("source_batch_id") or "")
            decision = cached.get("decision") or {}
            if (
                cached.get("schema_version") != APPROVED_SCHEMA_VERSION
                or cached.get("ranking_effect") != "none"
                or not event_key
                or str(decision.get("event_key") or "") != event_key
                or not BATCH_ID_PATTERN.fullmatch(batch_id)
            ):
                raise ValueError("approved enrichment cache identity is invalid")
            pending_path = handoff_root / "pending" / f"{batch_id}.json"
            batch = json.loads(pending_path.read_text(encoding="utf-8"))
            if (
                batch.get("schema_version") != SCHEMA_VERSION
                or batch.get("batch_id") != batch_id
                or batch.get("immutable_sha256") != cached.get("immutable_sha256")
            ):
                raise ValueError("approved enrichment source batch is invalid")
            if review_cutoff_at is not None:
                cutoff = review_cutoff_at.astimezone(UTC)
                try:
                    cached_reviewed_at = datetime.fromisoformat(
                        str(cached.get("reviewed_at") or "")
                    )
                except (TypeError, ValueError):
                    cached_reviewed_at = None
                review_path = handoff_root / "reviewed" / f"{batch_id}.json"
                if (
                    cached_reviewed_at is None
                    or cached_reviewed_at.tzinfo is None
                    or cached_reviewed_at.astimezone(UTC) > cutoff
                    or not _review_is_within_cutoff(review_path, cutoff)
                ):
                    deferred_after_cutoff += 1
                    continue
            _validate_review(batch, {
                "schema_version": REVIEW_SCHEMA_VERSION,
                "batch_id": batch_id,
                "immutable_sha256": batch["immutable_sha256"],
                "decisions": [decision],
            })
            item = by_key.get(event_key)
            if item is None:
                continue
            if item.get("lane") == "issue" and decision.get("lane") != "issue":
                raise ValueError("approved cache cannot promote a current hard issue")
            for field in (
                "lane", "broad_category", "context_research", "related_keywords",
                "companies", "keyword_company_links",
            ):
                if field in decision:
                    item[field] = decision[field]
            item["llm_review_handoff"] = {
                "batch_id": batch_id,
                "reviewed_at": cached.get("reviewed_at"),
                "reviewer": cached.get("reviewer"),
                "merge_event_keys": list(decision.get("merge_event_keys") or []),
                "ranking_effect": "none",
                "persistence": "approved_cache_reapplied",
            }
            reapplied += 1
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            rejected += 1
    after = {
        key: (
            item.get("observed_rank"), item.get("rank"), item.get("score"),
            item.get("latest_source_ranks"), item.get("series"),
        )
        for key, item in by_key.items()
    }
    if before != after:
        raise ValueError("approved enrichment cache mutated observed ranking state")
    return {
        "status": "reapplied" if reapplied else "empty",
        "reapplied_count": reapplied,
        "rejected_count": rejected,
        "deferred_after_cutoff_count": deferred_after_cutoff,
        "ranking_effect": "none",
    }


def run_handoff(
    intelligence: dict,
    *,
    handoff_root: Path,
    at: datetime,
    enabled: bool,
    review_cutoff_at: datetime | None = None,
) -> dict:
    approved_cache = _reapply_approved_cache(
        intelligence,
        handoff_root=handoff_root,
        review_cutoff_at=review_cutoff_at,
    )
    if not enabled:
        return {
            "status": "deferred_to_enrichment_checkpoint",
            "approved_cache": approved_cache,
            "review_cutoff_at": (
                review_cutoff_at.astimezone(UTC).isoformat()
                if review_cutoff_at else None
            ),
            "deferred_after_cutoff_count": 0,
            "ranking_effect": "none",
        }
    batch, pending_path = export_candidate_batch(
        intelligence, handoff_root=handoff_root, at=at
    )
    template_path = handoff_root / "templates" / f"{batch['batch_id']}.json"
    if not template_path.exists():
        _atomic_json(template_path, review_template(batch))
    review_path = handoff_root / "reviewed" / f"{batch['batch_id']}.json"
    import_review_path = review_path
    try:
        selected = _latest_unconsumed_review(
            handoff_root,
            current_batch_id=batch["batch_id"],
            review_cutoff_at=review_cutoff_at,
        )
        import_batch, import_review_path = selected or (batch, review_path)
        if (
            selected is None
            and import_review_path.is_file()
            and not _review_is_within_cutoff(import_review_path, review_cutoff_at)
        ):
            # The current hour's review uses the same batch id.  Do not let the
            # direct-path fallback bypass the cutoff that rejected it above.
            result = {
                "status": "exported_waiting_review",
                "review_path": str(import_review_path),
            }
        else:
            result = import_reviewed_batch(
                intelligence, batch=import_batch, review_path=import_review_path
            )
        receipt_path = None
        imported_batch_id = None
        if result["status"] in {"reviewed_imported", "reviewed_empty"}:
            approved_paths = _persist_approved_decisions(
                handoff_root,
                batch=import_batch,
                review_path=import_review_path,
                at=at,
            )
            receipt_path = _record_consumed_review(
                handoff_root, batch=import_batch, result=result, at=at
            )
            imported_batch_id = import_batch["batch_id"]
            if imported_batch_id != batch["batch_id"]:
                result["status"] += "_previous"
            result["approved_cache_paths"] = [str(path) for path in approved_paths]
        result["imported_batch_id"] = imported_batch_id
        result["receipt_path"] = str(receipt_path) if receipt_path else None
    except (OSError, ValueError, json.JSONDecodeError):
        # A malformed human/LLM response is an auditable enrichment failure,
        # not a reason to lose the raw X/Google hourly collection.
        result = {
            "status": "reviewed_rejected",
            "review_path": str(import_review_path),
            "error_code": "reviewed_enrichment_validation_failed",
            "ranking_effect": "none",
        }
    return {
        **result,
        "schema_version": SCHEMA_VERSION,
        "batch_id": batch["batch_id"],
        "current_batch_id": batch["batch_id"],
        "pending_path": str(pending_path),
        "template_path": str(template_path),
        "candidate_count": len(batch["candidates"]),
        "review_cutoff_at": (
            review_cutoff_at.astimezone(UTC).isoformat()
            if review_cutoff_at else None
        ),
        "deferred_after_cutoff_count": _deferred_after_cutoff_count(
            handoff_root,
            current_batch_id=batch["batch_id"],
            review_cutoff_at=review_cutoff_at,
        ),
        "prohibited_authority": sorted(PROHIBITED_FIELDS),
        "approved_cache": approved_cache,
    }
