from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy


# This module only classifies companies that already have trend-specific
# evidence. It must never manufacture a company merely because an industry
# normally has an upstream, core, or downstream layer.
ROLE_STAGE = {
    "원재료·부품": "upstream",
    "인프라·서비스": "upstream",
    "제조": "core",
    "브랜드·IP": "core",
    "직접 기업": "core",
    "플랫폼·채널": "downstream",
    "유통·리테일": "downstream",
    "공간·운영": "consumer",
    "현장 소비": "consumer",
    "스폰서·협업": "consumer",
    "검증 제외": "excluded",
}

STAGE_LABEL = {
    "upstream": "원재료·부품·인프라",
    "core": "직접 제조·브랜드·IP",
    "downstream": "유통·플랫폼·채널",
    "consumer": "공간·현장 소비",
    "excluded": "연결 제외",
    "other": "기타 검증 관계",
}

ROLE_CATEGORY_STAGE = {
    "raw_materials_components": "upstream",
    "manufacturing_development": "core",
    "content_production": "core",
    "ownership_investment": "core",
    "distribution": "downstream",
    "retail_sales": "downstream",
    "platform_service": "downstream",
    "brand_marketing": "consumer",
    "event_sponsorship": "consumer",
    "industry_adjacent": "consumer",
}


def expand_value_chain(
    topic: str,
    category: str,
    companies: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Group evidence-backed companies without filling a category quota.

    ``topic`` and ``category`` remain in the signature for the public contract,
    but they do not select generic template companies. Zero companies and an
    incomplete value chain are both valid outcomes.
    """
    del topic, category
    evidence_companies = [deepcopy(company) for company in companies]
    grouped: OrderedDict[tuple[str, str], list[dict]] = OrderedDict()

    for company in evidence_companies:
        role_category = str(company.get("company_role_category") or "")
        role = str(company.get("company_role") or "기타 검증 관계")
        stage = ROLE_CATEGORY_STAGE.get(role_category, ROLE_STAGE.get(role, "other"))
        category_name = STAGE_LABEL[stage]
        company["relation_category"] = category_name
        company["value_chain_stage"] = stage
        grouped.setdefault((stage, category_name), []).append(company)

    categories = [
        {
            "name": category_name,
            "value_chain_stage": stage,
            "companies": [company["company"] for company in members],
            "candidate_count": len(members),
            "policy": "해당 트렌드에 대한 개별 관계 근거가 있는 기업만 표시",
        }
        for (stage, category_name), members in grouped.items()
    ]
    return categories, evidence_companies
