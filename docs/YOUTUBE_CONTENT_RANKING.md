# YouTube 대한민국 콘텐츠 트렌드 계약

## 목적

X와 Google Trends가 놓칠 수 있는 영화, 음악, 게임 콘텐츠를 YouTube Data API v3의 대한민국 `mostPopular` 차트로 발견한다.

## 순위 분리

- `home_top10`, `rising_top10`: X와 Google Trends 관측만으로 계산한 확산 순위
- `youtube_content_ranking`: YouTube 대한민국 인기 영상을 동일 콘텐츠 단위로 병합한 별도 순위
- `youtube_content_top10`: 위 콘텐츠 순위의 상위 10개
- `youtube_content_discovery.video_chart`: API 원본 영상 차트와 영상별 순위 변화
- `youtube_content_discovery.category_charts`: 영화·애니메이션, 음악, 게임, 엔터테인먼트의 대한민국 카테고리별 인기 차트

YouTube 순위는 `affects_x_google_rank=false`다. 서로 다른 척도를 한 점수로 합치지 않으며, YouTube에 없는 작품을 임의로 삽입하지 않는다.

## 정규화와 근거

- 공식 예고편의 작품명, 공식 MV·음원의 곡명처럼 짧은 콘텐츠명을 추출한다.
- 같은 작품·곡을 다룬 여러 영상은 하나의 이벤트 키로 병합한다.
- 원본 제목, 채널, 영상 URL, 조회수와 차트 순위는 `source_evidence`에 보존한다.
- `오디세이`는 `The Odyssey | Official Trailer`처럼 영화 맥락이 명확한 경우에만 한국어 작품명으로 정규화한다. 모니터 등 동명 제품과 섞지 않는다.

## 운영 제약

YouTube `mostPopular`는 지역별 인기 영상 차트이지 한국 문화 트렌드 전체의 완전한 표본은 아니다. 전체 인기 50개에서 특정 장르가 밀리는 문제를 줄이기 위해 카테고리 차트도 함께 보존하지만, 카테고리 순위를 전체 순위와 합산하지 않는다. API 미설정·쿼터·네트워크 실패는 `unavailable` 또는 `failed`로 공개하고 빈 차트를 인기 0으로 해석하지 않는다.
