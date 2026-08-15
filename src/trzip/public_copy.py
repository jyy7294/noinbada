"""Public-facing copy helpers for reviewed trend-company relationships.

Internal workflow labels belong in audit fields, not in approved customer copy.
This module removes those labels without inventing evidence or changing ranking.
"""

from __future__ import annotations

import re
from collections.abc import Iterable


_INTERNAL_RELATION_MARKER = re.compile(
    r"역할\s*후보|후보(?:입니다|입니다만|로\s*분류)|보강\s*(?:중|대기)|"
    r"(?:관계|근거|연결)\s*검토\s*(?:중|대기)|승인\s*대기|내부\s*(?:상태|검토)|"
    r"\b(?:candidate|unresolved|pending[_ -]?review)\b",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?", re.MULTILINE)


def strip_internal_relation_copy(value: object) -> str:
    """Return factual sentences only, omitting workflow-state sentences."""

    text = " ".join(str(value or "").split())
    if not text:
        return ""
    sentences = [
        sentence.strip()
        for sentence in _SENTENCE.findall(text)
        if sentence.strip() and not _INTERNAL_RELATION_MARKER.search(sentence)
    ]
    return " ".join(sentences).replace("은(는)", ":").strip()


def public_connection_explanation(
    *,
    company: object,
    role_label: object,
    connection_explanation: object = None,
    relationship_reason: object = None,
    reason: object = None,
    matched_keywords: Iterable[object] = (),
) -> str:
    """Build evidence-only public copy for an already approved company row.

    Existing clean editorial copy is preserved.  If the source contains an
    internal marker, its factual remainder is paired with the approved public
    role.  An empty result stays empty so callers can fail closed.
    """

    company_name = str(company or "").strip()
    public_role = str(role_label or "").strip()
    raw_connection = " ".join(str(connection_explanation or "").split())
    cleaned_connection = strip_internal_relation_copy(raw_connection)
    had_internal_marker = bool(_INTERNAL_RELATION_MARKER.search(raw_connection))
    if cleaned_connection and not had_internal_marker:
        return cleaned_connection

    factual_reason = cleaned_connection or next(
        (
            cleaned
            for cleaned in (
                strip_internal_relation_copy(relationship_reason),
                strip_internal_relation_copy(reason),
            )
            if cleaned
        ),
        "",
    )
    if not company_name or not public_role or not factual_reason:
        return ""

    keywords: list[str] = []
    for value in matched_keywords:
        text = str(value or "").strip()
        if text and text not in keywords:
            keywords.append(text)
    context = f"{', '.join(keywords)} 관련 맥락에서 " if keywords else ""
    return (
        f"{context}{company_name}: '{public_role}' 역할로 연결됩니다. "
        f"{factual_reason}"
    ).strip()


def contains_internal_relation_copy(value: object) -> bool:
    """Expose the public contract check without leaking the regex itself."""

    return bool(_INTERNAL_RELATION_MARKER.search(str(value or "")))
