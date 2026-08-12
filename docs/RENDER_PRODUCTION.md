# Render 프로덕션 운영 명세

## 확정 구조

```text
X 대한민국 ─┐
            ├─ Render Cron Job ─ Render PostgreSQL ─ Render FastAPI ─ Vercel Frontend
Google KR ──┘
```

- GitHub 원본 저장소: `jyy7294/noinbada`
- 백엔드: Render Web Service
- 정시 수집: Render Cron Job, 매시 `00분` UTC 실행
- 영구 저장: PostgreSQL
- 프론트: Vercel에서 별도 배포
- UI·UX: Claude Design 담당
- LLM: 운영 필수 의존성에서 제외

## Render Blueprint

루트의 `render.yaml`은 다음 자원을 정의합니다.

| 자원 | 이름 | 역할 |
|---|---|---|
| Web Service | `trzip-api` | FastAPI 공개 읽기 API |
| Cron Job | `trzip-hourly-collector` | 매시간 X·Google 수집 |
| PostgreSQL | `trzip-db` | 관측·감사·순위 계산 원천 영구 저장 |

Render Dashboard에서 **New → Blueprint**를 선택하고 `jyy7294/noinbada`를 연결합니다.

## 필수 환경변수

| 위치 | 변수 | 설명 |
|---|---|---|
| Web·Cron | `DATABASE_URL` | Blueprint가 PostgreSQL 연결문자열을 자동 주입 |
| Web | `TRZIP_CORS_ORIGINS` | Vercel 프론트 주소. 여러 개면 쉼표로 구분 |
| Cron | `X_BEARER_TOKEN` | X 한국 트렌드 직접 수집 키 |
| Web·Cron | `OPENDART_API_KEY` | 기업 공식정보 확인 키 |

`TRENDS_MCP_API_KEY`는 자동 수집에 등록하지 않습니다.

## 실행 명령

```text
Build: pip install -r requirements.txt
Web:   uvicorn trzip.api:app --host 0.0.0.0 --port $PORT
Cron:  PYTHONPATH=src python -m trzip.hourly_cli collect
```

## 배포 후 확인

```text
GET https://<render-service>.onrender.com/health
GET https://<render-service>.onrender.com/api/v1/hourly/coverage
GET https://<render-service>.onrender.com/api/v1/korea/curated-feed
GET https://<render-service>.onrender.com/api/v1/intelligence?hours=168
```

`/health` 응답의 `database`는 반드시 `postgresql`이어야 합니다.

## 요금·지속성 주의

- Render 무료 Web Service는 유휴 시 중지될 수 있습니다.
- Render 무료 PostgreSQL은 공식 정책상 30일 후 만료되므로 장기 프로덕션 적재용이 아닙니다.
- Render Cron Job은 월 최소 과금이 있습니다.
- 장기 운영에서는 유료 PostgreSQL로 전환하고 백업·복구 정책을 활성화해야 합니다.

유료 자원 생성은 팀의 비용 승인을 받은 뒤 진행합니다.
