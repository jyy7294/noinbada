# 다른 백엔드 팀원에게 전달할 작업 프롬프트

아래 내용을 그대로 복사해 사용합니다.

---

당신은 TRZIP 저장소의 후속 백엔드 담당자입니다.

저장소: `https://github.com/jyy7294/noinbada`

먼저 `README.md`, `docs/BACKEND_TEAM_HANDOFF.md`, `docs/COMPANY_RELATION_POLICY.md`, `docs/DESIGN_DATA_CONTRACT.md`를 읽고 현재 테스트를 실행하세요. 기존 사용자 변경과 프론트 디자인을 보존하세요.

`docs/BACKEND_TEAM_HANDOFF.md`의 2026-08-12 후속 구현 결과가 현재 코드에 존재하면 A~E를 처음부터 다시 작성하지 마세요. 먼저 테스트와 JSON 산출물로 구현 사실을 확인하고, 실패한 계약만 최소 범위로 수정하세요. 72회·168회처럼 실제 시간 누적이 필요한 측정치는 샘플을 복제해 완료로 만들지 말고 `collecting_baseline` 또는 `measuring_3_to_7_days`로 남기세요.

목표는 UI를 바꾸는 것이 아니라 다음 백엔드 품질을 개선하는 것입니다.

1. X와 Google Trends의 서로 다른 검색어를 동일 사건으로 안전하게 클러스터링합니다.
2. 작품명·인물명·일반명사의 동음이의어를 판별하고 불명확하면 `원인 미확인` 또는 `needs_context`로 남깁니다.
3. 실제 반복 관측된 관련 키워드만 `observed`로 승격하고, 없으면 `insufficient`와 구체적 사유를 반환합니다.
4. 기업을 `직접 관계`, `가치사슬`, `산업 관찰`, `연결 제외`로 구분하고 공식 근거 URL을 검증합니다.
5. `config/company_review_overrides.json`의 팀 승인 상태를 결과에 적용합니다.
6. 별도 수동 평가셋으로 사건명·카테고리·동음이의어 판별 정확도를 측정하고 오답 목록을 남깁니다.
7. `live-data/monitoring/run_history.json`을 이용해 최소 3일, 최종 7일 수집 성공률을 측정합니다.

현재 추가된 검증 자산:

- `config/normalization_holdout.json`: `live-data` 실제 관측에서 별도 라벨링해 고정한 24건 평가셋
- `scripts/evaluate-normalization.py`: 정확도와 오답 JSON 생성
- `GET /api/v1/keywords/google-related`: Google Trends KR RSS 제목·설명 반복 표현 집계
- `latest/normalization_evaluation.json`: 운영 파이프라인의 고정 평가 보고서

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
