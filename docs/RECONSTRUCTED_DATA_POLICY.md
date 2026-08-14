# TRZIP 검수 재구성 데이터 정책

## 목적

`data/reconstructed/trzip-final-50-20260814`는 2026-08-14 검수본 50건을
결정론적으로 가져온 연구·데모용 사건 카탈로그입니다. 이 자료는 과거 X·Google
실시간 순위표를 복원한 것이 아니므로 라이브 관측 원장이나 실제 순위 입력으로
사용하지 않습니다.

## 고정 구분

- `data_mode=reconstructed`
- `live_eligible=false`
- `ranking_eligible=false`
- `ranking_effect=none`
- 원본 XLSX의 SHA-256과 변환된 NDJSON의 SHA-256을 manifest에 기록

검수본은 별칭, 사건 설명, 1주·1개월·3개월 조사 여부, 관련 키워드와 기업 관계
후보를 데모 재생 및 보강 캐시에 제공합니다. 라이브 홈 카드는 같은 사건이 실제
X·Google 관측과 현재 공개 품질 계약을 별도로 통과할 때만 만들어집니다.

공개 관련 키워드는 실데이터와 동일하게 정확히 5개, 공백 제외 최대 6글자 계약을
적용합니다. 원본 조사항목은 감사용 `source_related_keywords`에 보존하고 긴 표현을
잘라 공개 키워드로 위장하지 않습니다.

## 현재 계약과의 차이

원본의 `완성`은 근거 2건·키워드 5개·기업 3개라는 이전 기준입니다. 현재 홈
계약은 키워드 5개, 근거 있는 상장기업 10개, 명확한 기업 역할 2~4개, 최소 2개
키워드의 기업 연결을 요구합니다. 가져오기 결과가 부족하면
`frontend_readiness_status=enrichment_pending`으로 남기며 숫자를 맞추기 위한
기업·키워드 패딩은 하지 않습니다.

## 다시 생성

```powershell
$env:PYTHONPATH='src'
py -3.13 scripts/import-reconstructed-workbook.py `
  data/reconstructed/trzip-final-50-20260814/source.xlsx `
  --output data/reconstructed/trzip-final-50-20260814
```
