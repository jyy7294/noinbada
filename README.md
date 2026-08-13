# TRZIP — 한국 실시간 트렌드에서 관련 상장기업까지

TRZIP 백엔드는 찬희님 Windows 노트북에서 매시 정각 한국 X 실시간 트렌드 1~30위와 Google Trending Now 대한민국 전체 목록을 수집합니다. 실제 원천 표현을 누적해 전체 순위를 계산하고, 약한 큐레이션과 증거 온톨로지로 관련 상장기업을 연결합니다.

- 저장소: <https://github.com/jyy7294/noinbada>
- 공개 데이터: `live-data` 브랜치
- 실행 환경: 찬희님 노트북의 Codex 정각 자동화 + 로컬 Python
- 사용하지 않음: GitHub Actions, Render, Google RSS, Trends MCP 자동호출, X API, 생성·백필 데이터
- 프런트: 별도 교체 가능. 이 저장소의 JSON 계약만 준수

## 운영 흐름

```text
매시 00분 Codex 데스크톱 자동화
  ├─ 현재 로그인된 Chrome 세션을 직접 제어 → X 한국 1~30위
  └─ 로컬 Playwright Chrome → Google Trending Now KR 전체 페이지
          ↓
로컬 SQLite 실제 원장 (무기한 누적)
          ↓
대표어·사건 그룹 → 전체 순위 → 약한 표시 필터
          ↓
관련어 0~5 → 증거 온톨로지 → 상장기업 5개 Gold 게이트
          ↓
NAVER·YouTube·Instagram·기사 맥락 별도 검증 (순위 영향 없음)
          ↓
latest / observations / monitoring JSON을 live-data에 게시
```

노트북 종료·로그아웃 중 누락은 결측으로 남습니다. 생성값으로 메우지 않습니다.

## 수집 원칙

| 계층 | 입력 | 역할 |
|---|---|---|
| Core rank | X 한국 실시간 1~30 | 시간별 현재 관심 순위 |
| Core rank | Google Trending Now KR 전체 | 페이지 총건수까지 검증한 급상승 목록 |
| Context only | NAVER 뉴스·블로그 | 국내 문맥·기사 근거 |
| Context only | YouTube Data API | 한국·한국어 최근 콘텐츠 반응 |
| Context only | Instagram | 토큰이 있을 때만 검증, 현재 없으면 `unavailable` |
| Discovery only | 검수 기사 | 후보 발견·소비/제품화 설명 |

보조 원천은 `ranking_effect=none`으로 별도 SQLite 원장에 저장합니다. 기사만으로 순위에 항목을 넣지 않습니다.

## 순위

```text
최종점수 = 현재 원천별 정규화 위치 40%
         + 같은 원천의 정확한 직전 정각 대비 변화 20%
         + 원천별 반복 관측 지속성 × 96시간 성숙도 20%
         + 24시간 반감기의 과거 관측 영향 15%
         + 현재 X·Google 교차관측 5%
```

- `unified_ranking`: 현재 한 출처 이상에 존재하는 전체 후보, 제한 없음
- `trend_top10`: 점수를 다시 계산하지 않고 `main` 후보 중 앞 10개
- `public_top10`: 프런트 전환 기간에만 유지하는 `trend_top10` 동일 별칭
- `company_ready_trends`: 증거 기반 상장기업 5개 Gold까지 준비된 별도 목록
- `lanes.issue`: 정치·사건·재난·단순 기상특보·사생활 논란
- `lanes.review`: 아직 정체나 문화·소비 맥락을 식별하지 못한 표현
- `needs_context` 항목은 전체 순위에 보존하되 관련어·온톨로지·보조 검증·기사 맥락 중 하나가 생기기 전에는 홈 대표 목록에 올리지 않음
- 검수된 기업이 5개 미만이어도 Top10에서는 제거하지 않습니다. 기업 카드만 보류하고 보강 큐에 남깁니다.
- 96시간 전 순위: `provisional`; 96시간 누적 후 성숙한 지속성 점수

원시 검색량·게시량을 플랫폼 간 합산하지 않으며 카테고리·기사·기업 수는 점수에 영향을 주지 않습니다.

### v3 컷오버

이전 수집기 행은 삭제하지 않고 `legacy_observed_rows`로 보존합니다. 다만 X 1~30 및 Google Trending Now KR 전체 목록 완전성 게이트를 통과한 v3 수집기 행만 순위·지속성·일별 집계에 사용합니다. 서로 다른 수집 범위의 과거 행을 섞어 가짜 지속성을 만들지 않습니다.

## 대표어·관련어

- 화면 제목은 실제 X/Google 표현 중 현재 관측 여부 → 반복 시간 → 출처 수 → 역순위 근거 → 최고 순위로 선택합니다.
- 정규화 사건명은 그룹 키일 뿐 실제 제목을 임의 설명문으로 바꾸지 않습니다.
- 관련어는 동일 사건의 실제 원천 표현·Google 관련 검색어·URL 근거가 있는 검수 온톨로지 동의어만 최대 5개입니다.
- 근거가 없으면 0개가 정상입니다.
- NAVER·YouTube 문서에서 지유님 후보 추출 규칙으로 찾은 표현은 별도 검토 대기열에 누적하며, 승인 전에는 관련어 칩이나 순위에 넣지 않습니다.

## 관련기업 온톨로지

```text
관측 대표어 → 관측 관련어 → 개체·제품·인물·장소
            → 산업·가치사슬 → 기업 → 상장종목
```

모든 edge에 URL·근거 유형·기준일·검수상태가 있어야 합니다. 완결 경로를 가진 서로 다른 국내 상장기업이 5개 이상일 때만 `companies`로 공개합니다. 1~4개면 후보는 감사용으로 남기되 공개 Gold는 `ontology_incomplete`로 비웁니다. 기업을 채우기 위한 포털·플랫폼 일반론이나 업종 연상은 금지합니다.

5개에 못 미친 메인 트렌드는 `ontology_enrichment_queue`에 부족한 경로 수와 실제 관측 표현을 남깁니다. 이후 공식 기업자료·공시·검수된 기사·산업구조 근거를 추가하는 연구 대상이며, 큐 자체는 순위에 영향을 주지 않습니다.

기업 필드에는 관계 이유, 상장시장·종목코드, 경로상 산업 특성, 증거 출처, 온톨로지 경로, 일별 pykrx 참고자료가 포함됩니다. 투자 추천이나 상승 예측은 아닙니다.

## 설치

Python 3.13과 Google Chrome이 설치된 Windows 기준입니다.

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
powershell -ExecutionPolicy Bypass -File scripts\setup-local-runtime.ps1
```

정각 실행은 `%USERPROFILE%\.codex\automations\trzip\automation.toml`의 Codex 자동화가 담당합니다. X는 확장 프로그램이나 별도 브라우저 프로필이 아니라, 사용자가 현재 로그인해 둔 Chrome에서 직접 읽습니다. Chrome 또는 Codex가 종료된 시간은 실패·결측으로 남기며 이전 값을 현재 값처럼 재사용하지 않습니다.

즉시 실행:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\collect-hourly.ps1
```

운영 확인:

```powershell
.venv\Scripts\python.exe scripts\audit-runtime.py
```

운영 감사 결과는 `PASS`, `PROVISIONAL`, `FAIL` 중 하나입니다. X 미연결 또는 96시간 미만 누적은 숨기지 않고 `PROVISIONAL` blocker로 표시합니다. 발표·인수인계 전에는 `--require-combined`를 붙여 X·Google 통합과 96시간 누적을 필수 조건으로 검사합니다.

## 개발과 검증

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m trzip.local_pipeline `
  --output work\local-publication `
  --database work\local.sqlite3
```

환경변수는 [.env.example](.env.example)을 참고하십시오. 키·Chrome 프로필·SQLite·로그는 Git에 올리지 않습니다.

팀원 workbook과 연관키워드 과제의 선택 통합 근거는 [팀 산출물 통합 결정](docs/TEAM_WORK_INTEGRATION.md)에 기록했습니다. 다른 Codex는 먼저 [현재 검증 상태](CURRENT_STATE.json)를 읽고, 같은 운영 상태를 바로 이어받기 위한 경로·검증·복구 절차는 [Codex 연속 작업·운영 인수인계](docs/CODEX_CONTINUITY.md)를 따릅니다.

## 공개 계약

| 파일 | 내용 |
|---|---|
| `latest/manifest.json` | 새 프런트가 가장 먼저 읽는 단일 발행 포인터·파일 해시 |
| `latest/delivery/{publication_id}/rankings.json` | 카드용 경량 전체 순위·트렌드 Top 10·기업 준비 목록 |
| `latest/delivery/{publication_id}/trends/*.json` | 사건별 시계열·키워드·온톨로지·기업 근거 상세 |
| `latest/intelligence.json` | 전체 순위·홈 subset·키워드·기업·검증 맥락 |
| `latest/status.json` | 부분수집·출처별 상태·실행 측정 상태 |
| `latest/metadata.json` | 게시 ID·관측시각·수집 감사·누적 범위 |
| `latest/coverage.json` | 실제 SQLite 누적 범위 |
| `observations/YYYY-MM-DD.json` | 시간별 원천 행 |
| `monitoring/run_history.json` | 최근 168회 실행 이력 |

새 프런트는 `latest/manifest.json`을 먼저 읽고, manifest가 가리키는 불변 `delivery/{publication_id}` 묶음만 사용합니다. manifest는 모든 파일 작성과 해시 검증이 끝난 뒤 마지막에 교체되므로 실행 중단 때 서로 다른 시간의 파일이 섞이지 않습니다. 기존 프런트 호환을 위해 `intelligence.json`, `metadata.json`, `status.json`도 유지하며 세 문서의 `publication_id`, `generated_at`, 관측시각은 항상 같아야 합니다. 상세 명세는 [프런트 연동 계약](docs/FRONTEND_BACKEND_CONTRACT_V3.md), 기계 계약은 [schemas](schemas/)를 사용합니다.

### 60일 MVP 데모 리플레이

실제 새 원장이 60일 쌓이기 전 프런트의 순위·등락·지속성·상세 차트를 시험할 때는 `data/demo-replay-60d/latest/manifest.json`을 별도 데이터 원본으로 사용합니다. 전체 모드는 `demo_replay`, 화면 표시는 `7일 순위 시뮬레이션 데모`이며 최근 7일만 운영 Ranking V2와 같은 공식으로 점수를 계산하고 60일은 라이프사이클 기준선으로만 사용합니다. 행별 `observed`·`historical_reference`·`reconstructed_reference`·`synthetic_backfill`을 보존하며 라이브 SQLite와 `live-data/latest`에는 삽입하지 않습니다. 사건 시점만 복원한 `research_reconstructed` seed는 원본 비순위 `research-events.ndjson`과, 근거 공개일 이후 활성 기간에만 생성되는 데모 전용 합성 관측으로 분리합니다. 생성·연동 규칙은 [60일 MVP 데모 리플레이](docs/DEMO_REPLAY_60D.md)를 따릅니다.

## 현재 기술 스택

| 영역 | 기술 | 역할 |
|---|---|---|
| 수집·계산 | Python 3.13 | 정규화, 순위 V2, 온톨로지, 게시물 생성 |
| Google 수집 | Playwright + Chrome | Google Trending Now KR 전체 페이지 수집 |
| X 수집 | Codex 데스크톱 + 현재 로그인 Chrome | 한국 실시간 트렌드 1~30위 직접 수집 |
| 원장 | SQLite | 시간별 원문·순위·감사·검증 결과 누적 |
| 시장 참고값 | pykrx | 일별 종가·거래량 참고값; 순위와 기업 관계 근거에는 미사용 |
| 계약 검증 | JSON Schema + pytest | 프런트 묶음·점수·출처·기업 게이트 검증 |
| 운영 | PowerShell + Codex 자동화 | 매시 정각 파이프라인 실행·안전 게시 |
| 전달 | Git/GitHub `live-data` | 정적 JSON 버전 관리와 프런트 전달 |

FastAPI·상시 API 서버·PostgreSQL·Render는 현재 운영 스택이 아닙니다.

## 핵심 코드

```text
src/trzip/google_web_collector.py        Google KR 전체 페이지 수집
src/trzip/x_web_collector.py             X 1~30 inbox 완전성 검증
src/trzip/hourly_store.py                단일 SQLite 원장·시간/일 집계
src/trzip/intelligence.py                대표어·점수·큐레이션·기업 연결
src/trzip/ontology.py                    증거 그래프와 5개 공개 게이트
src/trzip/provider_verification.py       NAVER·YouTube·Instagram·기사 원장
src/trzip/keyword_candidates.py          보조 문서 키워드 검토 대기열
src/trzip/publication_pipeline.py        전체 E2E·계약 검증·정적 게시물
scripts/collect-hourly.ps1               정각 실행·live-data 안전 게시
```

## 아직 코드만으로 확정할 수 없는 것

- X 정각 수집에는 Codex 데스크톱 앱과 현재 Chrome의 X 로그인·대한민국 지역 상태가 필요합니다.
- NAVER 기존 키는 실제 인증 오류 상태이며 재발급 또는 애플리케이션 설정 확인이 필요합니다.
- Instagram 토큰이 없어 현재 `unavailable`입니다.
- 72회·168회 실측이 쌓이기 전에는 3일·7일 성공률을 완료로 표현하지 않습니다.
- 온톨로지 5개 미달 트렌드는 증거를 추가하기 전까지 기업 Gold가 비어 있습니다.
