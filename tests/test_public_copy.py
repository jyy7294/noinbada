from trzip.public_copy import (
    contains_internal_relation_copy,
    public_connection_explanation,
    strip_internal_relation_copy,
)


def test_public_connection_copy_removes_internal_state_but_keeps_evidence() -> None:
    copy = public_connection_explanation(
        company="동원산업",
        role_label="제조·개발",
        connection_explanation=(
            "동원산업은(는) '제조·개발' 역할 후보입니다. "
            "동원F&B를 완전자회사로 편입했고 식품을 제조·판매합니다."
        ),
        matched_keywords=["삼계탕", "간편식"],
    )

    assert copy == (
        "삼계탕, 간편식 관련 맥락에서 동원산업: '제조·개발' 역할로 연결됩니다. "
        "동원F&B를 완전자회사로 편입했고 식품을 제조·판매합니다."
    )
    assert not contains_internal_relation_copy(copy)
    assert "은(는)" not in copy


def test_public_connection_copy_preserves_factual_review_wording() -> None:
    reason = "보도가 CJ제일제당이 홈플러스 납품 재개를 검토 중이라고 명시합니다."

    assert strip_internal_relation_copy(reason) == reason
    assert public_connection_explanation(
        company="CJ제일제당",
        role_label="배급·유통",
        reason=reason,
    ) == "CJ제일제당: '배급·유통' 역할로 연결됩니다. " + reason


def test_public_connection_copy_fails_closed_without_factual_reason() -> None:
    assert public_connection_explanation(
        company="가상기업",
        role_label="제조·개발",
        connection_explanation="가상기업은 제조·개발 역할 후보입니다. 관계 검토 중입니다.",
    ) == ""
