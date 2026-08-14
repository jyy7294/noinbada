from __future__ import annotations

import re


MAX_RELATED_KEYWORD_CHARACTERS = 6


def normalized_keyword_text(value: object) -> str:
    """Return a stable display label without changing its meaning."""

    return " ".join(str(value or "").strip().split())


def keyword_character_count(value: object) -> int:
    """Count visible keyword characters while ignoring whitespace."""

    return len(re.sub(r"\s+", "", normalized_keyword_text(value)))


def keyword_fits_public_label(value: object) -> bool:
    """Public related-keyword labels must be non-empty and at most six chars."""

    count = keyword_character_count(value)
    return 0 < count <= MAX_RELATED_KEYWORD_CHARACTERS
