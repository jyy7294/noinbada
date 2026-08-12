# 비용 0원 프로덕션 운영

## 확정 구조

```text
GitHub Actions(매시간 수집·분석)
        ↓
GitHub live-data 브랜치(날짜별 원본 + 최신 결과 JSON)
        ↓
Vercel 프론트(Claude Design)
```

## 데이터 주소

```text
https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest/intelligence.json
https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest/coverage.json
https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest/metadata.json
```

캐시 회피가 필요한 경우 쿼리에 현재 시각을 추가합니다.

## 저장 정책

- `latest/intelligence.json`: 프론트가 읽는 최신 통합 결과
- `latest/coverage.json`: 누적 관찰 범위
- `latest/metadata.json`: 실행시각·수집 감사·오류
- `observations/YYYY-MM-DD.json`: 시간별 원천 관측의 날짜 단위 원장
- 운영 관찰 보존기간: 최근 104일
- API 키·쿠키·SQLite 파일은 저장하지 않음

## 운영 특성

- 매시 정각 GitHub Actions 실행
- 동일 시간·소스·키워드는 결정론적으로 덮어써 중복 방지
- Trends MCP 자동사용 금지
- 수집 실패 시 워크플로 로그와 `metadata.json`에서 확인
- 장기 상용화 시 PostgreSQL 어댑터로 전환 가능
