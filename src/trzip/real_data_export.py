from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


EXPORT_SCHEMA_VERSION = "trzip-real-data-export-v1"
APPROVED_CURRENT_COLLECTORS = {
    ("x", "x_current_session_kr_v1"),
    ("google_trends", "google_trending_now_kr_v1"),
}
PUBLIC_SOURCE_URLS = {
    "x": "https://x.com/explore/tabs/trending",
    "google_trends": "https://trends.google.com/trending?geo=KR",
}
COMMON_COLUMNS = (
    "record_id",
    "record_type",
    "dataset_group",
    "source",
    "observed_at",
    "topic",
    "query",
    "metric_name",
    "metric_value",
    "metric_unit",
    "metric_semantics",
    "provenance",
    "dataset_role",
    "collector_version",
    "sampling_frame",
    "live_rank_eligible",
    "ranking_effect",
    "evidence_url",
    "evidence_coverage",
    "window_start",
    "window_end",
    "source_rank",
    "source_asset_id",
    "payload",
)


@dataclass(frozen=True)
class ExportInputs:
    current_db: Path | None = None
    legacy_current_db: Path | None = None
    legacy_x_db: Path | None = None
    legacy_provider_db: Path | None = None
    legacy_x_dbs: tuple[Path, ...] = ()
    legacy_provider_dbs: tuple[Path, ...] = ()
    ontology_files: tuple[Path, ...] = ()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _asset_descriptor(asset_id: str, path: Path) -> dict[str, Any]:
    return {
        "source_asset_id": asset_id,
        "sha256": sha256_file(path),
        "byte_size": path.stat().st_size,
        "file_type": path.suffix.lower().lstrip(".") or "unknown",
    }


def _record(**values: Any) -> dict[str, Any]:
    row = {column: values.get(column) for column in COMMON_COLUMNS}
    row["payload"] = dict(row.get("payload") or {})
    identity = {key: row[key] for key in COMMON_COLUMNS if key != "record_id"}
    row["record_id"] = f"real-{_sha256_bytes(_json(identity).encode('utf-8'))[:24]}"
    return row


def _safe_json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _source_sampling_frame(source: str, collector_version: str | None) -> str:
    if (source, collector_version or "") == ("x", "x_current_session_kr_v1"):
        return "x_korea_realtime_complete_ranked_list_30"
    if (source, collector_version or "") == (
        "google_trends",
        "google_trending_now_kr_v1",
    ):
        return "google_trending_now_kr_complete_web_list"
    return "legacy_hourly_rank_snapshot_unknown_frame"


def _hourly_rows(
    path: Path,
    *,
    asset_id: str,
    current_asset: bool,
) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with _connect_read_only(path) as connection:
        if not _table_exists(connection, "hourly_observations"):
            return []
        columns = _columns(connection, "hourly_observations")
        optional = {
            "collector_version": "collector_version" if "collector_version" in columns else "NULL",
            "source_payload_json": (
                "source_payload_json" if "source_payload_json" in columns else "NULL"
            ),
            "related_terms_json": (
                "related_terms_json" if "related_terms_json" in columns else "NULL"
            ),
            "seed_observed_at": (
                "seed_observed_at" if "seed_observed_at" in columns else "NULL"
            ),
        }
        sql = f"""
            SELECT observed_at, source, topic, source_rank, value, provenance,
                   {optional['collector_version']} AS collector_version,
                   {optional['source_payload_json']} AS source_payload_json,
                   {optional['related_terms_json']} AS related_terms_json,
                   {optional['seed_observed_at']} AS seed_observed_at
            FROM hourly_observations
            WHERE provenance = 'observed'
            ORDER BY observed_at, source, source_rank, topic
        """
        source_rows = connection.execute(sql).fetchall()

    output: list[dict[str, Any]] = []
    for source_row in source_rows:
        source = str(source_row["source"])
        collector = str(source_row["collector_version"] or "") or None
        eligible = current_asset and (source, collector or "") in APPROVED_CURRENT_COLLECTORS
        group = "current_live_hourly" if eligible else "legacy_current_observed"
        semantics = (
            "rank in the complete X Korea realtime list"
            if source == "x" and eligible
            else "rank in the complete Google Trending Now Korea web list"
            if source == "google_trends" and eligible
            else "legacy source rank; collector completeness is not established"
        )
        output.append(
            _record(
                record_type="trend_observation",
                dataset_group=group,
                source=source,
                observed_at=source_row["observed_at"],
                topic=source_row["topic"],
                query=source_row["topic"],
                metric_name="source_rank",
                metric_value=source_row["source_rank"],
                metric_unit="ordinal_position",
                metric_semantics=semantics,
                provenance="observed",
                dataset_role="live_rank_input" if eligible else "historical_reference",
                collector_version=collector,
                sampling_frame=_source_sampling_frame(source, collector),
                live_rank_eligible=eligible,
                ranking_effect="score_input" if eligible else "none",
                evidence_url=PUBLIC_SOURCE_URLS.get(source),
                evidence_coverage="complete_list" if eligible else "legacy_unknown",
                window_start=source_row["observed_at"],
                window_end=source_row["observed_at"],
                source_rank=source_row["source_rank"],
                source_asset_id=asset_id,
                payload={
                    "stored_value": source_row["value"],
                    "related_terms": _safe_json(source_row["related_terms_json"], []),
                    "source_payload": _safe_json(source_row["source_payload_json"], {}),
                    "seed_observed_at": source_row["seed_observed_at"],
                },
            )
        )
    return output


_QUOTED_QUERY = re.compile(r'^\(\"(?P<topic>.+?)\"\)')


def _legacy_x_rows(path: Path, *, asset_id: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with _connect_read_only(path) as connection:
        required = {"raw_signals", "collection_runs"}
        if not all(_table_exists(connection, table) for table in required):
            return []
        live_runs = connection.execute(
            "SELECT COUNT(*) FROM collection_runs WHERE data_mode='live'"
        ).fetchone()[0]
        if not live_runs:
            return []
        rows = connection.execute(
            """
            SELECT raw.*, records.access_mode, records.source_name
            FROM raw_signals AS raw
            LEFT JOIN source_records AS records ON records.id = raw.source_record_id
            WHERE raw.platform='x'
              AND raw.analysis_disposition IN ('analyzed','policy_labeled')
              AND raw.coverage_state='available'
            ORDER BY raw.observed_at, raw.title, raw.id
            """
        ).fetchall()

    output: list[dict[str, Any]] = []
    for source_row in rows:
        query = str(source_row["title"] or "")
        match = _QUOTED_QUERY.match(query)
        topic = match.group("topic") if match else query
        output.append(
            _record(
                record_type="fixed_query_metric_observation",
                dataset_group="legacy_x_fixed_query_observed",
                source="x",
                observed_at=source_row["observed_at"],
                topic=topic,
                query=query,
                metric_name="mention_count",
                metric_value=source_row["metric_value"],
                metric_unit=source_row["metric_unit"],
                metric_semantics=source_row["metric_semantics"],
                provenance="observed",
                dataset_role="validation_reference",
                collector_version=source_row["access_mode"],
                sampling_frame=source_row["sampling_frame"],
                live_rank_eligible=False,
                ranking_effect="none",
                evidence_url=source_row["source_url"],
                evidence_coverage=source_row["coverage_state"],
                window_start=source_row["window_start"],
                window_end=source_row["window_end"],
                source_rank=None,
                source_asset_id=asset_id,
                payload={
                    "signal_kind": source_row["signal_kind"],
                    "baseline_value": source_row["baseline_value"],
                    "analysis_disposition": source_row["analysis_disposition"],
                    "quantitative_eligible_in_legacy_system": bool(
                        source_row["quantitative_eligible"]
                    ),
                },
            )
        )
    return output


def _first_query_term(expression: Any) -> str:
    parsed = _safe_json(expression, [])
    if isinstance(parsed, list) and parsed:
        return str(parsed[0])
    return str(expression or "")


def _legacy_provider_rows(path: Path, *, asset_id: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    output: list[dict[str, Any]] = []
    with _connect_read_only(path) as connection:
        if _table_exists(connection, "collection_runs"):
            live_runs = connection.execute(
                "SELECT COUNT(*) FROM collection_runs WHERE data_mode='live'"
            ).fetchone()[0]
            if not live_runs:
                return []

        if _table_exists(connection, "raw_signals"):
            raw_rows = connection.execute(
                """
                SELECT * FROM raw_signals
                WHERE platform IN (
                    'google-trending-now','google-news-evidence',
                    'youtube','naver-news','naver-search-trend'
                )
                  AND analysis_disposition IN ('analyzed','policy_labeled')
                  AND coverage_state='available'
                ORDER BY observed_at,platform,title,id
                """
            ).fetchall()
            source_map = {
                "google-trending-now": "google_trends_rss_legacy",
                "google-news-evidence": "google_news_legacy",
                "youtube": "youtube",
                "naver-news": "naver_news",
                "naver-search-trend": "naver_search_trend",
            }
            for source_row in raw_rows:
                platform = str(source_row["platform"])
                metric_value = source_row["metric_value"]
                output.append(
                    _record(
                        record_type="provider_raw_observation",
                        dataset_group="legacy_provider_raw_observed",
                        source=source_map[platform],
                        observed_at=source_row["observed_at"],
                        topic=source_row["title"],
                        query=source_row["title"],
                        metric_name=source_row["signal_kind"],
                        metric_value=1 if metric_value is None else metric_value,
                        metric_unit=source_row["metric_unit"] or "observed_item",
                        metric_semantics=source_row["metric_semantics"],
                        provenance="observed",
                        dataset_role="historical_provider_reference",
                        collector_version=source_row["access_method"],
                        sampling_frame=source_row["sampling_frame"],
                        live_rank_eligible=False,
                        ranking_effect="none",
                        evidence_url=source_row["source_url"],
                        evidence_coverage=source_row["coverage_state"],
                        window_start=source_row["window_start"],
                        window_end=source_row["window_end"],
                        source_rank=None,
                        source_asset_id=asset_id,
                        payload={
                            "source_signal_id": source_row["source_signal_id"],
                            "source_record_id": source_row["source_record_id"],
                            "text_excerpt": source_row["text_excerpt"],
                            "collected_at": source_row["collected_at"],
                            "event_at": source_row["event_at"],
                            "baseline_value": source_row["baseline_value"],
                            "analysis_disposition": source_row["analysis_disposition"],
                            "quantitative_eligible_in_legacy_system": bool(
                                source_row["quantitative_eligible"]
                            ),
                        },
                    )
                )

        mention_tables = {
            "mention_document_observations",
            "mention_documents",
            "mention_query_definitions",
        }
        if all(_table_exists(connection, table) for table in mention_tables):
            coverage_join = ""
            coverage_fields = "NULL AS retrieval_state, NULL AS sampling_frame"
            if _table_exists(connection, "mention_coverage_buckets"):
                coverage_join = """
                    LEFT JOIN mention_coverage_buckets AS coverage
                      ON coverage.query_definition_id = query.id
                     AND coverage.collection_run_id = observation.collection_run_id
                """
                coverage_fields = "coverage.retrieval_state, coverage.sampling_frame"
            mention_rows = connection.execute(
                f"""
                SELECT observation.observed_at, observation.window_start,
                       observation.window_end, query.source_family, query.expression,
                       query.operation, query.adapter_version, query.region_scope,
                       document.content_unit, document.canonical_url,
                       document.published_at, document.language_scope,
                       document.region_scope AS document_region_scope,
                       document.source_payload_hash,
                       {coverage_fields}
                FROM mention_document_observations AS observation
                JOIN mention_documents AS document
                  ON document.id = observation.mention_document_id
                JOIN mention_query_definitions AS query
                  ON query.id = observation.query_definition_id
                {coverage_join}
                WHERE query.source_family IN ('youtube','naver')
                ORDER BY observation.observed_at, query.source_family,
                         query.expression, document.canonical_url
                """
            ).fetchall()
            for source_row in mention_rows:
                topic = _first_query_term(source_row["expression"])
                output.append(
                    _record(
                        record_type="provider_document_observation",
                        dataset_group="legacy_provider_verification_observed",
                        source=(
                            "youtube"
                            if source_row["source_family"] == "youtube"
                            else "naver_news"
                        ),
                        observed_at=source_row["observed_at"],
                        topic=topic,
                        query=source_row["expression"],
                        metric_name="matched_document",
                        metric_value=1,
                        metric_unit=source_row["content_unit"],
                        metric_semantics="document returned for the fixed provider query",
                        provenance="observed",
                        dataset_role="validation_reference",
                        collector_version=source_row["adapter_version"],
                        sampling_frame=source_row["sampling_frame"],
                        live_rank_eligible=False,
                        ranking_effect="none",
                        evidence_url=source_row["canonical_url"],
                        evidence_coverage=source_row["retrieval_state"] or "unknown",
                        window_start=source_row["window_start"],
                        window_end=source_row["window_end"],
                        source_rank=None,
                        source_asset_id=asset_id,
                        payload={
                            "operation": source_row["operation"],
                            "published_at": source_row["published_at"],
                            "language_scope": source_row["language_scope"],
                            "region_scope": source_row["document_region_scope"],
                            "source_payload_hash": source_row["source_payload_hash"],
                        },
                    )
                )

        if _table_exists(connection, "metric_observations") and _table_exists(
            connection, "raw_signals"
        ):
            metric_rows = connection.execute(
                """
                SELECT metric.*, raw.platform, raw.title, raw.source_url,
                       raw.access_method, raw.analysis_disposition
                FROM metric_observations AS metric
                JOIN raw_signals AS raw ON raw.id = metric.raw_signal_id
                WHERE raw.platform IN ('youtube','naver-search-trend')
                  AND raw.analysis_disposition IN ('analyzed','policy_labeled')
                  AND metric.coverage_state='available'
                ORDER BY metric.observed_at, raw.platform, raw.title, metric.id
                """
            ).fetchall()
            for source_row in metric_rows:
                platform = str(source_row["platform"])
                output.append(
                    _record(
                        record_type="provider_metric_observation",
                        dataset_group="legacy_provider_verification_observed",
                        source=(
                            "youtube" if platform == "youtube" else "naver_search_trend"
                        ),
                        observed_at=source_row["observed_at"],
                        topic=source_row["title"],
                        query=source_row["title"],
                        metric_name=source_row["metric_name"],
                        metric_value=source_row["metric_value"],
                        metric_unit=source_row["metric_unit"],
                        metric_semantics=source_row["metric_semantics"],
                        provenance="observed",
                        dataset_role="validation_reference",
                        collector_version=source_row["access_method"],
                        sampling_frame=source_row["sampling_frame"],
                        live_rank_eligible=False,
                        ranking_effect="none",
                        evidence_url=source_row["source_url"],
                        evidence_coverage=source_row["coverage_state"],
                        window_start=source_row["window_start"],
                        window_end=source_row["window_end"],
                        source_rank=None,
                        source_asset_id=asset_id,
                        payload={
                            "sampled_at": source_row["sampled_at"],
                            "quantitative_eligible_in_legacy_system": bool(
                                source_row["quantitative_eligible"]
                            ),
                            "analysis_disposition": source_row["analysis_disposition"],
                        },
                    )
                )
    return output


def _current_evidence_rows(path: Path, *, asset_id: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    output: list[dict[str, Any]] = []
    with _connect_read_only(path) as connection:
        if _table_exists(connection, "keyword_candidate_evidence"):
            task_join = ""
            task_fields = "evidence.candidate_key AS display_text"
            if _table_exists(connection, "keyword_candidate_tasks"):
                task_join = """
                    LEFT JOIN keyword_candidate_tasks AS task
                      ON task.event_key=evidence.event_key
                     AND task.candidate_key=evidence.candidate_key
                """
                task_fields = "COALESCE(task.display_text,evidence.candidate_key) AS display_text"
            representative_join = ""
            representative_field = "evidence.event_key AS representative_term"
            if _table_exists(connection, "enrichment_tasks"):
                representative_join = """
                    LEFT JOIN enrichment_tasks AS enrichment
                      ON enrichment.event_key=evidence.event_key
                """
                representative_field = (
                    "COALESCE(MAX(enrichment.representative_term),evidence.event_key) "
                    "AS representative_term"
                )
            rows = connection.execute(
                f"""
                SELECT evidence.*, {task_fields}, {representative_field}
                FROM keyword_candidate_evidence AS evidence
                {task_join}
                {representative_join}
                GROUP BY evidence.event_key,evidence.candidate_key,evidence.provider,
                         evidence.title,evidence.url,evidence.published_at,evidence.observed_at
                ORDER BY evidence.observed_at,evidence.event_key,evidence.candidate_key,
                         evidence.provider,evidence.url
                """
            ).fetchall()
            for source_row in rows:
                output.append(
                    _record(
                        record_type="related_keyword_evidence",
                        dataset_group="current_related_keyword_evidence",
                        source=source_row["provider"],
                        observed_at=source_row["observed_at"],
                        topic=source_row["representative_term"],
                        query=source_row["display_text"],
                        metric_name="evidence_item",
                        metric_value=1,
                        metric_unit="public_result",
                        metric_semantics="public provider result supporting a keyword candidate",
                        provenance="observed",
                        dataset_role="keyword_validation_reference",
                        collector_version="keyword_candidate_evidence_v1",
                        sampling_frame="provider_search_result_evidence",
                        live_rank_eligible=False,
                        ranking_effect="none",
                        evidence_url=source_row["url"],
                        evidence_coverage="observed_result",
                        window_start=source_row["published_at"],
                        window_end=source_row["observed_at"],
                        source_rank=None,
                        source_asset_id=asset_id,
                        payload={
                            "event_key": source_row["event_key"],
                            "candidate_key": source_row["candidate_key"],
                            "title": source_row["title"],
                            "published_at": source_row["published_at"],
                        },
                    )
                )

        provider_tables = {"provider_evidence_items", "provider_verification_runs"}
        if all(_table_exists(connection, table) for table in provider_tables):
            rows = connection.execute(
                """
                SELECT item.*, run.observed_at, run.trend_key,
                       run.representative_term, run.provider, run.status,
                       run.matched, run.endpoint, run.ranking_effect,
                       run.metrics_json AS run_metrics_json,
                       run.provenance_json AS run_provenance_json
                FROM provider_evidence_items AS item
                JOIN provider_verification_runs AS run ON run.id=item.run_id
                WHERE item.url IS NOT NULL AND trim(item.url) <> ''
                ORDER BY run.observed_at,run.representative_term,run.provider,
                         item.item_order,item.url
                """
            ).fetchall()
            for source_row in rows:
                output.append(
                    _record(
                        record_type="provider_evidence",
                        dataset_group="current_provider_verification_evidence",
                        source=source_row["provider"],
                        observed_at=source_row["observed_at"],
                        topic=source_row["representative_term"],
                        query=source_row["representative_term"],
                        metric_name=source_row["item_type"],
                        metric_value=1,
                        metric_unit="public_result",
                        metric_semantics="provider evidence returned for an observed trend",
                        provenance="observed",
                        dataset_role="provider_validation_reference",
                        collector_version="provider_verification_v1",
                        sampling_frame=source_row["endpoint"],
                        live_rank_eligible=False,
                        ranking_effect="none",
                        evidence_url=source_row["url"],
                        evidence_coverage=source_row["status"],
                        window_start=source_row["published_at"],
                        window_end=source_row["observed_at"],
                        source_rank=source_row["item_order"],
                        source_asset_id=asset_id,
                        payload={
                            "trend_key": source_row["trend_key"],
                            "matched": bool(source_row["matched"]),
                            "provider_item_id": source_row["provider_item_id"],
                            "title": source_row["title"],
                            "publisher": source_row["publisher"],
                            "metrics": _safe_json(source_row["metrics_json"], {}),
                            "provenance": _safe_json(
                                source_row["provenance_json"], {}
                            ),
                            "run_metrics": _safe_json(
                                source_row["run_metrics_json"], {}
                            ),
                        },
                    )
                )
    return output


def _ontology_rows(
    path: Path,
    *,
    asset_id: str,
    node_catalog: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    nodes = dict(node_catalog or {})
    nodes.update({str(item["id"]): item for item in payload.get("nodes") or []})
    evidence = {str(item["id"]): item for item in payload.get("evidence") or []}
    metadata = dict(payload.get("metadata") or {})
    reviewed_at = metadata.get("reviewed_at")
    output: list[dict[str, Any]] = []
    referenced_evidence: set[str] = set()

    approved_edges = [
        item
        for item in payload.get("edges") or []
        if str(item.get("review_status")) == "approved"
    ]
    for edge in approved_edges:
        evidence_ids = [str(value) for value in edge.get("evidence_ids") or []]
        records = [evidence[value] for value in evidence_ids if value in evidence]
        approved_records = [
            record for record in records if str(record.get("review_status")) == "approved"
        ]
        if not evidence_ids or len(approved_records) != len(evidence_ids):
            continue
        referenced_evidence.update(evidence_ids)
        start_id = str(edge.get("from_node"))
        end_id = str(edge.get("to_node"))
        start = nodes.get(start_id, {"id": start_id, "label": start_id, "type": "unknown"})
        end = nodes.get(end_id, {"id": end_id, "label": end_id, "type": "unknown"})
        urls = [str(record.get("url")) for record in approved_records if record.get("url")]
        if not urls:
            continue
        output.append(
            _record(
                record_type="ontology_edge",
                dataset_group="reviewed_company_ontology",
                source="reviewed_public_evidence",
                observed_at=reviewed_at,
                topic=start.get("label"),
                query=end.get("label"),
                metric_name=edge.get("relation_type"),
                metric_value=1,
                metric_unit="reviewed_relation",
                metric_semantics="URL-evidenced reviewed ontology relation",
                provenance="reviewed_public_evidence",
                dataset_role="ontology_training_reference",
                collector_version=payload.get("schema_version"),
                sampling_frame="manual_url_reviewed_public_sources",
                live_rank_eligible=False,
                ranking_effect="none",
                evidence_url=urls[0],
                evidence_coverage="all_referenced_evidence_approved",
                window_start=min(
                    (record.get("published_at") for record in approved_records if record.get("published_at")),
                    default=None,
                ),
                window_end=reviewed_at,
                source_rank=None,
                source_asset_id=asset_id,
                payload={
                    "edge_id": edge.get("id"),
                    "from_node": start,
                    "to_node": end,
                    "relation_type": edge.get("relation_type"),
                    "evidence_ids": evidence_ids,
                    "evidence_urls": urls,
                    "metadata": edge.get("metadata") or {},
                    "provenance": edge.get("provenance") or {},
                },
            )
        )

    for kind, record_type, label_field in (
        ("aliases", "reviewed_alias", "label"),
        ("related_terms", "reviewed_related_term", "label"),
    ):
        for item in payload.get(kind) or []:
            if str(item.get("review_status")) != "approved":
                continue
            evidence_ids = [str(value) for value in item.get("evidence_ids") or []]
            records = [evidence[value] for value in evidence_ids if value in evidence]
            if not evidence_ids or len(records) != len(evidence_ids):
                continue
            if any(str(record.get("review_status")) != "approved" for record in records):
                continue
            urls = [str(record.get("url")) for record in records if record.get("url")]
            if not urls:
                continue
            referenced_evidence.update(evidence_ids)
            target_id = str(item.get("target_node_id"))
            target = nodes.get(
                target_id,
                {"id": target_id, "label": target_id, "type": "unknown"},
            )
            output.append(
                _record(
                    record_type=record_type,
                    dataset_group="reviewed_company_ontology",
                    source="reviewed_public_evidence",
                    observed_at=reviewed_at,
                    topic=target.get("label"),
                    query=item.get(label_field),
                    metric_name=item.get("relation_role") or item.get("match_type"),
                    metric_value=1,
                    metric_unit="reviewed_relation",
                    metric_semantics="reviewed related term or literal alias",
                    provenance="reviewed_public_evidence",
                    dataset_role="ontology_training_reference",
                    collector_version=payload.get("schema_version"),
                    sampling_frame="manual_url_reviewed_public_sources",
                    live_rank_eligible=False,
                    ranking_effect="none",
                    evidence_url=urls[0],
                    evidence_coverage="all_referenced_evidence_approved",
                    window_start=min(
                        (record.get("published_at") for record in records if record.get("published_at")),
                        default=None,
                    ),
                    window_end=reviewed_at,
                    source_rank=None,
                    source_asset_id=asset_id,
                    payload={
                        "relation_id": item.get("id"),
                        "target_node": target,
                        "evidence_ids": evidence_ids,
                        "evidence_urls": urls,
                        "provenance": item.get("provenance") or {},
                    },
                )
            )

    for evidence_id in sorted(referenced_evidence):
        item = evidence.get(evidence_id)
        if not item or str(item.get("review_status")) != "approved" or not item.get("url"):
            continue
        output.append(
            _record(
                record_type="ontology_evidence",
                dataset_group="reviewed_company_ontology",
                source=item.get("publisher") or "reviewed_public_evidence",
                observed_at=reviewed_at,
                topic=item.get("title"),
                query=item.get("summary"),
                metric_name=item.get("evidence_type"),
                metric_value=1,
                metric_unit="reviewed_evidence",
                metric_semantics="reviewed public source supporting ontology relations",
                provenance="reviewed_public_evidence",
                dataset_role="ontology_training_reference",
                collector_version=payload.get("schema_version"),
                sampling_frame="manual_url_reviewed_public_sources",
                live_rank_eligible=False,
                ranking_effect="none",
                evidence_url=item.get("url"),
                evidence_coverage="approved",
                window_start=item.get("published_at"),
                window_end=reviewed_at,
                source_rank=None,
                source_asset_id=asset_id,
                payload={
                    "evidence_id": evidence_id,
                    "publisher": item.get("publisher"),
                    "summary": item.get("summary"),
                    "provenance": item.get("provenance") or {},
                },
            )
        )
    return output


def _deduplicate(records: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates = 0
    for record in records:
        key_payload = {
            key: value
            for key, value in record.items()
            if key not in {"record_id", "source_asset_id"}
        }
        key = _sha256_bytes(_json(key_payload).encode("utf-8"))
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        unique.append(record)
    unique.sort(
        key=lambda row: (
            str(row.get("dataset_group") or ""),
            str(row.get("source") or ""),
            str(row.get("observed_at") or ""),
            str(row.get("topic") or ""),
            str(row.get("query") or ""),
            str(row.get("record_id") or ""),
        )
    )
    return unique, duplicates


def _serializable(record: dict[str, Any]) -> dict[str, Any]:
    return {column: record.get(column) for column in COMMON_COLUMNS}


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(_json(_serializable(record)))
            handle.write("\n")


def _write_csv(path: Path, records: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COMMON_COLUMNS)
        writer.writeheader()
        for record in records:
            row = _serializable(record)
            row["payload"] = _json(row["payload"])
            writer.writerow(row)


def _write_inventory(path: Path, records: list[dict[str, Any]]) -> int:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    key_fields = (
        "dataset_group",
        "source",
        "record_type",
        "topic",
        "query",
        "metric_name",
        "metric_unit",
        "metric_semantics",
        "dataset_role",
        "collector_version",
        "sampling_frame",
        "live_rank_eligible",
        "ranking_effect",
    )
    for record in records:
        grouped[tuple(record.get(field) for field in key_fields)].append(record)
    fieldnames = (
        *key_fields,
        "row_count",
        "first_observed_at",
        "last_observed_at",
        "evidence_url_count",
        "example_evidence_url",
    )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for key in sorted(grouped, key=lambda value: tuple(str(item or "") for item in value)):
            group = grouped[key]
            timestamps = sorted(
                str(item["observed_at"]) for item in group if item.get("observed_at")
            )
            urls = sorted({str(item["evidence_url"]) for item in group if item.get("evidence_url")})
            writer.writerow(
                {
                    **dict(zip(key_fields, key, strict=True)),
                    "row_count": len(group),
                    "first_observed_at": timestamps[0] if timestamps else None,
                    "last_observed_at": timestamps[-1] if timestamps else None,
                    "evidence_url_count": len(urls),
                    "example_evidence_url": urls[0] if urls else None,
                }
            )
    return len(grouped)


def _write_ontology_relations(path: Path, records: list[dict[str, Any]]) -> int:
    relations = [
        record
        for record in records
        if record["dataset_group"] == "reviewed_company_ontology"
        and record["record_type"] in {"ontology_edge", "reviewed_alias", "reviewed_related_term"}
    ]
    fieldnames = (
        "record_type",
        "representative_term",
        "related_item",
        "target_type",
        "relationship",
        "evidence_url",
        "all_evidence_urls",
        "reviewed_at",
        "source_asset_id",
    )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in relations:
            payload = dict(record.get("payload") or {})
            target = dict(payload.get("to_node") or payload.get("target_node") or {})
            writer.writerow(
                {
                    "record_type": record["record_type"],
                    "representative_term": record["topic"],
                    "related_item": record["query"],
                    "target_type": target.get("type"),
                    "relationship": record["metric_name"],
                    "evidence_url": record["evidence_url"],
                    "all_evidence_urls": _json(payload.get("evidence_urls") or []),
                    "reviewed_at": record["observed_at"],
                    "source_asset_id": record["source_asset_id"],
                }
            )
    return len(relations)


def _dataset_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    timestamps = sorted(str(row["observed_at"]) for row in records if row.get("observed_at"))
    topic_values = {str(row["topic"]) for row in records if row.get("topic")}
    query_values = {str(row["query"]) for row in records if row.get("query")}
    url_count = sum(bool(row.get("evidence_url")) for row in records)
    required_missing = Counter()
    for field in ("source", "topic", "provenance", "dataset_role", "sampling_frame"):
        required_missing[field] = sum(not row.get(field) for row in records)
    return {
        "row_count": len(records),
        "source_counts": dict(sorted(Counter(str(row["source"]) for row in records).items())),
        "record_type_counts": dict(
            sorted(Counter(str(row["record_type"]) for row in records).items())
        ),
        "first_observed_at": timestamps[0] if timestamps else None,
        "last_observed_at": timestamps[-1] if timestamps else None,
        "unique_topics": len(topic_values),
        "unique_queries": len(query_values),
        "evidence_url_coverage": round(url_count / len(records), 6) if records else 0,
        "live_rank_eligible_rows": sum(bool(row["live_rank_eligible"]) for row in records),
        "required_field_missing": dict(required_missing),
    }


def build_real_data_export(
    inputs: ExportInputs,
    output_dir: Path,
    *,
    create_zip: bool = True,
) -> dict[str, Any]:
    """Export only real observations and reviewed public evidence.

    Generated, synthetic, fixture, replay-only and static-demo rows have no
    ingestion path in this function.  Current hourly rows additionally require
    ``provenance='observed'``; only production collector cohorts are marked
    eligible for the live ranking.
    """

    output_dir.mkdir(parents=True, exist_ok=False)
    dataset_dir = output_dir / "datasets"
    dataset_dir.mkdir()

    assets: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []

    def register(asset_id: str, path: Path | None) -> bool:
        if path is None or not path.exists():
            return False
        assets.append(_asset_descriptor(asset_id, path))
        return True

    if register("current_runtime_sqlite", inputs.current_db):
        assert inputs.current_db is not None
        records.extend(
            _hourly_rows(
                inputs.current_db,
                asset_id="current_runtime_sqlite",
                current_asset=True,
            )
        )
        records.extend(
            _current_evidence_rows(
                inputs.current_db,
                asset_id="current_runtime_sqlite",
            )
        )
    if register("legacy_current_sqlite", inputs.legacy_current_db):
        assert inputs.legacy_current_db is not None
        records.extend(
            _hourly_rows(
                inputs.legacy_current_db,
                asset_id="legacy_current_sqlite",
                current_asset=False,
            )
        )
    legacy_x_paths = tuple(
        dict.fromkeys(
            path
            for path in ((inputs.legacy_x_db,) + inputs.legacy_x_dbs)
            if path is not None
        )
    )
    for index, legacy_x_path in enumerate(legacy_x_paths, start=1):
        asset_id = f"legacy_x_fixed_query_sqlite_{index:02d}"
        if register(asset_id, legacy_x_path):
            records.extend(_legacy_x_rows(legacy_x_path, asset_id=asset_id))

    legacy_provider_paths = tuple(
        dict.fromkeys(
            path
            for path in ((inputs.legacy_provider_db,) + inputs.legacy_provider_dbs)
            if path is not None
        )
    )
    for index, legacy_provider_path in enumerate(legacy_provider_paths, start=1):
        asset_id = f"legacy_provider_sqlite_{index:02d}"
        if register(asset_id, legacy_provider_path):
            records.extend(
                _legacy_provider_rows(legacy_provider_path, asset_id=asset_id)
            )
    ontology_node_catalog: dict[str, dict[str, Any]] = {}
    for ontology_path in inputs.ontology_files:
        if not ontology_path.exists():
            continue
        ontology_payload = json.loads(ontology_path.read_text(encoding="utf-8"))
        ontology_node_catalog.update(
            {
                str(item["id"]): item
                for item in ontology_payload.get("nodes") or []
                if item.get("id")
            }
        )
    for index, ontology_path in enumerate(inputs.ontology_files, start=1):
        asset_id = f"reviewed_ontology_{index:02d}"
        if register(asset_id, ontology_path):
            records.extend(
                _ontology_rows(
                    ontology_path,
                    asset_id=asset_id,
                    node_catalog=ontology_node_catalog,
                )
            )

    records, duplicate_count = _deduplicate(records)
    if any(row["provenance"] not in {"observed", "reviewed_public_evidence"} for row in records):
        raise ValueError("export contains a non-real provenance row")
    if any(str(row["dataset_role"]).casefold() in {"fixture", "demo", "synthetic"} for row in records):
        raise ValueError("export contains a prohibited dataset role")

    all_jsonl = output_dir / "records.jsonl"
    all_csv = output_dir / "records.csv"
    inventory_csv = output_dir / "inventory_by_platform_and_topic.csv"
    ontology_relations_csv = output_dir / "keywords_and_company_relations.csv"
    _write_jsonl(all_jsonl, records)
    _write_csv(all_csv, records)
    inventory_count = _write_inventory(inventory_csv, records)
    ontology_relation_count = _write_ontology_relations(ontology_relations_csv, records)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["dataset_group"])].append(record)
    dataset_files: list[dict[str, Any]] = []
    summaries: dict[str, Any] = {}
    for group in sorted(grouped):
        group_jsonl = dataset_dir / f"{group}.jsonl"
        group_csv = dataset_dir / f"{group}.csv"
        _write_jsonl(group_jsonl, grouped[group])
        _write_csv(group_csv, grouped[group])
        summaries[group] = _dataset_summary(grouped[group])
        dataset_files.extend(
            [
                {
                    "path": group_jsonl.relative_to(output_dir).as_posix(),
                    "sha256": sha256_file(group_jsonl),
                    "byte_size": group_jsonl.stat().st_size,
                    "row_count": len(grouped[group]),
                },
                {
                    "path": group_csv.relative_to(output_dir).as_posix(),
                    "sha256": sha256_file(group_csv),
                    "byte_size": group_csv.stat().st_size,
                    "row_count": len(grouped[group]),
                },
            ]
        )

    x_legacy = grouped.get("legacy_x_fixed_query_observed", [])
    x_timestamps = sorted(
        str(row["observed_at"]) for row in x_legacy if row.get("observed_at")
    )
    quality_findings: list[dict[str, Any]] = []
    if x_legacy:
        quality_findings.append(
            {
                "severity": "high",
                "finding": "legacy X asset is recent-count buckets, not a verified 90-day full archive",
                "evidence": {
                    "row_count": len(x_legacy),
                    "first_observed_at": x_timestamps[0] if x_timestamps else None,
                    "last_observed_at": x_timestamps[-1] if x_timestamps else None,
                    "sampling_frames": sorted(
                        {str(row["sampling_frame"]) for row in x_legacy}
                    ),
                },
                "impact": "safe for historical query evidence, unsafe to describe as 90-day X coverage",
            }
        )
    legacy_rows = grouped.get("legacy_current_observed", [])
    if legacy_rows:
        quality_findings.append(
            {
                "severity": "medium",
                "finding": "legacy hourly observations lack the current collector-completeness contract",
                "evidence": {"row_count": len(legacy_rows)},
                "impact": "kept for fine-tuning/reference but excluded from current ranking",
            }
        )

    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    manifest = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "purpose": "fine-tuning and inspection export of real TRZIP observations",
        "row_grain": "one observed source record, provider evidence item, or reviewed ontology fact",
        "accepted_provenance": ["observed", "reviewed_public_evidence"],
        "hard_exclusions": [
            "generated",
            "synthetic",
            "fixture",
            "static_demo",
            "deterministic_replay_without_source_observation",
        ],
        "ranking_policy": {
            "current_rank_inputs": ["X Korea realtime complete list", "Google Trending Now Korea complete web list"],
            "validation_and_ontology_ranking_effect": "none",
            "legacy_observation_ranking_effect": "none",
        },
        "source_assets": assets,
        "overall": {
            "row_count": len(records),
            "exact_duplicate_rows_removed": duplicate_count,
            "dataset_count": len(grouped),
            "source_counts": dict(sorted(Counter(str(row["source"]) for row in records).items())),
            "provenance_counts": dict(
                sorted(Counter(str(row["provenance"]) for row in records).items())
            ),
            "live_rank_eligible_rows": sum(bool(row["live_rank_eligible"]) for row in records),
            "evidence_url_rows": sum(bool(row["evidence_url"]) for row in records),
        },
        "datasets": summaries,
        "files": [
            {
                "path": "records.jsonl",
                "sha256": sha256_file(all_jsonl),
                "byte_size": all_jsonl.stat().st_size,
                "row_count": len(records),
            },
            {
                "path": "records.csv",
                "sha256": sha256_file(all_csv),
                "byte_size": all_csv.stat().st_size,
                "row_count": len(records),
            },
            {
                "path": "inventory_by_platform_and_topic.csv",
                "sha256": sha256_file(inventory_csv),
                "byte_size": inventory_csv.stat().st_size,
                "row_count": inventory_count,
            },
            {
                "path": "keywords_and_company_relations.csv",
                "sha256": sha256_file(ontology_relations_csv),
                "byte_size": ontology_relations_csv.stat().st_size,
                "row_count": ontology_relation_count,
            },
            *dataset_files,
        ],
        "quality_findings": quality_findings,
        "privacy": {
            "absolute_local_paths_in_manifest": False,
            "credentials_exported": False,
            "source_assets_identified_by": "stable logical id plus sha256",
        },
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    zip_path: Path | None = None
    if create_zip:
        zip_path = output_dir.with_suffix(".zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(output_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(output_dir.parent))
    return {
        "output_dir": output_dir,
        "manifest_path": manifest_path,
        "jsonl_path": all_jsonl,
        "csv_path": all_csv,
        "zip_path": zip_path,
        "manifest": manifest,
    }
