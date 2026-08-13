from __future__ import annotations

from datetime import UTC, datetime
import json
import re
from pathlib import Path

from .company_roles import with_company_role
from .ontology import MINIMUM_FRONTEND_COMPANIES


SOURCE_URLS = {
    "x": "https://x.com/explore/tabs/trending",
    "google_trends": "https://trends.google.com/trending?geo=KR",
}

FINAL_KEYWORD_COUNT = 5
MINIMUM_VERIFIED_COMPANY_COUNT = MINIMUM_FRONTEND_COMPANIES
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
    "광 통신": ("광섬유", "광케이블", "광통신망", "데이터센터 광케이블", "FTTH", "광접속 자재", "광모듈", "CPO", "장거리 전송망", "초고속 통신", "통신 인프라", "광대역 네트워크", "광통신 장비", "광케이블 수요", "AI 데이터센터"),
    "개기일식": ("일식 관측", "일식 안경", "태양 필터", "천체망원경", "일식 촬영", "태양 관측", "부분일식", "개기일식 시간", "개기일식 경로", "천문대", "카메라 렌즈", "안전 관측", "태양 사진", "천문 이벤트", "관측 장비"),
    "유성우 시간": ("페르세우스 유성우", "유성우 극대기", "별똥별", "유성우 관측 시간", "유성우 방향", "천체망원경", "천체 촬영", "별자리 앱", "유성우 명소", "밤하늘", "천문대", "카메라 장노출", "삼각대", "광공해", "기상 조건"),
    "페르세우스 유성우": ("유성우 극대기", "별똥별", "유성우 관측 시간", "유성우 방향", "천체망원경", "천체 촬영", "별자리 앱", "유성우 명소", "밤하늘", "천문대", "카메라 장노출", "삼각대", "광공해", "기상 조건", "페르세우스자리"),
    "커피믹스": ("인스턴트 커피", "스틱 커피", "맥심 모카골드", "프렌치카페 카페믹스", "네스카페 믹스", "커피 프리마", "무설탕 커피믹스", "디카페인 커피믹스", "커피믹스 가격", "커피믹스 칼로리", "커피믹스 판매량", "사무실 커피", "홈카페", "커피 원두", "커피 크리머"),
    "용인반도체클러스터": ("용인 반도체 국가산단", "SK하이닉스 용인 팹", "삼성전자 용인 클러스터", "반도체 메가 클러스터", "반도체 전력 인프라", "반도체 용수", "반도체 소재 부품 장비", "용인 원삼면", "반도체 팹", "첨단 시스템반도체", "메모리 반도체", "반도체 공급망", "산업단지 조성", "반도체 투자", "반도체 인프라"),
    "아시안 게임": ("아이치 나고야 아시안게임", "아시안게임 일정", "아시안게임 종목", "아시안게임 국가대표", "아시안게임 메달", "아시안게임 중계", "아시안게임 개막식", "아시안게임 티켓", "아시안게임 경기장", "아시안게임 스폰서", "아시안게임 선수단", "아시안게임 야구", "아시안게임 축구", "아시안게임 e스포츠", "아시안게임 개최지"),
    "삼계탕": ("삼계탕 간편식", "복날 삼계탕", "삼계탕 HMR", "삼계탕 판매량", "삼계탕 원재료", "영양 삼계탕", "삼계탕 배달", "보양식", "국내산 영계", "삼계탕 신제품", "삼계탕 가격", "초복", "중복", "말복", "복날 외식"),
    "롤 패치 노트": ("리그 오브 레전드 패치", "LoL 업데이트", "롤 챔피언 밸런스", "롤 신규 스킨", "롤 패치 일정", "롤 메타", "롤 랭크", "롤 e스포츠", "LCK", "Riot Games", "롤 클라이언트", "롤 핫픽스", "롤 시즌", "롤 아이템 변경", "롤 패치 버전"),
}

# These are not category templates. Every company relation below has a
# relation-specific source which explicitly names the company/product link.
VERIFIED_COMPANIES = {
    "천체관측장비": (
        {
            "company": "Canon", "ticker": "7751", "market": "TSE",
            "company_description": "카메라·렌즈와 천체·일식 촬영 교육 콘텐츠를 제공하는 일본 상장 광학기업",
            "relation_tier": "direct", "reason": "Canon 공식 가이드가 EOS R·PowerShot을 일식 촬영용 카메라로 직접 설명",
            "evidence_url": "https://www.usa.canon.com/learning/training-articles/training-articles-list/choosing-a-camera-for-eclipse-photography",
            "evidence_owner": "Canon", "evidence_type": "official_eclipse_equipment_guide",
        },
        {
            "company": "Nikon", "ticker": "7731", "market": "TSE",
            "company_description": "천체 촬영용 카메라·렌즈와 태양·달·행성 촬영 가이드를 제공하는 일본 상장 광학기업",
            "relation_tier": "adjacent", "reason": "Nikon 공식 천체촬영 가이드가 태양·달·행성 관측 촬영 장비와 방법을 설명",
            "evidence_url": "https://nij.nikon.com/cms/sp/p1000_astrophotography/",
            "evidence_owner": "Nikon", "evidence_type": "official_astrophotography_guide",
        },
        {
            "company": "Ricoh", "ticker": "7752", "market": "TSE",
            "company_description": "PENTAX 카메라와 별 추적 촬영 장치 Astrotracer를 제공하는 일본 상장 광학기업",
            "relation_tier": "adjacent", "reason": "Ricoh Imaging 공식 페이지가 Astrotracer 기반 천체 추적 촬영 기능을 명시",
            "evidence_url": "https://www.ricoh-imaging.co.jp/english/products/o-gps2/feature/",
            "evidence_owner": "Ricoh Imaging", "evidence_type": "official_astrophotography_product_page",
        },
        {
            "company": "FUJIFILM Holdings", "ticker": "4901", "market": "TSE",
            "company_description": "천체 촬영용 카메라·렌즈와 별 궤적 촬영 가이드를 제공하는 일본 상장 광학기업",
            "relation_tier": "adjacent", "reason": "FUJIFILM 공식 가이드가 X Series 카메라와 렌즈를 이용한 별 궤적 촬영 장비·방법을 설명",
            "evidence_url": "https://www.fujifilm-x.com/en-gb/learning-centre/how-to-start-photographing-star-trails/",
            "evidence_owner": "FUJIFILM", "evidence_type": "official_astrophotography_guide",
        },
        {
            "company": "Sony Group", "ticker": "6758", "market": "TSE",
            "company_description": "저조도 천체 촬영이 가능한 카메라와 밤하늘 촬영 가이드를 제공하는 일본 상장 전자기업",
            "relation_tier": "adjacent", "reason": "Sony 공식 지원 문서가 별이 가득한 밤하늘 장노출 촬영법과 장비 사용을 설명",
            "evidence_url": "https://www.sony.com/electronics/support/compact-cameras-dsc-t-series/dsc-t110/articles/00223374",
            "evidence_owner": "Sony", "evidence_type": "official_astrophotography_guide",
        },
        {
            "company": "Adobe", "ticker": "ADBE", "market": "NASDAQ",
            "company_description": "천체 사진 보정·합성 워크플로를 제공하는 미국 상장 소프트웨어기업",
            "relation_tier": "adjacent", "reason": "Adobe 공식 가이드가 천체 사진 촬영과 후처리 워크플로를 별도 분야로 안내",
            "evidence_url": "https://www.adobe.com/creativecloud/photography/type/astrophotography.html",
            "evidence_owner": "Adobe", "evidence_type": "official_astrophotography_workflow",
        },
    ),
    "커피믹스": (
        {
            "company": "동서", "ticker": "026960", "market": "KOSPI",
            "company_description": "커피 제조·유통 계열 사업과 커피믹스 생산 기반을 보유한 국내 상장 식품기업",
            "relation_tier": "direct", "reason": "동서 공식 그룹 소개가 동서식품의 커피 제조·판매와 동서물산의 커피믹스 제조를 명시",
            "evidence_url": "https://www.dongsuh.com/kor/index.asp",
            "evidence_owner": "동서", "evidence_type": "official_group_business_page",
        },
        {
            "company": "남양유업", "ticker": "003920", "market": "KOSPI",
            "company_description": "프렌치카페 카페믹스를 생산·판매하는 국내 상장 식품기업",
            "relation_tier": "direct", "reason": "남양유업 공식 브랜드 페이지가 프렌치카페 카페믹스 제품군을 직접 소개",
            "evidence_url": "https://company.namyangi.com/ko/brand/signature/5",
            "evidence_owner": "남양유업", "evidence_type": "official_product_page",
        },
        {
            "company": "Nestle", "ticker": "NESN", "market": "SIX",
            "company_description": "NESCAFE 인스턴트 커피와 3-in-1 믹스 제품을 판매하는 스위스 상장 식품기업",
            "relation_tier": "direct", "reason": "Nestle 공식 NESCAFE 브랜드 페이지가 커피 믹스와 3-in-1 제품을 명시",
            "evidence_url": "https://www.nestle.com/brands/coffee/nescafe",
            "evidence_owner": "Nestle", "evidence_type": "official_brand_page",
        },
        {
            "company": "Ajinomoto", "ticker": "2802", "market": "TSE",
            "company_description": "Blendy 인스턴트·스틱 커피를 보유한 일본 상장 식품기업",
            "relation_tier": "direct", "reason": "Ajinomoto AGF 공식 제품 페이지가 Blendy 스틱·인스턴트 커피 제품군을 직접 소개",
            "evidence_url": "https://agf.ajinomoto.co.jp/product/brands/blendy",
            "evidence_owner": "Ajinomoto AGF", "evidence_type": "official_product_portfolio",
        },
        {
            "company": "JDE Peet's", "ticker": "JDEP", "market": "EURONEXT_AMSTERDAM",
            "company_description": "Jacobs·Moccona·OldTown 등 인스턴트 커피 브랜드를 보유한 상장 커피기업",
            "relation_tier": "direct", "reason": "JDE Peet's 공식 브랜드 페이지가 Jacobs·Moccona·OldTown 등 커피 브랜드 포트폴리오를 공개",
            "evidence_url": "https://www.jdepeets.com/brands",
            "evidence_owner": "JDE Peet's", "evidence_type": "official_brand_portfolio",
        },
        {
            "company": "Tata Consumer Products", "ticker": "TATACONSUM", "market": "NSE",
            "company_description": "Tata Coffee Grand 인스턴트·프리믹스 커피를 판매하는 인도 상장 소비재기업",
            "relation_tier": "direct", "reason": "Tata Consumer Products 공식 페이지가 Tata Coffee Grand의 인스턴트 커피 사업과 제품을 명시",
            "evidence_url": "https://www.tataconsumer.com/brands/coffee/tata-coffee-grand",
            "evidence_owner": "Tata Consumer Products", "evidence_type": "official_brand_page",
        },
    ),
    "용인반도체클러스터": (
        {
            "company": "SK하이닉스", "ticker": "000660", "market": "KOSPI",
            "company_description": "용인 반도체 클러스터에 대규모 팹 투자를 진행하는 국내 상장 메모리기업",
            "relation_tier": "direct", "reason": "SK하이닉스 공식 자료가 용인 클러스터 첫 팹 투자 계획을 직접 명시",
            "evidence_url": "https://news.skhynix.co.kr/fact-04/",
            "evidence_owner": "SK hynix", "evidence_type": "official_investment_release",
        },
        {
            "company": "삼성전자", "ticker": "005930", "market": "KOSPI",
            "company_description": "용인 반도체 클러스터를 연구·생산 거점으로 추진하는 국내 상장 반도체기업",
            "relation_tier": "direct", "reason": "Samsung Semiconductor 공식 연혁이 용인 반도체 클러스터 구축 계획을 명시",
            "evidence_url": "https://semiconductor.samsung.com/kr/about-us/our-story/",
            "evidence_owner": "Samsung Semiconductor", "evidence_type": "official_corporate_history",
        },
        {
            "company": "가온전선", "ticker": "000500", "market": "KOSPI",
            "company_description": "반도체 클러스터 전력 인프라용 케이블을 공급하는 국내 상장 전선기업",
            "relation_tier": "value_chain", "reason": "LS전선 공식 보도가 가온전선의 SK하이닉스 용인 클러스터 배전 케이블 공급을 명시",
            "evidence_url": "https://www.lscns.co.kr/kr/pr/news_view.asp?brd_id=news1&idx=120188&lang_cd=kr&mode=MOD",
            "evidence_owner": "LS Cable & System", "evidence_type": "official_supply_release",
        },
        {
            "company": "LS", "ticker": "006260", "market": "KOSPI",
            "company_description": "용인 반도체 클러스터 전력 인프라 공급 계열사를 둔 국내 상장 지주기업",
            "relation_tier": "value_chain", "reason": "LS전선 공식 보도가 용인 클러스터에 초고압 케이블을 공급한다고 명시",
            "evidence_url": "https://www.lscns.co.kr/kr/pr/news_view.asp?brd_id=news1&idx=120188&lang_cd=kr&mode=MOD",
            "evidence_owner": "LS Cable & System", "evidence_type": "official_supply_release",
        },
        {
            "company": "SG", "ticker": "255220", "market": "KOSDAQ",
            "company_description": "용인 반도체 클러스터 건설 현장에 포장 소재를 공급하는 국내 상장 아스콘기업",
            "relation_tier": "value_chain", "reason": "보도 자료가 SG의 SK하이닉스 용인 클러스터 아스콘 단독 공급 사실을 명시",
            "evidence_url": "https://biz.chosun.com/stock/stock_general/2026/07/08/KPI33IKYMRAP7EZTEPDBDMPEOM/",
            "evidence_owner": "ChosunBiz", "evidence_type": "reported_supply_disclosure",
        },
        {
            "company": "현대건설", "ticker": "000720", "market": "KOSPI",
            "company_description": "용인 첨단시스템반도체 국가산단 조성공사 입찰 참여가 보도된 국내 상장 건설기업",
            "relation_tier": "industry_watch", "reason": "산단 조성공사 발주 보도가 현대건설을 1공구 입찰 참여 후보로 명시",
            "evidence_url": "https://biz.chosun.com/real_estate/real_estate_general/2025/12/18/RC7MFPVPYBAAPN62N54KSYQ3QQ/",
            "evidence_owner": "ChosunBiz", "evidence_type": "reported_tender_participation",
        },
    ),
    "아시안 게임": (
        {
            "company": "Toyota Motor", "ticker": "7203", "market": "TSE",
            "company_description": "2026 아이치·나고야 아시안게임의 모빌리티 분야 공식 후원사인 일본 상장 자동차기업",
            "relation_tier": "direct", "reason": "대회 공식 파트너 명단이 Toyota를 Tier 1 모빌리티 후원사로 명시",
            "evidence_url": "https://www.aichi-nagoya2026.org/en/assets/file/donations/partner-list_45.pdf",
            "evidence_owner": "Aichi-Nagoya 2026 Organising Committee", "evidence_type": "official_sponsor_list",
        },
        {
            "company": "Chubu Electric Power", "ticker": "9502", "market": "TSE",
            "company_description": "2026 아이치·나고야 아시안게임의 유틸리티 분야 공식 후원사인 일본 상장 전력기업",
            "relation_tier": "direct", "reason": "대회 공식 파트너 명단이 Chubu Electric Power를 Tier 1 유틸리티 후원사로 명시",
            "evidence_url": "https://www.aichi-nagoya2026.org/en/assets/file/donations/partner-list_45.pdf",
            "evidence_owner": "Aichi-Nagoya 2026 Organising Committee", "evidence_type": "official_sponsor_list",
        },
        {
            "company": "AEON", "ticker": "8267", "market": "TSE",
            "company_description": "2026 아이치·나고야 아시안게임의 유통·리테일 분야 공식 후원사인 일본 상장 유통기업",
            "relation_tier": "direct", "reason": "대회 공식 파트너 명단이 AEON을 Tier 1 유통·리테일 후원사로 명시",
            "evidence_url": "https://www.aichi-nagoya2026.org/en/assets/file/donations/partner-list_45.pdf",
            "evidence_owner": "Aichi-Nagoya 2026 Organising Committee", "evidence_type": "official_sponsor_list",
        },
        {
            "company": "NTT", "ticker": "9432", "market": "TSE",
            "company_description": "2026 아이치·나고야 아시안게임의 통신 서비스 공식 파트너인 일본 상장 통신기업",
            "relation_tier": "direct", "reason": "대회 공식 파트너 명단이 NTT를 통신 서비스 공식 파트너로 명시",
            "evidence_url": "https://www.aichi-nagoya2026.org/en/assets/file/donations/partner-list_20.pdf",
            "evidence_owner": "Aichi-Nagoya 2026 Organising Committee", "evidence_type": "official_sponsor_list",
        },
        {
            "company": "YONEX", "ticker": "7906", "market": "TSE",
            "company_description": "2026 아이치·나고야 아시안게임 배드민턴·테니스 장비 공식 공급사인 일본 상장기업",
            "relation_tier": "direct", "reason": "대회 공식 파트너 명단이 YONEX를 배드민턴·테니스 장비 공식 공급사로 명시",
            "evidence_url": "https://www.aichi-nagoya2026.org/en/assets/file/donations/partner-list_20.pdf",
            "evidence_owner": "Aichi-Nagoya 2026 Organising Committee", "evidence_type": "official_sponsor_list",
        },
        {
            "company": "Brother Industries", "ticker": "6448", "market": "TSE",
            "company_description": "2026 아이치·나고야 아시안게임 현장 냉방 장비 공식 공급사인 일본 상장기업",
            "relation_tier": "direct", "reason": "대회 공식 파트너 명단이 Brother Industries를 현장 장비 공식 공급사로 명시",
            "evidence_url": "https://www.aichi-nagoya2026.org/en/assets/file/donations/partner-list_20.pdf",
            "evidence_owner": "Aichi-Nagoya 2026 Organising Committee", "evidence_type": "official_sponsor_list",
        },
    ),
    "광 통신": (
        {
            "company": "대한광통신", "ticker": "010170", "market": "KOSDAQ",
            "company_description": "광섬유와 광케이블을 생산하는 국내 상장 광통신 소재·케이블 기업",
            "relation_tier": "direct", "reason": "광섬유와 광케이블을 함께 생산하는 광통신 직접 사업자",
            "evidence_url": "https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?MenuYn=Y&NewMenuID=Y&ReportGB=B&gicode=A010170&pGB=1&stkGb=701",
            "evidence_owner": "FnGuide Company Guide", "evidence_type": "listed_company_business_profile",
        },
        {
            "company": "Corning", "ticker": "GLW", "market": "NYSE",
            "company_description": "광섬유·광케이블·접속 솔루션을 공급하는 미국 상장 소재기업",
            "relation_tier": "direct", "reason": "공식 광통신 제품군에 광섬유와 광케이블을 명시",
            "evidence_url": "https://www.corning.com/optical-communications/worldwide/en/home/products.html",
            "evidence_owner": "Corning", "evidence_type": "official_product_page",
        },
        {
            "company": "LS", "ticker": "006260", "market": "KOSPI",
            "company_description": "통신·전력 케이블 계열사를 보유한 국내 상장 지주회사",
            "relation_tier": "ownership", "reason": "LS 공식 IR이 계열사 LS전선의 주력제품을 통신·전력으로 공시",
            "evidence_url": "https://www.lsholdings.com/en/ir/investment",
            "evidence_owner": "LS Corp.", "evidence_type": "official_group_ir",
        },
        {
            "company": "Nokia", "ticker": "NOK", "market": "NYSE",
            "company_description": "광전송 플랫폼·광엔진·데이터센터 연결 솔루션을 공급하는 핀란드 상장 통신장비기업",
            "relation_tier": "direct", "reason": "Nokia 공식 광네트워크 페이지가 광전송 플랫폼·광엔진·데이터센터 광연결 제품군을 명시",
            "evidence_url": "https://www.nokia.com/optical-networks/",
            "evidence_owner": "Nokia", "evidence_type": "official_optical_network_portfolio",
        },
        {
            "company": "Prysmian", "ticker": "PRY", "market": "BIT",
            "company_description": "단일·다중모드 광섬유와 광케이블을 생산하는 이탈리아 상장 케이블기업",
            "relation_tier": "direct", "reason": "Prysmian 공식 제품 페이지가 데이터센터·기업망용 광섬유와 광케이블 제품을 직접 소개",
            "evidence_url": "https://na.prysmian.com/markets/digital-solutions/optical-fiber",
            "evidence_owner": "Prysmian", "evidence_type": "official_optical_fiber_portfolio",
        },
        {
            "company": "Ciena", "ticker": "CIEN", "market": "NYSE",
            "company_description": "패킷광 전송 플랫폼과 코히어런트 광통신 장비를 공급하는 미국 상장 네트워크기업",
            "relation_tier": "direct", "reason": "Ciena 공식 제품군이 패킷광 플랫폼·코히어런트 광시스템·광인터커넥트를 명시",
            "evidence_url": "https://www.ciena.com/products",
            "evidence_owner": "Ciena", "evidence_type": "official_optical_network_product_portfolio",
        },
    ),
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
        {
            "company": "대상", "ticker": "001680", "market": "KRX",
            "company_description": "청정원·종가 브랜드로 삼계탕 등 한식 간편식을 개발하는 종합식품기업",
            "relation_tier": "direct", "reason": "공식 사업보고서의 편의식 개발 실적에 종가집 삼계탕을 명시",
            "evidence_url": "https://www.daesang.com/common/popup/download.jsp?fileName=66%EA%B8%B0+%EC%82%AC%EC%97%85%EB%B3%B4%EA%B3%A0%EC%84%9C.pdf&realName=1585556877635.pdf",
            "evidence_owner": "대상", "evidence_type": "official_business_report",
        },
        {
            "company": "풀무원", "ticker": "017810", "market": "KRX",
            "company_description": "반듯한식·올가 브랜드로 삼계탕과 여름 보양 간편식을 판매하는 식품기업",
            "relation_tier": "direct", "reason": "공식 뉴스룸이 산삼배양근 삼계탕 제품과 복날 판매행사를 직접 소개",
            "evidence_url": "https://news.pulmuone.co.kr/pulmuone/newsroom/viewNewsroom.do?id=3884",
            "evidence_owner": "풀무원", "evidence_type": "official_product_release",
        },
        {
            "company": "신세계푸드", "ticker": "031440", "market": "KRX",
            "company_description": "올반 브랜드의 삼계탕 간편식을 제조·유통하는 종합식품기업",
            "relation_tier": "direct", "reason": "공식 제품 페이지가 올반 삼계탕의 제품 사양과 원재료를 공개",
            "evidence_url": "https://www.shinsegaefood.com/olbaan_master/menu/menu_view.sf?category1Seq=1&goodId=155",
            "evidence_owner": "신세계푸드", "evidence_type": "official_product_page",
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
        {
            "company": "Canon", "ticker": "7751", "market": "TSE",
            "company_description": "불꽃 촬영용 카메라와 촬영 모드를 제공하는 일본 상장 광학기업",
            "relation_tier": "adjacent", "reason": "Canon 공식 카메라 설명서가 불꽃 촬영 전용 장면 모드와 삼각대 사용법을 명시",
            "evidence_url": "https://files.canon-europe.com/files/soft39129/Manual/1000HS_CUG_EN.pdf",
            "evidence_owner": "Canon", "evidence_type": "official_fireworks_camera_guide",
        },
        {
            "company": "Nikon", "ticker": "7731", "market": "TSE",
            "company_description": "불꽃 촬영용 카메라·렌즈와 촬영 교육 콘텐츠를 제공하는 일본 상장 광학기업",
            "relation_tier": "adjacent", "reason": "Nikon 공식 가이드가 DSLR·Z 시리즈·COOLPIX를 이용한 불꽃 촬영법을 직접 안내",
            "evidence_url": "https://www.nikonusa.com/learn-and-explore/c/tips-and-techniques/taking-pictures-of-fireworks",
            "evidence_owner": "Nikon", "evidence_type": "official_fireworks_photography_guide",
        },
        {
            "company": "Sony Group", "ticker": "6758", "market": "TSE",
            "company_description": "불꽃 촬영 기능과 카메라·렌즈 제품군을 제공하는 일본 상장 전자기업",
            "relation_tier": "adjacent", "reason": "Sony 공식 가이드가 불꽃 촬영용 장비·렌즈·설정과 촬영 절차를 직접 설명",
            "evidence_url": "https://www.sony.com/electronics/support/articles/00223375",
            "evidence_owner": "Sony", "evidence_type": "official_fireworks_photography_guide",
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
        {
            "company": "네오위즈", "ticker": "095660", "market": "KOSDAQ",
            "company_description": "지스타 공식 참가사 목록에 등재된 국내 상장 게임기업",
            "relation_tier": "direct", "reason": "지스타 공식 BTC 참가사 안내가 네오위즈를 참가사로 명시",
            "evidence_url": "https://www.gstar.or.kr/gstar/gstar_booth_info.do?page=1",
            "evidence_owner": "G-STAR", "evidence_type": "official_exhibitor_list",
        },
        {
            "company": "웹젠", "ticker": "069080", "market": "KOSDAQ",
            "company_description": "지스타 공식 참가사 목록에 등재된 국내 상장 게임기업",
            "relation_tier": "direct", "reason": "지스타 공식 BTC 참가사 안내가 웹젠을 참가사로 명시",
            "evidence_url": "https://www.gstar.or.kr/gstar/gstar_booth_info.do?page=1",
            "evidence_owner": "G-STAR", "evidence_type": "official_exhibitor_list",
        },
        {
            "company": "카카오게임즈", "ticker": "293490", "market": "KOSDAQ",
            "company_description": "지스타 참가사 페이지에 등록된 국내 상장 게임 퍼블리셔",
            "relation_tier": "direct", "reason": "지스타 공식 참가사 상세 페이지가 카카오게임즈의 참가사 정보를 제공",
            "evidence_url": "https://www.gstar.or.kr/gstar/popup/gstar_mini_info.do?gft_idx=888",
            "evidence_owner": "G-STAR", "evidence_type": "official_exhibitor_profile",
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
            "evidence_url": "https://www.ntv.co.jp/movie/index.html",
            "evidence_owner": "Nippon Television", "evidence_type": "official_movie_catalog",
        },
        {
            "company": "Takara Tomy", "ticker": "7867", "market": "TSE",
            "company_description": "명탐정 코난 공식 트레이딩 카드게임을 기획·판매하는 일본 완구기업",
            "relation_tier": "value_chain", "reason": "공식 코난 카드게임 사이트에서 상품·이벤트를 지속 운영",
            "evidence_url": "https://www.takaratomy.co.jp/products/conan-cardgame/",
            "evidence_owner": "Takara Tomy", "evidence_type": "official_ip_product_page",
        },
        {
            "company": "McDonald's Holdings Company Japan", "ticker": "2702", "market": "TSE",
            "company_description": "일본 맥도날드를 운영하며 명탐정 코난 IP 캠페인을 전개한 상장 외식기업",
            "relation_tier": "brand_collaboration", "reason": "코난 세계관을 활용한 치킨 타츠타 상품과 오리지널 애니메이션 캠페인을 공식 진행",
            "evidence_url": "https://www.mcdonalds.co.jp/company/news/2025/0410a/",
            "evidence_owner": "McDonald's Japan", "evidence_type": "official_collaboration_release",
        },
        {
            "company": "Bandai Namco Holdings", "ticker": "7832", "market": "TSE",
            "company_description": "명탐정 코난 IP를 게임 콘텐츠로 상품화한 일본 엔터테인먼트기업",
            "relation_tier": "adjacent", "reason": "공식 게임 자료에서 명탐정 코난 콘텐츠 수록과 IP 활용을 확인",
            "evidence_url": "https://www.bandainamcoent.co.jp/corporate/press/pdf/53-034.pdf",
            "evidence_owner": "Bandai Namco Entertainment", "evidence_type": "official_ip_product_release",
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
        {
            "company": "UBTECH Robotics", "ticker": "9880", "market": "HKEX",
            "company_description": "Walker 시리즈 산업용 휴머노이드 로봇을 개발하는 홍콩 상장 로봇기업",
            "relation_tier": "direct", "reason": "UBTECH 공식 제품 페이지가 Walker 휴머노이드 로봇과 산업 적용을 직접 소개",
            "evidence_url": "https://www.ubtrobot.com/en/humanoid/products/walker-s2",
            "evidence_owner": "UBTECH Robotics", "evidence_type": "official_humanoid_product_page",
        },
        {
            "company": "XPeng", "ticker": "9868", "market": "HKEX",
            "company_description": "IRON 휴머노이드 로봇을 개발하는 홍콩 상장 전기차·AI기업",
            "relation_tier": "direct", "reason": "XPeng 공식 기술 행사 자료가 자사 IRON 휴머노이드 로봇을 직접 공개",
            "evidence_url": "https://www.xpeng.com/news/019301d2135392fa562d8a0282200016",
            "evidence_owner": "XPeng", "evidence_type": "official_humanoid_release",
        },
        {
            "company": "레인보우로보틱스", "ticker": "277810", "market": "KOSDAQ",
            "company_description": "이족보행 휴머노이드 기술과 협동로봇을 개발하는 국내 상장 로봇기업",
            "relation_tier": "direct", "reason": "레인보우로보틱스 공식 기업 소개가 휴머노이드 로봇 HUBO 개발 이력을 명시",
            "evidence_url": "https://kind.krx.co.kr/external/2023/11/14/002431/20231114005368/11013.htm",
            "evidence_owner": "KRX KIND", "evidence_type": "official_listed_company_filing",
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
    "롤 패치 노트": (
        {
            "company": "Tencent Holdings", "ticker": "0700", "market": "HKEX",
            "company_description": "League of Legends 개발사 Riot Games를 자회사로 보유한 글로벌 인터넷·게임기업",
            "relation_tier": "ownership", "reason": "Tencent 공식 연차보고서가 Riot Games의 자회사 편입과 온라인게임 사업을 명시",
            "evidence_url": "https://static.www.tencent.com/storage/uploads/2019/11/09/16268c0ec6dbd0144fee788583389fd8.pdf",
            "evidence_owner": "Tencent Holdings", "evidence_type": "official_annual_report",
        },
        {
            "company": "Kia", "ticker": "000270", "market": "KRX",
            "company_description": "League of Legends e스포츠 생태계의 장기 브랜드 파트너인 자동차기업",
            "relation_tier": "brand_collaboration", "reason": "Riot Games가 Kia와의 LoL e스포츠 파트너십 연장·확대를 공식 확인",
            "evidence_url": "https://www.riotgames.com/en/news/lol-esports-strategy-adjustments-2024",
            "evidence_owner": "Riot Games", "evidence_type": "official_partner_release",
        },
        {
            "company": "Mastercard", "ticker": "MA", "market": "NYSE",
            "company_description": "League of Legends e스포츠의 글로벌 결제 브랜드 파트너",
            "relation_tier": "brand_collaboration", "reason": "Riot Games가 Mastercard와의 LoL e스포츠 파트너십 연장·확대를 공식 확인",
            "evidence_url": "https://www.riotgames.com/en/news/lol-esports-strategy-adjustments-2024",
            "evidence_owner": "Riot Games", "evidence_type": "official_partner_release",
        },
        {
            "company": "Mercedes-Benz Group", "ticker": "MBG", "market": "XETRA",
            "company_description": "League of Legends e스포츠의 글로벌 모빌리티 브랜드 파트너",
            "relation_tier": "brand_collaboration", "reason": "Riot Games가 Mercedes-Benz와의 LoL e스포츠 파트너십 연장·확대를 공식 확인",
            "evidence_url": "https://www.riotgames.com/en/news/lol-esports-strategy-adjustments-2024",
            "evidence_owner": "Riot Games", "evidence_type": "official_partner_release",
        },
        {
            "company": "HP", "ticker": "HPQ", "market": "NYSE",
            "company_description": "OMEN·HyperX 브랜드로 LoL e스포츠 생태계에 참여한 PC·게이밍기기 기업",
            "relation_tier": "brand_collaboration", "reason": "Riot Games가 HP의 OMEN·HyperX를 LoL e스포츠 신규 파트너로 공식 명시",
            "evidence_url": "https://www.riotgames.com/en/news/lol-esports-strategy-adjustments-2024",
            "evidence_owner": "Riot Games", "evidence_type": "official_partner_release",
        },
        {
            "company": "Cisco Systems", "ticker": "CSCO", "market": "NASDAQ",
            "company_description": "League of Legends 글로벌 e스포츠 경기망과 서버 인프라를 지원한 네트워크기업",
            "relation_tier": "value_chain", "reason": "Cisco 공식 발표가 LoL e스포츠의 기업용 네트워크 파트너 및 경기 서버 인프라 역할을 명시",
            "evidence_url": "https://newsroom.cisco.com/c/r/newsroom/en/us/a/y2020/m08/ping-beware-riot-games-partners-with-cisco-to-power-lol-esports.html",
            "evidence_owner": "Cisco", "evidence_type": "official_infrastructure_partnership",
        },
    ),
}

INDUSTRY_NODES = {
    "천체관측장비": "천문관측/광학기기/천체촬영",
    "커피믹스": "인스턴트커피/식품제조·유통",
    "용인반도체클러스터": "반도체팹/산업단지/전력인프라",
    "아시안 게임": "국제스포츠행사/공식후원/현장인프라",
    "롤 패치 노트": "게임IP/라이브서비스/글로벌e스포츠",
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
    "광 통신": "광섬유/광케이블/통신인프라",
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
        rows.append(with_company_role({
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
        }))
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


COMPANY_CACHE_ALIASES = {
    "개기일식": "천체관측장비",
    "유성우 시간": "천체관측장비",
    "페르세우스 유성우": "천체관측장비",
    "삼계탕": "말복",
}


def _company_cache_key(topic: str) -> str | None:
    direct = _cache_key(topic, VERIFIED_COMPANIES)
    if direct:
        return direct
    normalized = _key(topic)
    return next(
        (registry for alias, registry in COMPANY_CACHE_ALIASES.items() if _key(alias) == normalized),
        None,
    )


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


def apply_frontend_enrichment_cache(intelligence: dict, *, verified_at: str) -> dict:
    """Attach reviewed term-specific enrichment without affecting selection.

    The input ranking, lane, category and product-fit fields are treated as
    immutable. Cache membership can only complete keyword/company presentation
    fields for a trend that the deterministic X+Google engine already emitted.
    """

    for item in intelligence.get("unified_ranking", []):
        topic = str(
            item.get("display_name") or item.get("topic") or item.get("event_key") or ""
        ).strip()
        keyword_key = _cache_key(topic, KEYWORDS)
        company_key = _company_cache_key(topic)
        if keyword_key and (
            item.get("keyword_status") != "ready"
            or len(item.get("related_keywords") or []) != FINAL_KEYWORD_COUNT
        ):
            # Keep related queries measured by the collection pipeline.  The
            # reviewed cache only fills the remaining presentation slots and
            # must never erase stronger observed provenance.
            related_keywords = []
            seen_keywords: set[str] = set()
            for row in item.get("related_keywords") or []:
                if not isinstance(row, dict):
                    continue
                text = str(row.get("text") or "").strip()
                key = _key(text)
                if not text or not key or key in seen_keywords:
                    continue
                preserved = dict(row)
                preserved["affects_score"] = False
                related_keywords.append(preserved)
                seen_keywords.add(key)
                if len(related_keywords) == FINAL_KEYWORD_COUNT:
                    break
            for text in KEYWORDS[keyword_key]:
                key = _key(text)
                if not key or key in seen_keywords:
                    continue
                related_keywords.append({
                    "text": text,
                    "source": ["reviewed_ontology"],
                    "observed_hours": 0,
                    "status": "approved_ontology_related_term",
                    "role": "reviewed_related_expression",
                    "role_status": "reviewed_evidence",
                    "evidence_urls": [],
                    "affects_score": False,
                })
                seen_keywords.add(key)
                if len(related_keywords) == FINAL_KEYWORD_COUNT:
                    break
            item["related_keywords"] = related_keywords
            item["keyword_status"] = (
                "ready"
                if len(item["related_keywords"]) == FINAL_KEYWORD_COUNT
                else "enrichment_pending"
            )
        # Issue-lane events may still receive contextual keywords, but must
        # never expose investable company cards.  Reviewed enrichment is a
        # presentation cache, not permission to cross the editorial lane gate.
        if item.get("lane") == "issue":
            item["company_candidates"] = []
            item["companies"] = []
            item["company_eligible"] = False
            item["company_card_status"] = "not_applicable"
            item["company_status"] = "not_applicable"
            resolution = dict(item.get("company_resolution") or {})
            resolution.update({
                "status": "excluded_by_context",
                "publish_status": "not_published",
                "candidate_count": 0,
                "published_count": 0,
                "reason": "issue_lane_company_cards_are_disabled",
                "score_independent": True,
            })
            item["company_resolution"] = resolution
            continue
        complete_company_codes = {
            str(company.get("stock_code") or "").strip()
            for company in item.get("companies") or []
            if isinstance(company, dict)
            and str(company.get("company") or "").strip()
            and str(company.get("stock_code") or "").strip()
            and str(company.get("market") or "").strip()
            and str(company.get("company_description") or "").strip()
            and str(company.get("relationship_reason") or "").strip()
            and company.get("ontology_complete") is True
            and any(
                str(source.get("url") or "").strip()
                for source in company.get("evidence_sources") or []
                if isinstance(source, dict)
            )
        }
        if company_key and len(complete_company_codes) < MINIMUM_VERIFIED_COMPANY_COUNT:
            cached_companies = _verified_company_rows(company_key, verified_at=verified_at)
            companies = []
            for row in cached_companies:
                relation_tier = row["relation_tier"]
                display_type = {
                    "direct": "직접 관계",
                    "value_chain": "가치사슬",
                    "industry_watch": "산업 관찰",
                }[relation_tier]
                evidence_url = row["evidence_url"]
                industry = row["industry_node"]
                companies.append({
                    "company": row["company"],
                    "stock_code": row["ticker"],
                    "ticker": row["ticker"],
                    "market": row["market"],
                    "relation_type": row["relation_type"],
                    "strength": relation_tier,
                    "reason": row["reason"],
                    "relationship_reason": row["reason"],
                    "company_summary": row["company_description"],
                    "company_description": row["company_description"],
                    "business_features": [industry],
                    "evidence_kind": row["evidence_type"],
                    "evidence_url": evidence_url,
                    "evidence_sources": [{
                        "url": evidence_url,
                        "title": row["evidence_owner"],
                        "evidence_type": row["evidence_type"],
                        "published_at": None,
                        "review_status": "approved",
                    }],
                    "company_role": industry,
                    "company_role_category": row["company_role_category"],
                    "company_role_label": row["company_role_label"],
                    "relation_tier": relation_tier,
                    "ontology_relation_tier": row["ontology_relation_tier"],
                    "relation_tier_label": display_type,
                    "relation_horizon": "documented_relationship",
                    "exposure_status": "not_quantified",
                    "verification_status": "ontology_evidence",
                    "opportunity_status": "evidence_backed_candidate",
                    "relation_display_type": display_type,
                    "team_review_status": "ontology_reviewed",
                    "team_review_label": "근거 캐시 검수됨",
                    "investment_warning": "관계 분류는 주가 상승 예측이나 매수 추천이 아님",
                    "matched_ontology_term": company_key,
                    "matched_ontology_node": company_key,
                    "ontology_lookup_match_type": "exact_enrichment_cache",
                    "ontology_source": "term_specific_enrichment_cache",
                    "ontology_path": [
                        {
                            "from": topic,
                            "to": industry,
                            "edge_type": "classified_as",
                            "evidence_urls": [evidence_url],
                            "evidence_type": row["evidence_type"],
                            "as_of": verified_at,
                            "review_status": "approved",
                        },
                        {
                            "from": industry,
                            "to": row["company"],
                            "edge_type": row["relation_type"],
                            "evidence_urls": [evidence_url],
                            "evidence_type": row["evidence_type"],
                            "as_of": verified_at,
                            "review_status": "approved",
                        },
                    ],
                    "ontology_complete": True,
                    "ontology_status": "complete",
                })
            if len({row["stock_code"] for row in companies}) >= MINIMUM_VERIFIED_COMPANY_COUNT:
                item["company_candidates"] = companies
                item["companies"] = companies
                item["company_eligible"] = True
                item["company_card_status"] = "ready"
                item["company_status"] = "ready"
                item["company_resolution"] = {
                    "status": "published",
                    "publish_status": "published",
                    "candidate_count": len(companies),
                    "ontology_complete_count": len(companies),
                    "published_count": len(companies),
                    "minimum_gold_companies": MINIMUM_VERIFIED_COMPANY_COUNT,
                    "score_independent_of_company_count": True,
                    "direct_count": sum(row["relation_tier"] == "direct" for row in companies),
                    "role_coverage": sorted({row["company_role"] for row in companies}),
                    "tier_counts": {
                        tier: sum(row["relation_tier"] == tier for row in companies)
                        for tier in ("direct", "value_chain", "industry_watch")
                    },
                    "category_count": len({row["company_role_category"] for row in companies}),
                    "candidate_category_count": len({row["company_role_category"] for row in companies}),
                    "role_category_counts": {
                        category: sum(row["company_role_category"] == category for row in companies)
                        for category in sorted({row["company_role_category"] for row in companies})
                    },
                    "ontology_diagnostics": {
                        "source": "term_specific_enrichment_cache",
                        "padding_forbidden": True,
                        "ranking_effect": "none",
                    },
                    "reason": "용어별 근거 URL과 상장 식별자가 완비된 6개 이상 기업을 공개",
                }
    return intelligence


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
        company_cache_key = item.get("daily_editorial_enrichment_key") or _company_cache_key(topic)
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
            # Every unresolved expression remains an enrichment lead only.
            # Frontend-ready arrays are fail-closed regardless of how the
            # automatic candidate was selected.
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
        "publication_ready": len(trends) >= TARGET_COMPLETE_TREND_COUNT,
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
