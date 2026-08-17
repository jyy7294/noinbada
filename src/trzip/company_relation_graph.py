"""Evidence-backed corporate relationship paths used by company enrichment.

This is deliberately a small, reviewable graph rather than a keyword-to-stock
dictionary.  It resolves a public parent only when every ownership edge and
the final listing have a source.  The resolver is enrichment-only: it cannot
alter trend observations, scores, or ranks.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class CorporateRelation:
    child: str
    parent: str
    relation: str
    evidence_url: str


@dataclass(frozen=True)
class ListedCompany:
    company: str
    ticker: str
    market: str
    listing_evidence_url: str


# Keep legal ownership and familiar product names separate.  The compact
# display path is ``X -> xAI -> SpaceX``; the SEC source records the legal
# intermediate holding company and SpaceX's resulting indirect ownership of
# X Corp. and X.AI LLC.
CORPORATE_RELATIONS = (
    CorporateRelation(
        "X",
        "xAI",
        "common_parent",
        "https://www.sec.gov/Archives/edgar/data/1318605/000110465926053166/tm2611837d1_10ka.htm",
    ),
    CorporateRelation(
        "xAI",
        "SpaceX",
        "acquired_by",
        "https://www.sec.gov/Archives/edgar/data/1181412/000162828026036936/exhibit21-sx1.htm",
    ),
)

LISTED_COMPANIES = {
    "SpaceX": ListedCompany(
        company="SpaceX",
        ticker="SPCX",
        market="NASDAQ",
        listing_evidence_url=(
            "https://ir.spacex.com/updates/releases-details/2026/"
            "Space-Exploration-Technologies-Corp--Announces-Closing-of-Initial-"
            "Public-Offering-Including-Full-Exercise-of-Underwriters-Option-to-"
            "Purchase-Additional-Shares-2026-RgoR-Y1Vwh/default.aspx"
        ),
    ),
}


def _key(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def resolve_listed_parent(entity: str) -> dict:
    """Resolve an entity to its evidenced listed parent, if one exists.

    The result contains the complete path and every evidence URL so callers
    can explain *why* a parent is shown.  A name match or shared founder never
    creates an edge.
    """

    source = str(entity or "").strip()
    if not source:
        return {"status": "not_found", "path": [], "evidence_urls": []}

    canonical = {_key(node): node for edge in CORPORATE_RELATIONS for node in (edge.child, edge.parent)}
    start = canonical.get(_key(source))
    if start is None:
        return {"status": "not_found", "path": [], "evidence_urls": []}

    outgoing: dict[str, list[CorporateRelation]] = {}
    for edge in CORPORATE_RELATIONS:
        outgoing.setdefault(edge.child, []).append(edge)

    queue: deque[tuple[str, tuple[str, ...], tuple[CorporateRelation, ...]]] = deque(
        [(start, (start,), ())]
    )
    while queue:
        node, path, edges = queue.popleft()
        listed = LISTED_COMPANIES.get(node)
        if listed is not None and edges:
            return {
                "status": "resolved",
                "entity": start,
                "company": listed.company,
                "ticker": listed.ticker,
                "market": listed.market,
                "path": list(path),
                "relation_types": [edge.relation for edge in edges],
                "evidence_urls": [edge.evidence_url for edge in edges],
                "listing_evidence_url": listed.listing_evidence_url,
            }
        for edge in sorted(outgoing.get(node, ()), key=lambda row: row.parent):
            if edge.parent not in path:
                queue.append((edge.parent, (*path, edge.parent), (*edges, edge)))

    return {"status": "not_listed", "entity": start, "path": [start], "evidence_urls": []}
