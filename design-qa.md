# TRZIP 디자인 QA

- 검증일: 2026-08-14 KST
- 원본 시각 기준: 찬희님이 제공한 2026-08-14 21:21 모바일 홈 화면 캡처
- 원본 디자인 파일: `design/Trend App Zip v2.dc.html`
- 구현 화면: `frontend/index.html`
- 구현 캡처: `design/qa-implementation-home-error.png`
- 로컬 URL: `http://127.0.0.1:8766/index.html`
- 뷰포트: 430 × 930 CSS px, device scale 1
- 픽셀 크기: 원본 373 × 825 px, 구현 430 × 887 px
- 정규화: 두 화면의 휴대전화 프레임 전체를 같은 비교 입력에서 비례 비교했습니다. 원본 캡처와 구현 캡처의 래스터 크기가 달라 절대 픽셀 차이는 판정에 사용하지 않았습니다.
- 상태: 원본은 정상 데이터 상태, 구현은 승인된 `presentation_feed`가 원격에 아직 없는 오류 상태입니다.

**Findings**

- [P0] 승인된 Top10 발행본이 없어 정상 데이터 상태를 비교할 수 없음
  - Location: 홈 화면 / `frontend/index.html`
  - Evidence: 원본은 개기일식과 10개 트렌드가 채워져 있으나, 구현은 `frontend_default=true`인 10개 `presentation_feed`를 찾지 못해 `데이터를 불러오지 못했어요`를 표시합니다.
  - Impact: 디자인 쉘과 오류 상태는 확인했지만, 실제 키워드·추이·기업이 채워진 핵심 E2E 화면을 현재 원격 데이터로 검증할 수 없습니다.
  - Fix: 백엔드가 승인된 10개 `presentation_feed`를 `live-data`에 발행한 뒤 같은 뷰포트에서 홈·상세·기업·저장 화면을 다시 캡처합니다.

**Full-view comparison evidence**

- 같은 비교 입력에서 원본과 구현을 함께 열어 확인했습니다.
- 휴대전화 프레임, 상단 상태 영역, 헤더, 원형 트렌드 다이얼, 하단 밈트폴리오 영역의 비율·간격·색상·타이포 위계가 보존됐습니다.
- 구현 오류 상태는 목업 Top10으로 대체하지 않고 동일 레이아웃 안에 명확한 오류 문구를 표시합니다.

**Required fidelity surfaces**

- Fonts and typography: Wanted Sans 계열, 굵기 위계, 헤더와 본문 크기 관계가 원본과 일치합니다.
- Spacing and layout rhythm: 상단 헤더, 다이얼, 하단 카드의 영역 비율과 라운드 프레임이 보존됐습니다.
- Colors and visual tokens: 보라·분홍·노랑의 반투명 칩과 흰 배경, 진보라 강조색이 원본 토큰과 일치합니다.
- Image quality and asset fidelity: 원본의 인라인 SVG·장식 요소를 그대로 보존했습니다. 기업 로고는 백엔드의 검증된 `logo_url`만 사용하며 없으면 이니셜 아바타를 유지합니다.
- Copy and content: 실데이터 오류 상태를 정직하게 표시하고, 커뮤니티 목업에는 수익률이 실제 데이터가 아님을 명시했습니다.

**Focused region comparison evidence**

- 별도 확대 비교는 하지 않았습니다. 이번 차이는 컴포넌트 세부가 아니라 정상 데이터와 오류 데이터의 상태 차이이며, 폰 전체 캡처에서 헤더·다이얼·하단 카드 텍스트가 판독 가능했습니다.

**Primary interactions tested**

- 스플래시에서 홈 화면 진입
- 원격 발행본 검증 실패 시 목업 Top10 미사용
- 오류 상태의 트렌드 다이얼·상태 배지·커뮤니티 목업 경계 표시

**Console errors checked**

- 스크립트 구문 오류는 없습니다.
- 예상된 데이터 오류 1건: 승인된 `presentation_feed` Top10 미발행. 브라우저 기능 오류가 아니라 배포 데이터 게이트입니다.

**Comparison history**

1. 첫 확인에서 오류 상태인데도 원본 목업 트렌드 이름이 남는 P1 문제를 발견했습니다.
2. 오류 처리 뒤 `patchHomeLabels()`를 호출하도록 수정해 모든 트렌드 위치를 오류 상태 문구로 교체했습니다.
3. 재캡처에서 목업 Top10이 남지 않고 오류 상태가 일관되게 보이는 것을 확인했습니다.
4. 정상 데이터 상태는 원격 `presentation_feed` 미발행 때문에 아직 재비교하지 못했습니다.

**Implementation Checklist**

- [x] 원본 인터랙션 디자인을 `frontend/index.html`에 보존
- [x] `loadTrends()`와 `featuredTrends` 순서를 그대로 연결
- [x] 오류 시 목업 Top10 폴백 금지
- [x] 키워드·관심도 기간·기업 역할 폴더·로컬 저장·내보내기 연결
- [x] 5종 분석 이벤트 훅 연결
- [ ] 승인된 `presentation_feed` 발행 후 정상 데이터 상태 재검증

**Open Questions**

- 없음. 남은 항목은 디자인 결정이 아니라 백엔드 발행 데이터의 가용성입니다.

**Follow-up Polish**

- 정상 발행본이 올라오면 홈 외에 상세·기업·마이페이지의 실데이터 상태를 같은 크기로 추가 캡처합니다.

final result: blocked
