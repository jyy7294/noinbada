# 후속 백엔드 팀원용 프롬프트

당신은 `https://github.com/jyy7294/noinbada`의 TRZIP 백엔드 담당자입니다.

먼저 `README.md`, `docs/PRODUCT_DIRECTION_TRANSCRIPT.md`, `docs/PRODUCT_POLICY.md`, `docs/COMPANY_RELATION_POLICY.md`, `docs/FRONTEND_BACKEND_CONTRACT_V3.md`를 읽고 전체 테스트를 실행하십시오.

목표는 찬희님 Windows 노트북에서 매시 정각 X 한국 실시간 1~30위와 Google Trending Now 대한민국 전체 목록을 누적하고, 전체 공정 순위·실측 대표어·관련어·증거 온톨로지 기업을 정적 JSON으로 내보내는 것입니다.

확정 규칙:

- X·Google만 점수 입력입니다.
- NAVER·YouTube·Instagram·기사는 검증·발견·설명 전용이며 `ranking_effect=none`입니다.
- 화면 제목은 실제 원천 표현입니다. 설명형 이름을 만들지 마십시오.
- 관련어는 실제 원천 표현·Google 관련 검색어·URL 근거가 있는 검수 온톨로지 표현만 최대 5개이며, 프런트 완성 목록은 서로 다른 출처 기반 표현 정확히 5개를 요구합니다.
- 모든 관측 후보는 `unified_ranking`에 남기고 `main/issue/review`는 표시만 나눕니다.
- 일간 24시간·주간 168시간·월간 720시간 기간 순위를 제공하고 일간을 기본 호환 화면으로 사용합니다.
- 기업은 완결된 증거 경로가 있는 서로 다른 국내외 상장기업 10개 이상이고 역할 카테고리가 2~4개면 준비 완료입니다. 부족하면 트렌드는 유지하고 `enrichment_pending`으로 두며 임의로 채우지 마십시오.
- pykrx는 일별 시장 참고자료이며 관계·상승 예측 근거가 아닙니다.
- GitHub Actions, Render, Google RSS, Trends MCP 자동호출, X API, 생성·백필 데이터를 추가하지 마십시오.

필수 검증:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m trzip.local_pipeline `
  --output work\team-e2e\publication `
  --database work\team-e2e\data.sqlite3
```

추가 확인:

- 전체 순위가 1부터 연속인지
- 각 기간 점수가 현재 관심 강도 35 + 실제 상승 속도 25 + X·Google 교차 확산 20 + 관측 지속성 10 + 최신성 10인지
- 상승 속도가 트렌드 자체의 서로 다른 시각 관측 3회 이상일 때만 계산되고, 단일 출처에 교차 확산 점수를 주지 않는지
- 기간강도가 원천별 `70% 신선도 가중 평균 + 30% 최고점`인지, 비교 가능한 정상 스냅샷이 부족할 때 상승 속도가 `unavailable`·0점이고 중립점수를 지급하지 않는지
- 60일 이력이 생애주기에만 사용되고 점수에는 들어가지 않는지
- 보조 검증 전후 rank/score가 동일한지
- `mode=live`에 실제 `observed`만 있는지
- 같은 시간 재실행이 중복되지 않는지
- 프런트 Top10 관련어가 정확히 5개이고 비어 있거나 중복되거나 출처 없는 표현이 없는지
- 프런트 Top10마다 근거 온톨로지가 완결된 서로 다른 국내외 상장기업이 최소 10개이고 역할 카테고리가 2~4개인지
- `hourly-source-proof-v2`와 `frontend-result-quality-v5` 사전검사를 원격 게시 전에 통과하는지
- 원격 객체·해시 검증과 불변 영수증까지 8시간 연속 성공했는지
- 공개 기업마다 관계 이유·회사 요약·산업 특성·증거·온톨로지 경로가 있는지
- 세 공개 문서의 게시 ID와 시각이 같은지

검증하지 않은 항목은 완료라고 쓰지 마십시오.
