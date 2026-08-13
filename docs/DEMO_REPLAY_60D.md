# TRZIP 60일 MVP 데모 리플레이

## 목적

새 수집기의 실제 원장이 60일 쌓이기 전에도 프론트의 순위·등락·지속성·상세 차트를 시험할 수 있게 하는 별도 데이터 묶음입니다. 운영 데이터가 아니며 화면과 발표에서는 반드시 **7일 순위 시뮬레이션 데모**로 표시하고, 60일은 라이프사이클 기준선이라고 설명합니다.

## 데이터 구분

| 행별 `provenance` | 뜻 | 실측 주장 | 라이브 순위 반영 |
|---|---|---:|---:|
| `observed` | 현재 수집기 계약으로 실제 관측한 행 | 가능 | 데모 안에서만 계산, 운영 원장에는 미삽입 |
| `historical_reference` | 구형 수집기·과거 DB에서 가져온 참고 관측 | 구형 자산임을 밝혀서만 가능 | 없음 |
| `reconstructed_reference` | 별도 연구 JSONL에서 가져온 재구성 참고값 | 불가 | 없음 |
| `synthetic_backfill` | 빈 구간을 채운 결정론적 합성 행 | 불가 | 없음 |

- 전체 기간: 60일
- 순위 점수 구간: 최근 7일
- 순위 보기: `daily` 24시간(기본), `weekly` 7일, `monthly` 30일
- 라이프사이클 기준선과 차트: 60일
- 계산식: 운영 기간 집계와 동일한 `spread35_velocity25_breadth20_persistence10_recency10_v2`
- 출력 모드: `demo_replay`
- 운영 영향: `ranking_effect=none`, `live_eligible=false`

`rankings.json`의 `views.daily`, `views.weekly`, `views.monthly`는 동일한 트렌드 상세·키워드·기업을 공유하면서 기간별 `rank`, `score`, `rank_change`, `score_change`를 제공합니다. 비교 기준은 바로 앞의 동일 길이 구간입니다. 기존 프론트 호환을 위해 최상위 `unified_ranking`, `trend_top10`, `public_top10`은 `views.weekly`의 정확한 별칭입니다.

구형 운영 원장의 Google 128행과 X 423행은 합계 551행을 삭제하지 않고 최신 `trzip-observation-v1` 행으로 변환합니다. 원래 `observed_at`·`topic`·`raw_rank`·`value`는 보존하고, `region`·`event_key`처럼 계산 가능한 값은 `derived`, 원래 수집하지 않은 payload·관련어·seed 시각은 `not_collected`, 알 수 없는 수집기 버전은 `unknown`으로 `field_lineage`에 표시합니다. 동일 시각·출처에 같은 순위가 여러 개면 `raw_rank → event_key → topic → stable row id` 순으로 정렬해 `resolved_rank`를 부여합니다. `raw_rank`는 바꾸지 않습니다.

별도 연구 재구성 입력은 두 종류를 지원합니다. 플랫폼·순위까지 재구성한 행은 JSONL 한 줄당 `observed_at`, `source`, `topic`, `raw_rank`, `provenance=reconstructed_reference`를 제공할 수 있습니다. 사건 시점만 근거로 복원한 seed는 원본 sidecar에서 `provenance=research_reconstructed`, `measurement_status=event_timing_evidence_only`, `rank_eligible=false`를 유지합니다.

사건 seed는 데모 차트를 재생할 때만 `synthetic_backfill` 관측으로 펼칩니다. 시작일은 `max(active_from, 해당 시점까지 공개된 가장 이른 evidence.published_at)`이며 `active_to` 뒤에는 생성하지 않습니다. 따라서 미래 기사를 과거 순위에 사용하는 look-ahead와 만료 사건의 현재 순위 부활을 막습니다. 합성 행은 `reference_kind=research_seed_simulation`, `measurement_status=synthetic_not_measured`, `ranking_eligible=false`, `demo_ranking_eligible=true`, `live_eligible=false`입니다. X·Google 양쪽에서 실제 관측됐다는 뜻이 아니며, 해시 기반 기본 단일 source 슬롯과 peak 인근 일부 교차 슬롯만 사용합니다. 운영 원장에는 절대 적재하지 않습니다.

```powershell
py -3.13 scripts/build-demo-replay.py --research-input work/research-reconstruction.jsonl
```

## 생성

```powershell
py -3.13 scripts/build-demo-replay.py
```

고정 시점으로 재현하려면 다음처럼 실행합니다.

```powershell
py -3.13 scripts/build-demo-replay.py --as-of 2026-08-12T23:00:00+00:00
```

출력은 `data/demo-replay-60d/latest` 아래에 생성됩니다.

```text
latest/manifest.json
latest/replay.json
latest/delivery/{publication_id}/rankings.json
latest/delivery/{publication_id}/observations.ndjson
latest/delivery/{publication_id}/research-events.ndjson
latest/delivery/{publication_id}/trends/*.json
```

프론트는 운영 `live-data/latest/manifest.json`과 데모 경로를 환경 설정으로 분리해야 합니다. 데모 파일을 운영 `latest`에 복사하거나 라이브 SQLite에 적재하면 안 됩니다.
