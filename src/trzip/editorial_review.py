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
    "검은사막": ("검은사막 업데이트", "검은사막 신규 클래스", "검은사막 이벤트", "검은사막 콘솔", "검은사막 모바일", "검은사막 PC", "검은사막 PS5", "검은사막 Xbox", "펄어비스", "검은사막 스팀", "검은사막 이용자", "검은사막 게임패스", "검은사막 아이템", "검은사막 패치", "검은사막 굿즈"),
    "smr": ("소형모듈원전", "뉴스케일파워", "두산에너빌리티 SMR", "SMR 주기기", "SMR 원자로 모듈", "SMR 소재", "SMR 설계", "SMR 공급망", "SMR 건설", "SMR 인허가", "SMR 수출", "SMR 기자재", "차세대 원전", "원전 파운드리", "SMR 투자"),
    "불꽃축제": ("불꽃축제 일정", "불꽃축제 장소", "불꽃축제 명당", "불꽃축제 교통", "불꽃축제 티켓", "불꽃축제 숙박", "불꽃축제 관광", "불꽃축제 외식", "불꽃축제 편의점", "불꽃축제 사진", "불꽃축제 영상", "불꽃축제 SNS", "불꽃축제 굿즈", "불꽃축제 협찬", "불꽃축제 주최사"),
    "데이즈드": ("데이즈드 코리아", "데이즈드 화보", "데이즈드 커버", "데이즈드 패션", "데이즈드 뷰티", "데이즈드 모델", "데이즈드 인터뷰", "패션 매거진", "셀럽 화보", "패션 브랜드", "뷰티 브랜드", "메이크업", "향수", "광고 캠페인", "브랜드 협업"),
    "지스타": ("지스타 일정", "지스타 참가사", "지스타 신작", "지스타 부스", "지스타 티켓", "지스타 부산", "지스타 게임 시연", "지스타 e스포츠", "지스타 스트리머", "지스타 굿즈", "지스타 코스프레", "지스타 사전예약", "지스타 게임사", "지스타 유튜브", "지스타 SNS"),
    "티빙": ("티빙 신작", "티빙 오리지널", "티빙 드라마", "티빙 예능", "티빙 스포츠 중계", "티빙 구독료", "티빙 이용자", "티빙 광고요금제", "티빙 콘텐츠", "티빙 출연진", "티빙 시청률", "티빙 다시보기", "티빙 OTT 비교", "티빙 SNS", "티빙 후기"),
    "코난 극장판": ("코난 극장판 개봉", "코난 극장판 예고편", "코난 극장판 상영관", "코난 극장판 특전", "코난 극장판 굿즈", "코난 극장판 더빙", "코난 극장판 자막", "코난 극장판 관객수", "코난 극장판 박스오피스", "코난 캐릭터", "코난 팝업스토어", "코난 콜라보", "코난 OTT", "코난 후기", "코난 SNS"),
    "챱챱 물개": ("챱챱 물개 원본", "챱챱 물개 밈", "챱챱 물개 영상", "챱챱 물개 뜻", "챱챱 물개 유래", "챱챱 물개 챌린지", "챱챱 물개 패러디", "챱챱 물개 이모티콘", "챱챱 물개 인형", "챱챱 물개 굿즈", "챱챱 물개 스티커", "챱챱 물개 SNS", "챱챱 물개 커뮤니티", "챱챱 물개 콜라보", "챱챱 물개 팝업"),
    "휴머노이드 로봇": ("AI 휴머노이드", "산업용 휴머노이드", "가정용 휴머노이드", "휴머노이드 액추에이터", "휴머노이드 감속기", "휴머노이드 센서", "휴머노이드 반도체", "휴머노이드 제조", "휴머노이드 물류", "휴머노이드 자동차", "휴머노이드 시제품", "휴머노이드 상용화", "휴머노이드 공급망", "휴머노이드 기업", "휴머노이드 시장"),
    "삼전닉스": ("삼성전자", "SK하이닉스", "HBM", "메모리 반도체", "AI 반도체", "DRAM", "NAND", "반도체 실적", "반도체 수출", "반도체 공급망", "반도체 투자", "반도체 주가", "HBM 경쟁", "메모리 가격", "AI 데이터센터"),
}

# These are not category templates. Every company relation below has a
# relation-specific source which explicitly names the company/product link.
VERIFIED_COMPANIES = {
    "말복": (
        {
            "company": "CJ제일제당", "ticker": "097950", "market": "KRX",
            "company_description": "가정간편식과 비비고 브랜드를 운영하는 식품기업",
            "relation_tier": "direct", "reason": "비비고 삼계탕을 생산·판매하고 복날 보양식 매출을 공식 발표",
            "evidence_url": "https://www.cj.co.kr/kr/newsroom/pressreleases/news-detail/1345",
            "evidence_owner": "CJ제일제당", "evidence_type": "official_company_release",
        },
        {
            "company": "하림", "ticker": "136480", "market": "KRX",
            "company_description": "닭고기 생산·가공과 삼계탕 제품을 운영하는 식품기업",
            "relation_tier": "direct", "reason": "하림 공식 제품관에서 자사 삼계탕 제품을 판매",
            "evidence_url": "https://www.harim.com/main/?menu=98",
            "evidence_owner": "하림", "evidence_type": "official_product_page",
        },
    ),
    "아이폰": (
        {
            "company": "Apple", "ticker": "AAPL", "market": "NASDAQ",
            "company_description": "아이폰을 개발·판매하는 글로벌 소비자 전자기업",
            "relation_tier": "direct", "reason": "아이폰의 개발·판매 주체",
            "evidence_url": "https://www.apple.com/iphone/", "evidence_owner": "Apple",
            "evidence_type": "official_product_page",
        },
        {
            "company": "Hon Hai Precision", "ticker": "2317", "market": "TWSE",
            "company_description": "전자제품 위탁생산과 조립을 수행하는 글로벌 제조기업",
            "relation_tier": "value_chain", "reason": "Apple이 공개한 공급업체 명단에 Hon Hai Precision이 포함",
            "evidence_url": "https://www.apple.com/newsroom/kr/pdfs/product/support/standard/Apple%20Supplier%20Clean%20Energy%20Program_KR_221026.pdf",
            "evidence_owner": "Apple", "evidence_type": "official_supplier_document",
        },
        {
            "company": "TSMC", "ticker": "TSM", "market": "NYSE",
            "company_description": "첨단 반도체를 위탁생산하는 글로벌 파운드리 기업",
            "relation_tier": "value_chain", "reason": "Apple이 공개한 공급업체 명단에 TSMC가 포함",
            "evidence_url": "https://www.apple.com/newsroom/kr/pdfs/product/support/standard/Apple%20Supplier%20Clean%20Energy%20Program_KR_221026.pdf",
            "evidence_owner": "Apple", "evidence_type": "official_supplier_document",
        },
    ),
    "검은사막": (
        {
            "company": "펄어비스", "ticker": "263750", "market": "KOSDAQ",
            "company_description": "검은사막 IP를 개발·서비스하는 게임기업",
            "relation_tier": "direct", "reason": "검은사막 공식 개발·서비스 주체",
            "evidence_url": "https://blackdesert.pearlabyss.com/Console/en-US/Main",
            "evidence_owner": "Pearl Abyss", "evidence_type": "official_product_page",
        },
        {
            "company": "Sony Group", "ticker": "SONY", "market": "NYSE",
            "company_description": "PlayStation 게임 플랫폼을 운영하는 글로벌 엔터테인먼트 기업",
            "relation_tier": "distribution", "reason": "검은사막 공식 공지가 PlayStation 5 제공을 명시",
            "evidence_url": "https://blackdesert.pearlabyss.com/Console/en-US/News/Notice/Detail?_boardNo=12323",
            "evidence_owner": "Pearl Abyss", "evidence_type": "official_platform_release",
        },
        {
            "company": "Microsoft", "ticker": "MSFT", "market": "NASDAQ",
            "company_description": "Xbox 게임 플랫폼과 클라우드 서비스를 운영하는 기술기업",
            "relation_tier": "distribution", "reason": "검은사막 공식 공지가 Xbox Series X|S 제공을 명시",
            "evidence_url": "https://blackdesert.pearlabyss.com/Console/en-US/News/Notice/Detail?_boardNo=12323",
            "evidence_owner": "Pearl Abyss", "evidence_type": "official_platform_release",
        },
    ),
    "smr": (
        {
            "company": "NuScale Power", "ticker": "SMR", "market": "NYSE",
            "company_description": "소형모듈원자로 설계와 상용화를 추진하는 미국 원전기업",
            "relation_tier": "direct", "reason": "공식 자료에 SMR 개발사 및 프로젝트 사업자로 명시",
            "evidence_url": "https://www.doosanenerbility.com/en/about/news_board_view?id=21000472&page=0&pageSize=9",
            "evidence_owner": "Doosan Enerbility", "evidence_type": "official_company_release",
        },
        {
            "company": "두산에너빌리티", "ticker": "034020", "market": "KRX",
            "company_description": "원전 주기기와 발전설비를 제작하는 에너지 기자재 기업",
            "relation_tier": "value_chain", "reason": "NuScale과 SMR 소재·주기기 제작 계약을 공식 발표",
            "evidence_url": "https://www.doosanenerbility.com/kr/about/news_board_view?id=21000535",
            "evidence_owner": "두산에너빌리티", "evidence_type": "official_company_release",
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
            "company_display_policy": {
                "show_category_groups": len(company_rows) >= 6,
                "default_layout": "company_description_list",
                "grouping_reason": (
                    "many_companies_need_navigation" if len(company_rows) >= 6
                    else "few_companies_are_clearer_without_category_tabs"
                ),
            },
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
