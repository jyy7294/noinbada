# 팀 산출물 통합 결정

기준일: 2026-08-12

TRZIP 운영 저장소에는 같은 기능의 두 번째 파이프라인을 병합하지 않습니다. 팀 산출물은 근거와 검증 규칙을 현재 단일 생산 경로에 선택적으로 흡수합니다.

| 팀 산출물 | 반영 방식 | 생산 코드 판단 |
|---|---|---|
| `trend-meme-stock-cases (2).xlsx` | 과거 트렌드 298건과 근거 URL을 `data/ontology_seed.json`의 trend·term·evidence 노드로 변환 | 순위 입력 금지, 온톨로지 조회와 회귀 검증에만 사용 |
| `business-relationship-kospi-value-chain-FINAL (1).xlsx` | 24개 업종 구조와 명시적 기업·상장종목 관계를 evidence edge로 변환 | URL과 검수 상태가 없는 관계는 공개 금지 |
| `origin/jiyu`의 연관키워드 MVP | 원문 표현 정규화, 근거 보존, 역할 초안, 확인중 상태 원칙을 `intelligence._related_term_evidence()`에 흡수 | 별도 CSV/XLSX 수동 점수 파이프라인은 중복이므로 병합하지 않음 |
| `origin/inseong`의 과거 사례 workbook | 최신 사용자 제공본과 중복되는 사례 연구로 provenance에 반영 | 오래된 README와 출력 폴더 전체 병합은 금지 |

## 연관키워드 운영 규칙

- 후보는 X에 실제 함께 관측된 표현 또는 Google Trending Now가 제공한 관련 검색어만 사용합니다.
- 최대 5개이며 근거가 없으면 0개입니다.
- 역할은 `alias_or_variant`, `consumer_or_participation_signal`, `component_or_product`, `review_required`의 결정론적 초안입니다.
- 역할과 사람 검토 상태는 순위 점수에 영향을 주지 않습니다.
- 기사·NAVER·YouTube·Instagram 문서에서 새 후보를 발견해도 X 또는 Google 원문과 일치하기 전에는 순위나 공개 키워드로 승격하지 않습니다.

이 방식은 팀원이 만든 근거·규칙을 버리지 않으면서도, 프로덕트 저장소에 서로 다른 점수 체계와 수동 파일 파이프라인이 공존해 결과가 달라지는 문제를 막습니다.
