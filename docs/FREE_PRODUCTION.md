# 노트북 기반 무비용 운영 V3

## 확정 구조

Windows 작업 스케줄러가 매시 정각 `scripts/collect-hourly.ps1`을 실행합니다. 계산과 SQLite는 노트북에만 있고 GitHub는 코드 협업과 검증 완료 JSON 전달에만 사용합니다. GitHub Actions·Render·상시 서버는 없습니다.

```text
%LOCALAPPDATA%\TRZIP\
  data\                실제 SQLite 원장
  publication\         검증 완료 JSON 준비본
  live-data\           live-data 전용 Git worktree
  logs\                최근 30일 JSONL 실행 로그
```

X 인증은 Chrome이 기록한 마지막 사용 로그인 프로필에 한 번 수동 설치한 MV3 확장이 담당합니다. 확장은 쿠키·저장소 권한이 없고 자신이 연 비활성 탭의 한국 1~30위만 Downloads inbox로 전달합니다. Python은 해당 시간의 완전한 30행만 수락합니다.

## 안전한 게시

- 자동 stage 허용: `latest/`, `observations/`, `monitoring/`
- 원격과 로컬 `live-data`가 갈라지면 중단, force push 금지
- 한 출처 실패 시 다른 출처 저장
- 같은 시간의 기존 정상 출처 스냅샷은 재시도 실패로 삭제하지 않음
- 원시 SQLite는 무기한 보존; 게시 일별 JSON 삭제는 명시적 양수 보존기간 설정 때만 수행

## 현실적 한계

- 노트북 종료·로그아웃 중에는 실행되지 않습니다.
- 절전 복귀 시 지연 실행될 수 있으며 정각 관측을 생성값으로 보정하지 않습니다.
- X 로그인 만료·지역 변경·화면 구조 변경은 각각 명시적 실패상태로 남습니다.
- 72회와 168회가 실제로 쌓이기 전에는 3일·7일 안정성을 완료로 표시하지 않습니다.
