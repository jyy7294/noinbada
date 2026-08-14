from trzip.keyword_policy import (
    MAX_RELATED_KEYWORD_CHARACTERS,
    keyword_character_count,
    keyword_fits_public_label,
)


def test_public_keyword_limit_ignores_whitespace_but_never_truncates():
    assert MAX_RELATED_KEYWORD_CHARACTERS == 6
    assert keyword_character_count("일식 안경") == 4
    assert keyword_fits_public_label("일식 안경") is True
    assert keyword_fits_public_label("페르세우스 유성우") is False


def test_public_keyword_rejects_empty_values():
    assert keyword_fits_public_label("") is False
    assert keyword_fits_public_label("   ") is False
