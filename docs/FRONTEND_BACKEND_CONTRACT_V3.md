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
- 이슈·주의: `lanes.issue`
- 검토 대기: `lanes.review`
- 시간·일 단위 원천 이력: `hourly_rankings`, `daily_aggregates`
- 기업 근거 보강 대기열: `ontology_enrichment_queue` (운영·검수 화면용, 순위 영향 없음)

프런트는 `unified_ranking`을 재정렬하거나 홈 10개를 자체 계산하지 않습니다.

## 트렌드 카드 필드

| 목적 | 필드 |
|---|---|
| 실제 제목 | `display_name` |
| 정규화 그룹 키 | `event_key`, `resolved_entity_name` |
| 원천 표현 | `raw_terms` |
| 넓은 분류 | `broad_category` |
| 표시 레인 | `lane`, `selection_reason` |
| 공정 순위 | `rank`, `score`, `score_components` |
| 원천 순위 | `latest_source_ranks`, `source_badge` |
| 변화·지속 | `rank_change_by_source`, `lifecycle`, `persistence_rank`, `momentum_rank` |
| 신뢰 상태 | `data_confidence`, `home_context_status` |
| 관련어 | `keywords` (0~5), `role`은 결정론적 초안이고 `affects_score=false` |
| 기업 Gold | `companies` (0 또는 5개 이상) |
| 기업 후보 감사 | `company_candidates`, `company_resolution` |
| 보조 검증 | `verification_layer` |
| 보조 검증 실행상태 | `verification_run` (`ranking_effect=none`) |
| 기사 맥락 | `news_context` |

## 빈 상태 규칙

- 관련어 0개: 임의 키워드 칩을 만들지 않음
- `companies=[]`: 기업 CTA를 숨기고 `company_resolution.reason` 표시
- `partial=true`: 실패한 출처와 마지막 관측시각 표시
- `ranking_availability.is_combined_rank=false`: 통합 순위라고 표현하지 않고 잠정 배지 표시
- 데이터 묶음 검증 실패: 목업 트렌드로 대체하지 않음
- 시장자료는 `market_reference.status=observed`일 때만 일별 참고값으로 표시
- `coverage.legacy_observed_rows`는 구형 수집기 보존행이며 차트·순위에 사용하지 않음

정확한 기계 계약은 `schemas/intelligence-v3.schema.json`, `schemas/metadata-v3.schema.json`, `schemas/status-v1.schema.json`을 따릅니다.
