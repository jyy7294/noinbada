# Frontend trend and enrichment contract

The observed selector and the enrichment pipeline are deliberately separate.
Missing keywords or companies never change the X+Google score: the event stays
in `all_observed_ranking`, but it does not enter the complete `home_feed` until
the public card contract is satisfied.

## Home selection gate

`home_feed`, the numbered compatibility arrays, and each `period_top10` may
contain a trend when all of the following are true:

1. It was actually observed in X Korea or Google Trending Now Korea during the
   selected period. Only those two sources affect score and rank.
2. It is a concrete product, work, event, brand, meme, technology, market topic,
   or similarly identifiable object rather than an unresolved broad noun.
3. `context_research` provides a concrete current trigger, a `why_now`
   explanation, and at least one public HTTP(S) evidence URL. NAVER News,
   official pages, and reviewed industry sources may support this context but
   never alter rank.
4. It is current and does not match the manipulation-risk rule for an
   uncorroborated one-hour, single-source hashtag burst.

The deterministic home mix is velocity-first: up to seven positions go to
genuinely measured positive-slope `new`, `rising`, or `rebounding` trends, and
up to three positions retain strong current context. The emerging allowance is
a ceiling, not a quota: no weak candidate is inserted merely to fill it. Among
rising candidates, measured slope is ordered before current score. A soft
category cap improves variety, then relaxes if it would leave valid positions
empty. Food has no separate quota or exclusion rule.

## Enrichment readiness

Every selected trend separately reports whether the richer detail payload is
complete:

- exactly five distinct sourced related keywords;
- at least ten unique evidence-backed listed companies worldwide;
- two to four company role categories across those companies;
- company name, symbol, exchange, description, connection reason, ontology
  path, relationship tier, and public evidence URL for every exposed company.

`frontend_readiness_status=enrichment_pending` is a valid observed/detail
state, but not a complete home-feed card. `frontend_readiness_missing`,
`frontend_keyword_count`,
`frontend_company_count`, and `frontend_company_role_category_count` tell the
frontend and operators exactly what remains. Missing items are warnings for
enrichment work, not rank or home-selection inputs. Padding with invented
keywords or companies remains forbidden.

## Ontology and identity

The category ontology supplies entity slots, trigger types, and recommended
company roles for food, seasonal rituals, screen content, music, games,
sports, beauty/fashion, products, events, hobbies, wellness, memes, public
observation events, technology, and markets. These detailed categories map to
the eight public categories without changing score.

Listed-company identity may be checked through OpenDART for Korean issuers and
official exchange or SEC records for foreign issuers. Foreign tickers are
valid when paired with their exchange. Only six-digit KRX symbols are eligible
for the current Kiwoom S# handoff.

Transport publication is another independent gate: a live-data publication is
remote-publishable only when same-hour X and Google collection is complete.
