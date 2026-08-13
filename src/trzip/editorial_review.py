from __future__ import annotations

from datetime import UTC, datetime
import json
import re
from pathlib import Path


SOURCE_URLS = {
    "x": "https://x.com/explore/tabs/trending",
    "google_trends": "https://trends.google.com/trending?geo=KR",
}

FINAL_KEYWORD_COUNT = 5
MINIMUM_VERIFIED_COMPANY_COUNT = 3
TARGET_COMPLETE_TREND_COUNT = 10
AUTOMATIC_CANDIDATE_LIMIT = 30
MAX_HASHTAG_DISCOVERIES = 3
DAILY_EDITORIAL_SCHEMA_VERSION = "trzip-daily-editorial-v1"

# General lexical shapes for concrete discovery objects. These are classes of
# expressions, not trend names or a promotion whitelist.
X_DISCOVERY_OBJECT_PATTERN = re.compile(
    r"(?:일식|유성우|별똥별|축제|극장판|테스트|패드|버블|티켓|콘서트|챌린지|생일)",
    re.IGNORECASE,
)

# These dictionaries are enrichment caches only. Membership must never make a
# trend eligible, change its score/lane, or move it ahead of an observed item.
# Automatic candidate selection is performed before either cache is consulted.
PRODUCT_FIT_BROAD_CATEGORIES = {
    "consumer", "content", "culture", "food", "lifestyle", "technology",
}
PRODUCT_FIT_CATEGORIES = {
    "food_culinary", "seasonal_food_ritual", "music_performance",
    "screen_content", "gaming_digital", "fashion_collectible",
    "product_brand", "place_experience", "lifestyle_behavior",
    "wellness_behavior", "participation_meme", "technology_tool",
}

CATEGORY_DEFINITIONS = {
    "food_culinary": "음식·식품 소비와 관련된 구체적인 제품 또는 메뉴",
    "seasonal_food_ritual": "특정 시기와 소비 행동이 결합된 계절성 음식 문화",
    "music_performance": "음원·공연·아티스트 활동과 연결된 음악 콘텐츠",
    "screen_content": "영화·드라마·예능·OTT 등 화면 기반 콘텐츠",
    "gaming_digital": "게임·업데이트·플랫폼 활동과 연결된 디지털 콘텐츠",
    "fashion_collectible": "패션·뷰티·굿즈 소비와 연결된 제품 또는 스타일",
    "product_brand": "특정 제품이나 브랜드를 중심으로 형성된 관심 흐름",
    "place_experience": "행사·관광·공간 방문처럼 현장 경험과 연결된 흐름",
    "lifestyle_behavior": "일상에서 반복되는 구체적인 생활 행동",
    "wellness_behavior": "건강·운동·회복과 연결된 구체적인 생활 행동",
    "participation_meme": "공유·챌린지·밈처럼 이용자 참여로 확산되는 콘텐츠",
    "technology_tool": "기술·기기·서비스 활용과 연결된 구체적인 기술 주제",
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
    "챱챱 물개": ("토스뱅크 물개", "물개 배 만지기", "토스 5천원 이벤트", "토스 맞교환", "토스 링크 공유", "토스뱅크 이벤트", "토스 친구 초대", "토스 보상금", "토스 물개 챌린지", "토스 이벤트 링크", "토스뱅크 게임", "토스 앱 이벤트", "챱챱 물개 X", "챱챱 물개 실시간 트렌드", "토스 바이럴 이벤트"),
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
        {
            "company": "동원F&B", "ticker": "049770", "market": "KRX",
            "company_description": "양반 브랜드의 국·탕·보양식 HMR을 생산하는 종합식품기업",
            "relation_tier": "direct", "reason": "복날용 양반 보양식과 통다리 삼계탕을 생산·판매",
            "evidence_url": "https://www.dongwon.com/kr/media/2507",
            "evidence_owner": "동원그룹", "evidence_type": "official_company_release",
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
        {
            "company": "삼성물산", "ticker": "028260", "market": "KRX",
            "company_description": "SMR 발전소의 사업개발과 건설 참여를 추진하는 종합상사·건설기업",
            "relation_tier": "value_chain", "reason": "NuScale·두산에너빌리티·GS에너지와 SMR 발전소 사업개발 협약에 참여",
            "evidence_url": "https://www.gs.co.kr/ko/news/view?bbsSq=761",
            "evidence_owner": "GS Holdings", "evidence_type": "official_partner_release",
        },
    ),
    "불꽃축제": (
        {
            "company": "한화", "ticker": "000880", "market": "KRX",
            "company_description": "서울세계불꽃축제를 주최하고 연화 기술을 제공하는 한화그룹 지주 성격의 상장사",
            "relation_tier": "direct", "reason": "한화가 2000년부터 서울세계불꽃축제를 진행",
            "evidence_url": "https://www.hanwha.com/profile/src/pdf/2024%20Hanwha%20Profile%20Full%20Page%20KR.pdf",
            "evidence_owner": "Hanwha", "evidence_type": "official_group_profile",
        },
        {
            "company": "GS리테일", "ticker": "007070", "market": "KRX",
            "company_description": "GS25를 운영하며 대형 지역행사 인근의 식음료·행사용품 수요에 노출되는 유통기업",
            "relation_tier": "adjacent", "reason": "불꽃축제 인근 GS25 매장의 매출과 행사용품 판매가 급증한 실측 사례",
            "evidence_url": "https://www.youtube.com/watch?v=FCShe4_bSQ4",
            "evidence_owner": "연합뉴스TV", "evidence_type": "reported_sales_evidence",
        },
        {
            "company": "BGF리테일", "ticker": "282330", "market": "KRX",
            "company_description": "CU를 운영하며 축제 관람객의 식음료·간편식·행사용품 수요에 노출되는 유통기업",
            "relation_tier": "adjacent", "reason": "CU 편의점망을 통해 대형 행사 주변 소비 수요에 노출되는 비교 유통사",
            "evidence_url": "https://www.bgfretail.com/assets/file/bgf-retail/BGF%EB%A6%AC%ED%85%8C%EC%9D%BC_%EC%A7%80%EC%86%8D%EA%B0%80%EB%8A%A5%EA%B2%BD%EC%98%81%EB%B3%B4%EA%B3%A0%EC%84%9C%202022-2023%20%EC%B5%9C%EC%A2%85.pdf",
            "evidence_owner": "BGF리테일", "evidence_type": "business_exposure_evidence",
        },
    ),
    "데이즈드": (
        {
            "company": "HYBE", "ticker": "352820", "market": "KRX",
            "company_description": "BTS 등 아티스트 IP와 글로벌 팬 커머스 플랫폼 Weverse를 운영하는 엔터테인먼트기업",
            "relation_tier": "distribution", "reason": "HYBE 계열 Weverse Company가 BTS 표지의 DAZED KOREA 2026년 8월호를 공식 예약 판매",
            "evidence_url": "https://shop.weverse.io/ko/shop/KRW/artists/2/notices/13705",
            "evidence_owner": "Weverse Shop", "evidence_type": "official_distribution_page",
        },
        {
            "company": "Coupang", "ticker": "CPNG", "market": "NYSE",
            "company_description": "한국을 중심으로 전자상거래와 물류 서비스를 운영하는 미국 상장 유통플랫폼기업",
            "relation_tier": "distribution", "reason": "쿠팡 상품 페이지에서 DAZED KOREA 잡지를 실제 판매·유통",
            "evidence_url": "https://www.coupang.com/vp/products/9261978118",
            "evidence_owner": "Coupang", "evidence_type": "commerce_listing_evidence",
        },
        {
            "company": "Kering", "ticker": "KER", "market": "EURONEXT_PARIS",
            "company_description": "Saint Laurent·Gucci 등 패션 하우스를 보유한 프랑스 상장 럭셔리그룹",
            "relation_tier": "brand_collaboration", "reason": "Kering 산하 Saint Laurent가 아티스트와 DAZED 화보 협업 콘텐츠에 직접 참여",
            "evidence_url": "https://www.youtube.com/watch?v=HCB800c4Teo",
            "evidence_owner": "SEVENTEEN Official YouTube", "evidence_type": "official_collaboration_content",
        },
    ),
    "지스타": (
        {
            "company": "크래프톤", "ticker": "259960", "market": "KRX",
            "company_description": "지스타에서 신작 시연과 대형 체험 부스를 운영하는 게임기업",
            "relation_tier": "direct", "reason": "지스타 공식 전시관 참가사이자 자체 지스타 전용 페이지 운영",
            "evidence_url": "https://www.krafton.com/en/gstar2025/",
            "evidence_owner": "KRAFTON", "evidence_type": "official_event_page",
        },
        {
            "company": "넷마블", "ticker": "251270", "market": "KRX",
            "company_description": "지스타에서 다수 신작과 체험 부스를 공개하는 모바일·PC 게임기업",
            "relation_tier": "direct", "reason": "지스타 공식 부스 목록에 참가사로 등재되고 신작 5종을 전시",
            "evidence_url": "https://gstar.or.kr/eng/gstar/gstar_booth_info.do?classNm=&page=3",
            "evidence_owner": "G-STAR", "evidence_type": "official_exhibitor_list",
        },
        {
            "company": "엔씨소프트", "ticker": "036570", "market": "KRX",
            "company_description": "지스타 메인 스폰서와 대형 전시관으로 참가한 게임기업",
            "relation_tier": "direct", "reason": "지스타 메인 스폰서 및 참가사로 확인",
            "evidence_url": "https://www.korea.net/NewsFocus/Culture/view?articleId=282098",
            "evidence_owner": "Korea.net", "evidence_type": "government_event_report",
        },
    ),
    "티빙": (
        {
            "company": "CJ ENM", "ticker": "035760", "market": "KOSDAQ",
            "company_description": "티빙의 콘텐츠와 플랫폼 사업을 주도하는 미디어·엔터테인먼트 기업",
            "relation_tier": "direct", "reason": "CJ ENM이 자사 OTT 티빙의 사업 확장과 투자 관계를 공식 발표",
            "evidence_url": "https://www.cjenm.com/ko/news/ott-%ED%8B%B0%EB%B9%99tving-%EB%84%A4%EC%9D%B4%EB%B2%84-%ED%95%A9%EB%A5%98%EB%A1%9C-%EC%82%AC%EC%97%85-%ED%99%95%EC%9E%A5-%EC%86%8D%EB%8F%84-%EB%86%92%EC%9D%B8%EB%8B%A4/",
            "evidence_owner": "CJ ENM", "evidence_type": "official_company_release",
        },
        {
            "company": "NAVER", "ticker": "035420", "market": "KRX",
            "company_description": "티빙 지분투자와 멤버십 결합을 통해 가입자 유입을 지원한 플랫폼기업",
            "relation_tier": "value_chain", "reason": "티빙 지분투자 및 네이버플러스 멤버십 결합 상품 협력",
            "evidence_url": "https://www.cjenm.com/ko/news/ott-%ED%8B%B0%EB%B9%99tving-%EB%84%A4%EC%9D%B4%EB%B2%84-%ED%95%A9%EB%A5%98%EB%A1%9C-%EC%82%AC%EC%97%85-%ED%99%95%EC%9E%A5-%EC%86%8D%EB%8F%84-%EB%86%92%EC%9D%B8%EB%8B%A4/",
            "evidence_owner": "CJ ENM", "evidence_type": "official_partnership_release",
        },
        {
            "company": "KT", "ticker": "030200", "market": "KRX",
            "company_description": "통신 요금제와 구독 상품을 통해 티빙 이용권을 유통하는 통신기업",
            "relation_tier": "distribution", "reason": "KT 공식 상품에서 티빙 구독과 계정 연동을 제공",
            "evidence_url": "https://m.product.kt.com/static/prodetail/1486/mobile/itemForte/detail_view/tving/m_ott_pop_tving.html",
            "evidence_owner": "KT", "evidence_type": "official_distribution_page",
        },
    ),
    "코난 극장판": (
        {
            "company": "Sega Sammy Holdings", "ticker": "6460", "market": "TSE",
            "company_description": "명탐정 코난 TV·극장판 제작사 TMS Entertainment를 보유한 엔터테인먼트그룹",
            "relation_tier": "direct", "reason": "그룹 계열 TMS 공식 작품 목록에 명탐정 코난 극장판 시리즈 수록",
            "evidence_url": "https://www.tms-e.co.jp/alltitles/conan/",
            "evidence_owner": "TMS Entertainment", "evidence_type": "official_title_catalog",
        },
        {
            "company": "TOHO", "ticker": "9602", "market": "TSE",
            "company_description": "명탐정 코난 극장판을 일본 극장에 배급하는 영화기업",
            "relation_tier": "distribution", "reason": "TOHO가 코난 극장판 개봉과 공식 무대행사를 운영",
            "evidence_url": "https://www.toho.co.jp/movie/news/conan-movie-2026_20260411",
            "evidence_owner": "TOHO", "evidence_type": "official_movie_release",
        },
        {
            "company": "Nippon Television Holdings", "ticker": "9404", "market": "TSE",
            "company_description": "명탐정 코난 제작위원회와 방송에 참여하는 일본 미디어기업",
            "relation_tier": "value_chain", "reason": "코난 극장판 제작사 크레딧에 Nippon Television이 포함",
            "evidence_url": "https://www.imdb.com/title/tt27521477/companycredits/",
            "evidence_owner": "IMDb", "evidence_type": "production_credit_evidence",
        },
    ),
    "챱챱 물개": (
        {
            "company": "하나금융지주", "ticker": "086790", "market": "KRX",
            "company_description": "하나은행을 핵심 자회사로 둔 국내 상장 금융지주회사",
            "relation_tier": "ownership", "reason": "금융위원회가 토스뱅크 주주 구성에 KEB하나은행이 참여했다고 공식 설명",
            "evidence_url": "https://www.fsc.go.kr/no010103/24697",
            "evidence_owner": "금융위원회", "evidence_type": "government_shareholder_record",
        },
        {
            "company": "한화투자증권", "ticker": "003530", "market": "KRX",
            "company_description": "토스뱅크 컨소시엄에 주주로 참여한 국내 상장 증권사",
            "relation_tier": "ownership", "reason": "금융위원회가 토스뱅크 주주 구성에 한화투자증권이 참여했다고 공식 설명",
            "evidence_url": "https://www.fsc.go.kr/no010103/24697",
            "evidence_owner": "금융위원회", "evidence_type": "government_shareholder_record",
        },
        {
            "company": "한국전자인증", "ticker": "041460", "market": "KOSDAQ",
            "company_description": "전자서명·인증 서비스를 제공하며 토스뱅크 컨소시엄에 참여한 국내 상장 기술기업",
            "relation_tier": "ownership", "reason": "토스뱅크 인가 당시 공개된 컨소시엄 주주 구성에 한국전자인증이 포함",
            "evidence_url": "https://www.inews24.com/view/1215006",
            "evidence_owner": "아이뉴스24", "evidence_type": "reported_shareholder_record",
        },
    ),
    "휴머노이드 로봇": (
        {
            "company": "Tesla", "ticker": "TSLA", "market": "NASDAQ",
            "company_description": "범용 휴머노이드 Optimus를 개발하는 전기차·AI 기업",
            "relation_tier": "direct", "reason": "Tesla AI 사업에서 Optimus 휴머노이드를 직접 개발",
            "evidence_url": "https://www.tesla.com/AI",
            "evidence_owner": "Tesla", "evidence_type": "official_product_page",
        },
        {
            "company": "NVIDIA", "ticker": "NVDA", "market": "NASDAQ",
            "company_description": "휴머노이드용 GR00T 모델과 Isaac 로봇 플랫폼을 제공하는 AI 반도체기업",
            "relation_tier": "value_chain", "reason": "NVIDIA가 휴머노이드 범용 기반모델 Project GR00T를 공식 발표",
            "evidence_url": "https://nvidianews.nvidia.com/_gallery/download_pdf/65f8b9913d63321e2b746105/",
            "evidence_owner": "NVIDIA", "evidence_type": "official_technology_release",
        },
        {
            "company": "현대자동차", "ticker": "005380", "market": "KRX",
            "company_description": "Boston Dynamics의 Atlas를 제조현장에 적용하는 자동차·로보틱스 기업",
            "relation_tier": "direct", "reason": "현대차그룹과 Boston Dynamics가 전기식 Atlas의 산업 적용을 공동 추진",
            "evidence_url": "https://www.hyundai.com/content/hyundai/worldwide/en/newsroom/detail/uniting-humans-and-robots--hyundai-motor-group-and-boston-dynamics%E2%80%99-vision-for-the-future-of-work-and-hr-evolution-0000000983.html",
            "evidence_owner": "Hyundai Motor Group", "evidence_type": "official_company_release",
        },
    ),
    "삼전닉스": (
        {
            "company": "삼성전자", "ticker": "005930", "market": "KRX",
            "company_description": "DRAM·NAND·HBM을 생산하는 글로벌 메모리 반도체기업",
            "relation_tier": "direct", "reason": "삼전닉스의 '삼전'에 해당하며 HBM 제품군을 직접 생산",
            "evidence_url": "https://semiconductor.samsung.com/kr/dram/hbm/",
            "evidence_owner": "Samsung Semiconductor", "evidence_type": "official_product_page",
        },
        {
            "company": "SK하이닉스", "ticker": "000660", "market": "KRX",
            "company_description": "HBM과 DRAM을 핵심 제품으로 공급하는 글로벌 메모리 반도체기업",
            "relation_tier": "direct", "reason": "삼전닉스의 '닉스'에 해당하는 직접 구성 기업",
            "evidence_url": "https://www.skhynix.com/eng/product/dram/hbm.go",
            "evidence_owner": "SK hynix", "evidence_type": "official_product_page",
        },
        {
            "company": "Micron Technology", "ticker": "MU", "market": "NASDAQ",
            "company_description": "삼성전자·SK하이닉스와 경쟁하는 미국 메모리 및 HBM 생산기업",
            "relation_tier": "adjacent", "reason": "동일한 글로벌 HBM·메모리 시장의 직접 비교기업",
            "evidence_url": "https://www.micron.com/products/memory/hbm",
            "evidence_owner": "Micron Technology", "evidence_type": "official_product_page",
        },
    ),
}

INDUSTRY_NODES = {
    "말복": "식품/HMR/보양식",
    "아이폰": "스마트폰/전자부품/위탁생산",
    "검은사막": "게임IP/콘솔·PC 플랫폼",
    "smr": "원전/SMR 설계·기자재·건설",
    "불꽃축제": "문화행사/연화/현장소비",
    "데이즈드": "패션미디어/아티스트IP/브랜드협업·유통",
    "지스타": "게임전시/신작마케팅",
    "티빙": "OTT/콘텐츠/통신유통",
    "코난 극장판": "애니메이션IP/영화제작·배급",
    "챱챱 물개": "핀테크이벤트/바이럴공유/인터넷은행 지분관계",
    "휴머노이드 로봇": "로보틱스/AI모델/산업자동화",
    "삼전닉스": "메모리반도체/HBM",
}


def _key(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _verified_company_rows(registry_key: str, *, verified_at: str) -> list[dict]:
    required = {
        "company", "ticker", "market", "company_description", "relation_tier",
        "reason", "evidence_url", "evidence_owner", "evidence_type",
    }
    rows = []
    for source in VERIFIED_COMPANIES.get(registry_key, ()):
        if not required.issubset(source) or any(not str(source[field]).strip() for field in required):
            continue
        relation_type = source["relation_tier"]
        ontology_relation_tier = {
            "direct": "core",
            "distribution": "value_chain",
            "brand_collaboration": "value_chain",
            "ownership": "value_chain",
            "value_chain": "value_chain",
            "adjacent": "adjacent",
        }.get(relation_type, "adjacent")
        relation_tier = {
            "core": "direct",
            "value_chain": "value_chain",
            "adjacent": "industry_watch",
        }[ontology_relation_tier]
        rows.append({
            **source,
            "relation_type": relation_type,
            "relation_tier": relation_tier,
            "ontology_relation_tier": ontology_relation_tier,
            "industry_node": INDUSTRY_NODES.get(registry_key, "기타"),
            "ontology_path": [registry_key, INDUSTRY_NODES.get(registry_key, "기타"), source["company"]],
            "ontology_relation": ontology_relation_tier,
            "candidate_rank": len(rows) + 1,
            "verification_status": "evidence_verified",
            "verified_at": verified_at,
            "review_status": "unreviewed",
            "ranking_effect": "none",
            "investment_recommendation": False,
        })
    return rows


def _automatic_candidate(item: dict) -> tuple[bool, str]:
    """Apply general product-fit rules without consulting enrichment caches."""

    topic = str(
        item.get("display_name") or item.get("topic") or item.get("event_key") or ""
    ).strip()
    if not topic:
        return False, "empty_topic"
    lane = str(item.get("lane") or "review")
    latest_x_rank = (item.get("latest_source_ranks") or {}).get("x")
    # X's current top 30 is itself a high-value discovery surface for memes,
    # fandom, products and cultural moments.  Unknown context stays visibly
    # unresolved, but is no longer discarded merely because enrichment has not
    # caught up yet. Issue-lane items remain excluded.
    x_discovery_shape = topic.startswith("#") or bool(X_DISCOVERY_OBJECT_PATTERN.search(topic))
    x_discovery = (
        lane == "review"
        and latest_x_rank is not None
        and int(latest_x_rank) <= 30
        and str(item.get("context_status") or "") != "ambiguous_person"
        and x_discovery_shape
    )
    if lane == "issue":
        return False, "issue_lane"
    if lane != "main" and not x_discovery:
        return False, "not_main_or_x_discovery"
    if x_discovery:
        return True, "x_top30_discovery_signal"
    main_rank = item.get("main_rank")
    if main_rank is None or int(main_rank) > AUTOMATIC_CANDIDATE_LIMIT:
        return False, "outside_top_main_candidates"
    category = str(item.get("category") or "unclassified")
    broad_category = str(item.get("broad_category") or "other")
    if (
        category not in PRODUCT_FIT_CATEGORIES
        or broad_category not in PRODUCT_FIT_BROAD_CATEGORIES
    ):
        return False, "not_product_fit_category"
    if str(item.get("context_status") or "") in {"unresolved", "ambiguous_person"}:
        return False, "unresolved_context"
    if (
        item.get("category_basis") == "observed_related_terms_general_rule"
        and str(item.get("context_status") or "") == "needs_context"
    ):
        return False, "raw_expression_not_specific"
    if (
        category in {"music_performance", "screen_content"}
        and str(item.get("context_status") or "") == "needs_context"
    ):
        return False, "content_title_context_not_resolved"
    trend_fit = item.get("trend_fit") or {}
    if bool(trend_fit.get("generic_category_word")):
        return False, "generic_category_word"
    return True, "automatic_product_fit"


def _cache_key(topic: str, cache: dict) -> str | None:
    normalized = _key(topic)
    return next((name for name in cache if _key(name) == normalized), None)


def _keyword_rows(item: dict, *, cache_key: str | None) -> list[dict]:
    values: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in item.get("keywords") or []:
        text = str(row.get("text") if isinstance(row, dict) else row).strip()
        normalized = _key(text)
        if text and normalized not in seen:
            seen.add(normalized)
            values.append((text, "observed_or_reviewed_source_evidence"))
    if cache_key:
        for text in KEYWORDS.get(cache_key, ()):
            normalized = _key(text)
            if normalized not in seen:
                seen.add(normalized)
                values.append((text, "term_specific_enrichment_cache"))
    return [
        {
            "text": text,
            "candidate_rank": rank,
            "basis": basis,
            "review_status": "approved_for_display",
        }
        for rank, (text, basis) in enumerate(values[:FINAL_KEYWORD_COUNT], start=1)
    ]


def _published_company_rows(item: dict) -> list[dict]:
    rows = []
    for source in item.get("companies") or []:
        company = str(source.get("company") or "").strip()
        ticker = str(source.get("ticker") or source.get("stock_code") or "").strip()
        market = str(source.get("market") or "").strip()
        evidence_url = str(source.get("evidence_url") or "").strip()
        if not evidence_url:
            evidence_sources = source.get("evidence_sources") or []
            evidence_url = next(
                (str(row.get("url") or "").strip() for row in evidence_sources if row.get("url")),
                "",
            )
        if not all((company, ticker, market, evidence_url)):
            continue
        row = dict(source)
        row.update({
            "ticker": ticker,
            "company_description": str(
                source.get("company_description")
                or source.get("company_summary")
                or "상장기업"
            ),
            "reason": str(
                source.get("reason") or source.get("relationship_reason") or ""
            ),
            "evidence_url": evidence_url,
            "evidence_owner": str(source.get("evidence_owner") or "reviewed_ontology"),
            "evidence_type": str(source.get("evidence_type") or source.get("evidence_kind") or "reviewed_ontology_path"),
            "candidate_rank": len(rows) + 1,
            "verification_status": str(source.get("verification_status") or "evidence_verified"),
            "review_status": str(source.get("team_review_status") or "ontology_reviewed"),
            "ranking_effect": "none",
            "investment_recommendation": False,
        })
        rows.append(row)
    return rows


def _company_rows(item: dict, *, cache_key: str | None, verified_at: str) -> list[dict]:
    published = _published_company_rows(item)
    if len(published) >= MINIMUM_VERIFIED_COMPANY_COUNT:
        return published
    if cache_key:
        return _verified_company_rows(cache_key, verified_at=verified_at)
    return published


def _trend_definition(item: dict, topic: str) -> str:
    """Return a concise UI-safe definition without inventing a news cause."""

    category = str(item.get("category") or "unclassified")
    kind = CATEGORY_DEFINITIONS.get(category, "구체적인 대상이나 행동을 중심으로 형성된 관심 흐름")
    return f"‘{topic}’은(는) {kind}입니다."


def _observation_summary(item: dict, topic: str) -> str:
    labels = {
        "x": "X 한국 실시간",
        "google_trends": "Google Trends 한국",
    }
    sources = [labels[source] for source in item.get("period_sources") or [] if source in labels]
    joined = "와 ".join(sources) if sources else "X·Google 실측 데이터"
    return f"선택 기간에 {joined}에서 ‘{topic}’이(가) 실제 관측됐습니다."


def load_daily_editorial_review(path: Path) -> dict:
    """Load a reviewed daily selection without ever changing raw ranks."""

    review = json.loads(Path(path).read_text(encoding="utf-8"))
    if review.get("schema_version") != DAILY_EDITORIAL_SCHEMA_VERSION:
        raise ValueError("unsupported daily editorial schema")
    if review.get("ranking_effect") != "none":
        raise ValueError("daily editorial review cannot affect ranking")
    items = review.get("items")
    if not isinstance(items, list) or len(items) != TARGET_COMPLETE_TREND_COUNT:
        raise ValueError("daily editorial review requires exactly ten items")
    seen = set()
    for item in items:
        key = str(item.get("event_key") or "").strip()
        sources = item.get("source_event_keys") or []
        if not key or key in seen or not isinstance(sources, list) or not sources:
            raise ValueError("daily editorial item identity is invalid")
        seen.add(key)
    return review


def _daily_editorial_candidates(ranked: list[dict], daily_review: dict) -> tuple[list[tuple[dict, str]], list[dict]]:
    """Resolve a daily review against events observed by X or Google only."""

    by_event_key = {str(item.get("event_key") or ""): item for item in ranked}
    selected: list[tuple[dict, str]] = []
    audit: list[dict] = []
    for review in daily_review["items"]:
        source_keys = [str(key) for key in review["source_event_keys"]]
        source_rows = [by_event_key[key] for key in source_keys if key in by_event_key]
        if len(source_rows) != len(source_keys):
            missing = sorted(set(source_keys) - {str(row.get("event_key")) for row in source_rows})
            raise ValueError(f"daily editorial item was not observed: {missing}")
        primary = min(source_rows, key=lambda row: (int(row.get("rank") or 10**9), str(row.get("event_key") or "")))
        candidate = dict(primary)
        candidate.update({
            "event_key": review["event_key"],
            # A reviewed event can combine several observed terms. Keep this
            # pointer so the frontend resolves an immutable source detail.
            "detail_event_key": primary.get("event_key"),
            "display_name": review.get("display_name") or review["event_key"],
            "category": review.get("category") or primary.get("category") or "unclassified",
            "broad_category": review.get("broad_category") or primary.get("broad_category") or "other",
            "keywords": review.get("related_keywords") or [],
            "companies": review.get("companies") or [],
            "daily_editorial_source_event_keys": source_keys,
            "daily_editorial_source_ranks": [row.get("rank") for row in source_rows],
            "daily_editorial_enrichment_key": review.get("enrichment_key"),
            "daily_editorial_definition": review.get("trend_definition"),
            "daily_editorial_summary": review.get("observation_summary"),
            "period_sources": sorted({source for row in source_rows for source in row.get("period_sources", [])}),
        })
        selected.append((candidate, "daily_editorial_review"))
        audit.append({
            "event_key": candidate["event_key"],
            "source_event_keys": source_keys,
            "source_observed_ranks": candidate["daily_editorial_source_ranks"],
            "ranking_effect": "none",
            "eligible": True,
        })
    # Editorial review chooses the displayable *set* only.  The public order
    # remains the observed combined-rank order of the source candidates.
    selected.sort(key=lambda pair: (int(pair[0].get("rank") or 10**9), str(pair[0].get("event_key") or "")))
    return selected, audit


def build_editorial_review_pack(
    intelligence: dict,
    *,
    generated_at: datetime | None = None,
    daily_review: dict | None = None,
) -> dict:
    """Build a score-preserving pack from automatic product-fit candidates.

    Selection is independent of the keyword/company caches. Enrichment is
    attempted only after the highest-ranked automatic candidates are fixed.
    """

    now = (generated_at or datetime.now(UTC)).astimezone(UTC).isoformat()
    ranked = sorted(
        intelligence.get("unified_ranking") or [],
        key=lambda item: (int(item.get("rank") or 10**9), str(item.get("event_key") or "")),
    )
    selected = []
    selection_audit = []
    selected_hashtags = 0
    for item in ranked:
        eligible, reason = _automatic_candidate(item)
        topic = str(item.get("display_name") or item.get("topic") or "").strip()
        if eligible and topic.startswith("#"):
            if selected_hashtags >= MAX_HASHTAG_DISCOVERIES:
                eligible = False
                reason = "hashtag_discovery_diversity_cap"
            else:
                selected_hashtags += 1
        selection_audit.append({
            "observed_rank": item.get("rank"),
            "event_key": item.get("event_key"),
            "automatic_eligible": eligible,
            "reason": reason,
            "cache_membership_affects_selection": False,
        })
        if eligible:
            selected.append((item, reason))
        if len(selected) == AUTOMATIC_CANDIDATE_LIMIT:
            break

    trends = []
    rejected_incomplete = 0
    enrichment_queue = []
    for item, selection_reason in selected:
        topic = str(item.get("display_name") or item.get("topic") or item.get("event_key") or "").strip()
        keyword_cache_key = item.get("daily_editorial_enrichment_key") or _cache_key(topic, KEYWORDS)
        company_cache_key = item.get("daily_editorial_enrichment_key") or _cache_key(topic, VERIFIED_COMPANIES)
        source_evidence = [SOURCE_URLS[s] for s in item.get("period_sources", []) if s in SOURCE_URLS]
        keyword_rows = _keyword_rows(item, cache_key=keyword_cache_key)
        company_rows = _company_rows(item, cache_key=company_cache_key, verified_at=now)
        complete = (
            len(keyword_rows) == FINAL_KEYWORD_COUNT
            and len(company_rows) >= MINIMUM_VERIFIED_COMPANY_COUNT
            and bool(source_evidence)
        )
        if not complete:
            rejected_incomplete += 1
            enrichment_queue.append({
                "observed_rank": item.get("rank"),
                "event_key": item.get("event_key"),
                "keyword_count": len(keyword_rows),
                "company_count": len(company_rows),
                "missing_keywords": max(0, FINAL_KEYWORD_COUNT - len(keyword_rows)),
                "missing_companies": max(0, MINIMUM_VERIFIED_COMPANY_COUNT - len(company_rows)),
                "status": "enrichment_pending",
                "selection_reason": selection_reason,
            })
            # Discovery-only X expressions are useful enrichment leads, but
            # unresolved expressions are not home-ready product-fit trends.
            if selection_reason == "x_top30_discovery_signal":
                continue
        review_rank = len(trends) + 1
        trends.append({
            "review_rank": review_rank,
            "observed_rank": item["rank"],
            "event_key": item["event_key"],
            "detail_event_key": item.get("detail_event_key") or item["event_key"],
            "display_name": item.get("display_name") or topic,
            "score": item["score"],
            "period_sources": item.get("period_sources", []),
            "source_evidence_urls": source_evidence,
            "selection_basis": (
                "automatic_product_fit_then_enrichment"
            ),
            "selection_reason": selection_reason,
            "trend_definition": item.get("trend_definition") or _trend_definition(item, topic),
            "observation_summary": _observation_summary(item, topic),
            "definition_status": "category_based_observed_topic_definition",
            "related_keywords": keyword_rows,
            "company_candidates": company_rows,
            "company_display_policy": {
                "show_category_groups": len(company_rows) >= 6,
                "default_layout": "company_description_list",
                "grouping_reason": (
                    "many_companies_need_navigation" if len(company_rows) >= 6
                    else "few_companies_are_clearer_without_category_tabs"
                ),
            },
            "keyword_count": len(keyword_rows),
            "company_count": len(company_rows),
            "company_verification_status": (
                "ready_for_team_selection"
                if len(company_rows) >= MINIMUM_VERIFIED_COMPANY_COUNT
                else "enrichment_pending"
            ),
            "display_contract_status": "complete" if complete else "enrichment_pending",
            "review_status": "unreviewed",
            "source_event_keys": [item["event_key"]],
            "source_observed_ranks": [item["rank"]],
        })
    return {
        "schema_version": "trzip-editorial-review-v2",
        "generated_at": now,
        "selection_engine": "deterministic_rule_v2",
        "manual_review_supplied": daily_review is not None,
        "manual_review_selection_effect": "none",
        "ranking_engine": "deterministic_period_score_v1",
        "runtime_ai_used": False,
        "ranking_effect_of_enrichment": "none",
        "ranking_policy": "preserve_observed_rank_and_score_no_reranking",
        "candidate_policy": {
            "trend_candidate_maximum": 30,
            "product_fit_filter": {
                "must_be_observed_by_x_or_google_in_selected_period": True,
                "must_be_automatic_main_product_fit_or_x_top30_discovery_candidate": True,
                "registry_membership_affects_selection": False,
                "must_be_within_top_main_candidates": AUTOMATIC_CANDIDATE_LIMIT,
                "broad_generic_terms_rejected": True,
                "ranking_is_preserved_from_observed_global_rank": True,
            },
            "automatic_candidate_limit": AUTOMATIC_CANDIDATE_LIMIT,
            "maximum_hashtag_discoveries": MAX_HASHTAG_DISCOVERIES,
            "required_related_keywords_per_trend": FINAL_KEYWORD_COUNT,
            "minimum_verified_companies_for_selection": MINIMUM_VERIFIED_COMPANY_COUNT,
            "target_complete_trends": TARGET_COMPLETE_TREND_COUNT,
            "padding_forbidden": True,
            "broad_term_forbidden": True,
            "global_listed_companies_allowed": True,
        },
        "preview_ready": bool(trends),
        "publication_ready": bool(trends),
        "complete_trend_count": sum(
            item["display_contract_status"] == "complete" for item in trends[:TARGET_COMPLETE_TREND_COUNT]
        ),
        "display_candidate_count": len(trends),
        "qualified_trend_count": sum(
            item["display_contract_status"] == "complete" for item in trends
        ),
        "rejected_incomplete_count": rejected_incomplete,
        "automatic_candidate_count": len(selected),
        "selection_audit": selection_audit,
        "enrichment_queue": enrichment_queue,
        "trends": trends[:TARGET_COMPLETE_TREND_COUNT],
    }
