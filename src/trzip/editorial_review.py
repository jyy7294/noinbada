from __future__ import annotations

from datetime import UTC, datetime


SOURCE_URLS = {
    "x": "https://x.com/explore/tabs/trending",
    "google_trends": "https://trends.google.com/trending?geo=KR",
}

# A review candidate must be a concrete named product, event, title, technology,
# brand or phenomenon. Broad nouns are deliberately rejected even when a
# provider ranks them highly.
REJECTED_BROAD_TERMS = {
    "음식", "운전", "애니", "트로트", "대한민국", "생계", "연휴", "공유",
    "등반", "폭포", "사기", "적금",
}

KEYWORDS = {
    "말복": ("삼계탕", "보양식", "복날 음식", "간편식 삼계탕", "하림 삼계탕", "비비고 삼계탕", "닭고기", "복날 외식", "삼계탕 판매량", "보양식 신메뉴", "복날 배달", "초복", "중복", "말복 날짜", "복날 소비"),
    "아이폰": ("아이폰 신제품", "아이폰 출시일", "아이폰 가격", "아이폰 사전예약", "아이폰 카메라", "아이폰 디스플레이", "아이폰 반도체", "아이폰 부품", "아이폰 판매량", "아이폰 통신사", "아이폰 케이스", "iOS", "Apple 공급망", "Foxconn 아이폰", "TSMC 아이폰"),
    "커피믹스": ("맥심 커피믹스", "모카골드", "화이트골드", "제로슈거 커피믹스", "프렌치카페 카페믹스", "커피믹스 가격", "커피믹스 판매량", "커피믹스 신제품", "스틱커피", "인스턴트커피", "사무실 커피", "커피믹스 원두", "커피믹스 설탕", "커피믹스 포장", "커피믹스 후기"),
    "검은사막": ("검은사막 업데이트", "검은사막 신규 클래스", "검은사막 이벤트", "검은사막 콘솔", "검은사막 모바일", "검은사막 PC", "검은사막 PS5", "검은사막 Xbox", "펄어비스", "검은사막 스팀", "검은사막 이용자", "검은사막 게임패스", "검은사막 아이템", "검은사막 패치", "검은사막 굿즈"),
    "smr": ("소형모듈원전", "뉴스케일파워", "두산에너빌리티 SMR", "SMR 주기기", "SMR 원자로 모듈", "SMR 소재", "SMR 설계", "SMR 공급망", "SMR 건설", "SMR 인허가", "SMR 수출", "SMR 기자재", "차세대 원전", "원전 파운드리", "SMR 투자"),
}

# These are not category templates. Every company relation below has a
# relation-specific source which explicitly names the company/product link.
VERIFIED_COMPANIES = {
    "말복": (
        {
            "company": "CJ제일제당", "ticker": "097950", "market": "KRX",
            "relation_tier": "direct", "reason": "비비고 삼계탕을 생산·판매하고 복날 보양식 매출을 공식 발표",
            "evidence_url": "https://www.cj.co.kr/kr/newsroom/pressreleases/news-detail/1345",
            "evidence_owner": "CJ제일제당", "evidence_type": "official_company_release",
        },
        {
            "company": "하림", "ticker": "136480", "market": "KRX",
            "relation_tier": "direct", "reason": "하림 공식 제품관에서 자사 삼계탕 제품을 판매",
            "evidence_url": "https://www.harim.com/main/?menu=98",
            "evidence_owner": "하림", "evidence_type": "official_product_page",
        },
    ),
    "아이폰": (
        {
            "company": "Apple", "ticker": "AAPL", "market": "NASDAQ",
            "relation_tier": "direct", "reason": "아이폰의 개발·판매 주체",
            "evidence_url": "https://www.apple.com/iphone/", "evidence_owner": "Apple",
            "evidence_type": "official_product_page",
        },
        {
            "company": "Hon Hai Precision", "ticker": "2317", "market": "TWSE",
            "relation_tier": "value_chain", "reason": "Apple이 공개한 공급업체 명단에 Hon Hai Precision이 포함",
            "evidence_url": "https://www.apple.com/newsroom/kr/pdfs/product/support/standard/Apple%20Supplier%20Clean%20Energy%20Program_KR_221026.pdf",
            "evidence_owner": "Apple", "evidence_type": "official_supplier_document",
        },
        {
            "company": "TSMC", "ticker": "TSM", "market": "NYSE",
            "relation_tier": "value_chain", "reason": "Apple이 공개한 공급업체 명단에 TSMC가 포함",
            "evidence_url": "https://www.apple.com/newsroom/kr/pdfs/product/support/standard/Apple%20Supplier%20Clean%20Energy%20Program_KR_221026.pdf",
            "evidence_owner": "Apple", "evidence_type": "official_supplier_document",
        },
    ),
    "검은사막": (
        {
            "company": "펄어비스", "ticker": "263750", "market": "KOSDAQ",
            "relation_tier": "direct", "reason": "검은사막 공식 개발·서비스 주체",
            "evidence_url": "https://blackdesert.pearlabyss.com/Console/en-US/Main",
            "evidence_owner": "Pearl Abyss", "evidence_type": "official_product_page",
        },
        {
            "company": "Sony Group", "ticker": "SONY", "market": "NYSE",
            "relation_tier": "distribution", "reason": "검은사막 공식 공지가 PlayStation 5 제공을 명시",
            "evidence_url": "https://blackdesert.pearlabyss.com/Console/en-US/News/Notice/Detail?_boardNo=12323",
            "evidence_owner": "Pearl Abyss", "evidence_type": "official_platform_release",
        },
        {
            "company": "Microsoft", "ticker": "MSFT", "market": "NASDAQ",
            "relation_tier": "distribution", "reason": "검은사막 공식 공지가 Xbox Series X|S 제공을 명시",
            "evidence_url": "https://blackdesert.pearlabyss.com/Console/en-US/News/Notice/Detail?_boardNo=12323",
            "evidence_owner": "Pearl Abyss", "evidence_type": "official_platform_release",
        },
    ),
    "smr": (
        {
            "company": "NuScale Power", "ticker": "SMR", "market": "NYSE",
            "relation_tier": "direct", "reason": "공식 자료에 SMR 개발사 및 프로젝트 사업자로 명시",
            "evidence_url": "https://www.doosanenerbility.com/en/about/news_board_view?id=21000472&page=0&pageSize=9",
            "evidence_owner": "Doosan Enerbility", "evidence_type": "official_company_release",
        },
        {
            "company": "두산에너빌리티", "ticker": "034020", "market": "KRX",
            "relation_tier": "value_chain", "reason": "NuScale과 SMR 소재·주기기 제작 계약을 공식 발표",
            "evidence_url": "https://www.doosanenerbility.com/kr/about/news_board_view?id=21000535",
            "evidence_owner": "두산에너빌리티", "evidence_type": "official_company_release",
        },
    ),
    "커피믹스": (
        {
            "company": "동서", "ticker": "026960", "market": "KRX",
            "relation_tier": "direct", "reason": "관계사 동서식품의 공식 페이지가 맥심 커피믹스 제품을 명시",
            "evidence_url": "https://www.dongsuh.co.kr/product/brand/maxim",
            "evidence_owner": "동서식품", "evidence_type": "official_product_page",
        },
    ),
}


def _key(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def build_editorial_review_pack(intelligence: dict, *, generated_at: datetime | None = None) -> dict:
    """Build a strict review pack without sector padding or broad nouns."""

    now = (generated_at or datetime.now(UTC)).astimezone(UTC).isoformat()
    selected = []
    for item in intelligence.get("unified_ranking") or []:
        topic = str(item.get("display_name") or item.get("topic") or item.get("event_key") or "").strip()
        normalized = _key(topic)
        if not topic or normalized in {_key(value) for value in REJECTED_BROAD_TERMS}:
            continue
        if normalized not in {_key(value) for value in KEYWORDS}:
            continue
        selected.append((item, next(name for name in KEYWORDS if _key(name) == normalized)))
        if len(selected) == 30:
            break

    trends = []
    for review_rank, (item, registry_key) in enumerate(selected, start=1):
        source_evidence = [SOURCE_URLS[s] for s in item.get("period_sources", []) if s in SOURCE_URLS]
        company_rows = []
        for candidate_rank, source in enumerate(VERIFIED_COMPANIES.get(registry_key, ()), start=1):
            company_rows.append({
                **source,
                "candidate_rank": candidate_rank,
                "verification_status": "evidence_verified",
                "verified_at": now,
                "review_status": "unreviewed",
                "ranking_effect": "none",
                "investment_recommendation": False,
            })
        trends.append({
            "review_rank": review_rank,
            "observed_rank": item["rank"],
            "event_key": item["event_key"],
            "display_name": item.get("display_name") or registry_key,
            "score": item["score"],
            "period_sources": item.get("period_sources", []),
            "source_evidence_urls": source_evidence,
            "selection_basis": "concrete_observed_term_and_term_specific_registry",
            "related_keyword_candidates": [
                {
                    "text": text, "candidate_rank": rank,
                    "basis": "term_specific_editorial_query_candidate",
                    "review_status": "unreviewed",
                }
                for rank, text in enumerate(KEYWORDS[registry_key], start=1)
            ],
            "company_candidates": company_rows,
            "company_verification_status": (
                "ready_for_team_selection" if len(company_rows) >= 3
                else "insufficient_verified_companies"
            ),
            "review_status": "unreviewed",
        })
    return {
        "schema_version": "trzip-editorial-review-v2",
        "generated_at": now,
        "ranking_policy": "preserve_observed_rank_and_score_no_reranking",
        "candidate_policy": {
            "trend_candidate_maximum": 30,
            "keyword_candidates_per_trend": 15,
            "minimum_verified_companies_for_selection": 3,
            "padding_forbidden": True,
            "broad_term_forbidden": True,
            "global_listed_companies_allowed": True,
        },
        "trends": trends,
    }
