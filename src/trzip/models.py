from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Source(StrEnum):
    X = "x"
    GOOGLE = "google_trends"


class Lane(StrEnum):
    MAIN = "main"
    ISSUE = "issue"
    REVIEW = "review"


class RelationStrength(StrEnum):
    DIRECT = "direct"
    INDIRECT = "indirect"
    SECTOR_WATCH = "sector_watch"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class Keyword:
    text: str
    source: Source
    evidence: str

    def __post_init__(self) -> None:
        if not isinstance(self.source, Source):
            raise ValueError("keyword source must be X or Google Trends")


@dataclass(frozen=True)
class CompanyRelation:
    company: str
    ticker: str | None
    strength: RelationStrength
    relation_type: str
    rationale: str
    evidence_url: str | None = None


@dataclass(frozen=True)
class TopicObservation:
    topic_id: str
    name: str
    category: str
    form: str
    x_rank: int | None
    google_rank: int | None
    momentum: float
    persistence_days: int
    aliases: tuple[str, ...] = ()
    keywords: tuple[Keyword, ...] = ()
    companies: tuple[CompanyRelation, ...] = ()
    policy_tags: tuple[str, ...] = ()
    source_date: str | None = None


@dataclass(frozen=True)
class RankedTopic:
    rank: int
    lane: Lane
    score: float
    rrf_score: float
    momentum_score: float
    persistence_score: float
    cross_source_score: float
    observation: TopicObservation = field(compare=False)
