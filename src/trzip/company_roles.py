from __future__ import annotations


COMPANY_ROLE_LABELS = {
    "manufacturing_development": "제조·개발",
    "raw_materials_components": "원재료·핵심부품",
    "content_production": "콘텐츠 제작",
    "distribution": "배급·유통",
    "retail_sales": "판매·리테일",
    "brand_marketing": "브랜드·마케팅",
    "platform_service": "플랫폼·서비스",
    "ownership_investment": "투자·소유",
    "event_sponsorship": "행사 후원·운영",
}

INTERNAL_UNCLASSIFIED_ROLE = "unclassified"
INTERNAL_UNCLASSIFIED_LABEL = "역할 미확정"
PUBLIC_COMPANY_ROLE_CATEGORIES = frozenset(COMPANY_ROLE_LABELS)


def company_role_category(source: dict) -> str:
    """Classify a company's documented role without affecting trend ranking."""

    explicit = str(source.get("company_role_category") or "").strip()
    if explicit in COMPANY_ROLE_LABELS:
        return explicit
    relation_type = str(source.get("relation_type") or source.get("relation_tier") or "").strip()
    text = " ".join(
        str(source.get(field) or "").casefold()
        for field in (
            "company_description", "company_summary", "reason",
            "relationship_reason", "evidence_type", "company_role",
        )
    )
    if relation_type == "ownership" or any(token in text for token in ("지분", "투자 관계", "주주", "보유한")):
        return "ownership_investment"
    if relation_type == "brand_collaboration" or any(token in text for token in ("브랜드 협업", "콜라보", "캠페인")):
        return "brand_marketing"
    if relation_type == "distribution" or any(token in text for token in ("배급", "유통", "이용권")):
        return "distribution"
    if any(token in text for token in ("공식 파트너", "후원", "스폰서", "행사 운영", "전시관 참가")):
        return "event_sponsorship"
    if any(token in text for token in ("제작사", "제작위원회", "콘텐츠 제작", "영화기업", "게임 콘텐츠")):
        return "content_production"
    if any(token in text for token in ("플랫폼", "통신 서비스", "ott", "클라우드", "소프트웨어")):
        return "platform_service"
    if any(token in text for token in ("원재료", "소재", "부품", "케이블", "광섬유", "공급망", "기자재")):
        return "raw_materials_components"
    if any(token in text for token in ("판매", "리테일", "편의점", "외식", "매장")):
        return "retail_sales"
    if any(token in text for token in (
        "제조", "개발", "생산", "카메라", "렌즈", "장비", "기기", "로봇",
        "자동차", "건설", "시공", "식품기업", "전자기업", "광학기업",
    )):
        return "manufacturing_development"
    # A weak relation tier is not a business role. Keep an unresolved role
    # internal until the documented function can be classified precisely.
    return INTERNAL_UNCLASSIFIED_ROLE


def with_company_role(source: dict) -> dict:
    category = company_role_category(source)
    return {
        **source,
        "company_role_category": category,
        "company_role_label": COMPANY_ROLE_LABELS.get(
            category, INTERNAL_UNCLASSIFIED_LABEL
        ),
        "company_role_public": category in PUBLIC_COMPANY_ROLE_CATEGORIES,
    }
