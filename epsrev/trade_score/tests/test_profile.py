"""STEP 3 pytest — 섹터 특성 통계(ρ·π·σ) + 자동 가중."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from epsrev.trade_score.normalize import (indicator_stats, sector_profile_raw,
                                          auto_weights, finalize_profiles,
                                          W_BASE, PI_NEUTRAL)


def _monthly(vals, start="2020-01"):
    idx = pd.period_range(start, periods=len(vals), freq="M").to_timestamp(how="end")
    return pd.Series(vals, index=idx, dtype=float)


# ---------------- auto_weights 방향성 ----------------
def test_cyclical_rho_up_boosts_acc():
    w_lo = auto_weights(rho=0.1, pi=0.5, sigma=0.5)
    w_hi = auto_weights(rho=0.9, pi=0.5, sigma=0.5)
    assert w_hi["acc"] > w_lo["acc"]
    assert w_hi["cyc"] > w_lo["cyc"]          # ρ는 사이클축도 강조


def test_commodity_pi_up_boosts_qual():
    w_lo = auto_weights(rho=0.3, pi=0.5, sigma=0.5)   # 중립
    w_hi = auto_weights(rho=0.3, pi=0.9, sigma=0.5)   # 단가 주도(원자재형)
    assert w_hi["qual"] > w_lo["qual"]
    # π<0.5(물량 주도)는 부스트 없음 — 중립과 동일
    w_vol = auto_weights(rho=0.3, pi=0.2, sigma=0.5)
    assert w_vol["qual"] == pytest.approx(w_lo["qual"])


def test_volatility_sigma_up_lowers_mom():
    w_lo = auto_weights(rho=0.3, pi=0.5, sigma=0.1)
    w_hi = auto_weights(rho=0.3, pi=0.5, sigma=0.9)
    assert w_hi["mom"] < w_lo["mom"]


def test_weights_sum_to_one():
    for rho, pi, sigma in [(0, 0.5, 0), (1, 1, 1), (0.4, 0.7, 0.3), (None, None, None)]:
        w = auto_weights(rho, pi, sigma)
        assert sum(w.values()) == pytest.approx(1.0)
        assert all(v > 0 for v in w.values())


def test_neutral_defaults_for_none():
    # None 통계 → 중립값(ρ=0, π=0.5, σ=0.5)과 동일한 가중
    assert auto_weights(None, None, None) == pytest.approx(
        auto_weights(0.0, PI_NEUTRAL, 0.5))


# ---------------- indicator_stats ----------------
def test_growth_indicator_stats_with_price_volume():
    rng = np.random.default_rng(3)
    ma3 = _monthly(np.cumsum(rng.normal(0, 1, 60)).tolist())      # 자기상관 있는 시리즈
    price = _monthly(rng.normal(0, 10, 60).tolist())               # 단가 변동 큼
    vol = _monthly(rng.normal(0, 2, 60).tolist())                  # 물량 변동 작음
    st = indicator_stats(series_type="growth", ma3_yoy_hist=ma3,
                         price_yoy_hist=price, volume_yoy_hist=vol)
    assert st["pi"] is not None and st["pi"] > 0.5                 # 단가 주도
    assert st["rho"] is not None and st["mad"] is not None


def test_level_indicator_stats_uses_delta_and_pi_none():
    level = _monthly(np.cumsum([1.0] * 30).tolist())
    st = indicator_stats(values=level, series_type="level")
    assert st["pi"] is None                       # level-only → π 없음
    # Δ가 전부 1.0(상수) → autocorr 정의 불가 → rho=None graceful
    assert st["rho"] is None


def test_sector_profile_mixed_growth_level_graceful():
    rng = np.random.default_rng(11)
    g = indicator_stats(series_type="growth",
                        ma3_yoy_hist=_monthly(rng.normal(5, 8, 48).tolist()),
                        price_yoy_hist=_monthly(rng.normal(0, 3, 48).tolist()),
                        volume_yoy_hist=_monthly(rng.normal(0, 6, 48).tolist()))
    l = indicator_stats(values=_monthly(np.cumsum(rng.normal(0.5, 1, 48)).tolist()),
                        series_type="level")
    prof = sector_profile_raw([g, l])
    assert prof["sigma_raw"] is not None          # MAD 중앙값 집계
    assert prof["pi"] is not None                 # growth 지표에서만 π 취합


def test_level_only_sector_pi_neutral_qual():
    rng = np.random.default_rng(5)
    stats = [indicator_stats(values=_monthly(np.cumsum(rng.normal(0, 1, 48)).tolist()),
                             series_type="level") for _ in range(3)]
    prof = sector_profile_raw(stats)
    assert prof["pi"] is None                     # level-only → None
    w = auto_weights(prof["rho"], prof["pi"], 0.5)
    # π=None → 중립 0.5 → qual 부스트 없음(기본 비중 그대로 정규화됨)
    w_neutral = auto_weights(prof["rho"], 0.5, 0.5)
    assert w["qual"] == pytest.approx(w_neutral["qual"])


# ---------------- finalize(전섹터 min-max) ----------------
def test_finalize_sigma_minmax_across_sectors():
    raw = {
        "반도체": {"rho": 0.6, "pi": 0.4, "sigma_raw": 40.0},   # 고변동
        "화장품": {"rho": 0.2, "pi": 0.3, "sigma_raw": 8.0},    # 저변동
        "금융":   {"rho": 0.5, "pi": None, "sigma_raw": 24.0},  # 중간·level성
    }
    profs = finalize_profiles(raw)
    assert profs["반도체"].sigma == pytest.approx(1.0)
    assert profs["화장품"].sigma == pytest.approx(0.0)
    assert 0.0 < profs["금융"].sigma < 1.0
    for p in profs.values():
        assert sum(p.weights.values()) == pytest.approx(1.0)
    # 고변동 섹터의 w_mom이 저변동보다 낮아야
    assert profs["반도체"].weights["mom"] < profs["화장품"].weights["mom"]


def test_finalize_single_or_equal_sigma_neutral():
    profs = finalize_profiles({"A": {"rho": 0.3, "pi": 0.5, "sigma_raw": 10.0},
                               "B": {"rho": 0.3, "pi": 0.5, "sigma_raw": 10.0}})
    assert profs["A"].sigma == pytest.approx(0.5)   # min==max → 중립
    assert profs["B"].sigma == pytest.approx(0.5)
