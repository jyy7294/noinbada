"""Final, source-only adjudication for observed trend expressions.

This module deliberately completes every normalized source expression without
using a hand-picked trend list or external-provider data.  It is intended for
an auditable X-only or Google-only E2E run: every item becomes ``included``,
``excluded`` or ``not_selected``.  ``not_selected`` is a final source-only
outcome, not a review queue and not a claim that the observed term is false.

The rules answer a deliberately narrower question than the main multi-source
pipeline: *does the observed expression itself identify a concrete,
non-sensitive cultural, consumer, content, sport, technology or market
phenomenon?*  It never invents a trigger event, a related company or a causal
claim.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


POLICY_VERSION = "source-only-final-adjudication-v1"


def _terms(*values: str) -> tuple[str, ...]:
    return tuple(value.casefold() for value in values)


# Categories mirror the eight public categories.  These are general lexical
# structures, never a catalogue of approved observed terms.
_CATEGORY_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("food", _terms(
        "\ucfe0\ud0a4", "\uce58\ud0a8", "\ud1b5\ub2ed", "\uc0ac\ubc1c\uba74", "\ub77c\uba74", "\ucee4\ud53c", "\ub77c\ub5bc", "\ubc00\ud06c\ud2f0",
        "\uc6b0\ub871", "\ucd08\ucf5c\ub9bf", "\uba54\ub274", "\ub9db\uc9d1", "\uc2dd\ub2f9", "\uc74c\ub8cc", "\ubc29\uc1a1\uc6a9 \uc2dd\ud488",
    )),
    ("content", _terms(
        "\uc601\ud654", "\uadf9\uc7a5\ud310", "\uc0c1\uc601\ud68c", "\ub4dc\ub77c\ub9c8", "\uc608\ub2a5", "\ud32c\ubbf8\ud305", "\ucf58\uc11c\ud2b8", "\uacf5\uc5f0",
        "\uc568\ubc94", "\uac00\uc694\ub300\uc804", "\uc2dc\ub9ac\uc988", "episode", "\ud31d\ub9c8\ud2b8", "\ud569\ubc29",
        "\ub9cc\ud654", "\ubc29\uc1a1",
    )),
    ("sports", _terms(
        " vs ", "\ud648\ub7f0", "pba \ud300\ub9ac\uadf8", "\uc544\uc2dc\uc548 \uac8c\uc784",
    )),
    ("lifestyle", _terms(
        "\ud55c\ubcf5\uc0c1\uc810", "\uc5ec\ud589 \uc608\uc57d", "\uc120\uc608\ub9e4 \uc778\uc99d",
    )),
    ("culture", _terms(
        "\ucd95\uc81c", "\ud398\uc2a4\ud2f0\ubc8c", "\uc804\uc2dc", "\ud31d\uc5c5", "\ucc4c\ub9b0\uc9c0", "\uac1c\uae30\uc77c\uc2dd", "\uc720\uc131\uc6b0", "\ubcc4\ub625\ubcc4", "\uad11\ubcf5\uc808", "\uc0ac\uc778\ud68c",
    )),
    ("consumer", _terms(
        "\uc544\uc774\ud3f0", "\ubaa8\uacf5 \ud328\ub4dc", "\uc2a4\ub2c8\ucee4\uc988",
    )),
    ("technology", _terms(
        "\ud734\uba38\ub178\uc774\ub4dc \ub85c\ubd07", "\uc0dd\uc131\ud615 ai", "grok", "\uc624\ud508ai", "\ubc18\ub3c4\uccb4 \uc7a5\ube44", "\uc6b0\uc8fc \uad00\uce21",
    )),
    ("market", _terms(
        "etf", "\uc778\ub371\uc2a4 \ud380\ub4dc", "cpi \ubc1c\ud45c", "\uc2dc\uc7a5 \uc9c0\uc218", "\uc7a5\ub9c8\uac10", "\uacf5\ubaa8\uc8fc", "\ube44\ud2b8\ucf54\uc778",
    )),
)

_POLITICAL_MARKERS = _terms(
    "\ub300\ud1b5\ub839", "\uad6d\ud68c", "\uc120\uac70", "\uc815\ub2f9", "\uc9c0\uc9c0\uc728", "\ud0c4\ud575", "\ud2b9\uac80", "\uc7a5\uad00", "\uc5ec\uc57c", "\uc815\uce58", "\uc774\uc7ac\uba85", "\uc724\uc11d\uc5f4", "\uae40\uc815\uc740",
)
_CRIME_OR_HARM_MARKERS = _terms(
    "\uc0b4\uc778", "\uc0ac\ub9dd", "\uad6c\uc18d", "\uccb4\ud3ec", "\ubc94\uc8c4", "\uc131\ubc94\uc8c4", "\uc131\ud3ed\ub825", "\ub9c8\uc57d", "\uc0ac\uae30", "\uace0\ub3c5\uc0ac", "\ud53c\ud574\uc790", "\uad34\ub86d\ud798", "\ud3ed\ud589", "\uc2e4\uc885", "\ub17c\ub780", "\uc2a4\uce94\ub4e4",
)
_DISASTER_MARKERS = _terms(
    "\uc7ac\ub09c", "\ud0dc\ud48d", "\ud3ed\uc6b0", "\ud64d\uc218", "\uc9c0\uc9c4", "\uc0b0\ubd88", "\ud654\uc7ac", "\ubd95\uad34", "\uce68\uc218", "\ud3ed\uc124", "\ucc38\uc0ac", "\uc0ac\uace0",
)
_GENERIC_EXPRESSIONS = _terms(
    "\uc790\ub3d9\ucc28", "\uc74c\uc2dd", "\uae30\uc0ac", "\ub3c8", "\ub300\ud55c\ubbfc\uad6d", "\ub178\ub3d9\uc790", "\uacf5\uc720", "\uc544\ub4e4", "\ucd1d\uc7a5", "\uc6b4\uc804 \uae30\uc0ac", "\uc6b4\uc804", "\ucd95\uad6c", "\uc601\ud654", "\uae30\uc220", "\uad11 \ud1b5\uc2e0", "\uc6d0\uc790\ub825 \ubc1c\uc804\uc18c", "\uccad\uad81", "\uc801\uae08", "\uc608\uae08", "\uc5f0\uae08 \uac1c\ud601",
)
_GENERIC_CATEGORY_EXACT = _terms(
    "\ucee4\ud53c\ubbf9\uc2a4", "kbo \ub9ac\uadf8", "kbo \uc21c\uc704", "\uc57c\uad6c\uc21c\uc704", "\ud504\ub85c\uc57c\uad6c\uc21c\uc704", "\uc57c\uad6c \uac10\ub3c5",
    "\uac15\uc6d0 fc", "\uc5d8\uc5d0\uc774 fc", "\ub9e8\uc720", "\ud2b8\ub808\ud0b9", "\uad11\ubcf5\uc808", "\uc778\ub371\uc2a4 \ud380\ub4dc", "\ud2b9\uc9d1 \uc608\ub2a5", "\ube14\ub8e8\ub808\uc774",
    "\uc120\uc608\ub9e4 \uc778\uc99d", "\uba40\ud2f0\ud648\ub7f0", "\ubcc4\ub625\ubcc4 \ud558\ub098",
)

_HASHTAG_CONTEXT = _terms("series", "episode", "challenge", "\ucc4c\ub9b0\uc9c0", "\ucf58\uc11c\ud2b8", "\ud32c\ubbf8\ud305")
_KOREAN_NAME_ONLY = re.compile(r"^[\uac00-\ud7a3]{2,4}$")
_KOREAN_VERSUS = re.compile(r"^\S+\s+\ub300\s+\S+$")


@dataclass(frozen=True)
class SourceAdjudication:
    decision: str
    reason_code: str
    category: str | None
    evidence: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "reason_code": self.reason_code,
            "broad_category": self.category,
            "evidence": list(self.evidence),
            "finality": "final_for_source_only_run",
            "ranking_effect": "none",
        }


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def _contains(text: str, marker: str) -> bool:
    return marker in text


def _find_markers(text: str, markers: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(marker for marker in markers if _contains(text, marker))


def _specific_shape(text: str) -> bool:
    """Accept structured foreign-name and head-to-head sports expressions."""

    has_latin_word = bool(re.search(r"[a-z]{3,}", text))
    versus = bool(re.search(r"\S+\s+(?:vs\.?|v\.?)\s+\S+", text)) or bool(_KOREAN_VERSUS.fullmatch(text))
    return has_latin_word or versus


def _is_specific_sports_event(text: str) -> bool:
    """Require an actual fixture, named competition, or named player outcome.

    Broad labels such as ``KBO \uc21c\uc704`` and a club name alone are sports
    subjects, not self-contained trend events.
    """

    if _KOREAN_VERSUS.fullmatch(text) or re.search(r"\S+\s+(?:vs\.?|v\.?)\s+\S+", text):
        return True
    if "pba \ud300\ub9ac\uadf8" in text or "\uc544\uc2dc\uc548 \uac8c\uc784" in text:
        return True
    return bool(re.fullmatch(r"[\uac00-\ud7a3]{2,4}\s+\ud648\ub7f0", text))


def adjudicate_source_expression(expression: str) -> SourceAdjudication:
    """Resolve one observed expression to a final source-only result.

    This is intentionally conservative for standalone names.  A bare person,
    company or generic noun may have a perfectly legitimate cause, but that
    cause is not present in an X/Google trend label alone.
    """

    original = " ".join(str(expression or "").strip().split())
    text = _normalized(original)
    if not text:
        return SourceAdjudication("not_selected", "empty_expression", None, ())

    for reason, markers in (
        ("policy_or_political_topic", _POLITICAL_MARKERS),
        ("crime_or_personal_harm_topic", _CRIME_OR_HARM_MARKERS),
        ("disaster_or_accident_topic", _DISASTER_MARKERS),
    ):
        found = _find_markers(text, markers)
        if found:
            return SourceAdjudication("excluded", reason, None, found)

    category_matches: list[tuple[str, tuple[str, ...]]] = []
    for category, markers in _CATEGORY_MARKERS:
        found = _find_markers(text, markers)
        if found:
            category_matches.append((category, found))

    generic = text.lstrip("#") in _GENERIC_EXPRESSIONS
    generic = generic or text.lstrip("#") in _GENERIC_CATEGORY_EXACT
    starts_hashtag = original.startswith("#")
    has_hashtag_context = bool(_find_markers(text, _HASHTAG_CONTEXT))
    compact = text.lstrip("#").replace(" ", "")

    if generic:
        return SourceAdjudication("not_selected", "generic_expression_without_event_context", None, ())
    if starts_hashtag and not category_matches and not has_hashtag_context:
        return SourceAdjudication("not_selected", "hashtag_campaign_without_concrete_event_context", None, ())
    if _KOREAN_NAME_ONLY.fullmatch(compact) and not category_matches:
        return SourceAdjudication("not_selected", "standalone_person_or_entity_name_without_event_context", None, ())

    if category_matches:
        category, found = category_matches[0]
        if category == "sports" and not _is_specific_sports_event(text):
            return SourceAdjudication("not_selected", "sports_subject_without_specific_fixture_or_outcome", None, found)
        return SourceAdjudication("included", "concrete_observed_phenomenon", category, found)
    if _specific_shape(text):
        if _KOREAN_VERSUS.fullmatch(text) or re.search(r"\S+\s+(?:vs\.?|v\.?)\s+\S+", text):
            return SourceAdjudication("included", "concrete_head_to_head_event", "sports", ())
        return SourceAdjudication("not_selected", "named_expression_without_category_or_event_context", None, ())
    return SourceAdjudication("not_selected", "context_insufficient_from_source_label", None, ())
