# Claude Design 프론트엔드 연동 명세

## 연결 원칙

프론트는 GitHub의 생성 JSON이나 Vercel 함수가 아니라 **Render FastAPI**를 조회합니다.

```env
NEXT_PUBLIC_TRZIP_API_URL=https://<render-service>.onrender.com
```

Vite를 사용하면 변수명만 다음과 같이 바꿉니다.

```env
VITE_TRZIP_API_URL=https://<render-service>.onrender.com
```

백엔드의 `TRZIP_CORS_ORIGINS`에는 실제 Vercel 프론트 주소를 등록합니다.

## 기본 호출

```ts
const API = process.env.NEXT_PUBLIC_TRZIP_API_URL!;

export async function getLiveTrends(hours = 24) {
  const response = await fetch(`${API}/api/v1/intelligence?hours=${hours}`, {
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`TRZIP API ${response.status}`);
  return response.json();
}
```

## API

| 경로 | 프론트 사용처 |
|---|---|
| `GET /health` | 백엔드·PostgreSQL 상태 확인 |
| `GET /api/v1/intelligence?hours=24` | 전체 통합 순위와 상세 데이터 |
| `GET /api/v1/korea/curated-feed` | 최근 24시간 실측 피드 |
| `GET /api/v1/hourly/coverage` | 누적 관찰기간·행 수 |
| `GET /api/v1/hourly/snapshot?at=...` | 특정 시간 원천 데이터 |
| `GET /api/v1/keywords/x-related` | 관련 표현 보강 |
| `GET /api/v1/companies/profile` | 기업 공식·시장 참고정보 |

## 반드시 분리할 필드

```text
display_name       대표 사건·현상명. 예: 말복
raw_terms          X·Google에서 실제 관찰된 표현
phenomenon_summary 왜 관심이 증가했는지에 대한 설명
```

`phenomenon_summary`를 카드 제목으로 사용하면 안 됩니다.

## 목록 정렬

| 정렬 | 필드 |
|---|---|
| 통합 순위 | `rank` |
| 지속기간순 | `persistence_rank` |
| 급상승순 | `momentum_rank` |

카테고리와 인물 여부로 항목을 삭제하지 않습니다. `classification`, `lane`, `company_eligible`을 사용해 상태만 구분합니다.

## 관련기업 표시

- `official_evidence`: 공식 관계 확인
- `pending_evidence`: 추가 확인 필요
- `industry_structure_only`: 산업 구조 탐색 후보
- `excluded`: 표시 제외

`industry_structure_only`를 직접 수혜 기업이나 추천 종목처럼 표시하지 않습니다.

## 프론트 완료 조건

1. API 주소를 코드에 하드코딩하지 않고 환경변수로 관리
2. Render 장애·초기 기동 중 오류 화면 제공
3. 통합 순위·지속기간순·급상승순 전환
4. 대표명·원천 표현·현상 설명 분리
5. 기업 관계의 근거 상태와 투자 유의사항 표시
6. 실측과 재구성 데모를 명확히 구분
