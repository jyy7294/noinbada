# TRZIP 새 Windows PC 설치

## 가능한 범위

GitHub 저장소에는 코드, 설치 스크립트, 자동화 생성기, 테스트와 공개 `live-data` 계약이 들어 있습니다. API 키와 X 로그인 쿠키는 GitHub에 저장하지 않습니다. 따라서 공개 결과 조회는 즉시 가능하지만, 새 PC를 수집 노드로 만들려면 최초 한 번 X 로그인과 GitHub 인증이 필요합니다.

## 1. 준비

- Windows 10 또는 11
- Git
- Python 3.13 (`py -3.13`으로 확인)
- Google Chrome
- Codex 데스크톱 앱
- `live-data`에 push 가능한 GitHub 인증

## 2. 복제와 자동 설치

```powershell
git clone https://github.com/jyy7294/noinbada.git
cd noinbada
powershell -ExecutionPolicy Bypass -File scripts\bootstrap-new-pc.ps1 `
  -TargetThreadId "현재 Codex 작업 ID"
```

이 명령은 다음을 수행합니다.

1. 현재 브랜치가 최신 `origin/main`인지 확인
2. Python 가상환경과 개발·운영 의존성 설치
3. `%LOCALAPPDATA%\TRZIP\live-data` 전용 worktree 구성
4. 기존 Windows 작업 스케줄러 중복 실행 비활성화
5. 사용자 경로에 맞춘 Codex 정각 자동화 생성
6. 전체 테스트 실행

기존 자동화를 교체할 때만 내용을 먼저 확인하고 `-ForceAutomation`을 사용합니다.

## 3. 사람만 할 수 있는 최초 확인

1. 현재 Chrome에서 X에 로그인합니다.
2. <https://x.com/explore/tabs/trending>에서 대한민국 실시간 트렌드인지 확인합니다.
3. Codex 데스크톱 앱이 실행 중이고 `trzip` 자동화가 활성 상태인지 확인합니다.
4. GitHub CLI를 쓴다면 `gh auth login`으로 인증합니다.

로그인 쿠키와 토큰을 자동 복사하지 않는 것은 의도된 보안 경계입니다.

## 4. 최초 E2E

```powershell
powershell -ExecutionPolicy Bypass -File scripts\collect-hourly.ps1
.venv\Scripts\python.exe scripts\audit-runtime.py
```

감사 결과가 `PASS` 또는 데이터 누적시간만 부족한 `PROVISIONAL`이고, `failures`가 없으며 원격 `live-data` SHA가 일치해야 설치가 끝난 것입니다.

## 5. 다른 PC에서 결과만 사용

수집 노드가 아니라 결과 소비 PC라면 설치가 필요 없습니다.

```text
https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest/manifest.json
```

manifest가 가리키는 불변 `delivery/{publication_id}` 파일을 읽고 SHA-256을 검증합니다.
