from trzip.result_quality import evaluate_frontend_result


def _company(index: int) -> dict:
    return {
        "company": f"기업{index}",
        "stock_code": f"00000{index}",
        "market": "KRX",
        "company_description": "설명",
        "relationship_reason": "관계 이유",
        "company_role_category": "manufacturing_development",
        "company_role_label": "제조·개발",
        "ontology_complete": True,
        "evidence_sources": [{"url": f"https://example.com/{index}"}],
    }


def _trend(rank: int) -> dict:
    return {
        "publication_rank": rank,
        "event_key": f"event:{rank}",
        "display_name": f"트렌드 {rank}",
        "observed_rank": rank * 2,
        "frontend_readiness_status": "ready",
        "related_keywords": [{"text": f"키워드 {index}"} for index in range(5)],
        "companies": [_company(index) for index in range(1, 7)],
    }


def test_complete_frontend_result_passes_quality_gate():
    result = evaluate_frontend_result({"home_top10": [_trend(rank) for rank in range(1, 11)]})

    assert result["passed"] is True
    assert result["trend_count"] == 10
    assert all(row["keyword_count"] == 5 and row["company_count"] == 6 for row in result["trends"])


def test_quality_gate_rejects_missing_company_role_and_non_contiguous_rank():
    trends = [_trend(rank) for rank in range(1, 11)]
    trends[0]["publication_rank"] = 7
    trends[1]["companies"][0].pop("company_role_category")

    result = evaluate_frontend_result({"home_top10": trends})

    assert result["passed"] is False
    assert "publication_rank_not_contiguous" in result["failures"]
    assert any("incomplete_company" in failure for failure in result["failures"])


def test_quality_gate_rejects_mismatched_company_role_label():
    trends = [_trend(rank) for rank in range(1, 11)]
    trends[0]["companies"][0]["company_role_label"] = "판매·리테일"

    result = evaluate_frontend_result({"home_top10": trends})

    assert result["passed"] is False
    assert any("invalid_company_role" in failure for failure in result["failures"])
