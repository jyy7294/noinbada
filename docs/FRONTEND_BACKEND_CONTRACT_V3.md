# TRZIP 프런트 연동 계약 V3

프런트는 화면을 자유롭게 교체할 수 있지만, 아래 세 문서를 하나의 묶음으로 읽어야 합니다.

```text
https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest/intelligence.json
https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest/status.json
https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest/metadata.json
```

## 묶음 검증

세 문서의 `mode=live`, `publication_id`, `generated_at`, 관측시각이 모두 같을 때만 화면에 반영합니다. 하나라도 다르면 새 묶음을 버리고 마지막 정상 캐시 또는 명시적 오류 상태를 사용합니다.

## 목록

- 전체 순위: `unified_ranking`
- 순위 확정도: `ranking_availability` (`단일출처 잠정` / `양출처 잠정` / `성숙 통합`)
- 홈 최대 10개: `public_top10`
- 홈 근거 게이트: `home_quality_gate` (`ranking_effect=none`)
- 이슈·주의: `lanes.issue`
- 검토 대기: `lanes.review`
- 시간·일 단위 원천 이력: `hourly_rankings`, `daily_aggregates`
- 기업 근거 보강 대기열: `ontology_enrichment_queue` (운영·검수 화면용, 순위 영향 없음)
- 전체 근거 작업 대기열: `enrichment_work_queue` (관련어·기업 각각 5개 충족 상태와 우선순위, 순위 영향 없음)
- 보조 플랫폼 문서 후보: `provider_keyword_candidate_queue` (지유님 알고리즘을 운영 원장에 맞게 이식한 검토 대기열, 자동 공개·순위 영향 없음)

프런트는 `unified_ranking`을 재정렬하거나 홈 10개를 자체 계산하지 않습니다.
`needs_context`인 항목은 관련 표현·검수 온톨로지·일치한 보조 검증·연결 기사 중
하나도 없으면 전체 순위에는 남지만 `public_top10`에서는 제외됩니다. 프런트는
`home_context_status`와 `home_context_reason`을 그대로 표시하고 자체 승격하지 않습니다.
또한 `companies`가 URL 근거를 갖춘 서로 다른 국내 상장종목 5개 미만이면
`company_ontology_incomplete`로 홈에서 보류됩니다. 이때 백엔드는 기업을 채워 넣지
않으며 `public_top10`은 10개보다 적을 수 있습니다.
보조 검증 스케줄러는 이 상태를 풀 수 있도록 `public_top10`만이 아니라 현재
`main` 후보 전체를 순환하며, 한 시간 최대 3개만 조회합니다. 검증 결과는 순위에
영향을 주지 않습니다.

## 트렌드 카드 필드

| 목적 | 필드 |
|---|---|
| 실제 제목 | `display_name` |
| 관측 대표어·표시 정책 | `observed_representative_term`, `display_name_policy` (기본은 관측어 그대로, 검수된 6자리 종목코드만 회사명 표시 허용) |
| 정규화 그룹 키 | `event_key`, `resolved_entity_name` |
| 원천 표현 | `raw_terms` |
| 넓은 분류 | `broad_category` |
| 표시 레인 | `lane`, `selection_reason` |
| 공정 순위 | `rank`, `score`, `score_components` (`total_points`, `formula_version`, `rounding_policy` 포함; 공개 구성점수 합계와 `score`가 항상 일치) |
| 원천 순위 | `latest_source_ranks`, `source_badge` |
| 변화·지속 | `rank_change_by_source`, `lifecycle`, `persistence_rank`, `momentum_rank` |
| 신뢰 상태 | `data_confidence`, `home_context_status` |
| 관련어 | `keywords` (0~5), 원천 관측 또는 검수된 온톨로지 표현만 허용하고 `affects_score=false` |
| 기업 Gold | `companies` (0 또는 5개 이상) |
| 기업 후보 감사 | `company_candidates`, `company_resolution` |
| 보조 검증 | `verification_layer` |
| 보조 검증 실행상태 | `verification_run` (`ranking_effect=none`) |
| 근거 보강 작업상태 | `enrichment_work_queue` (`ranking_effect=none`) |
| 보조 문서 키워드 후보 | `provider_keyword_candidate_queue` (`publishable=false`, 승인 전 칩 금지) |
| 기사 맥락 | `news_context` |
| 공식 기업개황 | `companies[].official_identity` (`provider=opendart`, 순위·관계 근거로 사용 금지) |

## 빈 상태 규칙

- 관련어 0개: 임의 키워드 칩을 만들지 않음
- `source=reviewed_ontology`: 별칭은 `status=approved_ontology_term`, 근거 기반 연관 개념은 `status=approved_ontology_related_term`으로 구분하고 `evidence_urls`를 함께 표시하며 순위에는 반영하지 않음
- `keywords[].role`은 온톨로지 관계를 설명하는 확장 가능한 문자열이므로 프론트가 고정 enum으로 분기하지 않음
- `approved_ontology_related_term`은 화면 설명용 근거이며, 그 용어를 다시 기업 탐색 시작점으로 사용하지 않음. 기업은 대표어·실제 관측 표현·검수된 동일어에서만 해석해 약한 다단계 연관 확장을 차단함
- `companies=[]`: 기업 CTA를 숨기고 `company_resolution.reason` 표시
- `partial=true`: 실패한 출처와 마지막 관측시각 표시
- `ranking_availability.is_combined_rank=false`: 통합 순위라고 표현하지 않고 잠정 배지 표시
- 데이터 묶음 검증 실패: 목업 트렌드로 대체하지 않음
- 시장자료는 `market_reference.status=observed`일 때만 일별 참고값으로 표시
- 공식 기업개황은 `official_identity.status=verified`일 때만 법인명·영문명·설립일·공식 홈페이지를 표시하고, `relationship_evidence=false`를 관계 근거로 오해하지 않음
- `coverage.legacy_observed_rows`는 구형 수집기 보존행이며 차트·순위에 사용하지 않음

정확한 기계 계약은 `schemas/intelligence-v3.schema.json`, `schemas/metadata-v3.schema.json`, `schemas/status-v1.schema.json`을 따릅니다.
