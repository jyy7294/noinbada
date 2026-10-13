# TRZIP production recovery — 2026-10-14

This contract supersedes laptop-only, exact-five-keyword, exact-ten-company,
per-edition manual approval, and showcase-as-live policies. Approved by the user
in the implementation request following the recovery plan.

## Runtime

- Python collectors and enrichment, SQLite WAL with separate runtime tables,
  a single writer protected by an OS lock, FastAPI read-only endpoints.
- Google public KR page every ten minutes; official RSS fallback declares its
  limited sampling frame. Do not impose a minimum of 100 rows.
- Optional YouTube official API every ten minutes when configured. X and Instagram are unavailable until
  an approved free adapter is connected. Paid API budget is zero.
- Linux systemd, isolated `/srv/services/trzip`, localhost-only API behind nginx.
  Vercel serves the UI with same-origin API rewrites after the production gate.
- No LLM, Codex session, personal browser login or Git push is needed per cycle.

## Truth and publication

Observations retain source, sampling frame, receipt time and source time. Only
fresh successful source snapshots contribute to the score; stale rows are labelled as last-known-good. Changes
in sampling frame reset comparisons. RRF k=60 combines source-native ranks;
single-source output is labelled as such. RSS feed order is explicitly a feed
position, not a whole-platform popularity rank. Gaps are null, never filled.
Rank and enrichment publish independently. Companies may be empty or any
verified count. Related terms are observed terms, not invented summaries.
Publication IDs lock list and detail data; files are immutable and a pointer is
replaced last. The API evaluates freshness using server time, not build time.

## Evidence and media

Domestic and US listed companies only. Official listing identity and an
independent supported business claim are both required. Old ontology entries
are candidates, never automatically current facts. Store evidence URL, excerpt,
hash, retrieval time and relation type; contradictions stay pending. Licensed
media or official identification assets have attribution; absent media becomes
a deterministic text card. Block non-public addresses, unsafe redirects, SVG
scripts, oversize and malformed images. No paid AI image generation.

## Release gate

Preserve the old public deployment and local user storage. Validate unit and
regression tests, real collection, evidence, responsive browser flows and
restore. A candidate is not a completed public release. Promotion requires
72 hours with >=95% scheduled Google receipts, recovery within two intervals,
no mixed edition or duplicate publication, and >=5 GiB server disk reserve.
Until then the new service is a separately labelled candidate; the old public
surface must clearly disclose that it is a historical demonstration.

## Retention

Keep 14 days of normalized observations in the hot database and compress older
observations, receipts and runs before removing their hot rows. Retain seven
days of immutable compressed editions. Never invent missing observations or
delete legacy data. Media is a bounded 128 MiB cache ordered by creation time,
operational logs have a dedicated 32 MiB journal, and backups use SQLite's backup
API plus integrity checks. Disk reserve failure stops new media/enrichment and
publishing safely, retaining the last known good edition and an explicit error.
Three daily integrity-checked backups are retained. Archives remain private on
the server; if their growth reaches the reserve floor, collection stops rather
than deleting archives or data belonging to another service.
