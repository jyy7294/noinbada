# TRZIP — 한국 트렌드에서 관련 기업까지

TRZIP은 대한민국의 X 실시간 트렌드와 Google Trends 신호를 시간별로 수집하고, 관측된 트렌드를 관련 키워드·산업·상장기업으로 연결하는 트렌드 인텔리전스 백엔드입니다.

> 주식도 트렌드가 된 시대, 내가 아는 유행에서 기업을 찾다.

- 배포 서비스: <https://trzip-x-google.vercel.app>
- API 문서: <https://trzip-x-google.vercel.app/docs>
- 데이터 소스: X 대한민국, Google Trends `geo=KR`
- 자동 수집에서 Trends MCP 사용: 비활성화

## 1. 해결하려는 문제

트렌드에 민감하지만 투자 연결에는 익숙하지 않은 사용자는 `말복`, `불닭`, `러닝크루`, `콘텐츠`, `게임` 같은 유행을 알고 있어도 다음을 직접 찾기 어렵습니다.

1. 실제로 얼마나 빠르게 관심이 커지고 있는가?
2. 잠깐 나타난 검색어인가, 여러 시간 지속되는 현상인가?
3. 어떤 산업과 소비 행동으로 연결되는가?
4. 직접 사업자뿐 아니라 제조·유통·플랫폼·주변 소비 기업은 무엇인가?
5. 공식적으로 확인된 관계와 단순 산업 후보는 어떻게 다른가?

TRZIP은 `트렌드 탐지 → 원천 표현 보존 → 현상 해석 → 관련 키워드 → 가치사슬 기업 → 공식 정보 확인` 흐름으로 이 문제를 해결합니다.

## 2. 가장 중요한 데이터 원칙

### 원천 트렌드명과 해석을 섞지 않습니다

```json
{
  "display_name": "말복",
  "raw_terms": ["말복", "삼계탕", "보양식"],
  "phenomenon_summary": "말복을 앞두고 삼계탕·보양식·외식 관심이 증가"
}
```

- 순위명은 실제 관측된 짧은 대표어를 사용합니다.
- `말복 삼계탕·보양식 소비`처럼 해석 문장을 트렌드명으로 만들지 않습니다.
- 동의어와 연관 표현은 `raw_terms`에 보존합니다.
- 현상 해석은 `phenomenon_summary`에만 기록합니다.
- 원인을 확인하지 못했으면 `원인 미확인 — X·Google 관측 신호 증가`로 표시합니다.

이 분리는 프론트에서도 반드시 유지해야 합니다.

| UI 열 | API 필드 | 용도 |
|---|---|---|
| 트렌드 | `display_name` | 사용자가 보는 대표명 |
| 원천 | `raw_terms` | 실제 관측 표현 |
| 왜 뜨는가 | `phenomenon_summary` | 검증된 맥락 또는 원인 미확인 상태 |

## 3. 순위 설계

모든 관측 항목은 하나의 제한 없는 통합 순위에 들어갑니다. 음식·문화·인물·게임·스포츠·생활·제품·금융 관련 표현을 미리 삭제하지 않습니다.

```text
통합 점수 = 60% 최신 플랫폼 순위 RRF
          + 20% 모멘텀
          + 15% 관측 지속성
          +  5% X·Google 교차 관측
```

- `rank`: 기본 통합 순위
- `persistence_rank`: 지속기간순
- `momentum_rank`: 급상승순
- `lifecycle`: 신규, 급상승, 지속, 대중화, 재부상, 둔화
- `data_confidence`: 초기 관찰, 보통, 높음, 재구성 데모

미분류 표현과 사건·논란 맥락은 삭제하지 않고 각각 `맥락 확인`, `이슈·주의`로 표시합니다. 다만 상단을 점령하지 않도록 점수를 감쇠합니다.

## 4. 인물·논란 처리

인물명 자체는 트렌드에서 제외하지 않습니다. `지드래곤`, `진`처럼 공연·음악·팬덤·콘텐츠 맥락이 있으면 일반 트렌드와 공식 소속사 관계를 보여줄 수 있습니다.

반면 다음 문맥은 순위에는 남기되 기업 연결을 차단합니다.

- 논란·사생활·불륜·스토커
- 범죄·혐의·폭행·구속
- 재난·전쟁·테러
- 단순 정책·기관·사건성 검색어
- 사업 맥락을 아직 분류하지 못한 표현

즉, `순위 포함 여부`와 `기업 연결 가능 여부`는 별도 판단입니다.

## 5. 관련기업 설계

직접 관련 기업 한두 곳만 보여주지 않고 트렌드당 최소 3개 사업 관점으로 확장합니다.

예시 — 야구 트렌드:

1. 스포츠웨어·유니폼·굿즈
2. 미디어·중계·플랫폼
3. 경기장·식음료·주변 소비

기업 상태는 반드시 구분합니다.

| 상태 | 의미 |
|---|---|
| `official_evidence` | 공식 제품·소속·계열·사업 관계가 확인됨 |
| `pending_evidence` | 관계 가설이 있으나 추가 검증 필요 |
| `industry_structure_only` | 업종·가치사슬 탐색 후보일 뿐 실제 수혜를 뜻하지 않음 |
| `excluded` | 연결 근거가 부족해 제외 |

OpenDART는 기업 식별·공시 근거에 사용하고, pykrx는 국내 종목명과 일별 OHLCV 참고정보에 사용합니다. 주가 자료는 트렌드 순위나 기업 관계 판정에 사용하지 않습니다.

## 6. 데모와 실측의 구분

- `provenance=observed`: 실제 수집된 X·Google 결과
- `provenance=generated`: 2026-05-01~2026-08-12 시연용 결정론적 재구성 데이터

생성 데이터는 실제 과거 검색량이 아닙니다. 화면의 기본 데모는 2026-08-12 기준 최근 7일을 사용합니다.

과거 트렌드가 최신 순위에 계속 남지 않도록 항목별 활성 기간을 적용합니다.

- 오징어 게임·두바이 초콜릿: 6월 중순 이후 종료
- 리센느: 5월 중순~7월 중순
- 폴더블폰: 7월 이후
- 말복·삼계탕·보양식: 8월 활성화

## 7. 핵심 API

| 경로 | 역할 |
|---|---|
| `GET /api/v1/intelligence` | 특정 기준시각·관찰창의 통합 순위와 전체 상세 |
| `GET /api/v1/korea/curated-feed` | 최근 실측 24시간 피드 |
| `GET /api/v1/hourly/coverage` | 데이터 시간 범위와 실측/생성 비중 |
| `GET /api/v1/hourly/snapshot` | 특정 시간의 원천 스냅샷 |
| `GET /api/v1/keywords/x-related` | X 동시출현 관련 표현 최대 5개 |
| `GET /api/v1/companies/profile` | OpenDART 기업정보와 pykrx 시장 참고정보 |
| `GET /api/v1/integrations` | 외부 연동 상태 |
| `GET /health` | 서버 상태 |

데모 호출 예시:

```text
GET /api/v1/intelligence?at=2026-08-12T11:00:00%2B09:00&hours=168
```

프론트 연결 예시는 [docs/FRONTEND_HANDOFF.md](docs/FRONTEND_HANDOFF.md)를 참고하십시오.

## 8. 프로젝트 구조

```text
api/index.py                  Vercel Python 진입점
src/trzip/api.py              FastAPI 라우트
src/trzip/hourly_store.py     시간별 수집·저장·데모 재생성
src/trzip/intelligence.py     정규화·통합순위·상태·기업 연결
src/trzip/curation.py         분류·민감 맥락 규칙
src/trzip/related_keywords.py X 관련 표현 도출
src/trzip/value_chain.py      3개 이상 가치사슬 관점 확장
src/trzip/company_adapters.py OpenDART·pykrx 어댑터
src/trzip/e2e.py              수집부터 보고서까지 E2E 실행
web/                          현재 확인용 프론트
tests/                        단위·통합 테스트
docs/                         정책·분류·설계 문서
```

## 9. 로컬 실행

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
Copy-Item .env.example .env
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m trzip.hourly_cli backfill
.venv\Scripts\python -m uvicorn trzip.api:app --reload
```

브라우저에서 <http://127.0.0.1:8000>을 엽니다.

## 10. 환경변수

```env
X_BEARER_TOKEN=
X_KOREA_WOEID=23424868
OPENDART_API_KEY=
TRZIP_DB_PATH=data/trzip-hourly.sqlite3
```

- 키는 저장소에 커밋하지 않습니다.
- Trends MCP 자동 실행은 금지합니다.
- X 키가 없으면 X 수집은 `unavailable`로 기록합니다.
- pykrx는 별도 키가 없습니다.

## 11. 시간별 운영

Windows 작업 스케줄러 설치:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-hourly-task.ps1
```

매시 정각 실행, 누락 시 재실행, 배터리 상태 실행 허용, 최대 실행시간 15분을 설정합니다.

Vercel의 `/tmp` SQLite는 영구 저장소가 아닙니다. 현재 Vercel 배포는 데모·API 확인용이며, 장기 실측 운영에서는 PostgreSQL 또는 외부 영구 DB로 저장소 어댑터를 교체해야 합니다.

## 12. 현재 검증 상태

- Python 테스트: 34개 통과
- JavaScript 구문검사: 통과
- Vercel 홈·Health·통합순위 API: HTTP 200
- 8월 데모에서 오징어 게임 잔존: 0건
- 실측과 생성 데이터의 동일 시각 공존: 검증
- 논란·미분류 항목의 기업 오연결 차단: 검증
- 트렌드 대표명과 현상 설명 분리: 검증

## 13. 해석 한계

TRZIP은 종목 추천이나 수익률 예측 서비스가 아닙니다. 관련기업은 공식 관계와 산업 구조를 탐색하기 위한 후보이며, 기업 실적·시장 기대·밸류에이션·매수 시점에 따라 주가 반응은 달라질 수 있습니다.
