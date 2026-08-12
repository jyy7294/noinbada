# 다른 백엔드 팀원에게 전달할 작업 프롬프트

아래 내용을 그대로 복사해 사용합니다.

---

당신은 TRZIP 저장소의 후속 백엔드 담당자입니다.

저장소: `https://github.com/jyy7294/noinbada`

먼저 `README.md`, `docs/BACKEND_TEAM_HANDOFF.md`, `docs/COMPANY_RELATION_POLICY.md`, `docs/DESIGN_DATA_CONTRACT.md`를 읽고 현재 테스트를 실행하세요. 기존 사용자 변경과 프론트 디자인을 보존하세요.

목표는 UI를 바꾸는 것이 아니라 다음 백엔드 품질을 개선하는 것입니다.

1. X와 Google Trends의 서로 다른 검색어를 동일 사건으로 안전하게 클러스터링합니다.
2. 작품명·인물명·일반명사의 동음이의어를 판별하고 불명확하면 `원인 미확인` 또는 `needs_context`로 남깁니다.
3. 실제 반복 관측된 관련 키워드만 `observed`로 승격하고, 없으면 `insufficient`와 구체적 사유를 반환합니다.
4. 기업을 `직접 관계`, `가치사슬`, `산업 관찰`, `연결 제외`로 구분하고 공식 근거 URL을 검증합니다.
5. `config/company_review_overrides.json`의 팀 승인 상태를 결과에 적용합니다.
6. 별도 수동 평가셋으로 사건명·카테고리·동음이의어 판별 정확도를 측정하고 오답 목록을 남깁니다.
7. `live-data/monitoring/run_history.json`을 이용해 최소 3일, 최종 7일 수집 성공률을 측정합니다.

강제 제약:

- 운영 트렌드 원천은 X 한국 실시간과 Google Trends KR만 사용합니다.
- Trends MCP 자동호출, YouTube, NAVER, Instagram을 추가하지 않습니다.
- 생성 데이터나 fixture를 운영 순위에 넣지 않습니다.
- KRX·키움 REST API를 사용하지 않습니다.
- 시장가격을 관련기업 선정 근거나 미래 수익 예측에 사용하지 않습니다.
- `frontend/`와 `design/`의 UI·레이아웃·스타일을 수정하지 않습니다.
- Z4·Z5 밈트폴리오 목업은 유지합니다.
- 근거가 없는데 기업 3개를 직접 수혜기업처럼 만들지 않습니다. 산업 후보는 반드시 `산업 관찰`로 표시합니다.

먼저 읽을 파일:

- `src/trzip/event_resolution.py`
- `src/trzip/intelligence.py`
- `src/trzip/related_keywords.py`
- `src/trzip/value_chain.py`
- `src/trzip/github_pipeline.py`
- `config/company_review_overrides.json`

완료 전에 반드시 수행할 검증:

```powershell
python -m pytest -q
python -m trzip.github_pipeline --output work\team-e2e --retention-days 104
```

최종 보고에는 다음을 분리해 작성하세요.

- 실제로 개선한 정확도
- 새 평가셋 규모와 오답
- 관련 키워드 실측률
- 공식 검증 기업과 산업 관찰기업 수
- 3일/7일 수집 성공률
- 아직 검증되지 않은 부분
- 변경 파일과 커밋 해시

완료 기준을 충족하지 못한 항목을 완료라고 표현하지 마세요.

---
