from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from .company_adapters import company_profile, integration_status
from .hourly_store import collect_current, coverage, floor_hour
from .intelligence import KEYWORD_REGISTRY, build_intelligence
from .related_keywords import x_related_keywords


def run_e2e(*, collect: bool = True, hours: int = 24,
            verify_companies: bool = True, live_keywords: bool = True) -> dict:
    collection = collect_current(use_trends_mcp=False) if collect else None
    at = datetime.fromisoformat(collection["observed_at"]) if collection else floor_hour(datetime.now(UTC))
    intelligence = build_intelligence(at, hours=hours)
    topics: list[dict] = []
    company_rows: list[dict] = []

    for item in intelligence["unified_ranking"]:
        keyword_result = None
        if live_keywords:
            query = item["raw_terms"][0] if item["raw_terms"] else item["topic"]
            keyword_result = x_related_keywords(
                query, candidates=KEYWORD_REGISTRY.get(item["topic"], [])
            )
        observed_keywords = (
            keyword_result.get("keywords", [])
            if keyword_result and keyword_result.get("status") == "observed" else []
        )
        keyword_rows = list(observed_keywords[:5])
        keyword_seen = {row.get("text", "").casefold() for row in keyword_rows}
        for stored in item["keywords"]:
            if stored.get("text", "").casefold() in keyword_seen:
                continue
            keyword_rows.append(stored)
            keyword_seen.add(stored.get("text", "").casefold())
            if len(keyword_rows) >= 5:
                break

        topics.append({
            "rank": item["rank"], "topic": item["topic"], "display_name": item["display_name"],
            "phenomenon_summary": item["phenomenon_summary"], "raw_terms": item["raw_terms"],
            "category": item["category"],
            "classification": item["classification"], "company_eligible": item["company_eligible"],
            "persistence_rank": item["persistence_rank"], "momentum_rank": item["momentum_rank"],
            "age_hours": item["age_hours"],
            "score": item["score"], "lifecycle": item["lifecycle"],
            "data_confidence": item["data_confidence"],
            "source_ranks": item["latest_source_ranks"], "persistence": item["persistence"],
            "selection_reason": item["selection_reason"], "keywords": keyword_rows,
            "keyword_source_status": keyword_result.get("status") if keyword_result else "stored_context",
            "company_count": len(item["companies"]),
            "company_categories": item["company_categories"],
            "minimum_category_met": item["company_resolution"]["minimum_category_met"],
        })

        for company in item["companies"]:
            profile = None
            if verify_companies and company.get("stock_code") and company["strength"] != "excluded":
                profile = company_profile(company["company"], company["stock_code"])
            company_rows.append({
                "trend_rank": item["rank"], "trend": item["topic"],
                "company": company["company"], "stock_code": company.get("stock_code"),
                "relation_category": company.get("relation_category"),
                "value_chain_stage": company.get("value_chain_stage"),
                "role": company["company_role"], "relation_tier": company["relation_tier_label"],
                "relation_strength": company["strength"],
                "verification_status": company["verification_status"],
                "opportunity_status": company["opportunity_status"],
                "reason": company["reason"], "evidence_url": company.get("evidence_url"),
                "dart_status": profile["official_identity"]["status"] if profile else "not_run",
                "market_status": profile["market_reference"]["status"] if profile else "not_run",
                "market_reaction": profile["market_reference"].get("market_reaction") if profile else None,
            })

    public_top10 = intelligence["public_top10"]
    eligible_ranked = [item for item in intelligence["unified_ranking"] if item["company_eligible"]]
    category_quality = {
        "required_categories_per_trend": 3,
        "eligible_trends_meeting_requirement": sum(
            item["company_resolution"]["minimum_category_met"] for item in eligible_ranked
        ),
        "minimum_categories_observed": min(
            (len(item["company_categories"]) for item in eligible_ranked), default=0
        ),
        "minimum_companies_in_any_category": min(
            (category["candidate_count"] for item in eligible_ranked
             for category in item["company_categories"]), default=0
        ),
        "total_company_rows": len(company_rows),
        "confirmed_relationship_rows": sum(
            row["opportunity_status"] == "confirmed_relationship" for row in company_rows
        ),
        "industry_candidate_rows": sum(
            row["opportunity_status"] == "observable_opportunity" for row in company_rows
        ),
    }

    return {
        "run": {
            "executed_at": datetime.now(UTC).isoformat(), "ranking_at": at.isoformat(),
            "mode": intelligence["mode"], "hours": hours,
            "sources": intelligence["sources"], "trends_mcp_used": False,
        },
        "collection": collection,
        "coverage": coverage(),
        "integrations": integration_status(),
        "ranking_policy": {
            "formula": intelligence["score_formula"],
            "ranking": "all observed topics in one unlimited list",
            "classification_tags": ["일반 트렌드", "맥락 확인", "이슈·주의"],
            "company_relation_is_not_rank_evidence": True,
        },
        "quality_summary": {**intelligence["quality_summary"], **category_quality},
        "ranking": topics,
        "top10": topics[:10],
        "companies": company_rows,
        "other_lanes": {
            lane: [{
                "rank": item["rank"], "topic": item["topic"],
                "category": item["category"], "score": item["score"],
                "selection_reason": item["selection_reason"],
            } for item in intelligence["lanes"][lane]]
            for lane in ("issue", "review")
        },
    }


def to_markdown(result: dict) -> str:
    run = result["run"]
    quality = result.get("quality_summary", {})
    collection = result.get("collection") or {}
    lines = [
        "# TRZIP 통합 E2E 결과", "",
        "## 제품 진입 논리", "",
        "주식 투자 자체가 대중적인 참여 문화가 된 상황에서, 무엇부터 봐야 할지 모르는 사용자가 자신이 이미 이해하는 음식·콘텐츠·패션·게임·생활 트렌드로 기업과 산업을 탐색하도록 돕습니다.",
        "종목명 자체가 X·Google에서 관찰되면 숨기지 않지만, 단순 급등락·풍문·인물 논란은 이슈로 분리하고 사업 원인이 확인된 경우에만 기업 탐색으로 연결합니다.", "",
        f"- 순위 기준시각: `{run['ranking_at']}`",
        f"- 모드: `{run['mode']}` / 관찰창: `{run['hours']}시간`",
        "- 데이터 소스: `X 한국`, `Google Trends geo=KR`",
        "- Trends MCP 자동사용: `아니요`", "",
        "## 이번 실행 수집 감사", "",
        f"- 현재 회차 실측 수집: `{collection.get('observed', 0)}건`",
        f"- 현재 회차 생성 데이터: `{collection.get('generated', 0)}건`",
        f"- 누적 DB 행: `{result.get('coverage', {}).get('rows', 0):,}건`",
        f"- 누적 실측 행: `{result.get('coverage', {}).get('observed_rows', 0):,}건`",
        f"- 재구성 데모 행: `{result.get('coverage', {}).get('generated_rows', 0):,}건`",
        "- 현재 순위는 `live` 모드의 최근 24시간 실측 관찰창으로 계산", "",
        "실측 이력이 짧으면 순위는 계산할 수 있어도 지속성 판단은 약합니다. 한 플랫폼·한 시간대만 관찰된 항목은 `초기 관찰`, 교차출처 또는 2시간 이상 반복은 `보통`, 양 플랫폼·6시간 이상 반복은 `높음`으로 표시합니다.", "",
        "## 품질 조건", "",
        f"- 기업 연결 가능 트렌드 중 사업 카테고리 3개 조건 충족: `{quality.get('eligible_trends_meeting_requirement', '-')}`건",
        f"- 트렌드별 최소 사업 카테고리 수: `{quality.get('minimum_categories_observed', '-')}`",
        f"- 카테고리별 최소 기업 수: `{quality.get('minimum_companies_in_any_category', '-')}`",
        f"- 전체 기업 연결 행: `{quality.get('total_company_rows', len(result.get('companies', [])))}`",
        f"- 확인된 관계 행: `{quality.get('confirmed_relationship_rows', '-')}`",
        f"- 산업 구조 후보 행: `{quality.get('industry_candidate_rows', '-')}`", "",
        "## 트렌드 통합 전체 순위", "",
        "| 순위 | 트렌드 | 왜 뜨는가 | 원천 표현 | 분류 | 점수 | 상태 | 지속기간순 | 급상승순 | X | Google | 지속시간 | 관련 키워드 | 기업 수 |",
        "|---:|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---|---:|",
    ]
    ranking = result.get("ranking", result.get("top10", []))
    for row in ranking:
        keywords = ", ".join(keyword.get("text", "") for keyword in row["keywords"]) or "검증 키워드 없음"
        ranks = row["source_ranks"]
        lines.append(
            f"| {row['rank']} | {row.get('display_name', row['topic'])} | {row.get('phenomenon_summary', '-')} | {', '.join(row.get('raw_terms', [])) or row['topic']} | {row.get('classification', '일반 트렌드')} | {row['score']:.2f} | {row['lifecycle']} | "
            f"{row.get('persistence_rank', '-')} | {row.get('momentum_rank', '-')} | {ranks.get('x', '-')} | {ranks.get('google_trends', '-')} | "
            f"{row.get('age_hours', '-')}시간 | {keywords} | {row['company_count']} |"
        )

    lines += ["", "## 관련기업·가치사슬 전체 결과", "",
              "| 트렌드 | 사업 카테고리 | 기업 | 코드 | 역할 | 연결 단계 | 근거 상태 | 기회 상태 | DART | pykrx | 연결 이유 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    if not result["companies"]:
        lines.append("| - | - | 검증 가능한 기업 없음 | - | - | - | - | - | - | - | 억지 연결 보류 |")
    for row in result["companies"]:
        lines.append(
            f"| {row['trend']} | {row['relation_category']} | {row['company']} | {row['stock_code'] or '비상장/해외'} | {row['role']} | "
            f"{row['relation_tier']} | {row.get('verification_status', '-')} | {row['opportunity_status']} | "
            f"{row['dart_status']} | {row['market_status']} | {row['reason']} |"
        )
    lines += ["", "## 트렌드별 상세", ""]
    company_by_trend: dict[str, list[dict]] = {}
    for company in result["companies"]:
        company_by_trend.setdefault(company["trend"], []).append(company)
    for row in ranking:
        lines += [f"### {row['rank']}위. {row['topic']}", "",
                  f"- 선정 근거: {row.get('selection_reason', '통합 트렌드 점수 기준')}",
                  f"- 생애주기: `{row['lifecycle']}` / 점수: `{row['score']:.2f}` / 지속성: `{row['persistence'] * 100:.0f}%`",
                  f"- 데이터 신뢰도: `{row.get('data_confidence', {}).get('label', '-')}` — {row.get('data_confidence', {}).get('reason', '')}",
                  f"- 관련 키워드: {', '.join(item.get('text', '') for item in row['keywords'])}",
                  "- 사업 카테고리:"]
        for category in row.get("company_categories", []):
            lines.append(f"  - {category['name']} ({category['value_chain_stage']}): {', '.join(category['companies'])}")
        lines += ["", "| 사업 카테고리 | 기업 | 역할 | 근거 상태 | 기회 상태 |", "|---|---|---|---|---|"]
        for company in company_by_trend.get(row["topic"], []):
            lines.append(
                f"| {company['relation_category']} | {company['company']} | {company['role']} | "
                f"{company.get('verification_status', '-')} | {company['opportunity_status']} |"
            )
        lines.append("")

    lines += ["## 메인에서 분리한 항목", "",
              "정치·사건·단순 인물 이슈는 삭제하지 않고 이슈 레인으로, 문맥이 불명확한 단어는 검토 레인으로 보존합니다.", ""]
    for lane, label in (("issue", "실시간 이슈"), ("review", "검토 후보")):
        lines += [f"### {label}", "", "| 순위 | 항목 | 점수 | 분리 이유 |", "|---:|---|---:|---|"]
        rows = result.get("other_lanes", {}).get(lane, [])
        if not rows:
            lines.append("| - | 없음 | - | - |")
        for item in rows:
            lines.append(f"| {item['rank']} | {item['topic']} | {item['score']:.2f} | {item['selection_reason']} |")
        lines.append("")
    lines += ["", "## 해석 제한", "",
              "관련 기업은 사업 관계와 소비 접점을 보여주는 분석 결과이며 매수 추천이나 주가 상승 예측이 아닙니다.",
              "`확인된 관계`와 `산업 구조 후보`를 구분합니다. 산업 구조 후보는 업종·밸류체인 탐색용이며 실제 계약이나 수혜를 뜻하지 않습니다.",
              "pykrx 값은 일별 사후 참고자료이고 기업 관계 판정이나 트렌드 순위에는 사용하지 않습니다.", ""]
    lines += ["## 사용자 검증 설문", "",
              "1. 주변 사람의 권유나 수익 인증을 보고 주식을 시작하거나 관심을 가진 적이 있습니까?",
              "2. 현재 투자 상태는 계속 투자, 가끔 투자, 중단, 미시작 중 어디에 해당합니까?",
              "3. 중단·미시작 이유는 손실, 물림, 종목 선택 어려움, 정보 난이도, 자금 부족 중 무엇입니까?",
              "4. 알고 있던 유행이 기업 매출이나 주가에 연결된 사례를 경험하거나 본 적이 있습니까?",
              "5. 기업 판단에 필요한 기준은 지속기간, 직접 관계, 가치사슬, 과거 시장반응, 거래량, 재무 안정성, 위험 중 무엇입니까?",
              "6. 관계 근거·지속기간·과거 시장반응이 함께 제공되면 기업 상세를 확인할 의향이 있습니까?", "",
              "설문은 수익을 보장하는 표현을 쓰지 않고 `트렌드 확인 → 관계 근거 확인 → 기업 상세 확인` 행동을 검증합니다.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run TRZIP collection-to-company E2E")
    parser.add_argument("--no-collect", action="store_true")
    parser.add_argument("--no-verify-companies", action="store_true")
    parser.add_argument("--no-live-keywords", action="store_true")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    result = run_e2e(
        collect=not args.no_collect,
        hours=max(1, min(args.hours, 2484)),
        verify_companies=not args.no_verify_companies,
        live_keywords=not args.no_live_keywords,
    )
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(to_markdown(result), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
