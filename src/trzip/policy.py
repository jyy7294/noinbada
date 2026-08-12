from __future__ import annotations

from .models import Lane, Source, TopicObservation

MAIN_CATEGORIES = {
    "food", "music", "content", "product", "fashion", "beauty", "game",
    "travel", "place", "hobby", "meme", "participation", "technology", "sports",
}
ISSUE_TAGS = {"politics", "crime", "accident", "disaster", "conflict", "plain_weather", "breaking_news"}
REVIEW_TAGS = {"ambiguous", "generic_noun", "unidentified_person", "insufficient_context"}


def classify_lane(topic: TopicObservation) -> Lane:
    tags = set(topic.policy_tags)
    if tags & ISSUE_TAGS:
        return Lane.ISSUE
    if tags & REVIEW_TAGS:
        return Lane.REVIEW
    if topic.category in MAIN_CATEGORIES:
        return Lane.MAIN
    return Lane.REVIEW


def validate_topic(topic: TopicObservation) -> None:
    if topic.x_rank is None and topic.google_rank is None:
        raise ValueError("at least one X or Google Trends rank is required")
    for value in (topic.x_rank, topic.google_rank):
        if value is not None and value < 1:
            raise ValueError("source rank must be positive")
    if not 0 <= topic.momentum <= 1:
        raise ValueError("momentum must be between 0 and 1")
    if topic.persistence_days < 1:
        raise ValueError("persistence_days must be positive")
    if len(topic.keywords) > 5:
        raise ValueError("at most five related keywords are public")
    if any(keyword.source not in {Source.X, Source.GOOGLE} for keyword in topic.keywords):
        raise ValueError("keywords must come only from X or Google Trends")

