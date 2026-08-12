# TRZIP 백엔드 팀원 인계서

## 0. 2026-08-12 후속 구현 결과

이 문서의 A~E 요구사항을 `codex/noinbada-backend-handoff`에서 다음과 같이 반영했습니다.

| 우선순위 | 구현 결과 | 검증 상태 |
|---|---|---|
| A 사건 클러스터링 | NFKC, 선행 해시태그, 언더스코어, 연속 공백, 영문 대소문자를 정규화하고 명시적 별칭·공백 제거 일치만 병합합니다. 미등록 일반어는 `needs_context`, 한국인명 형태는 보수적으로 `ambiguous_person`에 둡니다. | 별도 단위 변형 테스트와 최근 실측 고정 평가셋 통과. 새로운 미관측 사건 전체의 일반화 성능을 뜻하지 않음 |
| B 관련 키워드 | X와 Google KR RSS 모두 문서 단위로 중복을 제거하고 서로 다른 문서 2건 이상에서 반복된 표현만 `observed`로 냅니다. 실측 키워드와 운영자 후보는 `keywords`와 `keyword_candidates`로 분리합니다. | 단위·통합 테스트 통과. X 실데이터는 토큰이 있는 실행 환경에서 별도 검증 필요 |
| C 기업 근거·승인 | HTTPS 공식 근거와 관계 강도를 함께 검증해 `official_evidence`, `pending_evidence`, `industry_structure_only`, `excluded`로 분리합니다. 팀 승인 JSON에는 세 허용 상태만 입력할 수 있습니다. | 모든 출력 기업에 관계 표시와 팀 검수 상태를 강제하는 계약 검사 추가 |
| D 정규화 평가 | `noinbada/live-data`의 2026-08-12 실제 X·Google Trends KR 관측에서 24건을 별도 라벨링해 고정하고, 독립 실행 스크립트와 정확도·위험 오연결·오답 JSON을 추가했습니다. | 사건명 100%, 대분류 100%, 보류 100%, 위험 오연결 0건. 해당 24건 고정 평가 결과 |
| E 수집 안정성 | 시간 슬롯 중복 갱신을 유지하면서 출처별 실패를 인증·쿼터·네트워크·파서·기타로 집계하고, 168회 전에는 95% 목표 달성으로 표시하지 않습니다. | 로컬 실제 Google KR RSS 10건 수집 성공. X 미설정. 3일·7일 수치는 시간 경과 전 미완료 |

평가 보고서는 `python scripts/evaluate-normalization.py --output work/normalization-evaluation.json`으로 재생성합니다. 운영 파이프라인은 `latest/normalization_evaluation.json`에도 같은 고정 평가 결과를 게시합니다.

## 1. 현재 구현 완료 범위

- X 한국 실시간·Google Trends KR 시간별 수집과 `live-data` 브랜치 게시
- 생성 데이터가 운영 순위에 들어가지 못하도록 계약 검증
- 30건 수동 기준셋 기반 사건명·동음이의어 1차 정규화
- 출처에 맞는 설명 생성: X 단독, Google 단독, 교차출처를 구분
- 통합점수 구성요소(`score_components`) 공개
- 관련 키워드의 `observed / insufficient` 상태와 실패 사유 공개
- 기업 관계를 `직접 관계 / 가치사슬 / 산업 관찰 / 연결 제외`로 분리
- `config/company_review_overrides.json`을 통한 팀 검수 상태 분리
- pykrx 일별 종가·등락률·거래량 참고정보 연결
- 168회 기준 수집 성공률·출처별 성공률·15분 이내 시작률 누적
- 프론트는 기존 UI를 유지하며 위 필드를 표시
- Z4·Z5 밈트폴리오의 사용자명·좋아요·수익률은 의도된 발표 목업

## 2. 팀원이 고칠 백엔드 범위와 구현 기준

### A. 사건 클러스터링 고도화 — 최우선

현재는 명시적 별칭과 30건 기준셋 중심입니다. 다음을 추가합니다.

1. 띄어쓰기·해시태그·영문/한글 표기 정규화
2. X와 Google의 서로 다른 표현을 같은 사건으로 묶기
3. 작품명·인물명·일반명사의 동음이의어 판별
4. 원인을 확인할 근거가 없으면 `원인 미확인` 유지
5. 원문 근거 없이 사건 원인을 생성하지 않기

담당 파일: `src/trzip/event_resolution.py`, `src/trzip/intelligence.py`

### B. 관련 키워드 실측률 개선

현재 후보어는 순위 근거가 아니며, 실제 반복 관측이 없으면 `insufficient`입니다.

1. X 최근 게시물의 해시태그·복합명사 공동출현 개선
2. Google Trends RSS 항목 제목·설명에서 사건별 표현 추출
3. 최소 2회 이상 반복된 표현만 `observed` 승격
4. 키워드가 없으면 빈 배열과 실패 사유 유지
5. 후보어를 실측 키워드로 위장하지 않기

담당 파일: `src/trzip/related_keywords.py`, `src/trzip/intelligence.py`

### C. 기업 근거 검증과 팀 승인

1. 공식 홈페이지·IR·OpenDART 근거를 기업별로 보강
2. 사건 직접 관계와 업종 대표기업을 분리
3. `산업 관찰` 기업을 수혜 예상기업으로 표현하지 않기
4. `config/company_review_overrides.json`에 `approved`, `rejected`, `needs_revision` 기록
5. 승인되지 않은 기업도 노출할 수 있지만 반드시 `팀 미검수` 표시 유지

담당 파일: `src/trzip/intelligence.py`, `src/trzip/value_chain.py`, `config/company_review_overrides.json`

검수 키 형식:

```json
{
  "회사명|근거URL": "approved"
}
```

### D. 정규화 정확도 평가

현재 `normalization_evaluation`은 기준셋과 현재 수집 결과가 겹친 항목만 평가합니다. 일반화 성능으로 과장하면 안 됩니다.

1. 팀원이 최근 실제 트렌드 20~30건을 별도 라벨링
2. 개발 규칙을 수정하기 전에 평가셋을 고정
3. 사건명 정확도, 카테고리 정확도, 동음이의어 보류 정확도를 각각 측정
4. 오답 목록을 JSON으로 남기기
5. 최소 목표: 사건명 85%, 대분류 90%, 위험한 오연결 0건

### E. 3~7일 수집 안정성 측정

`live-data/monitoring/run_history.json`은 시간별 성공 여부를 최대 168회 보존합니다.

1. 72회 전에는 `collecting_baseline`
2. 72~167회는 `measuring_3_to_7_days`
3. 168회부터 `measured_7d`
4. X·Google 각각 성공률 95% 이상 목표
5. 실패 시 원인을 API 인증, 쿼터, 네트워크, 파서 변경으로 구분

## 3. 건드리면 안 되는 계약

- 운영 트렌드 원천은 X와 Google Trends만 사용
- Trends MCP 자동호출 금지
- YouTube·NAVER·Instagram을 순위 엔진에 추가하지 않기
- 생성·fixture 데이터를 `mode=live`에 넣지 않기
- KRX·키움 REST API 사용 금지
- 시장가격은 관계 근거나 상승 예측으로 사용하지 않기
- Z4·Z5 밈트폴리오 목업 제거 금지
- `frontend/`, `design/`의 레이아웃·색상·컴포넌트 변경 금지
- `unified_ranking` 연속 순위와 기존 필드 삭제 금지

## 4. 완료 조건

- `python -m pytest -q` 전체 통과
- 실데이터 파이프라인 1회 성공
- 단일출처 설명에 존재하지 않는 플랫폼명이 나오지 않음
- `피의 게임`이 `screen_content`로 분류됨
- 키워드 0건과 수집 실패가 명시적으로 구분됨
- 모든 기업에 `relation_display_type`, `team_review_status` 존재
- 모니터링 파일이 시간별로 누적되고 중복 실행은 같은 시간 슬롯을 갱신
- README와 데이터 계약 문서가 변경 스키마를 반영

## 5. 실행 명령

```powershell
python -m pytest -q
python -m trzip.github_pipeline --output work\team-e2e --retention-days 104
python -m json.tool work\team-e2e\latest\intelligence.json > $null
```

