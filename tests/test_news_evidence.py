from datetime import UTC, datetime

import pytest

from trzip.news_evidence import NewsEvidenceError, build_discovery_queue, validate_news_evidence


def article_record(*, review_status="approved"):
    return {
        "title": "중화권 디저트 열풍 다음 주자 양즈깐루",
        "publisher": "서울경제",
        "url": "https://www.sedaily.com/article/20058091",
        "published_at": "2026-06-20T14:00:00+09:00",
        "retrieved_at": datetime(2026, 8, 12, tzinfo=UTC).isoformat(),
        "observed_term": "양즈깐루",
        "claims": [
            {"type": "search_growth", "text": "Google 검색 관심 증가를 기사에서 제시"},
            {"type": "product_launch", "text": "편의점·카페의 관련 제품 출시를 제시"},
            {"type": "sales_rank", "text": "출시 후 판매 순위 사례를 제시"},
            {"type": "consumer_behavior", "text": "SNS·여행 후기 확산 맥락을 제시"},
        ],
        "review_status": review_status,
    }


def test_article_can_support_context_but_never_ranking():
    result = validate_news_evidence(article_record(), allowed_hosts={"www.sedaily.com"})
    assert result["evidence_publishable"] is True
    assert result["ranking_evidence"] is False
    assert result["claim_types"] == ["consumer_behavior", "product_launch", "sales_rank", "search_growth"]


def test_news_discovery_waits_for_x_or_google_observation():
    queue = build_discovery_queue([article_record()])
    assert queue[0]["term"] == "양즈깐루"
    assert queue[0]["ranking_eligible"] is False
    assert queue[0]["status"] == "awaiting_x_or_google_observation"


@pytest.mark.parametrize(
    "field,value",
    [
        ("url", "http://www.sedaily.com/article/20058091"),
        ("url", "https://127.0.0.1/article"),
        ("published_at", "2026-06-20"),
    ],
)
def test_invalid_or_local_news_evidence_is_rejected(field, value):
    record = article_record()
    record[field] = value
    with pytest.raises(NewsEvidenceError):
        validate_news_evidence(record)


def test_unreviewed_article_is_not_publishable_evidence():
    assert validate_news_evidence(article_record(review_status="unreviewed"))["evidence_publishable"] is False

