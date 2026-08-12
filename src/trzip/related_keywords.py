from __future__ import annotations

from collections import Counter


def repeated_candidate_keywords(
    documents: list[str],
    *,
    query: str,
    candidates: list[str],
    limit: int = 5,
) -> list[dict]:
    """Return candidate phrases present in at least two independent documents.

    Each document contributes at most one count per candidate. An empty
    vocabulary stays empty; it never enables arbitrary term extraction.
    """
    clean_query = " ".join(str(query).split()).casefold()
    counts: Counter[str] = Counter()
    for document in documents:
        folded = str(document).casefold()
        observed_in_document = {
            candidate
            for candidate in candidates
            if candidate.strip()
            and candidate.casefold() != clean_query
            and candidate.casefold() in folded
        }
        counts.update(observed_in_document)
    ranked = sorted(
        ((text, count) for text, count in counts.items() if count >= 2),
        key=lambda item: (-item[1], item[0].casefold()),
    )
    return [
        {"text": text, "count": count, "status": "observed_repeated_expression"}
        for text, count in ranked[: max(1, min(limit, 5))]
    ]


def x_related_keywords(
    query: str,
    limit: int = 5,
    candidates: list[str] | None = None,
    *,
    documents: list[str] | None = None,
) -> dict:
    """Resolve related expressions without calling X paid search APIs.

    The X realtime trends page provides ranked topic names, not post search
    results. Consequently, the public endpoint fails closed unless independent
    evidence documents were explicitly supplied by an approved collector.
    """
    clean_query = " ".join(str(query).split())
    if not clean_query:
        return {"status": "invalid", "source": "x", "query": clean_query,
                "keywords": [], "evidence_status": "insufficient", "reason": "query required"}
    vocabulary = list(candidates or [])
    evidence_documents = list(documents or [])
    keywords = repeated_candidate_keywords(
        evidence_documents,
        query=clean_query,
        candidates=vocabulary,
        limit=limit,
    ) if evidence_documents and vocabulary else []
    return {
        "status": "observed" if keywords else "insufficient",
        "source": "x_realtime_page",
        "query": clean_query,
        "document_count": len(evidence_documents),
        "keywords": keywords,
        "candidate_vocabulary_size": len(vocabulary),
        "evidence_status": "verified_candidates" if keywords else "insufficient",
        "reason": None if keywords else (
            "X realtime trend ranks do not contain independent related-keyword evidence"
        ),
        "note": "no X API call; ranking is unchanged; raw posts are not stored",
    }
