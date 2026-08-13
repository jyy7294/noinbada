from __future__ import annotations

CONTROVERSY_CONTEXT_MARKERS = {
    "논란", "사생활", "불륜", "스토커", "친일", "폭행", "구속", "범죄", "사망",
    "경찰서", "미사일", "국방부", "전쟁", "테러", "재난", "혐의", "고소", "피해자",
    "지진", "태풍", "폭염", "호우", "산불", "경보", "날씨",
    "대통령", "국회", "정당", "선거", "탄핵", "정부 정책",
}


def is_sensitive_context(term: str) -> bool:
    # Preserve token boundaries.  Removing whitespace made unrelated adjacent
    # words such as ``보고 소원`` look as if they contained ``고소``.
    normalized = " ".join(str(term or "").casefold().split())
    return any(
        " ".join(marker.casefold().split()) in normalized
        for marker in CONTROVERSY_CONTEXT_MARKERS
    )
