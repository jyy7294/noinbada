# TRZIP — 한국 실시간 트렌드에서 관련 기업까지

TRZIP은 한국의 **X 실시간 트렌드 페이지**와 **Google Trends KR**을 매시간 수집하고, 원천 순위를 사건·현상으로 정규화한 뒤 가치사슬 기업 탐색까지 연결합니다.

> 주식도 트렌드가 된 시대, 내가 아는 유행에서 기업을 찾다.

- 저장소: <https://github.com/jyy7294/noinbada>
- 프론트: <https://trzip-x-google.vercel.app>
- 운영 데이터: `live-data` 브랜치의 정적 JSON
- 자동 실행: 찬희님 노트북의 Windows 작업 스케줄러
- GitHub Actions 시간별 실행: 사용하지 않음
- Trends MCP 자동 실행: 사용하지 않음
- X API·X API 키: 사용하지 않음

## 1. 현재 운영 구조

```text
Windows 작업 스케줄러 · 매시 00분
        ↓
설치된 Google Chrome + 전용 프로필
  └─ X /explore/tabs/trending (한국 지역 확인)
Google Trends RSS geo=KR
        ↓
로컬 SQLite 원장 (%LOCALAPPDATA%\TRZIP)
        ↓
정규화 → RRF 순위 → 상태 → 관련기업 → 계약 검증
        ↓
별도 live-data Git worktree에 JSON만 커밋·푸시
        ↓
Vercel 정적 프론트가 최신 JSON 조회
```

코드, 런타임, 공개 데이터를 분리합니다.

| 구분 | 위치 | 내용 |
|---|---|---|
| 제품 코드 | `main` | 팀원이 수정·검토하는 소스코드 |
| 로컬 런타임 | `%LOCALAPPDATA%\TRZIP` | Chrome 세션, SQLite, 로그, 게시 준비물 |
| 공개 데이터 | `live-data` | `latest/`, `observations/`, `monitoring/` JSON만 저장 |
| 사용자 저장 | 브라우저 `localStorage` | 사용자가 만든 밈트폴리오 |

노트북이 종료되거나 사용자가 로그아웃한 동안에는 수집할 수 없습니다. 누락 시간을 생성 데이터로 메우지 않고 실패·누락 상태로 남깁니다.

## 2. 데이터 원칙

### 원천명과 해석 분리

```json
{
  "display_name": "말복",
  "raw_terms": ["말복"],
  "phenomenon_summary": "말복을 앞두고 삼계탕·보양식 관련 관심 증가",
  "context_status": "resolved_reference"
}
```

- 제목은 원천 대표어를 유지합니다. `말복`을 임의의 긴 사건명으로 바꾸지 않습니다.
- 동의어나 실제 함께 관측된 표현은 `raw_terms`에 남깁니다.
- 원인을 확인하지 못하면 `원인 미확인`과 `review_required`를 표시합니다.
- 논란·범죄·재난 등은 순위 원장에는 남지만 기업 연결에서 제외합니다.
- 키워드 증거가 없으면 0개가 정상입니다. 운영자 후보어를 실측 키워드로 표시하지 않습니다.

### 실측과 재구성 데모 분리

- `provenance=observed`: 실제 X·Google 관측
- `provenance=generated`: 2026-05-01~2026-08-12 시연용 결정론적 재구성

라이브 모드에는 `generated` 행이 들어갈 수 없습니다. Z4·Z5 밈트폴리오의 좋아요·수익률은 의도된 발표 목업이며 트렌드·기업 실측과 분리됩니다.

## 3. 순위와 화면 노출

```text
통합 점수 = 60% 최신 원천 순위 RRF
          + 20% 모멘텀
          + 15% 지속성
          +  5% X·Google 교차관측
```

- `unified_ranking`: 관측된 전체 순위, 개수 제한 없음
- `public_top10`: 원천 점수 순서를 유지한 홈 10개. 맥락 미확정 항목도 삭제하지 않고 `review_required`로 표시
- `lanes.main`: 일반 트렌드
- `lanes.issue`: 논란·정책·범죄·재난 등 주의 항목
- `lanes.review`: 정규화 검토 항목
- `persistence_rank`, `momentum_rank`: 지속기간순·급상승순

맥락 미확정 항목은 홈에서 보일 수 있지만 기업은 붙이지 않습니다. 따라서 “실시간 검색어를 숨기지 않기”와 “근거 없는 테마주 연결을 막기”를 동시에 지킵니다.

## 4. 관련기업

관계가 확인된 기업과 산업 탐색 후보를 분리합니다.

| 상태 | 의미 |
|---|---|
| `official_evidence` | 공식 제품·소속·사업 관계 확인 |
| `pending_evidence` | 관계 가설은 있으나 추가 검증 필요 |
| `industry_structure_only` | 가치사슬 탐색 후보이며 직접 수혜가 아님 |
| `excluded` | 연결 제외 |

트렌드당 원재료·제조·유통·플랫폼·현장 소비 등 세 가지 사업 관점을 제시할 수 있지만, 후보가 부족하다고 관계를 만들어내지는 않습니다. pykrx 자료는 일별 참고자료이며 순위 계산이나 매수 추천에 사용하지 않습니다.

## 5. 설치와 시간별 실행

Python 3.13과 Google Chrome이 설치된 Windows 노트북 기준입니다.

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
powershell -ExecutionPolicy Bypass -File scripts\install-hourly-task.ps1
powershell -ExecutionPolicy Bypass -File scripts\setup-x-chrome.ps1
```

마지막 명령은 TRZIP 전용 Chrome 프로필로 X의 `실시간 트렌드` 페이지를 직접 엽니다. 로그인이 필요하면 브라우저에서 한 번만 완료하면 되며, 대한민국 항목 10개 이상이 확인되는 순간 자동으로 준비 상태가 저장됩니다. Enter 입력은 필요 없고 개인 기본 Chrome 프로필이나 쿠키도 복사하지 않습니다.

즉시 전체 파이프라인을 시험하려면:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\collect-hourly.ps1
```

작업 확인:

```powershell
Get-ScheduledTask -TaskName "TRZIP X Google Hourly Collector"
Get-ScheduledTaskInfo -TaskName "TRZIP X Google Hourly Collector"
```

로그는 `%LOCALAPPDATA%\TRZIP\logs\hourly-YYYY-MM-DD.jsonl`에 30일간 보존합니다. 쿠키·토큰·요청 헤더는 기록하지 않습니다.

## 6. 개발 실행

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m trzip.local_pipeline `
  --output work\local-publication `
  --database work\local.sqlite3
.venv\Scripts\python.exe -m uvicorn trzip.api:app --reload
```

환경변수 예시는 [.env.example](.env.example)을 참고하십시오. OpenDART 외에는 시간별 수집에 API 키가 필요하지 않습니다.

## 7. 공개 데이터 계약

| 파일 | 역할 |
|---|---|
| `latest/intelligence.json` | 전체 순위·홈 목록·상태·키워드·기업 |
| `latest/status.json` | 부분수집·출처별 상태·측정 진행상태 |
| `latest/metadata.json` | 실행시각·수집 감사·저장 방식 |
| `latest/coverage.json` | SQLite 누적 범위·실측/생성 비중 |
| `observations/YYYY-MM-DD.json` | 시간별 원천 순위 |
| `monitoring/run_history.json` | 최근 168회 실행 이력 |

프론트는 GitHub 토큰 없이 `live-data/latest`의 JSON을 읽습니다. 90분 초과는 지연, 3시간 초과 또는 캐시 사용은 오래된 데이터로 표시합니다.

세부 계약은 [프론트 연동](docs/FRONTEND_HANDOFF.md), [디자인 데이터 계약](docs/DESIGN_DATA_CONTRACT.md), [로컬 무비용 운영](docs/FREE_PRODUCTION.md)을 참고하십시오.

## 8. 핵심 파일

```text
src/trzip/x_web_collector.py   Chrome 기반 X 한국 실시간 페이지 수집
src/trzip/hourly_store.py      Google·X 수집과 SQLite 원장
src/trzip/intelligence.py      정규화·통합순위·기업 연결
src/trzip/publication_pipeline.py 발행 로직과 정적 출력 계약
src/trzip/local_pipeline.py    노트북 정식 CLI 진입점
scripts/collect-hourly.ps1     잠금·검증·live-data 커밋/푸시
scripts/install-hourly-task.ps1 작업 스케줄러·전용 worktree 설치
frontend/                      기존 디자인을 유지한 Vercel 정적 앱
tests/                         단위·계약·통합 테스트
```

## 9. 한계

- X는 웹 UI 구조가 바뀌거나 로그인이 만료되면 `browser_page_change` 또는 `browser_authentication`으로 실패합니다.
- X 실시간 페이지는 관련 게시물 검색 API가 아닙니다. 관련 키워드는 독립 관측 근거가 있을 때만 공개합니다.
- 사건 정규화 회귀셋은 이미 라벨링한 24건의 규칙 퇴행 방지 자료이며 신규 사건 일반화 정확도를 증명하지 않습니다.
- 3일·7일 성공률은 새 로컬 파이프라인 실행 후 각각 72회·168회가 실제로 쌓여야 확정됩니다.
- 관련기업은 투자 추천이나 수익 예측이 아닙니다.
