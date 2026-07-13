"""4축 원신호 (핸드오프 1절 · STEP 1) — 순수 함수, raw 값 반환.

규약:
  - 반환은 AxisSignals(raw). 정규화(z)는 STEP 2, 가중합은 STEP 5.
  - 결측/가드 미달 축은 None (0 채우기 금지 — 집계에서 가중제외 재정규화).
  - series_type 분기:
      growth : 모멘텀=ma3_yoy · 가속=Δma3_yoy(+저점반등 보너스) · 품질=물량-단가 · 사이클=runrate_gap
      level  : 모멘텀=Δ레벨 · 가속=레벨 2차차분 · 품질=None(항상) · 사이클=레벨 vs 24M평균
               ★ level형에 YoY-성장률 로직 금지(레벨의 YoY%는 왜곡) — 이 모듈은 구조적으로 미사용.
  - 모든 시계열은 이 모듈 진입 전(또는 compute_signals 내부에서) 월간 리샘플 완료 상태여야 함.
"""
from __future__ import annotations

import math
from typing import Optional

import pandas as pd

from epsrev.trade_score.schema import AxisSignals
from epsrev.trade_score.preprocess import resample_monthly

# 저점반등 보너스: ma3_yoy_prev<0(트로프)에서 개선(accel>0) 시 가속에 얹는 배수
TROUGH_BONUS = 0.5
# 사이클 축 최소 이력(개월) — 미달 시 None
CYCLE_MIN_MONTHS = 12
CYCLE_WINDOW = 24
# level 사이클 분모 가드: |24M평균| 이 시리즈 MAD 대비 이보다 작으면 None(0 근처 발산 방지)
_LEVEL_DENOM_EPS = 1e-9


def _num(v) -> Optional[float]:
    """유효 숫자만 통과(None/NaN → None)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


# ---------- growth형 ----------
def growth_accel(ma3_yoy, ma3_yoy_prev) -> Optional[float]:
    """가속 = Δma3_yoy. 저점반등(전월 ma3_yoy<0에서 개선)이면 개선폭에 보너스."""
    m, p = _num(ma3_yoy), _num(ma3_yoy_prev)
    if m is None or p is None:
        return None
    accel = m - p
    if p < 0 and accel > 0:                 # 음수 저점 통과 후 개선 → 사이클 전환 신호 강화
        accel += TROUGH_BONUS * accel
    return accel


def growth_quality(volume_yoy, price_yoy) -> Optional[float]:
    """품질 = 물량 우세 가점 / 단가 우세 감점 (raw = volume_yoy − price_yoy).
    스케일 정규화는 STEP 2의 자기이력 z가 담당."""
    v, p = _num(volume_yoy), _num(price_yoy)
    if v is None or p is None:
        return None
    return v - p


def runrate_gap(values: pd.Series) -> Optional[float]:
    """사이클 = 최근값/24M평균 − 1. 이력<12M 또는 분모 가드 미달 → None."""
    if values is None or len(values.dropna()) < CYCLE_MIN_MONTHS:
        return None
    clean = values.dropna()
    latest = _num(clean.iloc[-1])
    denom = _num(clean.tail(CYCLE_WINDOW).mean())
    if latest is None or denom is None or abs(denom) < _LEVEL_DENOM_EPS:
        return None
    return latest / denom - 1.0


def growth_signals(values: Optional[pd.Series] = None, *,
                   ma3_yoy=None, ma3_yoy_prev=None,
                   volume_yoy=None, price_yoy=None) -> AxisSignals:
    """growth형 4축. 수출 실측은 compute_item/company_metrics의 사전계산 값을 그대로 받고,
    산업 시계열은 values(월간)만 주면 ma3_yoy·prev를 내부 파생한다."""
    if (ma3_yoy is None or ma3_yoy_prev is None) and values is not None and len(values.dropna()) >= 15:
        yoy = values.pct_change(12) * 100.0
        ma3 = yoy.rolling(3).mean()
        if ma3_yoy is None:
            ma3_yoy = ma3.iloc[-1]
        if ma3_yoy_prev is None and len(ma3.dropna()) >= 2:
            ma3_yoy_prev = ma3.iloc[-2]
    return AxisSignals(
        mom=_num(ma3_yoy),
        acc=growth_accel(ma3_yoy, ma3_yoy_prev),
        qual=growth_quality(volume_yoy, price_yoy),
        cyc=runrate_gap(values) if values is not None else None,
    )


# ---------- level형 ----------
def level_delta(values: pd.Series) -> Optional[float]:
    """모멘텀 = Δ레벨(전월 대비). 관측<2 → None. (레벨 YoY% 금지)"""
    clean = values.dropna() if values is not None else pd.Series(dtype=float)
    if len(clean) < 2:
        return None
    return _num(clean.iloc[-1] - clean.iloc[-2])


def level_accel(values: pd.Series) -> Optional[float]:
    """가속 = 레벨 2차 차분 = x_t − 2x_{t−1} + x_{t−2}. 관측<3 → None."""
    clean = values.dropna() if values is not None else pd.Series(dtype=float)
    if len(clean) < 3:
        return None
    return _num(clean.iloc[-1] - 2.0 * clean.iloc[-2] + clean.iloc[-3])


def level_signals(values: pd.Series) -> AxisSignals:
    """level형 4축. 품질축은 정의상 항상 None(집계에서 w_qual 제외·재정규화)."""
    return AxisSignals(
        mom=level_delta(values),
        acc=level_accel(values),
        qual=None,                       # 가격/수준엔 물량·단가 개념 없음
        cyc=runrate_gap(values),         # 레벨 vs 24M 추세 위치(동일식, 분모 가드 포함)
    )


# ---------- 통합 진입점 ----------
def compute_signals(series: Optional[pd.Series], series_type: str,
                    freq: str = "월", how: str = "auto", **growth_metrics) -> AxisSignals:
    """시계열 1개 → (월간 리샘플) → series_type 분기 → AxisSignals(raw).

    growth_metrics: 수출 실측처럼 사전계산 지표가 있으면 전달
                    (ma3_yoy, ma3_yoy_prev, volume_yoy, price_yoy).
    """
    monthly = resample_monthly(series, how=how, freq=freq, series_type=series_type) \
        if series is not None else None
    if series_type == "level":
        if monthly is None:
            return AxisSignals()
        return level_signals(monthly)
    if series_type == "growth":
        return growth_signals(monthly, **growth_metrics)
    raise ValueError(f"unknown series_type={series_type!r}")
