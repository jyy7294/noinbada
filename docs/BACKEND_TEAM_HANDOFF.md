# TRZIP 백엔드 팀 인계서 V3

## 한 줄 구조

찬희님 노트북이 매시 X 한국 30개와 Google Trending Now KR 전체를 실제 수집해 SQLite에 누적하고, 결정론적 순위·약한 큐레이션·증거 온톨로지를 거쳐 정적 JSON을 `live-data`에 게시합니다.

## 책임 경계

- Core rank: X·Google만
- Context verification: NAVER·YouTube·Instagram·기사, 순위 영향 없음
- Company ready: 증거 경로 완결 + 국내외 상장기업 10개 이상 + 역할 카테고리 2~4개
- Market reference: pykrx 일별 값, 관계·추천 근거 아님
- Frontend: `docs/FRONTEND_BACKEND_CONTRACT_V3.md`와 `schemas/`만 준수

## 반드시 보존할 계약

1. 실제 원천 표현만 대표어와 관련어로 사용
2. 최근 24시간 전체 실측 순위는 `all_observed_ranking`에 보존
3. 표시 필터·카테고리·기사·기업은 점수 변경 금지
4. 기사 발견어는 X/Google 실제 관측 전 순위 삽입 금지
5. 기업 10개 미달이면 `enrichment_pending`, filler 금지
6. 생성·백필·fixture는 라이브 원장에 쓰기 금지
7. 공개 세 문서는 같은 `publication_id/generated_at/observed_at` 묶음
8. GitHub Actions·Render·Google RSS·Trends MCP·X API 추가 금지

## 팀원이 확장할 일

- 실제 신규 트렌드 정규화 정답셋을 늘리고 오답을 분리 보고
- 온톨로지 10개 미달 트렌드의 공식·기사·IR 근거 edge 추가
- NAVER 인증 오류 원인 확인 및 키 재설정
- Instagram 공식 토큰이 생길 때 검증 provider 연결
- 72/168회 실행 후 출처별 성공률과 실패유형 평가

## 검증

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m trzip.local_pipeline `
  --output work\team-e2e\publication `
  --database work\team-e2e\data.sqlite3
```

완료 보고에서 코드·실제 수집·누적시간·정규화 정확도·기업 Gold·외부 인증 상태를 분리하십시오.
