from __future__ import annotations

from datetime import UTC, datetime


SOURCE_URLS = {
    "x": "https://x.com/explore/tabs/trending",
    "google_trends": "https://trends.google.com/trending?geo=KR",
}

PRODUCT_CATEGORIES = ("food", "consumer", "lifestyle", "culture", "technology", "content")

KEYWORD_SUFFIXES = {
    "food": ("제품", "브랜드", "신메뉴", "레시피", "후기", "편의점", "카페", "디저트", "맛집", "가격", "판매량", "품절", "SNS", "챌린지", "콜라보"),
    "consumer": ("제품", "브랜드", "신제품", "출시일", "가격", "후기", "비교", "구매", "판매량", "품절", "디자인", "한정판", "콜라보", "SNS", "부품"),
    "lifestyle": ("일정", "장소", "후기", "예약", "티켓", "명소", "SNS", "체험", "굿즈", "교통", "지역", "행사", "브랜드", "콜라보", "관람"),
    "culture": ("밈", "영상", "챌린지", "SNS", "원본", "뜻", "유래", "반응", "굿즈", "캐릭터", "콘텐츠", "커뮤니티", "패러디", "브랜드", "콜라보"),
    "technology": ("기술", "제품", "부품", "플랫폼", "시장", "수요", "공급망", "제조", "서비스", "기업", "출시", "투자", "특허", "정책", "전망"),
    "content": ("방송", "영상", "출연진", "공연", "음원", "OTT", "시청률", "화제성", "팬덤", "굿즈", "브랜드", "광고", "콜라보", "SNS", "후기"),
}

COMPANIES = {
    "food": (
        ("CJ제일제당", "097950", "KRX", "식품 제조·브랜드 후보", "https://www.cj.co.kr"),
        ("농심", "004370", "KRX", "식품·간편식 제조 후보", "https://www.nongshim.com"),
        ("오뚜기", "007310", "KRX", "식품·소스·간편식 후보", "https://www.ottogi.co.kr"),
        ("동서", "026960", "KRX", "음료·식품 유통 후보", "https://www.dongsuh.com"),
        ("Nestle", "NESN", "SIX", "글로벌 식품·음료 브랜드 후보", "https://www.nestle.com"),
        ("Mondelez", "MDLZ", "NASDAQ", "글로벌 스낵·디저트 후보", "https://www.mondelezinternational.com"),
        ("Starbucks", "SBUX", "NASDAQ", "카페·음료 소비 접점 후보", "https://www.starbucks.com"),
        ("McDonald's", "MCD", "NYSE", "외식·한정 메뉴 접점 후보", "https://corporate.mcdonalds.com"),
        ("Coupang", "CPNG", "NYSE", "온라인 식품 유통·수요 접점 후보", "https://www.coupang.com"),
    ),
    "content": (
        ("CJ ENM", "035760", "KOSDAQ", "콘텐츠 제작·유통 후보", "https://www.cjenm.com"),
        ("하이브", "352820", "KRX", "음악·팬덤·공연 후보", "https://hybecorp.com"),
        ("SM엔터테인먼트", "041510", "KOSDAQ", "음악·아티스트 IP 후보", "https://www.smentertainment.com"),
        ("YG엔터테인먼트", "122870", "KOSDAQ", "음악·아티스트 IP 후보", "https://www.ygfamily.com"),
        ("Netflix", "NFLX", "NASDAQ", "글로벌 OTT 유통 후보", "https://about.netflix.com"),
        ("Walt Disney", "DIS", "NYSE", "글로벌 콘텐츠·IP 후보", "https://thewaltdisneycompany.com"),
        ("Sony Group", "SONY", "NYSE", "음악·영상·게임 IP 후보", "https://www.sony.com"),
        ("Tencent", "0700", "HKEX", "게임·영상·플랫폼 후보", "https://www.tencent.com"),
        ("Kakao", "035720", "KRX", "콘텐츠·커뮤니티 유통 후보", "https://www.kakaocorp.com"),
    ),
    "consumer": (
        ("Apple", "AAPL", "NASDAQ", "글로벌 소비자 제품·브랜드 후보", "https://www.apple.com"),
        ("삼성전자", "005930", "KRX", "전자제품·부품 후보", "https://www.samsung.com"),
        ("LG이노텍", "011070", "KRX", "전자 부품 가치사슬 후보", "https://www.lginnotek.com"),
        ("Sony Group", "SONY", "NYSE", "전자제품·콘텐츠 IP 후보", "https://www.sony.com"),
        ("LVMH", "MC", "EURONEXT", "글로벌 패션·뷰티 브랜드 후보", "https://www.lvmh.com"),
        ("L'Oreal", "OR", "EURONEXT", "글로벌 뷰티 브랜드 후보", "https://www.loreal.com"),
        ("Estee Lauder", "EL", "NYSE", "글로벌 뷰티 브랜드 후보", "https://www.elcompanies.com"),
        ("Nike", "NKE", "NYSE", "글로벌 패션·스포츠 브랜드 후보", "https://about.nike.com"),
        ("Adidas", "ADS", "XETRA", "글로벌 패션·스포츠 브랜드 후보", "https://www.adidas-group.com"),
    ),
    "lifestyle": (
        ("한화", "000880", "KRX", "축제·레저·서비스 생태계 후보", "https://www.hanwha.com"),
        ("Live Nation", "LYV", "NYSE", "공연·티켓·현장 경험 후보", "https://www.livenationentertainment.com"),
        ("Airbnb", "ABNB", "NASDAQ", "여행·지역 경험 후보", "https://www.airbnb.com"),
        ("Booking Holdings", "BKNG", "NASDAQ", "여행·숙박 수요 후보", "https://www.bookingholdings.com"),
        ("Walt Disney", "DIS", "NYSE", "테마파크·현장 경험 후보", "https://thewaltdisneycompany.com"),
        ("CJ ENM", "035760", "KOSDAQ", "공연·콘텐츠 경험 후보", "https://www.cjenm.com"),
        ("Coupang", "CPNG", "NYSE", "티켓·소비 접점 후보", "https://www.coupang.com"),
        ("Naver", "035420", "KRX", "검색·예약·지역 정보 후보", "https://www.navercorp.com"),
        ("Kakao", "035720", "KRX", "지도·예약·모빌리티 후보", "https://www.kakaocorp.com"),
    ),
    "culture": (
        ("Naver", "035420", "KRX", "검색·콘텐츠 확산 후보", "https://www.navercorp.com"),
        ("Kakao", "035720", "KRX", "커뮤니티·콘텐츠 확산 후보", "https://www.kakaocorp.com"),
        ("Meta", "META", "NASDAQ", "SNS 확산·광고 후보", "https://about.meta.com"),
        ("Alphabet", "GOOGL", "NASDAQ", "영상·검색 확산 후보", "https://abc.xyz"),
        ("Tencent", "0700", "HKEX", "커뮤니티·콘텐츠 플랫폼 후보", "https://www.tencent.com"),
        ("Snap", "SNAP", "NYSE", "숏폼·AR 확산 후보", "https://investor.snap.com"),
        ("Reddit", "RDDT", "NYSE", "커뮤니티 확산 후보", "https://www.redditinc.com"),
        ("Pinterest", "PINS", "NYSE", "이미지·취향 확산 후보", "https://investor.pinterestinc.com"),
        ("Walt Disney", "DIS", "NYSE", "캐릭터·IP 상품화 후보", "https://thewaltdisneycompany.com"),
    ),
    "technology": (
        ("삼성전자", "005930", "KRX", "전자·반도체 가치사슬 후보", "https://www.samsung.com"),
        ("SK하이닉스", "000660", "KRX", "메모리 반도체 가치사슬 후보", "https://www.skhynix.com"),
        ("NVIDIA", "NVDA", "NASDAQ", "AI 컴퓨팅 가치사슬 후보", "https://www.nvidia.com"),
        ("TSMC", "TSM", "NYSE", "반도체 제조 가치사슬 후보", "https://www.tsmc.com"),
        ("ABB", "ABB", "NYSE", "산업 자동화·로봇 후보", "https://global.abb"),
        ("Siemens", "SIE", "XETRA", "산업 기술·인프라 후보", "https://www.siemens.com"),
        ("현대자동차", "005380", "KRX", "모빌리티·로봇 적용 후보", "https://www.hyundai.com"),
        ("두산로보틱스", "454910", "KRX", "로봇 제조 후보", "https://www.doosanrobotics.com"),
        ("레인보우로보틱스", "277810", "KOSDAQ", "로봇 제조 후보", "https://www.rainbow-robotics.com"),
    ),
}


def build_editorial_review_pack(intelligence: dict, *, generated_at: datetime | None = None) -> dict:
    """Build a non-public, evidence-labelled 3x selection pool.

    The observed rank and score are never recalculated. Suggested keywords and
    companies are editorial hypotheses and cannot enter the public arrays until
    a team member explicitly approves them.
    """

    now = (generated_at or datetime.now(UTC)).astimezone(UTC).isoformat()
    ranked = list(intelligence.get("unified_ranking") or [])
    eligible = [item for item in ranked if item.get("broad_category") in PRODUCT_CATEGORIES]
    eligible.sort(key=lambda item: item["rank"])
    selected = eligible[:30]
    trends = []
    for review_rank, item in enumerate(selected, start=1):
        topic = str(item.get("display_name") or item.get("topic") or item["event_key"])
        category = str(item["broad_category"])
        source_evidence = [SOURCE_URLS[s] for s in item.get("period_sources", []) if s in SOURCE_URLS]
        keywords = [
            {
                "text": f"{topic} {suffix}",
                "candidate_rank": rank,
                "basis": "observed_trend_plus_editorial_query_expansion",
                "evidence_urls": source_evidence,
                "confidence": "candidate",
                "review_status": "unreviewed",
            }
            for rank, suffix in enumerate(KEYWORD_SUFFIXES[category], start=1)
        ]
        companies = [
            {
                "company": company,
                "ticker": ticker,
                "market": market,
                "candidate_rank": rank,
                "relation_tier": "adjacent",
                "reason": f"{topic}와 관련해 검토할 {reason}",
                "basis": "editorial_ecosystem_hypothesis",
                "evidence_urls": [url, *source_evidence],
                "confidence": "candidate",
                "review_status": "unreviewed",
                "ranking_effect": "none",
                "investment_recommendation": False,
            }
            for rank, (company, ticker, market, reason, url) in enumerate(COMPANIES[category], start=1)
        ]
        trends.append({
            "review_rank": review_rank,
            "observed_rank": item["rank"],
            "event_key": item["event_key"],
            "display_name": topic,
            "score": item["score"],
            "broad_category": category,
            "period_sources": item.get("period_sources", []),
            "source_evidence_urls": source_evidence,
            "selection_basis": "observed_x_google_product_category_filter_then_observed_rank",
            "related_keyword_candidates": keywords,
            "company_candidates": companies,
            "review_status": "unreviewed",
        })
    return {
        "schema_version": "trzip-editorial-review-v1",
        "generated_at": now,
        "ranking_policy": "preserve_observed_rank_and_score_no_reranking",
        "candidate_policy": {
            "trend_candidates": 30,
            "keyword_candidates_per_trend": 15,
            "company_candidates_per_trend": 9,
            "promotion_target": {"trends": 10, "keywords_per_trend": 5, "companies_per_trend_minimum": 3},
            "approval_required": True,
            "official_relationship_required": False,
            "global_listed_companies_allowed": True,
        },
        "trends": trends,
    }
