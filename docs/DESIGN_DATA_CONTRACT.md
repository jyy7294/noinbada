# Trend App Zip v2 데이터 계약

## 1. 책임 경계

| 계층 | 책임 | 저장 위치 |
|---|---|---|
| GitHub Actions | 매시 X 대한민국·Google Trends KR 수집, 정규화, 통합 순위와 기업관계 생성 | `live-data` 브랜치 |
| 디자인 데이터 어댑터 | 최신 JSON 조회, 화면용 필드 변환, 오프라인 캐시 | `design/trendzip-data.js` |
| Trend App 화면 | 순위·상세·키워드·기업 표시, 밈트폴리오 편집 | 브라우저 메모리 |
| 사용자 저장 | 이름·키워드·선택 기업 저장 | `localStorage` |
| 사용자 내보내기 | 저장된 밈트폴리오 전체를 JSON 또는 CSV로 다운로드 | 사용자 다운로드 폴더 |

서버에는 사용자의 밈트폴리오를 저장하지 않습니다. 로그인·기기간 동기화가 필요해지는 시점에만 별도 사용자 DB를 추가합니다.

## 2. 입력 데이터

```text
https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest/intelligence.json
```

- 운영 화면은 `mode=live`만 허용합니다.
- 트렌드·키워드·관련기업·기업 일별 시장자료에는 생성·fixture 데이터를 넣지 않습니다.
- Z4·Z5의 밈트폴리오 사용자명·좋아요·수익률·구성 비중은 발표용 목업으로 유지합니다. 이 값은 실제 투자성과나 백엔드 관측값으로 취급하지 않습니다.
- 네트워크 실패 시 마지막 정상 응답을 `trzip:latest-intelligence:v1`에서 읽고 `stale=true`로 구분합니다.
- GitHub 토큰이나 API 키를 브라우저에 넣지 않습니다.

## 3. 화면 매핑

| 화면 | 표시 내용 | 원본 필드 |
|---|---|---|
| Z1 홈 다이얼 | 맥락 품질 게이트를 통과한 최대 10개 대표명 | `public_top10[].display_name` |
| Z1 순위 | 통합 순위 | `rank` |
| Z1 분류 | 넓은 트렌드 분류 | `category` |
| Z1 변화 | 소스별 이전 순위 대비 변화 | `rank_change_by_source` |
| Z2 제목 | 정규화된 사건·현상명 | `display_name` |
| Z2 상태 | 신규·급상승·지속·대중화 등 | `lifecycle`, `lifecycle_reason` |
| Z2 설명 | 왜 관측됐는지에 대한 설명 | `phenomenon_summary` |
| Z2 신뢰도 | 초기 관찰·교차 관찰 등 | `data_confidence` |
| Z2 출처 | X·Google의 최신 원천 순위 | `latest_source_ranks` |
| Z2 키워드 | 관측 근거가 있는 최대 5개 | `keywords` |
| Z2 기업 탭 | 관계 범주별 기업 | `companies[].relation_category` |
| Z2 기업 카드 | 역할·관계 강도·검증 상태·근거·주의 | `companies[]` |
| Z2 기업 일별 시장자료 | 기준일·종가·등락률·거래량 | `companies[].market_reference.summary` |
| Z3 내 폴더 | 이 기기에 저장한 밈트폴리오 | `trzip:portfolios:v1` |
| Z6 만들기 | 현재 트렌드의 키워드·기업 후보 | 선택한 정규화 트렌드 |
| Z7 내 데이터 | JSON·CSV 내보내기 | 저장된 밈트폴리오 전체 |

홈은 디자인 구조상 `public_top10`을 보여주며, 미해결·동음이의·맥락부족 항목으로 10칸을 억지로 채우지 않습니다. `loadTrends()`의 `trends`에는 제한 없는 `unified_ranking`, `featuredTrends`에는 공개 품질 게이트를 통과한 목록을 유지합니다.

## 4. 저장 스키마

키: `trzip:portfolios:v1`

```json
{
  "schemaVersion": "trzip-portfolio-v1",
  "id": "portfolio-...",
  "name": "피의 게임 연결기업",
  "trendTopic": "피의 게임",
  "observedAt": "2026-08-12T07:00:00+00:00",
  "keywords": ["피의 게임"],
  "companies": [],
  "createdAt": "ISO-8601",
  "updatedAt": "ISO-8601"
}
```

- 저장 버튼은 현재 화면의 이름, 활성 키워드, 현재 트렌드의 기업 후보를 함께 저장합니다.
- 같은 `id`를 다시 저장하면 갱신하고, 새 저장은 최신순으로 앞에 배치합니다.
- 키워드와 기업은 각각 최대 10개입니다.
- 새로 만드는 사용자 밈트폴리오에는 주가·수익률을 임의 생성해 저장하지 않습니다. Z4·Z5의 사전 제작 밈트폴리오 목업은 별도입니다.

## 5. 내보내기

### JSON

- 스키마: `trzip-export-v1`
- 밈트폴리오 구조와 기업 근거를 손실 없이 보존합니다.
- 팀 간 전달, 재가공, 향후 가져오기 기능에 사용합니다.

### CSV

한 행은 `밈트폴리오 × 키워드 × 기업` 조합입니다.

```text
portfolio_id,portfolio_name,trend_topic,keyword,company,stock_code,
relation_category,verification_status,created_at
```

엑셀에서 한글이 깨지지 않도록 UTF-8 BOM을 포함합니다.

## 6. 표시 금지와 실패 상태

- 실측되지 않은 관련 키워드는 채우지 않고 빈 상태로 둡니다.
- `operator_candidate_not_rank_evidence`는 감사 데이터에만 남기고 화면 키워드 칩과 저장 데이터에서는 제외합니다.
- `company_eligible=false`인 트렌드는 기업을 억지로 붙이지 않습니다.
- `verification_status=industry_structure_only`는 업종 후보로 표시하며 직접 수혜로 표현하지 않습니다.
- `investment_warning`은 기업 상세에서 항상 함께 표시합니다.
- 네트워크와 캐시가 모두 없으면 목업으로 대체하지 않고 `데이터 연결 실패`를 표시합니다.
- X 또는 Google 한쪽 수집이 실패하면 `collection_status.partial=true`를 전달하고 홈 기준일에 `부분 수집 (X 실패)`처럼 표시합니다.
- Z2 시장자료는 pykrx의 실제 일별 자료가 `observed`일 때만 표시하며 실시간 체결가라고 표현하지 않습니다.
- Z3·Z4·Z5의 좋아요·수익률·사용자 구성은 목업임을 화면 안에서 명시합니다.
- 주문 버튼은 실제 증권사 연동 전까지 이동 안내만 제공하며 매매 기능으로 표현하지 않습니다.

## 7. 파일 구성

```text
design/Trend App Zip v2.dc.html  제공 디자인과 상호작용
design/trendzip-data.js          수집 결과 변환·저장·내보내기
docs/DESIGN_DATA_CONTRACT.md     프론트·백엔드 합의 계약
```
