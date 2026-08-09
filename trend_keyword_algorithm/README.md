# 트렌드 키워드 알고리즘 MVP

이 프로젝트는 두 단계로 나뉩니다. `candidate_generator.py`는 사람이 준비한 문서 CSV에서 검토용 후보와 근거를 만들고, 기존 `scorer.py`는 사람이 M:S 점수를 입력한 뒤 총점과 최종 판정을 계산합니다. 외부 API·크롤링·LLM은 사용하지 않습니다.

## 1. 입력 파일 준비

`data/raw_documents_template.csv`을 `data/raw_documents.csv`로 복사해 실제 수집 문서를 채웁니다. 열 설명은 [data_contract.md](data_contract.md)에 있습니다.

`data/seed_aliases_template.csv`을 `data/seed_aliases.csv`로 복사해 대표명·별칭·줄임말을 넣습니다. 원본 엑셀의 `trend_id`를 사용해야 합니다.

## 2. 후보 수집 실행

Windows PowerShell 예시입니다.

```powershell
python trend_keyword_algorithm/candidate_generator.py `
  --workbook "트렌드_키워드마스터_MVP_템플릿_v1.1.xlsx" `
  --documents trend_keyword_algorithm/data/raw_documents.csv `
  --aliases trend_keyword_algorithm/data/seed_aliases.csv `
  --output-dir trend_keyword_algorithm/output/candidates
```

생성되는 `candidate_pool.csv`와 `candidate_evidence.csv`는 후보와 근거를 확인하는 파일입니다. `candidate_review_template.xlsx`에는 자동 생성한 후보 정보가 채워지고, M:S 점수 칸은 비어 있습니다.

## 3. 점수 검토와 최종 판정

검토자가 템플릿의 M:S 점수와 역할을 확정합니다. 점수가 비어 있으면 파이프라인은 채점을 막고 안내만 출력합니다.

```powershell
python trend_keyword_algorithm/pipeline.py `
  --workbook "트렌드_키워드마스터_MVP_템플릿_v1.1.xlsx" `
  --documents trend_keyword_algorithm/data/raw_documents.csv `
  --aliases trend_keyword_algorithm/data/seed_aliases.csv `
  --output-dir trend_keyword_algorithm/output/candidates
```

기존 `scorer.py`는 현재의 트렌드·키워드 마스터 형식을 입력으로 사용합니다. 기존 `result_keywords` 파일 보호를 위해 파이프라인은 자동으로 이를 덮어쓰지 않습니다.

점수 입력을 완료한 템플릿으로 최종 판정을 실행하려면, 덮어쓰기 권한을 명시하고 검토 파일을 지정합니다.

```powershell
python trend_keyword_algorithm/pipeline.py `
  --workbook "트렌드_키워드마스터_MVP_템플릿_v1.1.xlsx" `
  --review trend_keyword_algorithm/output/candidates/candidate_review_template.xlsx `
  --output-dir trend_keyword_algorithm/output/candidates `
  --allow-overwrite-results
```

## 설치와 테스트

```powershell
python -m pip install -r trend_keyword_algorithm/requirements.txt
python -m unittest discover -s trend_keyword_algorithm/tests -v
```

`tests/fixtures`는 **Synthetic test fixture / 가상 테스트 데이터**이며, 실제 SNS 게시물이나 실제 URL이 아닙니다.
