# Claude Design 프론트엔드 연동 명세

## 연결 원칙

비용 0원 운영에서는 프론트가 `live-data` 브랜치의 최신 JSON을 조회합니다.

```env
NEXT_PUBLIC_TRZIP_DATA_URL=https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest
```

Vite를 사용하면 변수명만 다음과 같이 바꿉니다.

```env
VITE_TRZIP_DATA_URL=https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest
```

공개 저장소의 JSON이므로 프론트에 GitHub 토큰을 넣지 않습니다.

## 기본 호출

```ts
const DATA = process.env.NEXT_PUBLIC_TRZIP_DATA_URL!;

export async function getLiveTrends(hours = 24) {
  const response = await fetch(`${DATA}/intelligence.json?t=${Date.now()}`, {
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`TRZIP data ${response.status}`);
  return response.json();
}
```

## 데이터 파일

| 파일 | 프론트 사용처 |
|---|---|
| `latest/intelligence.json` | 전체 통합 순위와 상세 데이터 |
| `latest/coverage.json` | 누적 관찰기간·행 수 |
| `latest/metadata.json` | 마지막 실행·수집 성공·오류 상태 |

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

1. 데이터 주소를 코드에 하드코딩하지 않고 환경변수로 관리
2. GitHub 데이터 갱신 지연·실패 상태 표시
3. 통합 순위·지속기간순·급상승순 전환
4. 대표명·원천 표현·현상 설명 분리
5. 기업 관계의 근거 상태와 투자 유의사항 표시
6. 실측과 재구성 데모를 명확히 구분
