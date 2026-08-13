# TRZIP 프런트 연동 계약 V3

프런트는 화면을 자유롭게 교체할 수 있지만, `manifest.json`이 가리키는 불변 발행 묶음만 읽어야 합니다.

```text
https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest/manifest.json
https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest/delivery/{publication_id}/rankings.json
https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest/delivery/{publication_id}/trends/{trend_file}.json
```

아래 세 문서는 기존 프런트 전환 기간의 호환 경로입니다.

```text
https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest/intelligence.json
https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest/status.json
https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest/metadata.json
```

## 묶음 검증

1. `latest/manifest.json`을 먼저 읽습니다.
2. manifest가 지정한 `rankings.json`과 트렌드 상세 파일만 가져옵니다.
3. 파일별 SHA-256, `publication_id`, `generated_at`, `observed_at`이 manifest와 모두 일치할 때만 화면에 반영합니다.
4. 하나라도 다르면 새 묶음을 버리고 마지막 정상 캐시 또는 명시적 오류 상태를 사용합니다. 목업 데이터로 대체하지 않습니다.

호환 경로를 쓰는 동안에는 세 문서의 `mode=live`, `publication_id`, `generated_at`, 관측시각이 모두 같아야 합니다.

## 목록

- 전체 순위: `unified_ranking`
- 순위 확정도: `ranking_availability` (`단일출처 잠정` / `양출처 잠정` / `성숙 통합`)
- 홈 최대 10개: `trend_top10` (`lanes.main`의 점수 순 앞 10개)
- 기존 홈 필드: `public_top10` (`trend_top10`과 값이 같은 마이그레이션 별칭)
- 기업 카드 준비 목록: `company_ready_trends` (기업 Gold가 준비된 main 항목을 전역 순위 그대로 보존)
- 홈 계약 설명: `home_quality_gate` (`ranking_effect=none`, 기업 수가 홈 순위에 영향 없음)
- 이슈·주의: `lanes.issue`
- 검토 대기: `lanes.review`
- 시간·일 단위 원천 이력: `hourly_rankings`, `daily_aggregates`
- 기업 근거 보강 대기열: `ontology_enrichment_queue` (운영·검수 화면용, 순위 영향 없음)
- 전체 근거 작업 대기열: `enrichment_work_queue` (관련어·기업 각각 5개 충족 상태와 우선순위, 순위 영향 없음)
- 보조 플랫폼 문서 후보: `provider_keyword_candidate_queue` (지유님 알고리즘을 운영 원장에 맞게 이식한 검토 대기열, 자동 공개·순위 영향 없음)

프런트는 `unified_ranking`을 재정렬하거나 홈 10개를 자체 계산하지 않습니다.
백엔드는 전체 순위를 유지한 채 main 레인에 `main_rank`를 1부터 연속 부여하고,
그 앞 10개를 `trend_top10`으로 제공합니다. 기업이 0개여도 main 레인의 트렌드를
제거하거나 더 낮은 기업 준비 항목으로 교체하지 않습니다.

대표 사건·현상의 문맥을 해소하지 못한 `needs_context`·`unresolved`·`ambiguous_person`
항목은 분류 단계에서 `lanes.review`에 둡니다. 따라서 홈에서 다시 숨기는 별도
문맥 필터는 없으며, 문맥 증거가 생긴 뒤 다음 계산에서 main으로 분류될 수 있습니다.

`home_context_status`와 `home_context_reason`은 동음이의어·짧은 인물명 등 사건 맥락의
해결 여부만 나타냅니다. 기업 준비 여부는 `company_card_status`로 분리합니다.
`ready`는 URL 증거가 이어진 서로 다른 국내외 상장종목이 6개 이상인 경우,
`enrichment_pending`은 근거 보강 중인 경우, `not_applicable`은 이슈·민감 맥락 등
기업 연결 대상이 아닌 경우입니다. 기업 수를 맞추기 위한 padding은 금지하며,
준비된 항목만 `company_ready_trends`에도 포함합니다.
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
| 공정 순위 | `observed_rank`, `home_rank`, `rising_rank`, `score`, `score_components` |
| 원천 순위 | `latest_source_ranks`, `source_badge` |
| 기간 상태 | `candidate_status` (`is_current`/`period_observed`), `last_seen_at`, `freshness`, `hours_since_last_seen` |
| 변화·지속 | `previous_period_rank`, `rank_change`, `rank_change_status`, `rank_change_by_source`, `lifecycle`, `persistence_rank`, `momentum_rank` |
| 신뢰 상태 | `data_confidence`, `home_context_status`, `home_context_reason` |
| 관련어 | `keywords` (0~5), 원천 관측 또는 검수된 온톨로지 표현만 허용하고 `affects_score=false` |
| 기업 Gold | `companies` (0 또는 6개 이상) |
| 기업 역할 | `companies[].company_role_category`, `companies[].company_role_label` (제조·개발/원재료·핵심부품/콘텐츠 제작/배급·유통/판매·리테일/브랜드·마케팅/플랫폼·서비스/투자·소유/행사 후원·운영/산업 연관) |
| 관계 강도 | `companies[].relation_tier` (`direct`/`value_chain`/`industry_watch`) |
| 기업 카드 준비 상태 | `company_card_status`, `company_card_reason` |
| 기업 후보 감사 | `company_candidates`, `company_resolution` |
| 보조 검증 | `verification_layer` |
| 보조 검증 실행상태 | `verification_run` (`ranking_effect=none`) |
| 근거 보강 작업상태 | `enrichment_work_queue` (`ranking_effect=none`) |
| 보조 문서 키워드 후보 | `provider_keyword_candidate_queue` (`publishable=false`, 승인 전 칩 금지) |
| 기사 맥락 | `news_context` |
| 공식 기업개황 | `companies[].official_identity` (`provider=opendart`, 순위·관계 근거로 사용 금지) |

`news_context.affects_score`와 `news_context.ranking_source`는 항상 `false`입니다. 기사만으로 순위 항목을 생성하거나 점수를 바꾸지 않습니다.

## S# 종목화면 인계 경계

- `companies[].stock_code`와 `companies[].ticker`는 거래소 표기 종목 식별자입니다. KRX 상장사는 6자리 숫자, 해외 상장사는 문자·숫자 티커를 사용하며 `companies[].market`과 함께 해석합니다.
- 키움 S# 종목화면 인계는 현재 KRX 6자리 종목만 대상으로 합니다. 해외 종목은 프런트가 `market`을 확인해 S# CTA를 숨기거나 별도 해외주식 인계 정책을 적용해야 합니다.
- 정적 `live-data`는 로그인·계좌 개설·주문을 수행하지 않으며 인증정보도 보관하지 않습니다.
- 실제 S# 딥링크 URI, 비로그인 탐색 허용 범위, 매매 단계 인증은 키움 프런트·정책 의존사항입니다. 해당 정책 확인 전에는 종목화면 이동을 구현 완료로 표시하지 않습니다.

## 행동 측정 계약

MAU는 보조 지표로만 사용하고 다음 이벤트를 핵심 퍼널로 고정합니다.

| 이벤트 | 발생 조건 | 기본 집계 |
|---|---|---|
| `trend_card_impression` | 트렌드 카드가 화면에 유효 노출 | 사용자·세션·트렌드별 1회 |
| `trend_detail_view` | 트렌드 상세를 열람 | 사용자·세션·트렌드별 1회 |
| `company_card_click` | 관련기업 카드를 선택 | 사용자·세션·트렌드·종목별 1회 |
| `company_evidence_view` | 관계 근거를 열람 | 사용자·세션·트렌드·종목별 1회 |
| `kiwoom_symbol_open` | 키움 종목화면 인계를 요청 | 사용자·세션·종목별 1회 |

7일·30일 재방문은 동일 익명 사용자 키의 `trend_detail_view`가 최초 열람 후 해당 기간에 다시 발생했는지로 계산합니다. 현재 저장소에는 이벤트 수집·분석 서버가 없으므로 이는 측정 계약이며 실측 완료가 아닙니다.

## 밈트폴리오 목업 경계

밈트폴리오의 사용자 수·좋아요·수익률은 현재 프런트 목업이며 `live-data` 계약 밖입니다. 화면에 목업 라벨을 고정하고 실측 순위·기업 Gold·시장 참고값과 합치거나 실제 성과처럼 표현하지 않습니다. 데이터 묶음 실패 시 밈트폴리오나 다른 목업으로 트렌드 목록을 대체할 수 없습니다.

## 빈 상태 규칙

- 관련어 0개: 임의 키워드 칩을 만들지 않음
- `source=reviewed_ontology`: 별칭은 `status=approved_ontology_term`, 근거 기반 연관 개념은 `status=approved_ontology_related_term`으로 구분하고 `evidence_urls`를 함께 표시하며 순위에는 반영하지 않음
- `keywords[].role`은 온톨로지 관계를 설명하는 확장 가능한 문자열이므로 프론트가 고정 enum으로 분기하지 않음
- `approved_ontology_related_term`은 화면 설명용 근거이며, 그 용어를 다시 기업 탐색 시작점으로 사용하지 않음. 기업은 대표어·실제 관측 표현·검수된 동일어에서만 해석해 약한 다단계 연관 확장을 차단함
- `companies=[]`: 트렌드 카드는 유지하고 기업 CTA를 숨긴 뒤 `company_card_status=enrichment_pending`과 `company_resolution.reason` 표시
- `partial=true`: 실패한 출처와 마지막 관측시각 표시
- `ranking_availability.is_combined_rank=false`: 통합 순위라고 표현하지 않고 잠정 배지 표시
- 데이터 묶음 검증 실패: 목업 트렌드로 대체하지 않음
- 시장자료는 `market_reference.status=observed`일 때만 일별 참고값으로 표시
- 공식 기업개황은 `official_identity.status=verified`일 때만 법인명·영문명·설립일·공식 홈페이지를 표시하고, `relationship_evidence=false`를 관계 근거로 오해하지 않음
- `coverage.legacy_observed_rows`는 구형 수집기 보존행이며 차트·순위에 사용하지 않음

## 기간별 순위 계약

- 기본 기간: `ranking_default_period=daily`
- 기간 목록: `ranking_periods`를 `daily(24h)`, `weekly(168h)`, `monthly(720h)` 순서로 제공
- 기간별 결과: `ranking_views.{period}.unified_ranking`, `period_top10`, `window`, `data_readiness`
- 최상위 `unified_ranking`, `all_observed_ranking`은 24시간 전체 실측 순위이며 `trend_top10`, `public_top10`은 `home_top10` 호환 별칭

## 완성 트렌드 노출 팩

`latest/editorial-review.json`의 `trends` 배열은 완성 노출 계약을 모두 통과한
항목만 담습니다. manifest의
`compatibility_documents.editorial_review` 경로와 SHA로 읽습니다.

- 트렌드 후보: 실측 점수순 `main` 상위 30개 안에서 일반 제품 적합 규칙을 통과한 항목
- `related_keywords`: 트렌드마다 정확히 5개
- `company_candidates`: 해당 트렌드와의 개별 관계 자료가 확인된 국내외 상장사만 수록
- `음식`, `운전`, `애니` 같은 포괄어와 업종별 회사 채우기는 금지합니다.
- 회사마다 `reason`, `evidence_url`, `evidence_owner`, `evidence_type`,
  `verified_at`, `verification_status`, `company_description`을 제공합니다.
- 검증 기업이 6개 미만이거나 관련 키워드가 5개 미만이어도 자동 제품 적합 조건을
  통과한 트렌드는 유지합니다. 부족한 필드는 `enrichment_pending`으로 표시하며 임의로 채우지 않습니다.
- 미충족 후보를 빈 기업이나 임의 기업으로 채우는 것은 금지합니다.
- 키워드·기업 레지스트리는 자동 선발 뒤에만 사용하는 보강 캐시입니다. 등록 여부는
  원본 점수·순위, 레인, 제품 적합 판정, 상위 30개 진입에 영향을 주지 않습니다.
- 기본 화면은 `company_description_list`입니다. 검증 기업이 6개 이상으로
  많아질 때만 `company_display_policy.show_category_groups=true`로 제공하며,
  그 전에는 카테고리 탭을 만들지 않습니다.
- `review_status=unreviewed` 후보는 기존 `keywords`·`companies`에 자동 병합하지
  않습니다. 팀 승인 이후에만 공개 필드로 승격합니다.
- 이 후보 팩은 점수·순위에 영향을 주지 않으며 프론트가 사용하지 않아도 기존
  공개 계약은 그대로 동작합니다.
- 각 기간은 동일한 적격 `observed` X·Google 원장에서 **그 기간 안에 실제 관측된 모든 사건**을 후보로 사용함
- 점수는 `35 현재 관심 강도 + 25 실제 상승 속도 + 20 X·Google 교차 확산 + 10 관측 지속성 + 10 최신성`이며, 기업·분류 결과는 점수에 들어가지 않음
- 공식 버전은 `spread35_velocity25_breadth20_persistence10_recency10_v2`임
- 상승 속도는 해당 트렌드가 현재 비교면에서 서로 다른 시각에 최소 3회 관측돼야 계산되며, 0~2회면 `unavailable`·0점임
- 교차 확산 20점은 X와 Google 양쪽에서 같은 사건이 관측된 경우에만 부여하며 단일 출처는 0점임
- 기간강도는 출처별 정규화 위치의 `70% 신선도 가중 평균 + 30% 기간 최고점`을 출처 간 평균함
- 상승 속도는 직전 동일 길이 기간을 우선 비교하고, 비교 원장이 없으면 현 기간 전반부→후반부를 비교함. 양쪽 정상 스냅샷이 각각 3회 미만이면 `unavailable`·0점임
- 신선도 반감기는 선택 기간의 절반(일간 12시간, 주간 84시간, 월간 360시간)임
- `candidate_status=period_observed`는 현재 정각에는 없지만 선택 기간 안에서 관측된 사건임을 뜻하므로 `last_seen_at`·`freshness`를 함께 표시해야 함
- `rank_change`는 직전 동일 길이 기간 순위와의 차이이며 비교 원장이 없으면 `rank_change_status=unavailable_no_previous_period_coverage`로 표시함
- 60일 이력은 `new`·`rebounding` 생애주기 판별에만 사용하고 점수에는 반영하지 않음
- 기간 항목의 `detail_event_key`로 상세를 조회함. 기본 24시간 상세 목록 밖의 주간·월간 전용 사건은 `detail_status=period_summary_only`이며 근거 없는 기업·관련어를 생성하지 않음
- 기업 수와 기업 준비상태는 어떤 기간의 점수·순위·Top 10에도 영향을 주지 않음

프런트는 사용자가 기간 탭을 바꾸면 해당 `ranking_views`를 그대로 표시하고 자체 재계산하지 않습니다. `data_readiness.status`가 잠정이면 기간명 옆에 잠정 배지를 표시합니다.

정확한 기계 계약은 `schemas/intelligence-v3.schema.json`, `schemas/metadata-v3.schema.json`, `schemas/status-v1.schema.json`을 따릅니다.
## YouTube 콘텐츠 순위

- `youtube_content_ranking`: 대한민국 `mostPopular` 영상을 작품·곡·게임 단위로 병합한 전체 콘텐츠 순위
- `youtube_content_top10`: 콘텐츠 순위의 상위 10개
- `youtube_content_discovery.video_chart`: API 원본 영상 차트와 영상별 등락

YouTube 콘텐츠 순위는 `affects_x_google_rank=false`입니다. 프런트는 이 순위를 기존 `home_top10`의 점수나 등락과 혼용하면 안 됩니다.
