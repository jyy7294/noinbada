# Frontend completion contract

The frontend Top10 arrays are fail-closed. `home_top10`, `trend_top10`,
`public_top10`, `rising_top10`, and every `period_top10` contain only trends
that meet both requirements below.

1. Exactly five evidence-backed related keywords.
2. At least six unique listed companies with a stock code, market, company
   description, relationship reason, complete ontology path, and evidence URL.
3. A valid `company_role_category` and matching Korean `company_role_label`
   for every published company.

Listed-company identity may be verified through OpenDART for Korean issuers or
through an official exchange/SEC record for foreign issuers. Country does not
affect rank, product fit, or relationship tier.

Incomplete score-ordered candidates remain in `unified_ranking` with their
original score and rank. The fields `frontend_readiness_status`,
`frontend_readiness_missing`, `frontend_keyword_count`, and
`frontend_company_count` explain what is missing. The persistent enrichment
queue prioritises these gaps with required counts of five keywords and three
companies.

`publication_readiness.publication_ready` becomes true only when at least ten
fully prepared candidates exist. This product-readiness flag is separate from
The role taxonomy covers manufacturing/development, raw materials/components,
content production, distribution, retail/sales, brand/marketing,
platform/service, ownership/investment, event sponsorship/operation, and
industry-adjacent exposure. Foreign tickers are valid when paired with their
exchange in `market`; only six-digit KRX symbols are eligible for the current
Kiwoom S# handoff.

Transport publication eligibility is separate: a valid X+Google collection may be
published while fewer than ten completed candidates exist, but neither keyword
nor company padding is allowed. Enrichment data never changes score, rank, or
product-fit eligibility.
