# TRZIP Codex 연속 작업·운영 인수인계

이 문서는 새 Codex 작업이 로컬 상황을 추측하지 않고 현재 프로덕트 백엔드를 바로 점검·계속 개발하기 위한 기준입니다. README는 제품 설명, `AGENTS.md`는 강제 원칙, 이 문서는 실제 운영 체크리스트입니다. 새 작업은 먼저 루트의 `CURRENT_STATE.json`을 읽어 마지막 검증 단위·남은 작업·수동 게이트를 확인합니다.

## 1. 제품 완료 조건

매시 정각 찬희님 노트북이 아래 한 사이클을 끝내야 합니다.

```text
X 한국 실시간 1~30 + Google Trending Now KR 전체
  → append-only SQLite 원장
  → 실제 표현 정규화·사건 그룹
  → 출처 순위만 이용한 전체 결정론적 순위
  → 약한 표시 적합성 분류
  → 실제 관련어 0~5
  → 증거 온톨로지·국내 상장기업 공개 게이트
  → 보조 플랫폼 검증(순위 영향 0)
  → V3 JSON 계약 검증
  → origin/live-data 게시 및 원격 SHA 확인
```

프런트 화면 성공은 이 백엔드 완료 조건에 포함하지 않습니다. 프런트는 V3 JSON 묶음을 소비하는 별도 클라이언트입니다.

## 2. 저장소·로컬 경로

| 용도 | 기준 |
|---|---|
| GitHub | `jyy7294/noinbada` |
| 검증된 코드 | `main` |
| 매시간 공개 관측 | `live-data` |
| 안정 실행 checkout | `$env:USERPROFILE\Documents\Codex\noinbada-runtime` |
| 런타임 루트 | `$env:LOCALAPPDATA\TRZIP` |
| SQLite | `$env:LOCALAPPDATA\TRZIP\data\trzip-hourly.sqlite3` |
| publication | `$env:LOCALAPPDATA\TRZIP\publication` |
| live-data worktree | `$env:LOCALAPPDATA\TRZIP\live-data` |
| 로그 | `$env:LOCALAPPDATA\TRZIP\logs` |
| 정각 실행 주체 | Codex 데스크톱 자동화 `trzip` |
| 자동화 설정 | `$env:USERPROFILE\.codex\automations\trzip\automation.toml` |

환경변수와 API 키는 Windows 사용자 환경 또는 로컬 `.env`에만 둡니다. 값 자체를 문서·로그·커밋·대화에 복사하지 않습니다.

## 3. 새 Codex가 먼저 확인할 것

```powershell
git status -sb
git fetch origin
git log --oneline --decorate -8 --all
$automation = Join-Path $env:USERPROFILE ".codex\automations\trzip\automation.toml"
Get-Content -Raw -Encoding UTF8 $automation
git -C "$env:LOCALAPPDATA\TRZIP\live-data" status -sb
git -C "$env:LOCALAPPDATA\TRZIP\live-data" rev-parse HEAD
git ls-remote origin refs/heads/main refs/heads/live-data
```

자동화 설정의 `status = "ACTIVE"`, `rrule = "FREQ=HOURLY;INTERVAL=1;BYMINUTE=0"`, 안정 실행 checkout 경로를 확인합니다. 그다음 최신 `status.json`의 `partial`, `source_status`, `observed_at`과 SQLite 최신 출처별 행 수를 확인합니다. 자동화 실행 성공 표시는 작업이 끝났다는 뜻일 뿐 X와 Google이 모두 관측됐다는 뜻이 아닙니다.

## 4. 코드 체크포인트와 원격 복구 원칙

- 독립적으로 검증 가능한 기능 단위가 끝날 때마다, 장시간 작업은 늦어도 30~45분마다, 그리고 작업 종료·컨텍스트 소진 전에는 반드시 원격 체크포인트를 만듭니다.
- 완료된 기능은 전체 회귀검증 후 같은 작업 안에서 `main`까지 병합·푸시합니다. 시간만 지났다는 이유로 깨진 코드를 자동 커밋하지 않습니다.
- 푸시 후 `git ls-remote origin refs/heads/main`과 로컬 HEAD가 같은지 확인합니다.
- `main` 갱신 뒤 안정 실행 checkout을 fast-forward합니다.
- Codex 정각 자동화는 코드 저장용이 아닙니다. 매시간 `latest`, `observations`, `monitoring`만 `live-data`에 커밋·푸시합니다.
- 토큰·세션 종료가 임박했는데 테스트가 끝나지 않았다면 깨진 코드를 `main`에 넣지 않습니다. 안전한 범위만 별도 `wip/codex-*` 브랜치에 올리고 실패·남은 작업을 명시합니다.
- 팀 브랜치를 통합할 때 브랜치 전체를 무조건 병합하지 않습니다. 현재 원칙과 겹치는 데이터·규칙만 출처를 보존해 선택 통합하고 전체 회귀검증을 다시 실행합니다.

권장 검증:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m compileall -q src tests
git diff --check
```

체크포인트 전에는 명시한 파일만 스테이징하고, 이미 스테이징된 다른 파일이나 작업 범위 밖 변경이 있으면 중단합니다. 테스트 시작 시점의 `origin/main` SHA와 push 직전 SHA가 달라졌으면 최신 main을 통합한 뒤 전체 검증을 다시 수행합니다. 검증 실패 또는 미완성 작업은 `main`에 올리지 않고 `wip/codex-YYYYMMDD-HHMM-*` 브랜치에 필요한 파일만 백업하며, 실패 검사와 다음 실행 명령을 인수인계에 기록합니다.

PowerShell 스크립트는 파서로 구문검사하고, 실제 publication을 만든 뒤 V3 schema와 공개 정보 누출 검사를 수행합니다.

검증된 단위를 게시할 때는 아래처럼 명시 파일만 전달합니다. 이 스크립트는 전체 테스트·컴파일·PowerShell 구문·비밀/개인경로·원격 경쟁을 검사하고, `CURRENT_STATE.json`을 갱신한 뒤 non-force 방식으로 `main`에 푸시합니다. 성공 후 `origin/main` SHA와 안정 실행 checkout도 같은 SHA인지 확인합니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\checkpoint-main.ps1 `
  -IncludePath @("src/trzip/example.py", "tests/test_example.py") `
  -Message "fix: verify example behavior" `
  -Objective "설명 가능한 기능 단위를 검증·게시" `
  -Completed @("구현과 전체 회귀검증 완료") `
  -NextAction @("다음 독립 작업") `
  -Blocker @("남은 수동 게이트")
```

작업 범위 밖 변경이 있거나 원격 main이 검증 도중 바뀌면 스크립트는 커밋하지 않고 중단합니다. 검증되지 않은 WIP는 별도 `wip/codex-*` 브랜치에 필요한 파일만 백업하며 main에는 병합하지 않습니다.

## 5. main 갱신 뒤 안정 실행 checkout 반영

```powershell
$runtime = Join-Path $env:USERPROFILE "Documents\Codex\noinbada-runtime"
powershell -ExecutionPolicy Bypass -File scripts\promote-runtime.ps1 -RuntimeCheckout $runtime
```

승격 스크립트는 다른 로컬 변경이나 fast-forward 불가 상태에서 중단하고, 활성화된 Codex 정각 자동화가 매시 0분 규칙과 해당 런타임 경로를 사용하는지 확인합니다. 강제 reset이나 force push는 하지 않습니다.

## 6. X 현재 로그인 Chrome 게이트

X는 확장 프로그램이나 전용 프로필을 사용하지 않습니다. Codex 정각 자동화가 찬희님이 현재 로그인해 둔 Chrome 세션에서 한국 실시간 트렌드 페이지를 직접 읽습니다.

1. 평소 사용하는 Chrome에서 X 로그인 상태 확인
2. `https://x.com/explore/tabs/trending`에서 대한민국 트렌드가 보이는지 확인
3. Codex 데스크톱 앱과 `trzip` 정각 자동화가 활성 상태인지 확인

자동화가 실제 1~30위를 완전히 읽은 경우에만 해당 정각 X 스냅샷을 저장합니다. 로그인 만료·지역 불명·30개 미달이면 실패로 남기고 이전 시각 데이터를 재사용하지 않습니다.

## 7. 실제 E2E 확인

```powershell
$runtime = Join-Path $env:USERPROFILE "Documents\Codex\noinbada-runtime"
powershell -ExecutionPolicy Bypass -File "$runtime\scripts\collect-hourly.ps1" -ProjectRoot $runtime
& "$runtime\.venv\Scripts\python.exe" "$runtime\scripts\audit-runtime.py"
```

확인 항목:

- SQLite 최신 시각의 X 순위가 정확히 1~30이고 Google 행 수가 페이지 선언 총건수와 같습니다.
- 최신 `status.json`의 `partial=false`이고 두 핵심 출처가 `observed`입니다.
- 단일 출처면 결과가 발행되더라도 `ranking_availability.is_combined_rank=false`입니다.
- 세 latest 문서의 `publication_id`, `generated_at`, `observed_at`이 일치합니다.
- 공개 운영 상태에 사용자명, 로컬 경로, 토큰, 비밀키, 요청 쿼리가 없습니다.
- `live-data` 로컬 HEAD와 원격 SHA가 같습니다.
- 운영 감사 `failures`가 비어 있습니다. `blockers`는 X 미연결·통합 순위 미확정·96시간 미성숙을 명시하며, 이 상태를 완료로 표현하지 않습니다.

## 8. 현재 허용된 외부 보조 데이터

- YouTube Data API: 최근 한국어 콘텐츠 관측 증거. 순위 영향 없음.
- NAVER 뉴스·블로그: 국내 기사·문맥 증거. 인증 실패는 비차단 상태로 기록.
- Instagram: 구현·토큰이 없으면 `unavailable`. 성공한 것처럼 표현하지 않음.
- pykrx: 공개된 기업의 일별 시장 참고 정보. 투자 추천이나 상승 예측이 아님.
- 공식 기관·기업 자료·검증 기사: 온톨로지 edge의 근거. URL·기준일·검수상태 필수.

## 9. 알려진 운영 게이트

- Codex 데스크톱 앱이 실행되지 않았거나 현재 Chrome의 X 로그인이 만료되면 X는 수집되지 않습니다.
- 노트북 종료·로그아웃·장시간 절전은 Codex 자동화의 정시 관측을 보장하지 않습니다. 놓친 시간은 결측으로 남깁니다.
- NAVER 키가 인증 실패 상태면 검증 레이어만 실패하며 핵심 수집과 순위는 계속됩니다.
- 기업 5개를 증명하지 못한 트렌드는 기업 공개가 보류됩니다. 이는 오류가 아니라 억지 연결을 막는 품질 게이트입니다.
- 최소 3~7일 연속 성공률이 쌓이기 전에는 운영 안정성을 확정하지 않습니다.
