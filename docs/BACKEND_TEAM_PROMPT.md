# 후속 백엔드 팀원용 프롬프트

당신은 `https://github.com/jyy7294/noinbada`의 TRZIP 백엔드 담당자입니다.

먼저 `README.md`, `docs/PRODUCT_POLICY.md`, `docs/COMPANY_RELATION_POLICY.md`, `docs/FRONTEND_BACKEND_CONTRACT_V3.md`를 읽고 전체 테스트를 실행하십시오.

목표는 찬희님 Windows 노트북에서 매시 정각 X 한국 실시간 1~30위와 Google Trending Now 대한민국 전체 목록을 누적하고, 전체 공정 순위·실측 대표어·관련어·증거 온톨로지 기업을 정적 JSON으로 내보내는 것입니다.

확정 규칙:

- X·Google만 점수 입력입니다.
- NAVER·YouTube·Instagram·기사는 검증·발견·설명 전용이며 `ranking_effect=none`입니다.
- 화면 제목은 실제 원천 표현입니다. 설명형 이름을 만들지 마십시오.
- 관련어는 실제 원천 표현 또는 Google 관련 검색어만 0~5개입니다.
- 모든 관측 후보는 `unified_ranking`에 남기고 `main/issue/review`는 표시만 나눕니다.
- 기업은 완결된 증거 경로가 있는 서로 다른 국내 상장기업 5개 이상일 때만 공개합니다. 부족하면 `ontology_incomplete`로 두고 채우지 마십시오.
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
- 점수가 현재 위치 40 + 정확한 직전 정각 변화 20 + 출처별 성숙 지속성 20 + 시간감쇠 이력 15 + 교차출처 5인지
- 보조 검증 전후 rank/score가 동일한지
- `mode=live`에 실제 `observed`만 있는지
- 같은 시간 재실행이 중복되지 않는지
- 관련어에 임의 표현이 없는지
- 공개 기업마다 관계 이유·회사 요약·산업 특성·증거·온톨로지 경로가 있는지
- 세 공개 문서의 게시 ID와 시각이 같은지

검증하지 않은 항목은 완료라고 쓰지 마십시오.
