# 프론트엔드 연동 명세

## 단일 권위 데이터

정적 프론트는 다음 고정 경로만 읽습니다.

```text
https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest/intelligence.json
https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest/status.json
https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest/metadata.json
```

URL 쿼리로 임의 `dataBase`를 주입하거나 배포 시점의 `/live` 스냅샷으로 전환하지 않습니다. GitHub 토큰과 API 키도 브라우저에 넣지 않습니다.

## 목록

- 홈: `public_top10`
- 전체: `unified_ranking`
- 지속기간순: `persistence_rank`
- 급상승순: `momentum_rank`
- 이슈·주의: `lanes.issue`

`home_context_status=review_required`는 실제 순위에는 포함하되 현상 맥락과 기업 관계가 아직 미확정이라는 뜻입니다. 이를 삭제하거나 임의 설명·기업으로 채우지 않습니다.

## 상태 판정

| 조건 | 화면 상태 |
|---|---|
| 마지막 관측 90분 이내 | 최신 |
| 90분 초과~3시간 | 지연 |
| 3시간 초과 | 오래된 데이터 |
| X·Google 중 한쪽 실패 | 부분 수집 |
| 네트워크 실패 후 캐시 | 오래된 캐시 |
| 네트워크·캐시 모두 없음 | 데이터 연결 실패 |

실패 시 HTML에 남아 있는 목업 트렌드를 실데이터처럼 표시하면 안 됩니다.

## 필드 분리

| UI | 필드 |
|---|---|
| 제목 | `display_name` |
| 실제 관측 표현 | `raw_terms` |
| 설명 | `phenomenon_summary` |
| 검토 상태 | `context_status`, `home_context_status` |
| 출처 | `latest_source_ranks`, `source_badge` |
| 관련어 | `keywords` 중 실제 관측 상태만 |
| 기업 | `companies` |
| 기업 관계 | `relation_display_type`, `verification_status`, `team_review_label` |

원격 문자열은 `textContent`로 렌더링합니다. `innerHTML`에 직접 삽입하지 않습니다.

## 사용자 저장

사용자가 현재 화면에서 선택·삭제한 키워드와 기업만 `trzip:portfolios:v1`에 저장합니다. 저장 폴더를 열면 정적 목업이 아니라 해당 저장 객체를 표시합니다. Z4·Z5의 사전 제작 밈트폴리오는 발표 목업으로 별도 유지합니다.
