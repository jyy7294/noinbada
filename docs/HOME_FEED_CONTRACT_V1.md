# TRZIP Home Feed Contract v1

## Purpose

`home_feed` is a rank-free "today's flow" board. It never promises ten cards
and never pads incomplete trends. `all_observed_ranking` and `ranking_views`
retain X/Google ranks for audit and detail only.

## Public shape

```json
{
  "status": "ready",
  "groups": [
    {"key": "spreading", "label": "확산 중", "trends": []},
    {"key": "sustained", "label": "계속 화제", "trends": []},
    {"key": "emerging", "label": "막 포착됨", "trends": []}
  ]
}
```

Only non-empty groups are emitted. A card contains no rank, source score or
internal selection score. It includes `platform_observation_summary` so a
detail screen can distinguish X/Google observed ranks from NAVER News context.

## Selection

The private ordering formula is `35V + 25B + 20A + 10P + 10R`: measured
velocity, X+Google cross-platform spread, current attention, persistence, and
recency. Only X and Google feed these measurements. NAVER News is context-only;
keywords, companies, manual aliases and LLM prose cannot change this score.

## Card gate

Each card must be main lane, have at least one actual X/Google observation in
the latest 24-hour window, have a public NAVER News or official-page trigger
context, exactly five sourced keywords, at least ten evidence-backed listed
companies in the source candidate projected to exactly ten public companies,
two to four role groups, at least two distinct keyword-company links, and a
non-recommendation relationship explanation for every company. YouTube,
Instagram, NAVER Blog, Cafe and NAVER Search Trend are disabled by this policy.

## Compatibility

`home_top10`, `trend_top10`, `public_top10`, and `rising_top10` are deprecated
one-release compatibility arrays for the existing frontend. They contain at
most ten of the same ready events and retain contiguous `publication_rank`.
Their presence does not turn the rank-free `home_feed` into a leaderboard.
