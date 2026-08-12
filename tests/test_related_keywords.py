from trzip.related_keywords import repeated_candidate_keywords, x_related_keywords


def test_related_keywords_require_two_independent_documents():
    result = x_related_keywords(
        "말복",
        candidates=["삼계탕", "보양식"],
        documents=["말복에는 삼계탕 삼계탕", "말복 외식 삼계탕 할인"],
    )
    assert result["status"] == "observed"
    assert result["document_count"] == 2
    assert result["keywords"] == [
        {"text": "삼계탕", "count": 2, "status": "observed_repeated_expression"}
    ]


def test_event_vocabulary_blocks_unrelated_cooccurrence():
    result = x_related_keywords(
        "쿠우쿠우",
        candidates=["뷔페", "할인", "초밥"],
        documents=["쿠우쿠우 뷔페 친일 증조부", "쿠우쿠우 뷔페 할인"],
    )
    assert [row["text"] for row in result["keywords"]] == ["뷔페"]
    assert all(row["text"] not in {"친일", "증조부"} for row in result["keywords"])


def test_empty_event_vocabulary_does_not_fall_back_to_arbitrary_terms():
    result = x_related_keywords(
        "데이즈드",
        candidates=[],
        documents=["데이즈드 #NCTWISH 유우시 리쿠", "데이즈드 #NCTWISH 사진"],
    )
    assert result["keywords"] == []
    assert result["evidence_status"] == "insufficient"


def test_product_call_without_evidence_documents_never_calls_paid_api():
    result = x_related_keywords("말복", candidates=["삼계탕"])
    assert result["status"] == "insufficient"
    assert result["keywords"] == []
    assert result["source"] == "x_realtime_page"


def test_candidate_is_counted_once_per_document():
    rows = repeated_candidate_keywords(
        ["삼계탕 삼계탕 #삼계탕"], query="말복", candidates=["삼계탕"]
    )
    assert rows == []
