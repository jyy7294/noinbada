# TRZIP 디자인·동작 QA

- 검증일: 2026-08-15 KST
- 기준 시안: 사용자가 제공한 2026-08-14 모바일 화면 캡처와 `design/Trend App Zip v2.dc.html`
- 구현 파일: `frontend/index.html`, `frontend/trendzip-data.js`
- 운영 주소: `https://trzip-x-google.vercel.app`
- 검증 뷰포트: 기존 393×852 모바일 프레임을 데스크톱 프리뷰 안에서 확인
- 데이터 표면: `presentation_feed` 10개 카드

## 최종 판정

`passed`

승인된 10개 트렌드가 홈, 상세, 관련 기업, 밈트폴리오 목록·상세, 만들기, 마이페이지에 동일하게 연결됩니다. 고정 목업 목록과 JSON·CSV 내보내기는 제거됐고, 빈 데이터나 로딩 상태를 실제 데이터처럼 표시하지 않습니다.

## 화면과 데이터 계약

- 홈: 승인된 Top10 이름과 순서를 그대로 표시합니다.
- 트렌드 상세: 설명, 진입·포착·확산·대중화 단계, 현재 Top10 순위, 관련 키워드 5개를 표시합니다.
- 관심지수: 1주·1개월·3개월, 전체·X·Google 보기를 모두 제공합니다.
- 관련 기업: 카드마다 상장기업 10개를 3~4개 역할 폴더로 나누고, 기업명·로고·연결 이유를 표시합니다.
- 기업 하단시트: 30일 가격 차트와 가격·등락률·시가총액·PER·PBR·ROE·관계 근거를 표시합니다.
- 밈트폴리오: 목록·상세·만들기·저장·마이페이지가 같은 기업과 로고 데이터를 사용합니다.
- 긴 제목: 홈, 상세, 기업 화면에서 두 줄 제한과 줄바꿈을 적용해 가로 넘침을 막았습니다.

## 실제 브라우저 E2E

- 스플래시 → 홈 진입
- 홈 Top10과 인기 밈트폴리오 렌더링
- 트렌드 상세의 1주·1개월·3개월 전환
- 전체·X·Google 관심지수 표시
- 관련 기업 10개와 역할 폴더 3~4개 표시
- 기업 하단시트의 차트·밸류에이션 표시
- 밈트폴리오 목록·상세·만들기·저장·마이페이지 이동
- 운영 화면에서 구형 목업 문구와 내보내기 문구 0건
- 운영 브라우저 콘솔 오류 0건
- 가로 오버플로 0건

## 자동 검증

- 전체 테스트: 362 passed, 1 skipped
- Python compileall: passed
- PowerShell 구문 검사: passed
- 스키마 검사: passed
- 비밀값·사용자 절대경로 검사: passed
- Git diff check: passed
- 운영 `index.html`과 `trendzip-data.js`: 로컬 파일 SHA-256과 동일

## 캡처 증거

- `work/product-audit-after/01-home-preview.png`
- `work/product-audit-after/02-detail-preview.png`
- `work/product-audit-after/03-companies-preview.png`
- `work/product-audit-after/04-company-sheet-preview.png`
- `work/product-audit-after/05-portfolio-list-preview.png`
- `work/product-audit-after/07-maker-preview.png`
- `work/product-audit-after/08-saved-portfolio-preview.png`
- `work/product-audit-after/10-production-home.png`

## 운영상 남은 검증

- 1주·1개월·3개월 선은 발표용 보강 시계열이며 원천 순위 계산에는 영향을 주지 않습니다.
- 이전 자동화 실행 공백 때문에 8회 연속 정각 수집 증명은 아직 완료되지 않았습니다. 이후 실행에서 별도로 누적 검증합니다.
- 원격 `live-data`는 매일 06:00 KST에만 갱신하므로, 시간별 로컬 분석 결과와 프런트 공개 시각은 다를 수 있습니다.
