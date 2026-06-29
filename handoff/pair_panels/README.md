# 롱숏 페어 패널 패키지 — 통합 가이드 (팀원용)

페어 파인더에 **비율선 패널(진입 타이밍·헤지 건전성)** + **레그별 기술 확인 패널(발산 점수)** 을 추가하는 키트입니다.
순수 함수 2개는 그대로 쓰고, **일봉 소스만 연결**하면 켜집니다. 소스 연결 전엔 페이지가 안 깨지고 '비활성 캡션'만 표시됩니다.

## 들어있는 것
| 파일 | 놓을 위치 | 설명 |
|---|---|---|
| `pair_panel.py` | repo **루트** | 비율선 패널 순수 함수 `pair_ratio_panel(df_long, df_short, lookback=60)` |
| `pair_tech_panel.py` | repo **루트** | 레그 기술 패널 순수 함수 `leg_technical_panel(df_long, df_short)` |
| `get_price_df.py` | 내용을 **`data/scorer.py`** 에 붙여넣기 | 종목 일봉 어댑터 — `_load_daily`만 여러분 소스에 맞춰 구현 |
| `render_snippet.py` | 내용을 **페어 파인더 페이지** 끝에 붙여넣기 | 위 dict를 소비해 차트/메트릭 렌더(차트 코드는 여기에) |
| `tests/` | repo 루트 `tests/` | `pytest`로 두 순수 함수 검증 |

> 의존 패키지: `numpy`, `pandas`, `plotly`(렌더용), `streamlit`. (추가 설치 불필요할 가능성 높음)

## 4단계
1. **순수 함수 2개 복사** → `pair_panel.py`, `pair_tech_panel.py` 를 repo 루트에 둔다.
2. **일봉 어댑터 연결** → `get_price_df.py` 의 `get_price_df` 를 `data/scorer.py` 에 추가하고,
   `_load_daily(ticker)` 만 여러분의 일봉 소스(CSV/DB/API)에 맞춰 구현한다.
   - 반환 계약: `DataFrame[date, close, value]` (value=거래대금). 데이터 없으면 `None`.
   - **아직 소스가 없으면** `_load_daily`를 `return None` 그대로 두면 됨 → 패널은 비활성 캡션.
3. **렌더 스니펫 삽입** → `render_snippet.py` 의 블록을 페어 파인더 페이지의 *페어 상세 분석* 다음에 붙여넣는다.
   (이미 통합된 `pair_finder_v2.py`를 쓰고 있다면 이 블록은 들어가 있음 — 1·2번만 하면 됨.)
4. **검증** → `pytest tests/test_pair_panel.py tests/test_pair_tech_panel.py` (둘 다 통과해야 함).

## 동작/활성화 조건
- `get_price_df` 가 일봉을 반환 → 패널 **활성**(차트·메트릭·발산 점수).
- 반환 `None`(소스 미연결) 또는 모듈 부재 → 페이지는 **정상**, 패널 자리에 안내 캡션.
- 일봉 **60거래일** 이상이면 z-score·상관·MACD·RSI 산출. **120거래일** 이면 이동평균 정/역배열까지(미만이면 '혼조').

## 설계 원칙
- 두 함수는 **순수 함수**(외부 I/O·차트 코드 없음) → 어떤 대시보드에도 이식 가능. 입출력은 dict 계약.
- 차트/렌더는 **페이지 쪽**(render_snippet)에서만. 데이터 주입은 `get_price_df` 한 군데로 격리.

## 함수 출력 계약(요약)
- `pair_ratio_panel(...)` → `{"series":{date,log_ratio,ma20,ma60,zscore,roll_corr}, "current":{zscore,roll_corr,slope60,half_life,roll_beta}, "flags":{corr_ok,z_state,trend_state}}`
- `leg_technical_panel(...)` → `{"long":{disparity20,disparity60,ma_stack,macd_state,rsi14,vol_trend}, "short":{...}, "divergence_score":float|None, "flag":str}`
