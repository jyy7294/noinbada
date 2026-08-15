# TRZIP — 한국 실시간 트렌드에서 관련 상장기업까지

TRZIP 백엔드는 설정된 Windows 수집 노드에서 매시 정각 한국 X 실시간 트렌드 1~30위와 Google Trending Now 대한민국 전체 목록을 수집합니다. 실제 원천 표현을 누적해 전체 순위를 계산하고, 결정론적 분류와 증거 온톨로지로 관련 상장기업을 연결합니다.

- 저장소: <https://github.com/jyy7294/noinbada>
- 공개 데이터: `live-data` 브랜치
- 실행 환경: 로그인된 Chrome을 사용할 수 있는 Windows 수집 노드 + Codex 정각 자동화 + Python
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
관련어 정확히 5개 → 증거 온톨로지 → 국내외 상장기업 10개 준비 게이트
          ↓
4시간마다 NAVER 뉴스·LLM/검수 핸드오프 보강 (순위 영향 없음)
          ↓
매일 06:00 KST 완성 카드 0~10개를 불변 publication으로 게시
```

노트북 종료·로그아웃 중 누락은 결측으로 남습니다. 생성값으로 메우지 않습니다.

## 수집 원칙

| 계층 | 입력 | 역할 |
|---|---|---|
| Core rank | X 한국 실시간 1~30 | 시간별 현재 관심 순위 |
| Core rank | Google Trending Now KR 전체 | 페이지 총건수까지 검증한 급상승 목록 |
| Context only | NAVER 뉴스 | 관측 후보의 촉발 사건·왜 지금 떴는지 설명, 순위 영향 없음 |
| Disabled | YouTube·Instagram·NAVER 블로그·검색트렌드 | 현재 홈 선발·점수·보강에서 사용하지 않음 |
| Discovery only | 공식 발표·검수 기사 | 후보의 소비·제품화 맥락 설명 |

기사만으로 관측 순위에 항목을 넣지 않습니다. NAVER 뉴스는 후보의 맥락 근거일 뿐 X·Google 점수와 순위를 바꾸지 않습니다.

## 순위

```text
기간별 점수 = 현재 관심 강도 35%
             + 실제 상승 속도 25%
             + X·Google 교차 확산 20%
             + 관측 지속성 10%
             + 최신성 10%
```

- `ranking_views`: 일간 24시간·주간 168시간·월간 720시간에 실제 관측된 전체 후보
- `unified_ranking`, `all_observed_ranking`: 최근 24시간 전체 실측 순위
- `home_feed`: 완성 계약을 통과한 카드를 `spreading`·`sustained`·`emerging`으로 제공하는 무순위 보드
- `presentation_feed`: 최근 24시간 실제 관측 후보 중 전체 완성 계약을 통과한 프런트 기본 배열(0~10개, 패딩 없음)
- `home_top10`: 이전 프런트 전환용 호환 배열
- `rising_top10`: 비교 가능한 구간에서 실제 양의 상승이 측정된 상위 10개
- `trend_top10`, `public_top10`: 호환성을 위한 `home_top10` 동일 별칭
- `company_ready_trends`: 증거 기반 상장기업 10개 이상 준비된 별도 목록
- `lanes.issue`: 정치·사건·재난·단순 기상특보·사생활 논란
- `lanes.review`: 아직 정체나 문화·소비 맥락을 식별하지 못한 표현
- `needs_context` 항목은 전체 순위에 보존하되 관련어·온톨로지·보조 검증·기사 맥락 중 하나가 생기기 전에는 홈 대표 목록에 올리지 않음
- 자동 선발 순위는 기업 수와 독립적으로 유지합니다. 다만 프런트 공개 카드는 `main` 레인, URL 근거가 있는 `why_now`, 관련 키워드 정확히 5개, 검수된 상장기업 정확히 10개, 역할 카테고리 2~4개, 기업과 연결되는 서로 다른 키워드 2개 이상을 모두 충족해야 합니다.
- 최근 24시간 중 실제 관측된 시각만 계산에 사용합니다. 결측 시각이 있어도 공개를 막지 않지만 시각 수와 목록을 감사에 남기며 이전 값 재사용·보간·생성으로 메우지 않습니다.

관측 순위의 관심 강도는 X와 Google의 원천 순위를 각각 정규화해 같은 비중으로 계산합니다. NAVER 뉴스·키워드·기업·LLM 문구는 점수와 순위를 바꾸지 않습니다. 상승 속도는 직전 동일 기간을 우선 비교하고, 불가능하면 현 기간 전반부와 후반부를 비교합니다. 정상 스냅샷이 부족하면 `unavailable`·0점이며 중립점수를 주지 않습니다. 원시 검색량·게시량을 플랫폼 간 직접 합산하지 않고 각 플랫폼 안에서 정규화합니다. 카테고리·기업 수는 점수에 영향을 주지 않습니다.

### v3 컷오버

이전 수집기 행은 삭제하지 않고 `legacy_observed_rows`로 보존합니다. 다만 X 1~30 및 Google Trending Now KR 전체 목록 완전성 게이트를 통과한 v3 수집기 행만 순위·지속성·일별 집계에 사용합니다. 서로 다른 수집 범위의 과거 행을 섞어 가짜 지속성을 만들지 않습니다.

## 대표어·관련어

- 화면 제목은 실제 X/Google 표현 중 현재 관측 여부 → 반복 시간 → 출처 수 → 역순위 근거 → 최고 순위로 선택합니다.
- 정규화 사건명은 그룹 키일 뿐 실제 제목을 임의 설명문으로 바꾸지 않습니다.
- 관련어는 동일 사건의 실제 원천 표현·Google 관련 검색어·URL 근거가 있는 검수 온톨로지 동의어만 최대 5개입니다.
- 근거가 없으면 0개가 정상입니다.
- NAVER 뉴스에서 찾은 표현은 맥락 후보로만 보존하며, 원천 관련어 또는 검수 근거가 없으면 관련어 칩이나 순위에 넣지 않습니다.

## 관련기업 온톨로지

```text
관측 대표어 → 관측 관련어 → 개체·제품·인물·장소
            → 산업·가치사슬 → 기업 → 상장종목
```

모든 edge에 URL·근거 유형·기준일·검수상태가 있어야 합니다. 완결 경로를 가진 서로 다른 국내외 상장기업이 10개 이상이고 역할 카테고리가 2~4개일 때 `companies`가 준비 완료입니다. 0~9개면 검증 후보는 보존하되 기업 카드는 `enrichment_pending`으로 표시합니다. 기업을 채우기 위한 무근거 단어 연상은 금지합니다.

10개에 못 미친 메인 트렌드는 `ontology_enrichment_queue`에 부족한 경로 수와 실제 관측 표현을 남깁니다. 이후 공식 기업자료·공시·검수된 기사·산업구조 근거를 추가하는 연구 대상이며, 큐 자체는 순위에 영향을 주지 않습니다.

기업 필드에는 관계 이유, 상장시장·종목코드, 경로상 산업 특성, 증거 출처, 온톨로지 경로, 국내 pykrx·해외 Yahoo Finance의 실제 일별 참고자료가 포함됩니다. 투자 추천이나 상승 예측은 아닙니다.

## 설치

Python 3.13과 Google Chrome이 설치된 Windows 기준입니다.

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
powershell -ExecutionPolicy Bypass -File scripts\setup-local-runtime.ps1
```

새 Windows PC를 수집 노드로 구성할 때는 환경·`live-data`·Codex 정각 자동화와
전체 테스트를 한 번에 구성하는 부트스트랩을 사용합니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap-new-pc.ps1 `
  -TargetThreadId "현재 Codex 작업 ID"
```

X 로그인 쿠키와 GitHub 인증은 저장소에 포함하지 않습니다. 최초 로그인과 실제
수집 검증까지 포함한 절차는 [새 Windows PC 설치](docs/PORTABLE_WINDOWS_SETUP.md)를
따릅니다. 결과만 소비하는 PC는 `live-data/latest/manifest.json`을 바로 읽을 수 있습니다.

정각 실행은 `%USERPROFILE%\.codex\automations\trzip\automation.toml`의 Codex 자동화가 담당합니다. X는 확장 프로그램이나 별도 브라우저 프로필이 아니라, 사용자가 현재 로그인해 둔 Chrome에서 직접 읽습니다. Chrome 또는 Codex가 종료된 시간은 실패·결측으로 남기며 이전 값을 현재 값처럼 재사용하지 않습니다.

즉시 실행:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\collect-hourly.ps1
```

운영 확인:

```powershell
.venv\Scripts\python.exe scripts\audit-runtime.py
```

운영 감사 결과는 `PASS`, `PROVISIONAL`, `FAIL` 중 하나입니다. 발표·인수인계 전에는 X·Google의 마지막 성공시각, 최근 24시간 실제 관측시간 수·결측시간, 프런트 v4 계약 성공, 해당 일일 공개본의 원격 영수증을 함께 확인합니다. 일부 결측과 06:00 정각의 단일 출처 공백은 허용하지만, 최근 24시간 안에 X·Google이 각각 최소 한 번 완전하게 관측됐고 재사용·보간·생성 행이 없을 때만 원격 최신본을 교체합니다.

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
| `latest/delivery/{publication_id}/rankings.json` | 카드용 경량 전체 순위·완성 트렌드 0~10개·기업 준비 목록 |
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
| 시장 참고값 | pykrx·Yahoo Finance | 국내외 상장종목의 실제 일별 가격·거래량·공개 밸류에이션 참고값; 순위와 기업 관계 근거에는 미사용 |
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
src/trzip/ontology.py                    증거 그래프와 10개 준비 게이트
src/trzip/provider_verification.py       NAVER 뉴스 맥락 원장
src/trzip/processing_cycle.py            24시간 관측 커버리지·4시간 보강 체크포인트
src/trzip/enrichment_handoff.py          LLM/사람 보강 후보의 불변 인계·검증
src/trzip/keyword_candidates.py          보조 문서 키워드 검토 대기열
src/trzip/publication_pipeline.py        전체 E2E·계약 검증·정적 게시물
scripts/collect-hourly.ps1               정각 실행·live-data 안전 게시
```

## 아직 코드만으로 확정할 수 없는 것

- X 정각 수집에는 Codex 데스크톱 앱과 현재 Chrome의 X 로그인·대한민국 지역 상태가 필요합니다.
- NAVER 뉴스 보강은 인증정보뿐 아니라 런타임 보강 플래그가 켜져야 실행됩니다. 비활성·인증실패여도 X·Google 원천 순위는 계속 계산합니다.
- LLM 보강은 실행 연결값이 없으면 불변 인계 파일로 대기하며 Python 점수·순위를 바꾸지 않습니다.
- 실제 MAU, 키움 S# 딥링크·관심기업 계정 저장, 실시간 시장자료 공급자 연동은 코드만으로 완료했다고 볼 수 없습니다.
- 온톨로지 10개 미달 트렌드는 후보로 유지되며 증거를 추가하기 전까지 기업 카드와 프런트 완성 목록이 보강 대기 상태입니다.
