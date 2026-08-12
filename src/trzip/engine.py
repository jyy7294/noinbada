from __future__ import annotations

from collections.abc import Iterable

from .models import Lane, RankedTopic, TopicObservation
from .policy import classify_lane, validate_topic

RRF_K = 60


def _rrf(topic: TopicObservation) -> float:
    raw = sum(1 / (RRF_K + rank) for rank in (topic.x_rank, topic.google_rank) if rank is not None)
    maximum = 2 / (RRF_K + 1)
    return min(raw / maximum, 1.0)


def _score(topic: TopicObservation) -> tuple[float, float, float, float, float]:
    rrf = _rrf(topic)
    momentum = topic.momentum
    persistence = min(topic.persistence_days / 14, 1.0)
    cross = 1.0 if topic.x_rank is not None and topic.google_rank is not None else 0.0
    total = 0.60 * rrf + 0.20 * momentum + 0.15 * persistence + 0.05 * cross
    return total, rrf, momentum, persistence, cross


def rank_topics(topics: Iterable[TopicObservation], *, main_limit: int = 10) -> dict[str, list[RankedTopic]]:
    """Preserve every candidate while returning a curated public Main Top10."""
    buckets: dict[Lane, list[RankedTopic]] = {lane: [] for lane in Lane}
    for topic in topics:
        validate_topic(topic)
        lane = classify_lane(topic)
        total, rrf, momentum, persistence, cross = _score(topic)
        buckets[lane].append(RankedTopic(0, lane, total, rrf, momentum, persistence, cross, topic))
    output: dict[str, list[RankedTopic]] = {}
    for lane, values in buckets.items():
        values.sort(key=lambda item: (-item.score, item.observation.topic_id))
        ranked = [RankedTopic(index, item.lane, item.score, item.rrf_score, item.momentum_score,
                              item.persistence_score, item.cross_source_score, item.observation)
                  for index, item in enumerate(values, 1)]
        output[lane.value] = ranked[:main_limit] if lane is Lane.MAIN else ranked
    return output

