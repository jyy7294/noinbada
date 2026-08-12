# 노트북 기반 무비용 운영

## 확정 구조

```text
Windows 작업 스케줄러(매시 00분)
  → 로컬 Chrome X 한국 실시간 + Google Trends KR
  → 로컬 SQLite·분석·계약검증
  → live-data 브랜치에 JSON만 push
  → Vercel 정적 프론트가 최신 JSON 조회
```

GitHub Actions와 상시 유료 서버는 사용하지 않습니다. GitHub는 계산 서버가 아니라 코드 협업과 정적 데이터 전달에만 사용합니다.

## 런타임 위치

```text
%LOCALAPPDATA%\TRZIP\
  chrome-profile\     X 전용 로그인 세션
  data\                SQLite 원장
  publication\         검증 완료 JSON
  live-data\           별도 Git worktree
  logs\                30일 JSONL 실행 로그
```

개인 기본 Chrome 프로필, 쿠키, SQLite, `.env`는 Git에 올리지 않습니다.

## 발행 규칙

자동 커밋 허용 경로는 다음뿐입니다.

- `latest/`
- `observations/`
- `monitoring/`

원격과 로컬 `live-data`가 갈라지면 force push하지 않고 중단합니다. push가 실패하면 로컬 커밋을 보존하고 다음 실행에서 다시 전송합니다.

## 실패 의미

| 상태 | 의미 |
|---|---|
| `browser_authentication` | X 전용 프로필 로그인 필요 |
| `region_configuration` | 한국 지역 표시 확인 실패 |
| `browser_page_change` | X 페이지 셀렉터 변경 가능성 |
| `network` | 네트워크·시간초과 |
| `partial` | X·Google 중 한 출처만 성공 |
| `stale` | 마지막 정상 관측이 3시간 초과 |

한 출처 실패는 다른 출처 저장을 막지 않습니다. 같은 시간 재시도 실패가 앞선 정상 스냅샷을 지우지도 않습니다.

## 운영 제약

- 노트북이 켜져 있고 사용자가 로그인된 상태여야 합니다.
- 잠금 상태에서는 실행할 수 있지만 종료·로그아웃 중에는 실행되지 않습니다.
- `WakeToRun`은 절전 복귀를 도울 뿐 종료된 노트북을 켜지 못합니다.
- 성공률은 실제 72회·168회가 쌓이기 전 완료로 표시하지 않습니다.
