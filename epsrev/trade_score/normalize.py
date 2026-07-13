"""자기 이력 표준화 (핸드오프 2절① · STEP 2) — 각 축 신호를 '그 축 신호의 과거 분포'로 robust z화.

핵심 규약:
  - z = clip((x − median_hist) / MAD_hist, −3, +3). MAD=median(|v−median|).
    MAD=0 → std 폴백, std도 0/무효 → None. 이력 <MIN_HISTORY(12) → None.
  - ★ z의 기준은 '원값'이 아니라 '축 신호 자체의 이력':
      growth: mom←ma3_yoy 이력 · acc←accel(저점반등 포함) 이력 · qual←(vol−price) 이력 · cyc←runrate_gap 이력
      level : mom←Δ레벨(변화량) 이력 · acc←2차차분 이력 · cyc←레벨/24M평균−1 이력 · qual=None passthrough
    → 반도체(±80%)와 화장품(±15%)이 같은 스케일로. 단위 상이(금리 %p vs 수출 $)도 흡수.
  - None(결측 축)은 z화하지 않고 None 유지(가중제외 재정규화는 STEP 5).

섹터 특성 통계·자동 가중(2절②)은 STEP 3에서 이 모듈에 추가.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

from epsrev.trade_score.schema import AxisSignals
from epsrev.trade_score.signals import TROUGH_BONUS, CYCLE_WINDOW, CYCLE_MIN_MONTHS

MIN_HISTORY = 12   # 축 신호 이력 최소 관측수 — 미달 시 z=None
Z_CLIP = 3.0       # winsorize 한계
_DENOM_EPS = 1e-9


def self_history_z(hist_values, x, min_history: int = MIN_HISTORY) -> Optional[float]:
    """x를 hist_values(그 축 신호의 과거 시계열) 분포 기준으로 robust z화.

    z = clip((x − median)/MAD, ±3). MAD=0이면 std 폴백, 둘 다 무효면 None.
    이력(유효 관측) < min_history → None.
    """
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(xf) or math.isinf(xf):
        return None

    hist = pd.Series(hist_values, dtype=float).dropna()
    if len(hist) < min_history:
        return None

    med = float(hist.median())
    mad = float((hist - med).abs().median())
    scale = mad
    if scale < _DENOM_EPS:                       # MAD=0 → std 폴백
        std = float(hist.std(ddof=0))
        if not np.isfinite(std) or std < _DENOM_EPS:
            return None
        scale = std
    return float(np.clip((xf - med) / scale, -Z_CLIP, Z_CLIP))


# ---------- 축 신호 '이력' 구성 (과거 각 시점의 축 신호 시계열) ----------
def rolling_runrate_gap(values: pd.Series) -> pd.Series:
    """각 시점 t의 runrate_gap = x_t / mean(직전 24M까지, 최소 12M) − 1 이력.
    분모가 0 근처면 NaN(level 스프레드 발산 가드)."""
    if values is None or values.empty:
        return pd.Series(dtype=float)
    roll_mean = values.rolling(CYCLE_WINDOW, min_periods=CYCLE_MIN_MONTHS).mean()
    denom = roll_mean.where(roll_mean.abs() >= _DENOM_EPS)
    return values / denom - 1.0


def _growth_accel_hist(ma3_yoy_hist: pd.Series) -> pd.Series:
    """accel 이력: Δma3_yoy + 저점반등 보너스(신호 정의와 동일 — signals.growth_accel의 벡터판)."""
    accel = ma3_yoy_hist - ma3_yoy_hist.shift(1)
    prev = ma3_yoy_hist.shift(1)
    bonus_mask = (prev < 0) & (accel > 0)
    return accel.where(~bonus_mask, accel * (1.0 + TROUGH_BONUS))


def axis_signal_histories(values: Optional[pd.Series], series_type: str, *,
                          ma3_yoy_hist: Optional[pd.Series] = None,
                          volume_yoy_hist: Optional[pd.Series] = None,
                          price_yoy_hist: Optional[pd.Series] = None) -> dict:
    """축 신호 이력 dict {"mom","acc","qual","cyc"} 구성 (없으면 그 축은 None).

    growth: ma3_yoy_hist가 없으면 values(월간)에서 파생(YoY→3M평균).
    level : values(월간 레벨)에서 Δ/2차차분/추세갭 이력 파생. qual은 항상 None.
    """
    if series_type == "level":
        if values is None or values.empty:
            return {"mom": None, "acc": None, "qual": None, "cyc": None}
        delta = values.diff()
        return {
            "mom": delta,                          # 변화량 분포 기준 (레벨 원값 아님)
            "acc": delta.diff(),                   # 2차차분 이력
            "qual": None,                          # 정의상 없음 — passthrough
            "cyc": rolling_runrate_gap(values),
        }

    if series_type == "growth":
        ma3 = ma3_yoy_hist
        if ma3 is None and values is not None and len(values.dropna()) >= 15:
            ma3 = (values.pct_change(12) * 100.0).rolling(3).mean()
        qual = None
        if volume_yoy_hist is not None and price_yoy_hist is not None:
            qual = volume_yoy_hist - price_yoy_hist
        return {
            "mom": ma3,
            "acc": _growth_accel_hist(ma3) if ma3 is not None else None,
            "qual": qual,
            "cyc": rolling_runrate_gap(values) if values is not None else None,
        }

    raise ValueError(f"unknown series_type={series_type!r}")


def normalize_signals(raw: AxisSignals, histories: dict,
                      min_history: int = MIN_HISTORY) -> AxisSignals:
    """raw AxisSignals → 축별 자기이력 z화된 AxisSignals.

    각 축의 최신 raw 값을 그 축 신호 이력(histories["mom"|...])으로 z화.
    raw가 None이거나 이력이 없으면 None 유지(0 대체 금지).
    ⚠️ 이력 마지막 값이 최신 raw와 같은 시점이면 자기 자신 포함 z — 관측 1개 영향은
    미미하며(중앙값·MAD), 호출부가 이력에서 최신을 제외해 넘겨도 무방.
    """
    def _z(axis: str, x) -> Optional[float]:
        if x is None:
            return None
        hist = histories.get(axis)
        if hist is None:
            return None
        return self_history_z(hist, x, min_history=min_history)

    return AxisSignals(
        mom=_z("mom", raw.mom),
        acc=_z("acc", raw.acc),
        qual=_z("qual", raw.qual),
        cyc=_z("cyc", raw.cyc),
    )
