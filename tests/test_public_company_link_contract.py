from __future__ import annotations

from copy import deepcopy

from trzip.public_company_contract import keyword_company_link_coverage


def _card_parts() -> tuple[list[dict], list[dict], list[dict]]:
    keywords = [{"text": f"키워드{index}"} for index in range(5)]
    companies = []
    links = []
    roles = ("manufacturing_development", "distribution", "retail_sales")
    for index in range(10):
        keyword = f"키워드{index % 5}"
        role = roles[index % len(roles)]
        company = {
            "company": f"기업{index}",
            "stock_code": f"{index:06d}",
            "company_role_category": role,
            "company_role_label": f"역할{index % len(roles)}",
            "matched_keywords": [keyword],
        }
        companies.append(company)
        links.append({
            "keyword": keyword,
            "company": company["company"],
            "stock_code": company["stock_code"],
            "company_role_category": company["company_role_category"],
            "company_role_label": company["company_role_label"],
            "connection_explanation": "공식 공개 근거로 확인된 연결입니다.",
            "evidence_urls": [f"https://example.com/evidence/{index}"],
        })
    return keywords, companies, links


def test_public_link_contract_requires_all_five_keywords_and_all_ten_companies():
    keywords, companies, links = _card_parts()

    result = keyword_company_link_coverage(
        keywords=keywords,
        companies=companies,
        links=links,
        require_link_metadata=True,
    )

    assert result["ready"] is True
    assert result["linked_keyword_count"] == 5
    assert result["linked_company_count"] == 10
    assert result["valid_link_count"] == 10


def test_public_link_contract_rejects_unlinked_company_and_matched_keyword_drift():
    keywords, companies, links = _card_parts()
    incomplete = keyword_company_link_coverage(
        keywords=keywords,
        companies=companies,
        links=links[:-1],
        require_link_metadata=True,
    )
    assert incomplete["ready"] is False
    assert incomplete["unlinked_companies"] == ["기업9"]
    assert "기업9" in incomplete["matched_keyword_mismatches"]

    drifted_companies = deepcopy(companies)
    drifted_companies[0]["matched_keywords"] = ["키워드1"]
    drifted = keyword_company_link_coverage(
        keywords=keywords,
        companies=drifted_companies,
        links=links,
        require_link_metadata=True,
    )
    assert drifted["ready"] is False
    assert drifted["matched_keyword_mismatches"] == ["기업0"]


def test_public_link_contract_rejects_non_public_evidence_and_metadata_mismatch():
    keywords, companies, links = _card_parts()
    links[0]["evidence_urls"] = ["file:///private/evidence"]
    links[1]["stock_code"] = "WRONG"

    result = keyword_company_link_coverage(
        keywords=keywords,
        companies=companies,
        links=links,
        require_link_metadata=True,
    )

    assert result["ready"] is False
    assert result["invalid_link_indexes"] == [0, 1]
    assert set(result["unlinked_companies"]) == {"기업0", "기업1"}
