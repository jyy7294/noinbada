# TRZIP — 한국 실시간 트렌드에서 관련 상장기업까지

TRZIP 백엔드는 찬희님 Windows 노트북에서 매시 정각 한국 X 실시간 트렌드 1~30위와 Google Trending Now 대한민국 전체 목록을 수집합니다. 실제 원천 표현을 누적해 전체 순위를 계산하고, 약한 큐레이션과 증거 온톨로지로 관련 상장기업을 연결합니다.

- 저장소: <https://github.com/jyy7294/noinbada>
- 공개 데이터: `live-data` 브랜치
- 계산 서버: 찬희님 노트북의 Windows 작업 스케줄러
- 사용하지 않음: GitHub Actions, Render, Google RSS, Trends MCP 자동호출, X API, 생성·백필 데이터
- 프런트: 별도 교체 가능. 이 저장소의 JSON 계약만 준수

## 운영 흐름

```text
매시 00분 Windows 작업 스케줄러
  ├─ 마지막으로 사용한 로그인 Chrome 프로필의 MV3 확장 → X 한국 1~30위
  └─ 공개 Chrome 자동화 → Google Trending Now KR 전체 페이지
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
최종점수 = 최신 원천 순위 정규화 RRF 60%
         + 직전 대비 원천 순위 위치 변화 20%
         + 반복 관측 지속성 × 96시간 성숙도 15%
         + 현재 X·Google 교차관측 5%
```

- `unified_ranking`: 현재 한 출처 이상에 존재하는 전체 후보, 제한 없음
- `public_top10`: 점수를 다시 계산하지 않고 맥락 근거와 증거 기반 상장기업 5개 게이트를 통과한 `main` 후보 중 앞 10개
- `lanes.issue`: 정치·사건·재난·단순 기상특보·사생활 논란
- `lanes.review`: 아직 정체나 문화·소비 맥락을 식별하지 못한 표현
- `needs_context` 항목은 전체 순위에 보존하되 관련어·온톨로지·보조 검증·기사 맥락 중 하나가 생기기 전에는 홈 대표 목록에 올리지 않음
- 검수된 기업이 5개 미만이면 억지로 채우지 않고 전체 순위·보강 큐에 남기며 홈 목록은 10개 미만일 수 있음
- 96시간 전 순위: `provisional`; 96시간 누적 후 성숙한 지속성 점수

원시 검색량·게시량을 플랫폼 간 합산하지 않으며 카테고리·기사·기업 수는 점수에 영향을 주지 않습니다.

### v3 컷오버

이전 수집기 행은 삭제하지 않고 `legacy_observed_rows`로 보존합니다. 다만 X 1~30 및 Google Trending Now KR 전체 목록 완전성 게이트를 통과한 v3 수집기 행만 순위·지속성·일별 집계에 사용합니다. 서로 다른 수집 범위의 과거 행을 섞어 가짜 지속성을 만들지 않습니다.

## 대표어·관련어

- 화면 제목은 실제 X/Google 표현 중 반복 시간 → 출처 수 → RRF → 최고 순위로 선택합니다.
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
powershell -ExecutionPolicy Bypass -File scripts\install-hourly-task.ps1
powershell -ExecutionPolicy Bypass -File scripts\setup-x-chrome.ps1
```

마지막 명령은 Chrome이 기록한 마지막 사용 로그인 프로필의 `chrome://extensions`와 확장 폴더를 엽니다. 개발자 모드 → 압축해제된 확장 프로그램 로드 → `chrome-extension/trzip-x-current-session` 선택을 한 번만 수행합니다. 특정 표시 이름을 명시해야 할 때만 `-ProfileName "이름"`을 붙입니다. 확장은 쿠키·저장소 권한 없이 자신이 연 비활성 X 탭의 1~30위만 저장합니다.

즉시 실행:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\collect-hourly.ps1
```

작업 확인:

```powershell
Get-ScheduledTask -TaskName "TRZIP X Google Hourly Collector"
Get-ScheduledTaskInfo -TaskName "TRZIP X Google Hourly Collector"
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
| `latest/intelligence.json` | 전체 순위·홈 subset·키워드·기업·검증 맥락 |
| `latest/status.json` | 부분수집·출처별 상태·실행 측정 상태 |
| `latest/metadata.json` | 게시 ID·관측시각·수집 감사·누적 범위 |
| `latest/coverage.json` | 실제 SQLite 누적 범위 |
| `observations/YYYY-MM-DD.json` | 시간별 원천 행 |
| `monitoring/run_history.json` | 최근 168회 실행 이력 |

프런트는 세 `latest` 문서의 `publication_id`, `generated_at`, 관측시각이 모두 같은 묶음만 표시해야 합니다. 상세 명세는 [프런트 연동 계약](docs/FRONTEND_BACKEND_CONTRACT_V3.md), 기계 계약은 [schemas](schemas/)를 사용합니다.

## 핵심 코드

```text
chrome-extension/trzip-x-current-session/ 현재 로그인 X 세션 수집 확장
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

- 마지막으로 사용한 로그인 Chrome 프로필에 확장을 한 번 수동 설치해야 X 자동수집이 시작됩니다.
- NAVER 기존 키는 실제 인증 오류 상태이며 재발급 또는 애플리케이션 설정 확인이 필요합니다.
- Instagram 토큰이 없어 현재 `unavailable`입니다.
- 72회·168회 실측이 쌓이기 전에는 3일·7일 성공률을 완료로 표현하지 않습니다.
- 온톨로지 5개 미달 트렌드는 증거를 추가하기 전까지 기업 Gold가 비어 있습니다.
