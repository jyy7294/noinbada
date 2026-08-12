from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .curation import CATEGORY_BY_TERM, is_sensitive_context
from .hourly_store import (
    KST,
    connect,
    default_db_path,
    floor_hour,
    source_hour_quality,
)
from .value_chain import expand_value_chain
from .event_resolution import (
    GROUND_TRUTH,
    evaluate_resolution,
    observation_summary,
    resolve_event,
)
from .ontology import (
    DEFAULT_PUBLISHABLE_REVIEW_STATUSES,
    MINIMUM_PUBLISHED_COMPANIES,
    OntologyGraph,
)
from .provider_verification import latest_verification_by_trend
from .trend_fit import assess_trend_fit


ONTOLOGY_SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "ontology_seed.json"
ONTOLOGY_ENRICHMENT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "ontology_enrichment.json"
)


ALIASES = {
    "두바이초콜릿": "두바이 초콜릿",
    "오징어게임": "오징어 게임",
    # This is the one reviewed event grouping retained from the product
    # decision: the observed display term still comes from the source rows.
    "삼계탕": "말복",
    "보양식": "말복",
    # A release-query suffix does not create a second macro event. Both raw
    # expressions remain in raw_terms/keywords and the current observed form
    # still owns the public representative label.
    "cpi 발표": "cpi",
    "CPI 발표": "cpi",
}

def canonical_topic(raw: str) -> str:
    compact = " ".join(raw.strip().split())
    legacy = ALIASES.get(compact, compact)
    return resolve_event(legacy, set())["canonical"]


def _category(topic: str) -> str:
    if topic == "말복":
        return "seasonal_food_ritual"
    explicit = CATEGORY_BY_TERM.get(topic)
    if explicit:
        return explicit
    lowered = topic.casefold()
    heuristic_categories = (
        (("밥", "초밥", "치킨", "라면", "빵", "쿠키", "초콜릿", "커피", "맛집", "음식", "삼계탕", "디저트"), "food_culinary"),
        ((
            "영화", "드라마", "예능", "웹툰", "애니", "극장", "방송",
            "티빙", "넷플릭스", "ott", "시리즈", "사건반장", "블랙박스 리뷰",
            "건축탐구", "나솔", "미스코리아", "트로트",
        ), "screen_content"),
        (("콘서트", "공연", "앨범", "노래", "뮤직", "아이돌", "생일"), "music_performance"),
        ((
            "야구", "축구", "테니스", "농구", "선수", "감독", "타격왕",
            "프로골퍼", " fc", "자이언츠", "레드삭스", "블루제이스",
            "메츠", "브레이브스",
        ), "sports_participation"),
        ((
            "게임", "패치", "롤 ", "오버워치", "스팀", "리그 오브 레전드",
            "검은사막", "지스타", "펄어비스", "펍지",
        ), "gaming_digital"),
        (("패션", "유니폼", "가방", "신발", "화장품"), "fashion_collectible"),
        (("여행", "호텔", "축제", "팝업", "전시"), "place_experience"),
        ((
            "주식", "증시", "코스피", "코스닥", "채권", "금리", "증권",
            "상장폐지", "가상자산", "나스닥", "다우 존스", "cpi", "국채",
            "업비트", "미래에셋",
        ), "investment_market"),
        (("아이폰", "스마트폰", "폴더블", "메르세데스-amg"), "product_brand"),
        (("휴머노이드 로봇", "광 통신", "광통신", "smr"), "technology_tool"),
    )
    for markers, category in heuristic_categories:
        if any(marker in lowered for marker in markers):
            return category
    return "unclassified"


def _broad_category(category: str) -> str:
    """Map detailed internal labels to a compact frontend taxonomy."""
    mapping = {
        "food_culinary": "food",
        "seasonal_food_ritual": "food",
        "music_performance": "content",
        "screen_content": "content",
        "gaming_digital": "content",
        "sports_attendance": "sports",
        "sports_participation": "sports",
        "fashion_collectible": "lifestyle",
        "place_experience": "lifestyle",
        "lifestyle_behavior": "lifestyle",
        "wellness_behavior": "lifestyle",
        "participation_meme": "culture",
        "product_brand": "consumer",
        "technology_tool": "technology",
        "investment_market": "market",
        "policy_issue": "issue",
        "politics": "issue",
        "incident": "issue",
        "crime": "issue",
        "disaster": "issue",
        "weather_alert": "issue",
        "privacy_controversy": "issue",
    }
    return mapping.get(category, "other")


def _series_rows(start: datetime, end: datetime, path: Path | None = None) -> list[sqlite3.Row]:
    with connect(path) as connection:
        return connection.execute(
            """SELECT observation.observed_at,observation.source,observation.topic,
                       observation.source_rank,observation.value,observation.provenance,
                       observation.source_payload_json,observation.related_terms_json
               FROM hourly_observations AS observation
               JOIN source_hour_quality AS quality
                 USING (observed_at, source, provenance)
               WHERE observation.observed_at BETWEEN ? AND ?
                 AND observation.provenance='observed'
                 AND observation.collector_version IS NOT NULL
                 AND quality.quality_status='eligible'
               ORDER BY observation.observed_at,observation.source,
                        observation.source_rank,observation.topic""",
            (floor_hour(start).isoformat(), floor_hour(end).isoformat()),
        ).fetchall()


def _representative_observed_term(
    observations: list[dict],
    *,
    current_at: str | None = None,
) -> tuple[str, dict]:
    """Choose a representative only from observed source expressions.

    Current source expressions take precedence for a current ranking. Within
    that set the deterministic order is repeated hours, number of sources,
    reciprocal-rank evidence, best rank, then normalized lexical order. This
    prevents an expired historical alias from replacing what users can see in
    the latest source page. No hand-written narrative or entity label can
    replace the source expression.
    """
    evidence: dict[str, dict] = {}
    for item in observations:
        raw = " ".join(str(item["topic"]).strip().split())
        bucket = evidence.setdefault(
            raw,
            {
                "hours": set(),
                "sources": set(),
                "current_sources": set(),
                "rrf": 0.0,
                "best_rank": 10**9,
            },
        )
        bucket["hours"].add(item["observed_at"])
        bucket["sources"].add(item["source"])
        if current_at is not None and item["observed_at"] == current_at:
            bucket["current_sources"].add(item["source"])
        bucket["rrf"] += 1.0 / (60.0 + item["source_rank"])
        bucket["best_rank"] = min(bucket["best_rank"], item["source_rank"])
    representative = min(
        evidence,
        key=lambda term: (
            -bool(evidence[term]["current_sources"]),
            -len(evidence[term]["hours"]),
            -len(evidence[term]["sources"]),
            -evidence[term]["rrf"],
            evidence[term]["best_rank"],
            term.casefold(),
        ),
    )
    selected = evidence[representative]
    return representative, {
        "method": "current_observed_term_then_hours_sources_rrf",
        "currently_observed": bool(selected["current_sources"]),
        "current_source_count": len(selected["current_sources"]),
        "observed_hours": len(selected["hours"]),
        "source_count": len(selected["sources"]),
        "rrf_support": round(selected["rrf"], 6),
        "best_source_rank": selected["best_rank"],
    }


def _related_term_evidence(observations: list[dict], representative: str) -> list[dict]:
    evidence: dict[str, dict] = {}
    for item in observations:
        raw_term = " ".join(str(item["topic"]).strip().split())
        if raw_term and raw_term.casefold() != representative.casefold():
            bucket = evidence.setdefault(raw_term, {"sources": set(), "hours": set(), "kind": "observed_ranked_term"})
            bucket["sources"].add(item["source"])
            bucket["hours"].add(item["observed_at"])
        try:
            related_terms = json.loads(item.get("related_terms_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            related_terms = []
        if not isinstance(related_terms, list):
            continue
        for related in related_terms:
            text = " ".join(str(related).strip().split())
            if not text or text.casefold() == representative.casefold():
                continue
            bucket = evidence.setdefault(text, {"sources": set(), "hours": set(), "kind": "observed_related_query"})
            bucket["sources"].add(item["source"])
            bucket["hours"].add(item["observed_at"])
    ordered = sorted(
        evidence.items(),
        key=lambda pair: (-len(pair[1]["hours"]), -len(pair[1]["sources"]), pair[0].casefold()),
    )

    def draft_role(text: str) -> str:
        compact = text.casefold().replace(" ", "")
        representative_key = representative.casefold().replace(" ", "")
        if representative_key and (
            compact in representative_key or representative_key in compact
        ):
            return "alias_or_variant"
        if any(marker in compact for marker in (
            "레시피", "만들기", "챌린지", "품절", "구매처", "오픈런",
            "맛집", "후기", "먹방", "예약", "관람", "방문", "콜라보",
        )):
            return "consumer_or_participation_signal"
        if any(marker in compact for marker in (
            "재료", "제품", "메뉴", "굿즈", "브랜드", "신곡", "시즌",
            "패치", "유니폼", "앨범", "출연진",
        )):
            return "component_or_product"
        return "review_required"

    return [
        {
            "text": text,
            "source": sorted(meta["sources"]),
            "observed_hours": len(meta["hours"]),
            "status": meta["kind"],
            "role": draft_role(text),
            "role_status": "deterministic_draft",
            "affects_score": False,
        }
        for text, meta in ordered[:5]
    ]


def _hourly_and_daily_rankings(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    by_hour: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_hour[row["observed_at"]].append(row)
    hourly = []
    daily_events: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for stamp, hour_rows in sorted(by_hour.items()):
        available_sources = {row["source"] for row in hour_rows}
        denominator = max(len(available_sources) / 61.0, 1 / 61.0)
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in hour_rows:
            grouped[canonical_topic(row["topic"])].append(row)
        ranked = []
        for event_key, event_rows in grouped.items():
            representative, representative_evidence = _representative_observed_term(
                event_rows,
                current_at=stamp,
            )
            best_by_source = {
                source: min((row for row in event_rows if row["source"] == source), key=lambda row: row["source_rank"])
                for source in {row["source"] for row in event_rows}
            }
            normalized_rrf = sum(1 / (60 + row["source_rank"]) for row in best_by_source.values()) / denominator
            ranked.append({
                "event_key": event_key,
                "representative_term": representative,
                "representative_evidence": representative_evidence,
                "raw_terms": sorted({row["topic"] for row in event_rows}),
                "normalized_rrf": round(normalized_rrf, 6),
                "source_ranks": {source: row["source_rank"] for source, row in sorted(best_by_source.items())},
            })
        ranked.sort(key=lambda item: (-item["normalized_rrf"], item["representative_term"].casefold()))
        for rank, item in enumerate(ranked, 1):
            item["rank"] = rank
            daily_events[((datetime.fromisoformat(stamp) + KST).date().isoformat(), item["event_key"])].append(item)
        hourly.append({"observed_at": stamp, "available_sources": sorted(available_sources), "ranking": ranked})

    daily = []
    for (kst_date, event_key), items in sorted(daily_events.items()):
        representative_counts = Counter(item["representative_term"] for item in items)
        representative = min(representative_counts, key=lambda term: (-representative_counts[term], term.casefold()))
        daily.append({
            "kst_date": kst_date,
            "event_key": event_key,
            "representative_term": representative,
            "hours_present": len(items),
            "best_rank": min(item["rank"] for item in items),
            "mean_rank": round(sum(item["rank"] for item in items) / len(items), 4),
            "source_count": len({source for item in items for source in item["source_ranks"]}),
        })
    daily.sort(key=lambda item: (item["kst_date"], item["best_rank"], item["representative_term"].casefold()))
    return hourly, daily


def _ontology_company_candidates(
    graph: OntologyGraph,
    *,
    representative: str,
    related_terms: list[dict],
    sources: set[str],
    as_of: str,
) -> tuple[list[dict], dict]:
    """Resolve observed terms through the reviewed graph without padding.

    A candidate is complete only when the checked-in ontology contains a
    forward, evidence-backed path all the way to a listed-stock node.  The
    historical seed is a relationship lookup, never a ranking input.
    """

    source_urls = {
        "x": "https://x.com/explore/tabs/trending",
        "google_trends": "https://trends.google.com/trending?geo=KR",
    }
    observed_urls = [source_urls[source] for source in sorted(sources) if source in source_urls]
    observed_terms = [
        {"text": representative, "status": "observed_representative"},
        *[
            {"text": item["text"], "status": item.get("status", "observed_related_query")}
            for item in related_terms
        ],
    ]
    unique_terms: list[dict] = []
    seen_terms: set[str] = set()
    for item in observed_terms:
        key = str(item["text"]).casefold()
        if key not in seen_terms:
            unique_terms.append(item)
            seen_terms.add(key)

    edge_by_id = {str(edge["id"]): edge for edge in graph.edges}
    by_stock: dict[str, dict] = {}
    term_diagnostics: list[dict] = []
    for observed in unique_terms:
        term = str(observed["text"])
        resolution = graph.resolve_term(
            term,
            min_companies=MINIMUM_PUBLISHED_COMPANIES,
            max_hops=7,
        )
        term_diagnostics.append(
            {
                "term": term,
                "observation_status": observed["status"],
                "ontology_status": resolution["status"],
                "ontology_company_count": resolution["company_count"],
                "lookup_match": resolution.get("match"),
            }
        )
        lookup_match = resolution.get("match")
        if lookup_match is None:
            continue
        start_node_id = str(lookup_match["target_node_id"])
        paths = graph.trace_paths(
            start_node_id,
            target_types=("stock",),
            max_hops=7,
            allowed_review_statuses=DEFAULT_PUBLISHABLE_REVIEW_STATUSES,
        )
        for path in paths:
            nodes = [graph.node(node_id) for node_id in path.node_ids]
            company_node = next((node for node in nodes if node["type"] == "company"), None)
            stock_node = next((node for node in reversed(nodes) if node["type"] == "stock"), None)
            if not company_node or not stock_node:
                continue
            stock_code = str((stock_node.get("metadata") or {}).get("ticker") or "").strip()
            if not stock_code:
                continue

            ontology_path = [
                {
                    "from": representative,
                    "to": term,
                    "edge_type": (
                        "observed_term_exact_match"
                        if representative.casefold() == term.casefold()
                        else "observed_related_term"
                    ),
                    "evidence_urls": observed_urls,
                    "evidence_type": "source_page_observation",
                    "as_of": as_of,
                    "review_status": "observed",
                }
            ]
            evidence_records: list[dict] = []
            if lookup_match.get("match_type") != "exact_term":
                alias_records = list(lookup_match.get("evidence") or [])
                evidence_records.extend(alias_records)
                ontology_path.append(
                    {
                        "from": term,
                        "to": lookup_match["target_node_label"],
                        "edge_type": lookup_match["match_type"],
                        "evidence_urls": [record["url"] for record in alias_records],
                        "evidence_type": sorted(
                            {
                                str(record.get("evidence_type") or "documented_source")
                                for record in alias_records
                            }
                        ),
                        "as_of": next(
                            (
                                str(record.get("published_at"))
                                for record in alias_records
                                if record.get("published_at")
                            ),
                            as_of,
                        ),
                        "review_status": lookup_match["review_status"],
                    }
                )
            for edge_id in path.edge_ids:
                edge = edge_by_id[edge_id]
                records = [
                    graph.evidence_record(str(evidence_id))
                    for evidence_id in edge.get("evidence_ids", [])
                ]
                evidence_records.extend(records)
                ontology_path.append(
                    {
                        "from": graph.node(str(edge["from_node"]))["label"],
                        "to": graph.node(str(edge["to_node"]))["label"],
                        "edge_type": edge["relation_type"],
                        "evidence_urls": [record["url"] for record in records],
                        "evidence_type": sorted(
                            {str(record.get("evidence_type") or "documented_source") for record in records}
                        ),
                        "as_of": next(
                            (str(record.get("published_at")) for record in records if record.get("published_at")),
                            as_of,
                        ),
                        "review_status": edge["review_status"],
                    }
                )

            complete = bool(observed_urls) and all(
                edge["evidence_urls"]
                and edge["evidence_type"]
                and edge["as_of"]
                and edge["review_status"] in {
                    "observed", *DEFAULT_PUBLISHABLE_REVIEW_STATUSES,
                }
                for edge in ontology_path
            )
            relation_types = [edge_by_id[edge_id]["relation_type"] for edge_id in path.edge_ids]
            direct = any(
                relation
                in {
                    "historical_business_link",
                    "documented_business_relationship",
                    "documented_product_market_participant",
                    "denotes_listed_company",
                }
                for relation in relation_types
            )
            company_role = "직접 기업" if direct else "인프라·서비스"
            relation_tier = "core" if direct else "value_chain"
            first_evidence_url = next(
                (record["url"] for record in evidence_records if record.get("url")),
                None,
            )
            path_labels = [node["label"] for node in nodes]
            industry_labels = list(dict.fromkeys(
                node["label"] for node in nodes if node["type"] == "industry"
            ))
            evidence_sources = []
            seen_evidence_urls: set[str] = set()
            for record in evidence_records:
                url = str(record.get("url") or "").strip()
                if not url or url in seen_evidence_urls:
                    continue
                evidence_sources.append({
                    "url": url,
                    "title": record.get("title"),
                    "evidence_type": record.get("evidence_type"),
                    "published_at": record.get("published_at"),
                    "review_status": record.get("review_status"),
                })
                seen_evidence_urls.add(url)
            relation_reason = (
                f"관측어 '{term}'에서 {' → '.join(path_labels)}로 이어지는 "
                f"검수된 {len(path.edge_ids)}단계 온톨로지 경로"
            )
            candidate = {
                "company": company_node["label"],
                "stock_code": stock_code,
                "market": (stock_node.get("metadata") or {}).get("market"),
                "relation_type": relation_types[0] if relation_types else "ontology_path",
                "strength": "direct" if direct else "indirect",
                "reason": relation_reason,
                "relationship_reason": relation_reason,
                "company_summary": (
                    f"{(stock_node.get('metadata') or {}).get('market') or '국내'} 상장기업, "
                    f"종목코드 {stock_code}"
                ),
                "business_features": industry_labels,
                "evidence_kind": "reviewed_ontology_path",
                "evidence_url": first_evidence_url,
                "evidence_sources": evidence_sources,
                "company_role": company_role,
                "relation_tier": relation_tier,
                "relation_tier_label": "핵심 사업자" if direct else "가치사슬 기업",
                # The source observation is current, but an ontology document may
                # be historical.  Do not turn evidence of a relationship into an
                # unsupported claim that the relationship is current or that the
                # stock has high exposure.
                "relation_horizon": "근거 확인 직접 관계" if direct else "근거 확인 가치사슬 관계",
                "exposure_status": (
                    "evidence_backed_direct_relevance"
                    if direct
                    else "evidence_backed_value_chain_relevance"
                ),
                "verification_status": "ontology_evidence",
                "opportunity_status": "evidence_backed_candidate",
                "relation_display_type": "직접 관계" if direct else "가치사슬",
                "team_review_status": "ontology_reviewed",
                "team_review_label": "온톨로지 근거 검수됨",
                "investment_warning": "관계 분류는 주가 상승 예측이나 매수 추천이 아님",
                "matched_ontology_term": term,
                "matched_ontology_node": lookup_match["target_node_label"],
                "ontology_lookup_match_type": lookup_match["match_type"],
                "ontology_source": "reviewed_seed_plus_enrichment",
                "ontology_path": ontology_path,
                "ontology_complete": complete,
                "ontology_status": "complete" if complete else "incomplete",
            }
            previous = by_stock.get(stock_code)
            if complete and (
                previous is None
                or (term.casefold() == representative.casefold(), -len(path.edge_ids))
                > (
                    str(previous.get("matched_ontology_term", "")).casefold()
                    == representative.casefold(),
                    -len(previous.get("ontology_path", [])),
                )
            ):
                by_stock[stock_code] = candidate

    candidates = sorted(by_stock.values(), key=lambda item: (item["company"], item["stock_code"]))
    return candidates, {
        "seed_path": ONTOLOGY_SEED_PATH.name,
        "enrichment_path": ONTOLOGY_ENRICHMENT_PATH.name,
        "minimum_gold_companies": MINIMUM_PUBLISHED_COMPANIES,
        "matched_terms": term_diagnostics,
        "padding_forbidden": True,
        "ranking_effect": "none",
    }


def build_intelligence(
    at: datetime,
    *,
    hours: int = 24,
    path: Path | None = None,
    news_context_by_term: dict[str, dict] | None = None,
) -> dict:
    end = floor_hour(at)
    start = end - timedelta(hours=max(1, hours) - 1)
    rows = _series_rows(start, end, path)
    rows = [dict(row) for row in rows]
    hourly_ranking, daily_aggregates = _hourly_and_daily_rankings(rows)
    eligible_hours = sorted({row["observed_at"] for row in rows})
    eligible_hour_count = len(eligible_hours)
    snapshot_sizes = Counter((row["observed_at"], row["source"]) for row in rows)
    source_times: dict[str, list[str]] = defaultdict(list)
    for stamp, source in sorted(snapshot_sizes):
        source_times[source].append(stamp)
    current_available_sources = {
        source for source, stamps in source_times.items() if stamps and stamps[-1] == end.isoformat()
    }
    quality_rows = source_hour_quality(
        start,
        end,
        path,
    )
    quarantined_source_hours = [
        row for row in quality_rows if row["quality_status"] != "eligible"
    ]
    verification_by_trend = latest_verification_by_trend(path or default_db_path())
    ontology_graph = OntologyGraph.load_merged(
        ONTOLOGY_SEED_PATH,
        ONTOLOGY_ENRICHMENT_PATH,
    )
    news_context_by_term = news_context_by_term or {}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        item = dict(row)
        item["canonical_topic"] = canonical_topic(item["topic"])
        grouped[item["canonical_topic"]].append(item)

    candidates = []
    for event_key, observations in grouped.items():
        observations.sort(key=lambda item: (item["observed_at"], item["source"], item["source_rank"]))
        sources = {item["source"] for item in observations}
        representative_term, representative_evidence = _representative_observed_term(
            observations,
            current_at=end.isoformat(),
        )
        event_resolution = resolve_event(event_key, sources)
        observed_hours = len({item["observed_at"] for item in observations})
        history_by_source: dict[str, list[dict]] = defaultdict(list)
        for item in observations:
            history_by_source[item["source"]].append(item)
        current_by_source = {}
        for source in current_available_sources:
            current_rows = [
                item for item in history_by_source.get(source, [])
                if item["observed_at"] == end.isoformat()
            ]
            if current_rows:
                current_by_source[source] = min(current_rows, key=lambda item: item["source_rank"])

        # Historical observations remain in hourly/daily aggregates, but a
        # current ranking candidate must be present in at least one source's
        # verified snapshot for the requested hour. Persistence alone can
        # never resurrect an expired topic.
        if not current_by_source:
            continue

        rrf_raw = sum(1 / (60 + item["source_rank"]) for item in current_by_source.values())
        rrf_denominator = max(len(current_available_sources) / 61.0, 1 / 61.0)
        normalized_rrf = min(rrf_raw / rrf_denominator, 1.0)

        momentum_changes = []
        for source in sorted(current_available_sources):
            stamps = source_times[source]
            if len(stamps) < 2:
                continue
            previous_stamp, current_stamp = stamps[-2], stamps[-1]
            previous_rows = [
                item for item in history_by_source.get(source, [])
                if item["observed_at"] == previous_stamp
            ]
            current_rows = [
                item for item in history_by_source.get(source, [])
                if item["observed_at"] == current_stamp
            ]
            if not previous_rows and not current_rows:
                continue

            def position(items: list[dict], stamp: str) -> float:
                if not items:
                    return 0.0
                best_rank = min(item["source_rank"] for item in items)
                size = snapshot_sizes[(stamp, source)]
                return 1.0 if size <= 1 else 1.0 - ((best_rank - 1) / (size - 1))

            momentum_changes.append(
                position(current_rows, current_stamp) - position(previous_rows, previous_stamp)
            )
        momentum = (
            max(-1.0, min(1.0, sum(momentum_changes) / len(momentum_changes)))
            if momentum_changes else 0.0
        )
        persistence_rate = observed_hours / max(eligible_hour_count, 1)
        history_maturity = min(eligible_hour_count / 96.0, 1.0)
        persistence = min(persistence_rate * history_maturity, 1.0)
        cross = 1.0 if len(current_by_source) >= 2 else 0.0
        rank_changes = {}
        for source, history in history_by_source.items():
            best_rank_by_time = {}
            for item in history:
                stamp = item["observed_at"]
                best_rank_by_time[stamp] = min(best_rank_by_time.get(stamp, item["source_rank"]), item["source_rank"])
            ranked_times = sorted(best_rank_by_time)
            if len(ranked_times) >= 2:
                # Positive means the item moved upward (for example 8th -> 3rd is +5).
                rank_changes[source] = best_rank_by_time[ranked_times[-2]] - best_rank_by_time[ranked_times[-1]]
            else:
                rank_changes[source] = None
        first_seen = min(item["observed_at"] for item in observations)
        last_seen = max(item["observed_at"] for item in observations)
        first_seen_dt = datetime.fromisoformat(first_seen)
        last_seen_dt = datetime.fromisoformat(last_seen)
        is_current = last_seen_dt == end
        age_hours = max(0, int((end - first_seen_dt).total_seconds() // 3600))
        best_change = max((value for value in rank_changes.values() if value is not None), default=0)
        observed_times = sorted({datetime.fromisoformat(item["observed_at"]) for item in observations})
        max_gap_hours = max(
            ((later - earlier).total_seconds() / 3600 for earlier, later in zip(observed_times, observed_times[1:])),
            default=0,
        )
        if not is_current:
            lifecycle, lifecycle_reason = "cooling", "현재 시간에는 보이지 않아 둔화·이탈 관찰 중"
        elif age_hours <= 2:
            lifecycle, lifecycle_reason = "new", "최근 3시간 안에 처음 포착"
        elif max_gap_hours >= 24:
            lifecycle, lifecycle_reason = "rebounding", "24시간 이상 관측 공백 뒤 다시 포착"
        elif momentum >= 0.12 or best_change >= 3:
            lifecycle, lifecycle_reason = "rising", "관심 지표 또는 플랫폼 순위가 뚜렷하게 상승"
        elif len(sources) >= 2 and persistence >= 0.35:
            lifecycle, lifecycle_reason = "mainstream", "X와 Google에서 반복 관측되어 대중 확산 확인"
        else:
            lifecycle, lifecycle_reason = "sustained", "여러 시간 반복 관측되어 지속성 확인"
        score = 0.60 * normalized_rrf + 0.20 * ((momentum + 1) / 2) + 0.15 * persistence + 0.05 * cross
        phenomenon_summary = observation_summary(representative_term, sources)
        keyword_items = _related_term_evidence(observations, representative_term)
        detected_category = event_resolution["category"] or _category(event_key)
        if detected_category == "unclassified" and keyword_items:
            # Google related queries are observed source evidence, not an LLM
            # guess. They may disambiguate a person or short noun without
            # replacing the representative source title.
            detected_category = _category(" ".join(
                [event_key, *(item["text"] for item in keyword_items)]
            ))
        context_keys = {
            "".join(str(value).casefold().split())
            for value in [representative_term, event_key, *{item["topic"] for item in observations}]
        }
        news_context_records = [
            record for key, record in news_context_by_term.items()
            if "".join(str(key).casefold().split()) in context_keys
            and record.get("core_source_gate") == "satisfied_by_x_or_google"
        ]
        news_claim_types = sorted({
            str(claim_type)
            for record in news_context_records
            for claim_type in record.get("claim_types", [])
            if claim_type
        })
        fit_assessment = assess_trend_fit(
            representative_term,
            category=detected_category,
            context_terms=[item["text"] for item in keyword_items],
            news_claim_types=news_claim_types,
        )
        lane = fit_assessment["selection"]
        reason = fit_assessment["reason"]
        context_status = event_resolution["context_status"]
        if (
            context_status == "ambiguous_person"
            and detected_category != "unclassified"
            and keyword_items
        ):
            # A person's raw name remains unchanged, but observed Google/X
            # context such as "축구 선수" can resolve the homonym for this
            # snapshot. No generated biography or guessed identity is used.
            context_status = "resolved_by_observed_context"
        trend_fit = {
            **fit_assessment,
            "lane": lane,
            "label": {
                "main": "메인 트렌드 적합",
                "issue": "이슈·주의",
                "review": "맥락 검토",
            }[lane],
            "affects_score": False,
        }
        selection_layer = {
            "main": "main_subset",
            "issue": "issue_context",
            "review": "review_queue",
        }[lane]
        score_calibration = 1.0
        if eligible_hour_count >= 96 and len(sources) >= 2 and observed_hours >= 6:
            data_confidence = {"level": "high", "label": "높음",
                               "reason": "96시간 이상 원장과 양 플랫폼 반복 관측",
                               "window_observed_hours": eligible_hour_count,
                               "history_maturity": round(history_maturity, 4),
                               "ranking_status": "mature"}
        elif eligible_hour_count >= 24 and observed_hours >= 2:
            data_confidence = {"level": "medium", "label": "보통",
                               "reason": "반복 관측됐지만 96시간 성숙 게이트 전의 잠정 순위",
                               "window_observed_hours": eligible_hour_count,
                               "history_maturity": round(history_maturity, 4),
                               "ranking_status": "provisional"}
        elif eligible_hour_count >= 6:
            data_confidence = {"level": "low", "label": "낮음",
                               "reason": "원장 축적이 24시간 미만인 잠정 순위",
                               "window_observed_hours": eligible_hour_count,
                               "history_maturity": round(history_maturity, 4),
                               "ranking_status": "provisional"}
        else:
            data_confidence = {"level": "very_low", "label": "초기 표본",
                               "reason": "원장 축적이 6시간 미만이라 현재 순위만 확인 가능",
                               "window_observed_hours": eligible_hour_count,
                               "history_maturity": round(history_maturity, 4),
                               "ranking_status": "provisional"}
        verification_record = verification_by_trend.get(event_key, {})
        providers = verification_record.get("providers", {})
        verification_layer = {
            **verification_record,
            "status": (
                "observed"
                if any(record.get("matched") for record in providers.values())
                else "unavailable"
                if providers
                else "not_run"
            ),
            "observed_platforms": sorted(
                provider for provider, record in providers.items() if record.get("matched")
            ),
            "affects_score": False,
        }
        sensitive_context = any(is_sensitive_context(item["topic"]) for item in observations)
        company_eligible = lane == "main" and not sensitive_context
        if company_eligible:
            company_candidates, ontology_diagnostics = _ontology_company_candidates(
                ontology_graph,
                representative=representative_term,
                related_terms=keyword_items,
                sources=sources,
                as_of=last_seen,
            )
            candidate_company_categories, company_candidates = expand_value_chain(
                event_key,
                detected_category,
                company_candidates,
            )
        else:
            company_candidates = []
            candidate_company_categories = []
            ontology_diagnostics = {
                "seed_path": ONTOLOGY_SEED_PATH.name,
                "enrichment_path": ONTOLOGY_ENRICHMENT_PATH.name,
                "minimum_gold_companies": MINIMUM_PUBLISHED_COMPANIES,
                "matched_terms": [],
                "padding_forbidden": True,
                "ranking_effect": "none",
            }
        ontology_complete_companies = [
            company for company in company_candidates if company.get("ontology_complete")
        ]
        gold_publishable = len(ontology_complete_companies) >= MINIMUM_PUBLISHED_COMPANIES
        published_companies = ontology_complete_companies if gold_publishable else []
        if published_companies:
            company_categories, published_companies = expand_value_chain(
                event_key,
                detected_category,
                published_companies,
            )
        else:
            company_categories = []
        publish_status = (
            "published"
            if gold_publishable
            else "excluded_by_context"
            if not company_eligible
            else "ontology_incomplete"
        )
        company_resolution = {
            "status": publish_status,
            "publish_status": publish_status,
            "candidate_count": len(company_candidates),
            "ontology_complete_count": len(ontology_complete_companies),
            "published_count": len(published_companies),
            "minimum_gold_companies": MINIMUM_PUBLISHED_COMPANIES,
            "score_independent_of_company_count": True,
            "direct_count": sum(company["strength"] == "direct" for company in company_candidates),
            "role_coverage": sorted({company["company_role"] for company in company_candidates}),
            "tier_counts": {tier: sum(company["relation_tier"] == tier for company in company_candidates)
                            for tier in ("core", "value_chain", "adjacent", "excluded")},
            "category_count": len(company_categories),
            "candidate_category_count": len(candidate_company_categories),
            "ontology_diagnostics": ontology_diagnostics,
            "reason": (
                "증거 온톨로지 경로가 완결된 고유 상장기업 5개 이상을 Gold로 공개"
                if gold_publishable
                else "사건·정책·논란 맥락은 기업 연결을 공개하지 않음"
                if not company_eligible
                else "완결된 증거 온톨로지 기업이 5개 미만이라 기업 Gold 공개를 보류"
            ),
        }
        candidates.append({
            "event_key": event_key,
            "topic": representative_term,
            "display_name": representative_term,
            "resolved_entity_name": event_resolution["canonical"],
            "representative_evidence": representative_evidence,
            "raw_terms": sorted({item["topic"] for item in observations}),
            "phenomenon_summary": phenomenon_summary,
            "context_status": context_status,
            "ground_truth_match": event_resolution["ground_truth_match"],
            "category": detected_category,
            "broad_category": _broad_category(detected_category),
            "lane": lane,
            "selection_reason": reason,
            "trend_fit": trend_fit,
            "selection_layer": selection_layer,
            "score_calibration": score_calibration,
            "company_eligible": company_eligible,
            "score": round(score*100, 2),
            "rrf": round(normalized_rrf, 6),
            "rrf_raw": round(rrf_raw, 8),
            "momentum": round(momentum, 4), "persistence": round(persistence, 4),
            "score_components": {
                "rrf_points": round(60 * normalized_rrf, 2),
                "momentum_points": round(20 * ((momentum + 1) / 2), 2),
                "persistence_points": round(15 * persistence, 2),
                "cross_source_points": round(5 * cross, 2),
                "calibration": score_calibration,
            },
            "source_count": len(sources),
            "current_source_count": len(current_by_source),
            "source_badge": "교차출처" if len(current_by_source) >= 2 else "단일출처",
            "latest_source_ranks": {
                source: item["source_rank"] for source, item in current_by_source.items()
            },
            "rank_change_by_source": rank_changes,
            "first_seen_at": first_seen, "last_seen_at": last_seen, "age_hours": age_hours,
            "lifecycle": lifecycle, "lifecycle_reason": lifecycle_reason,
            "data_confidence": data_confidence,
            "verification_layer": verification_layer,
            "news_context": {
                "status": "observed" if news_context_records else "not_linked",
                "claim_types": news_claim_types,
                "records": news_context_records,
                "affects_score": False,
                "ranking_source": False,
            },
            "provenance": sorted({item["provenance"] for item in observations}),
            "series": [{"at": item["observed_at"], "source": item["source"],
                        "rank": item["source_rank"], "value": item["value"],
                        "provenance": item["provenance"],
                        "source_payload_json": item.get("source_payload_json"),
                        "related_terms_json": item.get("related_terms_json")}
                       for item in observations],
            "keywords": keyword_items,
            "keyword_evidence": {
                "total": len(keyword_items),
                "observed_source_count": sum(
                    item["status"] in {"observed_ranked_term", "observed_related_query"}
                    for item in keyword_items
                ),
                "candidate_count": 0,
                "status": "observed" if keyword_items else "insufficient",
                "reason": (
                    "동일 사건으로 묶인 관측 원문 또는 Google 관련 검색어만 표시"
                    if keyword_items
                    else "관측된 관련 원문이 없어 키워드를 비워 둠"
                ),
            },
            "companies": published_companies,
            "company_candidates": company_candidates,
            "company_categories": company_categories,
            "candidate_company_categories": candidate_company_categories,
            "company_resolution": company_resolution,
        })
    candidates.sort(key=lambda item: (-item["score"], item["topic"]))
    for rank, item in enumerate(candidates, 1):
        item["rank"] = rank
        item["classification"] = "이슈·주의" if item["lane"] == "issue" else "일반 트렌드" if item["company_eligible"] else "맥락 확인"
    by_persistence = sorted(candidates, key=lambda item: (-item["age_hours"], -item["persistence"], -item["score"], item["topic"]))
    by_momentum = sorted(candidates, key=lambda item: (-item["momentum"], -item["score"], item["topic"]))
    for rank, item in enumerate(by_persistence, 1):
        item["persistence_rank"] = rank
    for rank, item in enumerate(by_momentum, 1):
        item["momentum_rank"] = rank
    lanes = {name: [] for name in ("main", "issue", "review")}
    for item in candidates:
        lanes[item["lane"]].append(item)
    for lane in lanes.values():
        lane.sort(key=lambda item: item["rank"])
    evaluation_rows = []
    for item in candidates:
        expected = GROUND_TRUTH.get(item["event_key"])
        if expected:
            evaluation_rows.append({
                "display_name": item["display_name"],
                "category": item["category"],
                "ground_truth_expected": {"display_name": expected[0], "category": expected[1]},
            })
    resolved_public_candidates = [
        item for item in candidates
        if item["lane"] == "main"
        and item["category"] != "unclassified"
        and item["context_status"] not in {"unresolved", "ambiguous_person"}
    ]
    # The unified list preserves every observed candidate. The home subset is
    # a non-scoring presentation filter: issue and unresolved review items keep
    # their global rank but are exposed in their own lanes.
    home_candidates = [item for item in candidates if item["lane"] == "main"]
    for item in candidates:
        item["home_context_status"] = (
            "resolved" if item in resolved_public_candidates else "review_required"
        )
    public_top10 = home_candidates[:10]
    ontology_enrichment_queue = [
        {
            "rank": item["rank"],
            "event_key": item["event_key"],
            "representative_term": item["display_name"],
            "observed_terms": [item["display_name"], *[keyword["text"] for keyword in item["keywords"]]],
            "evidence_backed_company_count": item["company_resolution"]["candidate_count"],
            "minimum_required": MINIMUM_PUBLISHED_COMPANIES,
            "missing_company_paths": max(
                0,
                MINIMUM_PUBLISHED_COMPANIES - item["company_resolution"]["candidate_count"],
            ),
            "status": "evidence_research_required",
            "lookup_status": (
                "reviewed_match_below_gold_gate"
                if item["company_resolution"]["candidate_count"]
                else "no_reviewed_ontology_match"
            ),
            "research_stages": [
                "representative_or_related_term_lookup",
                "entity_product_or_industry_bridge",
                "company_relationship_evidence",
                "listed_stock_identity_evidence",
                "team_review",
            ],
            "allowed_evidence": ["company_official", "regulatory_filing", "reputable_news", "reviewed_industry_structure"],
            "padding_forbidden": True,
            "affects_score": False,
        }
        for item in home_candidates
        if item["company_resolution"]["publish_status"] == "ontology_incomplete"
    ]

    snapshot_quality = {}
    for source in ("x", "google_trends"):
        by_time = defaultdict(list)
        for row in rows:
            if row["source"] == source and row["provenance"] == "observed":
                by_time[row["observed_at"]].append((row["source_rank"], row["topic"]))
        fingerprints = [tuple(sorted(values)) for _, values in sorted(by_time.items())]
        top_sets = [
            {topic for rank, topic in values if rank <= 10}
            for _, values in sorted(by_time.items())
        ]
        unique_count = len(set(fingerprints))
        consecutive_unchanged = sum(
            left == right for left, right in zip(fingerprints, fingerprints[1:])
        )
        top10_overlaps = [
            len(left & right) / max(len(left | right), 1)
            for left, right in zip(top_sets, top_sets[1:])
        ]
        average_top10_overlap = (
            sum(top10_overlaps) / len(top10_overlaps) if top10_overlaps else 0.0
        )
        snapshot_quality[source] = {
            "snapshot_count": len(fingerprints),
            "unique_snapshot_count": unique_count,
            "consecutive_unchanged_count": consecutive_unchanged,
            "unchanged_rate": round(consecutive_unchanged / max(len(fingerprints) - 1, 1), 4),
            "average_top10_overlap": round(average_top10_overlap, 4),
            "status": (
                "insufficient_history" if len(fingerprints) < 3
                else "stale_or_static_feed" if consecutive_unchanged == len(fingerprints) - 1
                else "low_churn_needs_source_review" if average_top10_overlap >= 0.9
                else "changing"
            ),
        }
    expected_rank_sources = {"x", "google_trends"}
    missing_current_sources = sorted(expected_rank_sources - current_available_sources)
    if not current_available_sources:
        ranking_availability = {
            "status": "unavailable",
            "label": "현재 순위 없음",
            "is_combined_rank": False,
            "current_sources": [],
            "missing_sources": sorted(expected_rank_sources),
            "reason": "현재 시간에 품질 게이트를 통과한 X·Google 원장이 없음",
        }
    elif missing_current_sources:
        ranking_availability = {
            "status": "provisional_single_source",
            "label": "단일출처 잠정 순위",
            "is_combined_rank": False,
            "current_sources": sorted(current_available_sources),
            "missing_sources": missing_current_sources,
            "reason": "X와 Google 중 한 출처만 현재 시간에 관측되어 통합 순위로 확정할 수 없음",
        }
    elif eligible_hour_count < 96:
        ranking_availability = {
            "status": "provisional_history",
            "label": "양출처 잠정 순위",
            "is_combined_rank": True,
            "current_sources": sorted(current_available_sources),
            "missing_sources": [],
            "reason": "X·Google은 모두 관측됐지만 96시간 성숙 게이트 전",
        }
    else:
        ranking_availability = {
            "status": "mature_combined",
            "label": "양출처 성숙 순위",
            "is_combined_rank": True,
            "current_sources": sorted(current_available_sources),
            "missing_sources": [],
            "reason": "X·Google 현재 관측과 96시간 원장 성숙 게이트 충족",
        }

    for item in candidates:
        item["ranking_availability_status"] = ranking_availability["status"]

    return {
        "schema_version": "trzip-intelligence-v3",
        "mode": "live",
        "is_live": True,
        "window": {"from": start.isoformat(), "to": end.isoformat(), "hours": hours},
        "sources": ["x", "google_trends"],
        "ranking_availability": ranking_availability,
        "score_formula": (
            "60% current-hour normalized RRF + 20% previous-to-current normalized rank-position "
            "momentum + 15% eligible-hour persistence x 96-hour maturity + 5% current cross-source"
        ),
        "score_policy": {
            "source_values_used": False,
            "rrf_k": 60,
            "rrf_normalization": "sum(1/(60+rank)) / (available_current_sources/61)",
            "momentum": "mean(current normalized rank position - previous source snapshot position)",
            "missing_event_position": 0,
            "persistence": "event observed hours / eligible ledger hours, multiplied by min(eligible hours/96, 1)",
            "company_count_affects_rank": False,
            "future_rows_used": False,
            "active_candidate_gate": "present in at least one current eligible source snapshot",
            "maturity_gate_hours": 96,
        },
        "context_evidence_policy": {
            "news_is_ranking_source": False,
            "news_layers": ["discovery", "context", "company_evidence"],
            "promotion_gate": "뉴스 발견어는 X 또는 Google 원장 관측 전에는 unified ranking에 승격하지 않음",
            "context_affects_score": False,
        },
        "verification_policy": {
            "planned_platforms": ["naver", "youtube", "instagram"],
            "storage": "provider_verification_ledger_sqlite",
            "unavailable_platform_penalty": 0,
            "verification_affects_score": False,
        },
        "hourly_rankings": hourly_ranking,
        "daily_aggregates": daily_aggregates,
        "normalization_evaluation": evaluate_resolution(evaluation_rows),
        "unified_ranking": candidates,
        "public_top10": public_top10,
        "ontology_enrichment_queue": ontology_enrichment_queue,
        "quality_summary": {
            "total_ranked_candidates": len(candidates),
            "main_candidates": len(lanes["main"]),
            "public_eligible_candidates": len(home_candidates),
            "resolved_public_candidates": len(resolved_public_candidates),
            "review_required_in_public_top10": sum(
                item["home_context_status"] == "review_required" for item in public_top10
            ),
            "public_top10_count": len(public_top10),
            "excluded_from_public_due_to_issue_lane": len(candidates) - len(home_candidates),
            "top10_with_five_keywords": sum(
                len(item["keywords"]) == 5
                for item in public_top10
            ),
            "top10_with_company_mapping": sum(bool(item["companies"]) for item in public_top10),
            "top10_without_forced_company": sum(not item["companies"] for item in public_top10),
            "top10_low_confidence": sum(
                item["data_confidence"]["level"] in {"low", "very_low"}
                for item in public_top10
            ),
            "eligible_ledger_hours": eligible_hour_count,
            "current_available_sources": sorted(current_available_sources),
            "missing_current_sources": missing_current_sources,
            "ranking_availability_status": ranking_availability["status"],
            "ranking_maturity_status": "mature" if eligible_hour_count >= 96 else "provisional",
            "quarantined_source_hour_count": len(quarantined_source_hours),
            "quarantined_source_hours": quarantined_source_hours,
            "source_snapshot_quality": snapshot_quality,
        },
        "lanes": lanes,
    }
