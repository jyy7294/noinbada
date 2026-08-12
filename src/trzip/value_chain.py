from __future__ import annotations

from copy import deepcopy


def _candidate(company: str, stock_code: str | None, role: str, url: str, reason: str) -> dict:
    return {
        "company": company, "stock_code": stock_code, "company_role": role,
        "relation_type": "industry_structure_candidate", "strength": "sector_watch",
        "relation_tier": "adjacent", "relation_tier_label": "산업 후보",
        "verification_status": "industry_structure_only",
        "relation_horizon": "확장 기회 관찰", "opportunity_status": "observable_opportunity",
        "exposure_status": "watch_candidate", "reason": reason,
        "evidence_kind": "industry_structure_reference", "evidence_url": url,
        "investment_warning": "업종 대표기업 후보이며 해당 트렌드의 실제 계약·수혜·주가 상승을 의미하지 않음",
    }


TEMPLATES = {
    "food": [
        ("원재료·식품소재", "upstream", _candidate("CJ제일제당", "097950", "원재료·부품", "https://www.cj.co.kr/", "농수산 원료·식품소재·가공식품 가치사슬의 업종 후보")),
        ("제조·브랜드·상품", "core", _candidate("농심", "004370", "제조", "https://www.nongshim.com/", "음식료품 제조·브랜드 운영 단계의 업종 후보")),
        ("유통·외식·판매채널", "downstream", _candidate("BGF리테일", "282330", "유통·리테일", "https://www.bgfretail.com/", "편의점·오프라인 판매와 소비 접점의 업종 후보")),
    ],
    "music": [
        ("IP·기획·제작", "core", _candidate("하이브", "352820", "브랜드·IP", "https://hybecorp.com/", "음악 IP·아티스트 기획·콘텐츠 제작 업종 후보")),
        ("플랫폼·유통·미디어", "downstream", _candidate("카카오", "035720", "플랫폼·채널", "https://www.kakaocorp.com/", "디지털 콘텐츠 플랫폼·유통 접점의 업종 후보")),
        ("공연·티켓·팬덤소비", "consumer", _candidate("예스24", "053280", "현장 소비", "https://www.yes24.com/", "공연 티켓·음반·팬덤 소비 접점의 업종 후보")),
    ],
    "gaming": [
        ("게임·IP·운영", "core", _candidate("크래프톤", "259960", "브랜드·IP", "https://www.krafton.com/", "게임 개발·IP·라이브서비스 운영 업종 후보")),
        ("방송·커뮤니티·플랫폼", "downstream", _candidate("SOOP", "067160", "플랫폼·채널", "https://corp.sooplive.co.kr/", "게임 방송·스트리밍·커뮤니티 접점의 업종 후보")),
        ("기기·통신·인프라", "upstream", _candidate("삼성전자", "005930", "인프라·서비스", "https://www.samsung.com/sec/", "게임 이용 기기·디스플레이·전자 인프라 업종 후보")),
    ],
    "sports": [
        ("스포츠웨어·용품", "core", _candidate("휠라홀딩스", "081660", "굿즈·패션", "https://www.filaholdings.com/", "스포츠 의류·신발·용품 소비의 업종 후보")),
        ("미디어·중계·플랫폼", "downstream", _candidate("CJ ENM", "035760", "플랫폼·채널", "https://www.cjenm.com/", "스포츠 콘텐츠·미디어 유통 접점의 업종 후보")),
        ("시설·현장·주변소비", "consumer", _candidate("GS리테일", "007070", "현장 소비", "https://www.gsretail.com/", "관람·참여 전후 식음료와 편의 소비의 업종 후보")),
    ],
    "screen": [
        ("콘텐츠·IP·제작", "core", _candidate("CJ ENM", "035760", "브랜드·IP", "https://www.cjenm.com/", "영상 콘텐츠 기획·제작·IP 단계의 업종 후보")),
        ("배급·플랫폼·채널", "downstream", _candidate("NAVER", "035420", "플랫폼·채널", "https://www.navercorp.com/", "콘텐츠 검색·커뮤니티·디지털 유통 접점의 업종 후보")),
        ("기기·패키지·소비", "consumer", _candidate("삼성전자", "005930", "인프라·서비스", "https://www.samsung.com/sec/", "TV·디스플레이·가정용 콘텐츠 소비 기기의 업종 후보")),
    ],
    "fashion": [
        ("브랜드·디자인·IP", "core", _candidate("F&F", "383220", "브랜드·IP", "https://www.fnf.co.kr/", "패션 브랜드·라이선스·상품기획 업종 후보")),
        ("소재·OEM·제조", "upstream", _candidate("영원무역", "111770", "제조", "https://www.youngone.co.kr/", "의류 OEM·생산 가치사슬 업종 후보")),
        ("리테일·이커머스", "downstream", _candidate("신세계", "004170", "유통·리테일", "https://www.shinsegae.com/", "패션·뷰티 오프라인 유통 접점의 업종 후보")),
    ],
    "technology": [
        ("부품·기기·인프라", "upstream", _candidate("삼성전자", "005930", "원재료·부품", "https://www.samsung.com/sec/", "전자부품·기기·컴퓨팅 인프라 업종 후보")),
        ("서비스·플랫폼·운영", "core", _candidate("NAVER", "035420", "플랫폼·채널", "https://www.navercorp.com/", "AI·소프트웨어·디지털 서비스 운영 업종 후보")),
        ("유통·최종사용", "downstream", _candidate("롯데하이마트", "071840", "유통·리테일", "https://company.e-himart.co.kr/", "전자제품 판매·최종 소비 접점의 업종 후보")),
    ],
    "place": [
        ("공간·시설·운영", "core", _candidate("신세계", "004170", "공간·운영", "https://www.shinsegae.com/", "상업공간·체험공간 운영 업종 후보")),
        ("브랜드·팝업·콘텐츠", "consumer", _candidate("CJ ENM", "035760", "브랜드·IP", "https://www.cjenm.com/", "브랜드 콘텐츠·행사·체험 확장 업종 후보")),
        ("교통·숙박·주변소비", "downstream", _candidate("호텔신라", "008770", "현장 소비", "https://www.hotelshilla.net/", "관광·숙박·면세·지역 소비 접점의 업종 후보")),
    ],
    "lifestyle": [
        ("제품·브랜드", "core", _candidate("LG생활건강", "051900", "브랜드·IP", "https://www.lghnh.com/", "생활소비재·브랜드 상품 단계의 업종 후보")),
        ("콘텐츠·플랫폼", "consumer", _candidate("NAVER", "035420", "플랫폼·채널", "https://www.navercorp.com/", "검색·콘텐츠·커뮤니티 확산 접점의 업종 후보")),
        ("유통·판매채널", "downstream", _candidate("이마트", "139480", "유통·리테일", "https://company.emart.com/", "생활용품·취미상품 판매 접점의 업종 후보")),
    ],
}


CATEGORY_TEMPLATE = {
    "food_culinary": "food", "seasonal_food_ritual": "food",
    "music_performance": "music", "gaming_digital": "gaming",
    "sports_attendance": "sports", "sports_participation": "sports",
    "screen_content": "screen", "fashion_collectible": "fashion",
    "technology_tool": "technology", "product_brand": "technology",
    "place_experience": "place", "lifestyle_behavior": "lifestyle",
    "wellness_behavior": "lifestyle", "participation_meme": "lifestyle",
}


ROLE_STAGE = {
    "원재료·부품": "upstream", "제조": "core", "브랜드·IP": "core",
    "굿즈·패션": "core", "플랫폼·채널": "downstream", "유통·리테일": "downstream",
    "공간·운영": "consumer", "현장 소비": "consumer", "스폰서·협업": "consumer",
    "인프라·서비스": "upstream", "검증 제외": "excluded",
}


def expand_value_chain(topic: str, category: str, companies: list[dict]) -> tuple[list[dict], list[dict]]:
    """Guarantee three business lenses without pretending candidates are contracts."""
    template_name = CATEGORY_TEMPLATE.get(category, "lifestyle")
    definitions = TEMPLATES[template_name]
    existing = [deepcopy(company) for company in companies]
    used = {company["company"] for company in existing}
    categories = []
    for name, stage, fallback in definitions:
        members = []
        for company in existing:
            if company.get("relation_category"):
                continue
            if ROLE_STAGE.get(company.get("company_role"), "consumer") == stage:
                company["relation_category"] = name
                company["value_chain_stage"] = stage
                members.append(company)
        if fallback["company"] not in used:
            candidate = deepcopy(fallback)
            candidate["relation_category"] = name
            candidate["value_chain_stage"] = stage
            members.append(candidate)
            existing.append(candidate)
            used.add(candidate["company"])
        elif not members:
            # A diversified company may legitimately appear in more than one
            # lens. Keep the category row, but preserve candidate-only status.
            candidate = deepcopy(fallback)
            candidate["relation_category"] = name
            candidate["value_chain_stage"] = stage
            candidate["reason"] += " (동일 기업의 복수 사업 역할)"
            members.append(candidate)
            existing.append(candidate)
        categories.append({
            "name": name, "value_chain_stage": stage,
            "companies": [company["company"] for company in members],
            "candidate_count": len(members),
            "policy": "공식 관계와 산업 구조 후보를 구분해 표시",
        })
    for company in existing:
        if not company.get("relation_category"):
            company["relation_category"] = "기타 검증 관계"
            company["value_chain_stage"] = ROLE_STAGE.get(company.get("company_role"), "consumer")
    return categories, existing
