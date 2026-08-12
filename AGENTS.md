# TRZIP repository instructions

이 저장소의 목표는 찬희님 Windows 노트북에서 매시 정각 실제 한국 트렌드를 수집하고, 누적 원장·결정론적 순위·증거 기반 기업 온톨로지를 프런트가 읽을 수 있는 JSON으로 게시하는 것입니다.

## 변경 불가 원칙

- 순위 입력은 X 한국 실시간 트렌드 1~30위와 Google Trending Now 대한민국 전체 목록뿐입니다.
- NAVER·YouTube·Instagram·기사 검색은 검증과 맥락용이며 순위·점수에 영향을 주지 않습니다.
- Google RSS, Trends MCP 자동호출, X API, GitHub Actions, Render, 생성·더미·백필 데이터는 운영 경로에 넣지 않습니다.
- 대표어와 관련어는 실제 관측 표현을 사용합니다. 설명문을 트렌드명이나 관련어로 만들지 않습니다.
- 기업은 URL 증거가 이어진 온톨로지 경로로만 연결합니다. 서로 다른 국내 상장종목 5개 미만이면 공개 `companies`는 비우고 후보와 보강 대기 상태만 남깁니다. 숫자를 맞추기 위한 범용 기업·약한 연관 기업 삽입은 금지합니다.
- 분류, 기사량, 검증 결과, 기업 수는 순위를 바꾸지 않습니다.
- 프런트는 교체 대상입니다. 사용자가 명시적으로 요청하지 않으면 `frontend/`, `web/`, 디자인 파일을 수정하지 않습니다.
- 비밀키, Chrome 프로필, 쿠키, SQLite, 로컬 절대경로를 Git 또는 공개 JSON에 넣지 않습니다.

## 데이터와 실행 소유권

- 로컬 원장: `$env:LOCALAPPDATA\TRZIP\data\trzip-hourly.sqlite3`
- 게시 작업공간: `$env:LOCALAPPDATA\TRZIP\publication`
- 공개 데이터 worktree: `$env:LOCALAPPDATA\TRZIP\live-data`
- 안정 실행 checkout: `$env:USERPROFILE\Documents\Codex\noinbada-runtime`
- 예약 작업: `TRZIP X Google Hourly Collector`
- 코드 기준 브랜치: `origin/main`
- 공개 관측 브랜치: `origin/live-data`

SQLite 원본은 무기한 보존합니다. 구형 수집행은 삭제하지 않되 현재 수집기 버전 게이트를 통과한 행만 순위 계산에 사용합니다. 결측 시간은 생성값으로 채우지 않습니다.

## Codex 체크포인트 규칙

기능 단위 작업을 마칠 때마다 다음 순서를 지킵니다.

1. `git status -sb`와 전체 diff로 작업 범위를 확인합니다.
2. 관련 테스트, 전체 `pytest`, Python 컴파일, PowerShell 구문 검사와 `git diff --check`를 실행합니다.
3. 공개 JSON에 비밀·로컬 경로가 없는지 검사합니다.
4. 검증을 통과한 변경만 명확한 커밋으로 만들고 `origin/main`의 최신 변경을 확인합니다.
5. 팀 변경이 있으면 덮어쓰지 말고 통합·재검증합니다. 최종 검증 커밋은 반드시 `main`에 병합하고 원격 SHA 일치를 확인합니다.
6. 안정 실행 checkout을 `origin/main`으로 fast-forward하고 의존성을 갱신합니다.
7. 실제 파이프라인을 한 번 실행해 SQLite, publication, `live-data` 원격 게시까지 확인합니다.
8. 문서의 현재 상태와 남은 수동 게이트를 갱신합니다.

검증이 끝나지 않은 상태에서 중단해야 하면 `main`에 병합하지 않습니다. 비밀·무관 파일이 없음을 확인한 뒤 별도 `wip/codex-*` 브랜치로만 원격 백업하고, 실패한 검사와 이어서 할 명령을 커밋 또는 인수인계 문서에 남깁니다. 예약 작업이 임의의 소스 코드를 자동 커밋하도록 만들지 않습니다.

## 완료 기준

- 같은 관측 시간에 X 30개와 Google 페이지 선언 총건수가 모두 저장됩니다.
- 수집 감사가 행 수·순위 연속성·중복·수집기 버전을 검증합니다.
- `unified_ranking`은 전체 순위, `public_top10`은 그중 표시 적합 후보이며 재점수하지 않습니다.
- 단일 출처면 `provisional_single_source`로 명시하고 통합 순위라고 부르지 않습니다.
- `latest/intelligence.json`, `status.json`, `metadata.json`의 publication ID·생성시각·관측시각이 일치합니다.
- 공개 기업은 최소 5개와 각 온톨로지 경로·근거 URL을 갖습니다.
- 예약 작업 결과 0만으로 성공을 단정하지 않고 `status.partial`, 출처 상태, 실제 DB 행 수와 원격 `live-data` SHA를 함께 확인합니다.

상세 운영·복구 절차는 `docs/CODEX_CONTINUITY.md`, 프런트 계약은 `docs/FRONTEND_BACKEND_CONTRACT_V3.md`를 따릅니다.
