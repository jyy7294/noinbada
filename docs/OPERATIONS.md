# TR ZIP 운영·복구 안내

2026-10-14 KST 기준입니다. 새 운영 후보는 실제 수집 데이터를 사용합니다.
정식 공개 전환은 72시간 관찰 조건을 충족한 뒤 별도로 진행합니다.

## 현재 확인할 주소

- 운영 후보: https://trzip.62-171-141-206.sslip.io/
- 수집 상태: https://trzip.62-171-141-206.sslip.io/api/status
- 데이터 준비 상태: /health/ready (최근 Google 수집이 없으면 503)
- 기존 공개 주소: https://trzip-x-google.vercel.app/ (과거 시연 중단 안내)

서버의 /health 200은 프로세스가 응답한다는 뜻입니다. 수집 성공이나 정식
전환 완료를 뜻하지 않습니다. 후보 화면의 운영 현황에서 실제 수집 시각을 확인합니다.

## 실행 구성

서버 경로는 /srv/services/trzip 입니다. 코드 릴리스는 releases/,
현재 코드 포인터는 current, 영구 원장은 state/runtime.sqlite3에 있습니다.
수집은 매 10분, 기업 보강은 그 사이 5분 시점, 보관 정리는 매일 수행됩니다.
API는 전용 trzip 계정으로 127.0.0.1:8448에만 바인딩하며 nginx가 HTTPS를 제공합니다.

```bash
systemctl status trzip-api.service
systemctl list-timers 'trzip-*'
journalctl --namespace=trzip -u trzip-collect -n 20 --no-pager
journalctl --namespace=trzip -u trzip-enrich -n 20 --no-pager
```

API 키는 /srv/services/trzip/runtime.env에만 넣습니다. 파일은 root:trzip 0640입니다.
Google·공식 상장 확인에는 키가 필요 없습니다. YouTube는 미설정이고 X는 비활성입니다.
유료 API, 유료 이미지 생성, LLM 호출과 노트북 상시 실행에 의존하지 않습니다.
선택 기능을 설정해도 새 요금제를 자동 구매하지 않습니다.

## 저장과 복구

원 관측·수집 영수증은 14일간 DB에 보관하고 이후 압축 원장으로 먼저 옮깁니다.
게시본은 압축해 7일간 보관하며 목록과 상세에 같은 게시 식별자를 씁니다.
이미지는 128 MiB, 전용 로그는 32 MiB로 제한합니다. 일별 DB 백업은 3개를 보관합니다.
남은 공간이 5 GiB 미만이면 수집·보강이 중단되어 다른 서비스의 저장 공간을 침범하지 않습니다.
이 경우 state/archive 등을 외부 보관소로 옮길지는 운영자가 판단합니다. 자동 삭제하지 않습니다.

API는 종료 시 systemd가 재시작합니다. 중단된 수집은 다음 타이머에서 다시 시도하며
영수증의 중단 상태를 남깁니다. 실패 구간을 0이나 추정 관측값으로 채우지 않습니다.
코드 롤백에는 previous-release의 직전 호환 릴리스를 사용하고 SQLite 원장을 유지합니다.
DB 자체 복원은 두 타이머와 API를 중지한 후, 검증된 백업을 별도 경로에서 확인하고
기존 DB 및 WAL을 보존한 상태에서 교체합니다.

## 검증 결과

2026-10-14 02:23 KST까지 확인한 결과입니다.

| 구분 | 확인 결과 |
|---|---|
| 실제 Google 수집 | 전체 공개 목록 184~185개, 공식 RSS 복구 10개도 별도 확인 |
| 기업 연결 | 12개 트렌드 → 국내·미국 11개 상장기업, 공식 로고 4개 (해당 게시본 기준) |
| 자동 수집 | 서버 systemd 타이머 실행 및 관측 누적 확인 |
| API 강제 종료 | 8.16초 후 재시작, 같은 게시본 유지 |
| 수집기 강제 종료 | 18초 후 실제 원천 재수집 성공, 이전 관측 보존 |
| 백업 복원 | 별도 SQLite에 복원, integrity_check=ok |
| 남은 저장 공간 | 복구 시험 시 6,373,433,344 bytes (약 5.94 GiB) |
| 로컬 회귀검증 | 653 passed, 1 skipped; 변경 후 관련 시험 추가 통과 |
| 브라우저 | 390×844, 1440×1000; 검색·상세·기업 근거·저장 유지·다이얼·운영 현황 확인 |
| 브라우저 오류 | 확인한 사용자 흐름에서 콘솔 error 0건, 문서 가로 넘침 없음 |
| Vercel 연결 | 보호된 준비 배포에서 같은 출처 /api/trends와 /health 응답 확인 |
| 72시간 연속 운영 | 진행 중. 완료로 간주하지 않음 |

[데스크톱 화면](qa/desktop.png) · [모바일 화면](qa/mobile.png)
실물 휴대전화, YouTube 인증 연동과 유료 X 연동은 검증하지 않았습니다.

기존 테스트 4개는 공급자 설정이 없는 상태에서 설정 완료 경로를 기대하고 있었습니다.
실제 키 없이 설정 조건을 명시하는 fixture를 추가했고, 기존 검증 주장과 운영 코드는 유지했습니다.

## 정식 전환

관찰 시작은 2026-10-14 01:53:27 KST입니다. 가장 빠른 72시간 충족 시점은
2026-10-17 01:53:27 KST이며, 단순히 시간이 지났다고 전환하지 않습니다.

```bash
set -a
. /srv/services/trzip/runtime.env
set +a
/srv/services/trzip/venv/bin/python /srv/services/trzip/current/deploy/release_check.py
```

반환 ready_for_review=true와 모든 체크를 확인합니다. 수집 구간 성공률 95%,
현재 신선도, 두 종류의 복구, 백업 복원, 브라우저 QA, 타이머, 공간 기준이 필요합니다.
사용자에게 알려지지 않은 오류가 없고 현재 배포와 검증한 코드가 같아야 합니다.

Vercel 프로젝트: trzip-x-google / prj_hMZnKxRcgVYaCKeW9NYZuhcBPqzk
팀: mangos-projects-befba726 / team_luGYmIj0merMPnk1wddsU3kh

- 기존 시연 원본: dpl_8vJQ2VGKsywNZ9NwvyJPMZojQ5q4 (보존)
- 현재 복구 안내: dpl_Ap78H9wHverpjSmcgEWSh9DAMS8i
- 정식 전환 준비 배포: dpl_E6ftE39ua43pzq3ipXsvxb6Zgbtq

모든 조건을 확인한 다음에만 준비 배포를 promote하고,
서버 TRZIP_RELEASE_MODE를 production으로 바꾼 후 API를 재시작합니다.
원래 공개 주소에서 목록→상세→기사·기업 근거 흐름과 게시 식별자 일치를 다시 확인합니다.
문제가 있으면 복구 안내 배포로 되돌리고 서버 후보를 유지합니다.
