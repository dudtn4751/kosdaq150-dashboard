# FnSpace 목업 fixtures (개발/테스트용)

⚠️ **MOCK — STEP A에서 실제 FnSpace 응답으로 교체할 것.**

키 수령 전 파서·어댑터 개발/테스트를 위한 **가짜 응답**입니다. 종목은 삼성전자(005930),
값은 "상향 리비전" 시나리오로 임의 구성했습니다(단위·필드명은 실제와 다를 수 있음).

## 파일별 — 우리가 실제로 쓰는 값만 담음

| 파일 | 담긴 것 | 매핑 대상(StockInput / fnspace_extra) |
|---|---|---|
| `mock_forward.json` | 12M Fwd EPS **일별 시계열**(날짜, 값) | `eps_fy1 / _1m / _3m` (오늘·1M전·3M전) |
| `mock_estimate_daily.json` | 영업이익(·당기순이익) 추정 **일별 시계열** | `op_fy1 / _1m / _3m` |
| `mock_estimate_fiscal.json` | FY1/FY2 영업이익·EPS 추정 + 결산년월 | `op_fy2`, `eps_fy2`, `fy_consensus_op`(FY1 OP) |
| `mock_opinion_tp.json` | 목표주가(Adj.) 일별, 참여 증권사 수, 목표주가 상향/하향/전체(1주·1개월·3개월) | `tp_now / tp_3m_ago`, `analyst_n`, `diffusion`(proxy) |
| `mock_financial.json` | 최근 4분기 실제 영업이익 + 어닝 서프라이즈 | `surprise_4q` |

## 사용 규칙
- 각 JSON 최상단 `"_MOCK"` 키에 교체 안내 명시. 실제 응답을 받으면 **구조·필드명 그대로** 덮어쓰기.
- 원시 필드명(`DATE`/`VAL`/`OP_EST` 등)은 **임시값**입니다. 파서는 이 이름에 의존하지 말고,
  STEP A 실제 응답 확인 후 `fnspace.py`에서 매핑하세요.
- 원시 JSON ↔ `StockInput` 사이의 **정규화 중간표현**은 [`../fnspace_types.py`](../fnspace_types.py)에 정의.
  (원시 필드명과 분리 — 실제 필드명이 바뀌어도 중간표현·하위 로직은 불변)

## 직접 못 구하는 값(설계상 None 고정)
- `dispersion.std`, `dispersion.mean`, `dispersion.avg_estimate_age_days` → **None**
  (개별 증권사 추정치 분포 미제공 → Layer2 분산은 신뢰도 게이트에서 자연 강등)
