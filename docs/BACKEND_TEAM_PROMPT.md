# 다른 백엔드 팀원에게 전달할 작업 프롬프트

아래 내용을 그대로 복사해 사용하십시오.

---

당신은 TRZIP 저장소의 후속 백엔드 담당자입니다.

저장소: `https://github.com/jyy7294/noinbada`

작업 전에 `README.md`, `docs/BACKEND_TEAM_HANDOFF.md`, `docs/COMPANY_RELATION_POLICY.md`, `docs/DESIGN_DATA_CONTRACT.md`를 읽고 전체 테스트를 실행하십시오. 기존 사용자 변경과 승인된 UI를 보존하십시오.

## 확정 아키텍처

- 찬희님 Windows 노트북의 작업 스케줄러가 매시 00분 전체 파이프라인을 실행합니다.
- X는 설치된 Chrome의 TRZIP 전용 프로필로 `https://x.com/explore/tabs/trending`을 직접 읽습니다.
- Google은 Trends RSS `geo=KR`만 사용합니다.
- 영구 원장은 로컬 SQLite입니다.
- 공개 JSON만 `live-data` 브랜치의 `latest/`, `observations/`, `monitoring/`에 자동 커밋합니다.
- Vercel 프론트는 raw GitHub의 고정 JSON URL을 읽습니다.
- GitHub Actions, X API, Trends MCP 자동호출은 사용하지 않습니다.

## 작업 목표

1. 최근 실제 트렌드 20~30건으로 개발 규칙과 분리된 정규화 평가셋을 구축하십시오.
2. 사건명·대분류·동음이의어 보류 정확도를 각각 측정하고 오답 목록을 남기십시오.
3. 불명확한 인물명·작품명·일반명사는 원인을 만들지 말고 `needs_context`로 유지하십시오.
4. 기업 관계를 직접 관계·가치사슬·산업 관찰·연결 제외로 분리하고 공식 근거와 팀 검수 상태를 보강하십시오.
5. `pending_evidence`를 `confirmed_relationship`로 표시하지 마십시오.
6. 관련 키워드는 서로 다른 문서 또는 원천에서 2회 이상 실제 관측된 후보만 공개하십시오. 근거가 없으면 0개가 정상입니다.
7. `monitoring/run_history.json`으로 72회와 168회 실제 수집 성공률을 계산하십시오.

## 금지사항

- X API·X 최근 검색 API·Bearer Token 추가
- YouTube·NAVER·Instagram을 순위 입력으로 추가
- 생성·fixture 데이터를 라이브 순위에 혼합
- Google RSS의 무관한 다른 사건 제목을 관련 키워드 근거로 사용
- 후보어 사전을 실제 관측 키워드처럼 표시
- 근거가 없는데 기업 3개 또는 관계 범주 3개를 채우기
- pykrx 가격을 기업 관계 또는 미래 수익 근거로 사용
- 프론트 레이아웃·색상·컴포넌트 변경
- 코드·비밀키·Chrome 프로필·SQLite를 `live-data`에 게시

## 필수 검증

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m trzip.local_pipeline `
  --output work\team-e2e\publication `
  --database work\team-e2e\data.sqlite3
```

추가로 다음을 확인하십시오.

- X API 문자열과 `X_BEARER_TOKEN`이 런타임 코드에 0건
- `mode=live` 결과에 `provenance=generated` 0건
- 같은 시간 재실행 후 중복 행 0건
- 한 출처 실패 시 다른 출처와 이전 정상 스냅샷 보존
- 미확정 트렌드는 순위에 남되 기업 0개와 검토 상태 표시
- 산업 관찰기업이 직접 관계로 승격되지 않음
- 공개 관련 키워드가 모두 관측 근거를 가짐
- 자동 게시 경로가 `latest/`, `observations/`, `monitoring/`로 제한됨

## 최종 보고 형식

- 변경한 기능과 파일
- 테스트와 실제 수집 결과
- 평가셋 규모·정확도·오답
- 공식 검증 기업 / 산업 관찰기업 / 미검수 기업 수
- 실제 누적 실행 수·출처별 성공률
- 아직 완료되지 않은 외부·사람 검수 항목

검증하지 않은 항목을 완료라고 표현하지 마십시오.

---
