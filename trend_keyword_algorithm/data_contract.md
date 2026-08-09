# 입력 데이터 계약

실제 게시물은 직접 수집하거나 허용된 별도 API가 만든 CSV를 아래 형식으로 저장해 사용합니다. 이 MVP는 외부 API나 크롤링을 수행하지 않습니다.

## `raw_documents.csv`

`data/raw_documents_template.csv`을 복사해 사용합니다.

| 열 | 설명 |
| --- | --- |
| `trend_id` | 트렌드 마스터의 ID |
| `platform` | SNS, 뉴스, YouTube, 블로그 등 출처 유형 |
| `published_at` | `YYYY-MM-DD` 형식의 게시 날짜 |
| `text` | 제목·본문·게시물 내용·영상 설명 등 문서 텍스트 |
| `url` | 근거 문서 URL |

## `seed_aliases.csv`

`data/seed_aliases_template.csv`을 복사해 사용합니다. 트렌드별 정식명·별칭·줄임말을 미리 등록하는 파일입니다.

| 열 | 설명 |
| --- | --- |
| `trend_id` | 트렌드 마스터의 ID |
| `alias` | 문서 검색에 사용할 표기 |
| `normalized_alias` | 띄어쓰기·대소문자 차이를 통합한 대표 표기 |

템플릿의 별칭 행은 예시이며, 실제 문서나 실제 URL은 포함하지 않습니다.
