from __future__ import annotations


# The daily product view needs one complete rolling day. Longer history is
# valuable evidence, but must not prevent an otherwise valid MVP publication.
MVP_HISTORY_HOURS = 24
MVP_CONSECUTIVE_SOURCE_HOURS = 8
OPERATIONAL_HISTORY_TARGET_HOURS = 48
LONG_HORIZON_HISTORY_HOURS = 96


def history_stage(clean_history_hours: int) -> str:
    """Return the non-overlapping readiness stage for a clean hourly ledger."""

    if clean_history_hours < MVP_HISTORY_HOURS:
        return "initial"
    if clean_history_hours < OPERATIONAL_HISTORY_TARGET_HOURS:
        return "mvp_ready"
    if clean_history_hours < LONG_HORIZON_HISTORY_HOURS:
        return "operational"
    return "long_horizon"
