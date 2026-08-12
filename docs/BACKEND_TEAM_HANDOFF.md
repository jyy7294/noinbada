# TRZIP 백엔드 팀원 인계서

## 1. 확정된 운영 구조

TRZIP의 시간별 계산 서버는 GitHub Actions·Render가 아니라 찬희님 Windows 노트북입니다.

```text
Windows 작업 스케줄러 · 매시 00분
  → 설치된 Chrome의 TRZIP 전용 프로필로 X 실시간 트렌드 페이지 확인
  → Google Trends RSS geo=KR 수집
  → 로컬 SQLite 누적
  → 사건 정규화·RRF 순위·기업 관계·계약 검증
  → live-data 브랜치에 공개 JSON만 push
  → Vercel 정적 프론트가 고정 URL로 조회
```

분리 원칙:

| 영역 | 위치 | 자동 변경 |
|---|---|---|
| 제품 코드 | `main` | 금지. 사람의 검토·커밋만 허용 |
| 런타임 | `%LOCALAPPDATA%\TRZIP` | SQLite·Chrome 세션·로그 |
| 공개 데이터 | `live-data` | `latest/`, `observations/`, `monitoring/`만 허용 |
| 사용자 밈트폴리오 | 브라우저 `localStorage` | 현재 기기에만 저장 |

X API와 X API 키는 사용하지 않습니다. X 실시간 페이지는 게시물 검색 API가 아니므로 관련 게시물·해시태그를 임의 생성하거나 API로 보강하지 않습니다.

## 2. 현재 구현 범위

- X 한국 실시간 페이지와 Google Trends KR 수집
- 소스별 성공·실패를 분리한 SQLite 저장과 같은 시간 재실행 멱등성
- 한 출처 실패 시 다른 출처와 같은 시간의 이전 정상 스냅샷 보존
- 전체 `unified_ranking`, 홈 `public_top10`, 지속기간순, 급상승순 산출
- 미확정 원천어도 순위에서 삭제하지 않고 `review_required`로 공개하되 기업 연결 차단
- 논란·범죄·재난 등 주의 항목을 이슈 레인으로 분리
- 실측 관련어와 운영자 후보어 분리; 근거가 없으면 키워드 0개
- 기업을 직접 관계·가치사슬·산업 관찰·연결 제외로 분리하고 팀 검수 상태 제공
- pykrx 일별 참고자료 연결. 관계 근거나 매수 추천에는 사용하지 않음
- 실행 상태·출처 실패 유형·72/168회 안정성 측정 JSON 발행
- 프론트의 실패·캐시·부분수집 상태, 실제 저장·재열기·내보내기 연결

## 3. 다음 팀원이 고칠 우선순위

### P0 — 사건 정규화

현재 규칙 사전에 없는 새 실시간 검색어는 `needs_context` 또는 `ambiguous_person`으로 남는 것이 정상입니다. 이를 억지로 해석하지 말고 검수 가능한 규칙으로 개선합니다.

1. 최근 실제 트렌드 20~30건을 개발 규칙과 분리해 사람이 라벨링합니다.
2. 사건명, 대분류, 동음이의어 보류 여부를 각각 평가합니다.
3. X·Google의 서로 다른 원천 표현을 같은 사건으로 묶을 때 실제 표현 근거를 남깁니다.
4. 일반명사·작품명·인물명이 불명확하면 `needs_context`를 유지합니다.
5. 설명 원인을 확인하지 못하면 `원인 미확인`으로 둡니다.

담당: `src/trzip/event_resolution.py`, `src/trzip/intelligence.py`, `config/normalization_holdout.json`

### P0 — 기업 근거 검수

1. 공식 홈페이지·IR·OpenDART 근거를 기업별로 보강합니다.
2. 공식 도메인이라는 이유만으로 해당 사건의 직접 관계라고 단정하지 않습니다.
3. `pending_evidence`와 `confirmed_relationship`가 동시에 나오지 않게 유지합니다.
4. 산업 대표기업은 `industry_structure_only`로만 표시합니다.
5. `config/company_review_overrides.json`의 `approved`, `rejected`, `needs_revision`을 팀 검수 결과로 사용합니다.

담당: `src/trzip/event_resolution.py`, `src/trzip/intelligence.py`, `src/trzip/value_chain.py`

### P1 — 관련 키워드 실측률

X 실시간 순위 페이지에는 게시물 근거가 없습니다. 따라서 현재는 다음만 허용합니다.

- X·Google 순위 원천에서 독립적으로 반복된 표현
- 승인된 별도 수집기가 전달한 문서에서 2건 이상 반복된 후보어
- 근거가 없으면 빈 배열과 `insufficient`

금지:

- X 최근 검색 API 추가
- Google RSS 전체의 무관한 제목을 한 사건의 관련어로 사용
- 사전 후보어를 `observed` 키워드로 승격

담당: `src/trzip/related_keywords.py`, `src/trzip/intelligence.py`

### P1 — 3~7일 운영 검증

`monitoring/run_history.json`을 기준으로 실제 실행을 측정합니다.

| 기록 수 | 상태 |
|---:|---|
| 0~71 | `collecting_baseline` |
| 72~167 | `measuring_3_to_7_days` |
| 168 이상 | `measured_7d` |

목표는 X·Google 각각 95% 이상입니다. 로그인 만료, 지역 미확인, 페이지 구조 변경, 네트워크 실패를 분리해 기록합니다. 168회 전에는 7일 안정성 완료라고 쓰지 않습니다.

## 4. 건드리면 안 되는 계약

- 순위 원천은 X 한국 실시간 페이지와 Google Trends KR만 사용
- Trends MCP 자동호출 금지
- YouTube·NAVER·Instagram을 순위 엔진에 추가하지 않기
- X API·유료 검색 API 추가 금지
- 생성·fixture 데이터를 `mode=live`에 넣지 않기
- KRX·키움 REST API 사용 금지
- pykrx 시장자료를 관계 증거·상승 예측으로 사용하지 않기
- 근거가 부족하다고 기업 3개·관계 범주 3개를 만들어내지 않기
- `unified_ranking`의 연속 순위와 원천 표현 삭제 금지
- 프론트의 레이아웃·색상·컴포넌트를 임의로 바꾸지 않기
- Z4·Z5 사전 제작 밈트폴리오 목업은 명시적 목업 상태로 유지
- 코드·비밀키·Chrome 프로필·SQLite를 `live-data`에 올리지 않기

## 5. 실행과 완료 조건

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m trzip.local_pipeline `
  --output work\team-e2e\publication `
  --database work\team-e2e\data.sqlite3
python -m json.tool work\team-e2e\publication\latest\intelligence.json > $null
python -m json.tool work\team-e2e\publication\latest\status.json > $null
```

완료 보고에는 다음을 분리합니다.

- 코드와 테스트 통과
- 실제 X·Google 동시 수집 여부
- 새 정답셋의 표본 수와 오답 목록
- 공식 검증 기업과 산업 관찰기업 수
- 실제 누적 실행 횟수와 출처별 성공률
- 아직 사람 검수가 필요한 항목

코드가 존재한다는 이유만으로 실데이터·정확도·7일 안정성까지 완료라고 표현하지 않습니다.
