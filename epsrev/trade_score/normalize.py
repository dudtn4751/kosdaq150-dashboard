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


# ======================================================================
# 섹터 특성 통계 + 자동 가중 (핸드오프 2절② · STEP 3)
# ======================================================================
# 기본 가중과 부스트 계수 — 전 섹터 공통 튜닝상수
W_BASE = {"mom": 0.30, "acc": 0.30, "qual": 0.20, "cyc": 0.20}
ACC_RHO_COEF = 0.6     # 사이클성(ρ) → 가속 강조
ACC_SIGMA_COEF = 0.3   # 변동성(σ) → 가속 강조
CYC_RHO_COEF = 0.5     # 사이클성(ρ) → 사이클축 강조
QUAL_PI_COEF = 0.8     # 단가 주도성(π>0.5) → 품질 강조
MOM_SIGMA_COEF = 0.3   # 변동성(σ) → 모멘텀 신뢰 하향
AUTOCORR_LAG = 3
# None 통계의 중립 기본값 (이력 부족·level-only 등)
RHO_NEUTRAL, PI_NEUTRAL, SIGMA_NEUTRAL = 0.0, 0.5, 0.5


def _safe_autocorr(series: pd.Series, lag: int = AUTOCORR_LAG) -> Optional[float]:
    clean = series.dropna() if series is not None else pd.Series(dtype=float)
    if len(clean) < lag + 4 or float(clean.std(ddof=0)) < _DENOM_EPS:
        return None
    ac = clean.autocorr(lag=lag)
    return None if (ac is None or not np.isfinite(ac)) else float(ac)


def indicator_stats(values: Optional[pd.Series] = None, series_type: str = "growth", *,
                    ma3_yoy_hist: Optional[pd.Series] = None,
                    price_yoy_hist: Optional[pd.Series] = None,
                    volume_yoy_hist: Optional[pd.Series] = None) -> dict:
    """지표 1개의 특성 통계(집계 전 원료): {rho, pi, mad}.

    - growth: 기준 시계열=ma3_yoy 이력(없으면 values에서 파생).
              pi는 price/volume 이력 둘 다 있을 때만(없으면 None).
    - level : 기준 시계열=Δ레벨(변화량). pi=None(단가/물량 개념 없음).
    """
    if series_type == "level":
        base = values.diff() if values is not None else None
        pi = None
    elif series_type == "growth":
        base = ma3_yoy_hist
        if base is None and values is not None and len(values.dropna()) >= 15:
            base = (values.pct_change(12) * 100.0).rolling(3).mean()
        pi = None
        if price_yoy_hist is not None and volume_yoy_hist is not None:
            vp = float(price_yoy_hist.dropna().var(ddof=0))
            vv = float(volume_yoy_hist.dropna().var(ddof=0))
            if np.isfinite(vp) and np.isfinite(vv) and (vp + vv) > _DENOM_EPS:
                pi = vp / (vp + vv)
    else:
        raise ValueError(f"unknown series_type={series_type!r}")

    rho = _safe_autocorr(base) if base is not None else None
    mad = None
    if base is not None:
        clean = base.dropna()
        if len(clean) >= MIN_HISTORY:
            med = float(clean.median())
            mad = float((clean - med).abs().median())
    return {"rho": rho, "pi": pi, "mad": mad}


def sector_profile_raw(indicator_stats_list: list) -> dict:
    """섹터 내 지표 여러 개 → 대표 통계(중앙값 집계, mixed growth/level graceful).

    반환 {rho, pi, sigma_raw}: sigma_raw는 MAD 원값(전섹터 min-max는 finalize에서).
    - rho: 유효 지표 autocorr의 중앙값 → clip 0~1. 전부 None → None.
    - pi : price/volume 있는(growth) 지표들만의 중앙값. level-only 섹터 → None(→중립 0.5).
    - sigma_raw: 유효 MAD의 중앙값.
    """
    def _med(key):
        vals = [s[key] for s in indicator_stats_list if s.get(key) is not None]
        return float(np.median(vals)) if vals else None

    rho = _med("rho")
    if rho is not None:
        rho = float(np.clip(rho, 0.0, 1.0))
    return {"rho": rho, "pi": _med("pi"), "sigma_raw": _med("mad")}


def auto_weights(rho: Optional[float], pi: Optional[float],
                 sigma: Optional[float]) -> dict:
    """섹터 특성 → 축 가중(Σ=1). None 통계는 중립값으로 대체.

    w_acc  = 0.30·(1 + 0.6·ρ + 0.3·σ)   사이클형·고변동 → 가속 강조
    w_cyc  = 0.20·(1 + 0.5·ρ)            사이클형 → 사이클 강조
    w_qual = 0.20·(1 + 0.8·max(0,π−0.5)·2)  원자재형(단가 주도) → 품질 강조
    w_mom  = 0.30·(1 − 0.3·σ)            고변동 → 모멘텀 신뢰 하향
    ※ qual 없는(level) 지표·섹터는 '집계 시점'(STEP 5)에 w_qual 자연 제외·재정규화 —
      여기서는 π=0.5 중립이라 qual 부스트 없음(기본 비중 유지)."""
    r = RHO_NEUTRAL if rho is None else float(np.clip(rho, 0.0, 1.0))
    p = PI_NEUTRAL if pi is None else float(np.clip(pi, 0.0, 1.0))
    s = SIGMA_NEUTRAL if sigma is None else float(np.clip(sigma, 0.0, 1.0))

    w = {
        "acc": W_BASE["acc"] * (1.0 + ACC_RHO_COEF * r + ACC_SIGMA_COEF * s),
        "cyc": W_BASE["cyc"] * (1.0 + CYC_RHO_COEF * r),
        "qual": W_BASE["qual"] * (1.0 + QUAL_PI_COEF * max(0.0, p - 0.5) * 2.0),
        "mom": W_BASE["mom"] * (1.0 - MOM_SIGMA_COEF * s),
    }
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}


def finalize_profiles(raw_profiles: dict) -> dict:
    """{sector: sector_profile_raw 결과} → {sector: SectorProfile}.

    sigma_raw를 '전 섹터' min-max로 0~1 정규화(전부 동일/유효 1개 → 중립 0.5),
    각 섹터에 auto_weights 부여."""
    from epsrev.trade_score.schema import SectorProfile

    sig_vals = [p["sigma_raw"] for p in raw_profiles.values() if p.get("sigma_raw") is not None]
    lo = min(sig_vals) if sig_vals else None
    hi = max(sig_vals) if sig_vals else None

    out = {}
    for sec, p in raw_profiles.items():
        sigma = None
        if p.get("sigma_raw") is not None and lo is not None:
            sigma = SIGMA_NEUTRAL if hi - lo < _DENOM_EPS else (p["sigma_raw"] - lo) / (hi - lo)
        out[sec] = SectorProfile(
            rho=p.get("rho"), pi=p.get("pi"), sigma=sigma,
            weights=auto_weights(p.get("rho"), p.get("pi"), sigma),
        )
    return out
