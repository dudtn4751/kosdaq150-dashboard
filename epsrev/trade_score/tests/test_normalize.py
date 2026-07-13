"""STEP 2 pytest — 자기 이력 robust z (축 신호 분포 기준)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from epsrev.trade_score.schema import AxisSignals
from epsrev.trade_score.normalize import (self_history_z, axis_signal_histories,
                                          normalize_signals, rolling_runrate_gap,
                                          MIN_HISTORY, Z_CLIP)


def _monthly(vals, start="2020-01"):
    idx = pd.period_range(start, periods=len(vals), freq="M").to_timestamp(how="end")
    return pd.Series(vals, index=idx, dtype=float)


# ---------------- self_history_z 코어 ----------------
def test_high_vol_and_low_vol_same_scale():
    """반도체류(±80%)와 화장품류(±15%)가 같은 z 스케일로 정규화."""
    rng = np.random.default_rng(42)
    semi = rng.normal(0, 40, 60)     # 고변동 ma3_yoy 이력
    cosm = rng.normal(0, 8, 60)      # 저변동
    # 각자 'MAD 2배' 위치의 신규 관측 → z가 비슷해야 함
    z_semi = self_history_z(semi, np.median(semi) + 2 * np.median(np.abs(semi - np.median(semi))))
    z_cosm = self_history_z(cosm, np.median(cosm) + 2 * np.median(np.abs(cosm - np.median(cosm))))
    assert z_semi == pytest.approx(2.0, abs=1e-9)
    assert z_cosm == pytest.approx(2.0, abs=1e-9)


def test_mad_zero_std_fallback():
    hist = [5.0] * 20 + [5.5, 4.5]           # median=5, MAD=0 (과반 동일), std>0
    med = np.median(hist)
    assert np.median(np.abs(np.array(hist) - med)) == 0.0
    z = self_history_z(hist, 5.6)
    assert z is not None and z > 0            # std 폴백으로 유효 z


def test_all_identical_returns_none():
    assert self_history_z([3.0] * 24, 3.1) is None   # MAD=0·std=0 → None


def test_winsorize_pm3():
    hist = list(np.linspace(-10, 10, 40))
    assert self_history_z(hist, 1e6) == pytest.approx(Z_CLIP)
    assert self_history_z(hist, -1e6) == pytest.approx(-Z_CLIP)


def test_short_history_none():
    assert self_history_z([1.0, 2.0, 3.0], 2.0) is None            # <12
    assert self_history_z(list(range(MIN_HISTORY)), 5.0) is not None


def test_none_x_passthrough():
    assert self_history_z(list(range(30)), None) is None


# ---------------- 축 이력 구성 ----------------
def test_level_mom_z_uses_delta_distribution():
    """level mom의 z 기준이 '레벨 원값'이 아니라 'Δ(변화량) 분포'인지."""
    # 레벨: 매월 +0.8/+1.2 교대로 상승(Δ 이력≈1.0) 후 마지막 달 +5.0 점프
    deltas = [0.8, 1.2] * 12 + [5.0]
    level = pd.Series(np.cumsum([100.0] + deltas))
    values = _monthly(level.tolist())
    hists = axis_signal_histories(values, "level")
    raw = AxisSignals(mom=5.0, acc=None, qual=None, cyc=None)
    z = normalize_signals(raw, hists)
    # Δ분포(중앙값 1.0, MAD 0.2) 기준이면 (5-1)/0.2=20 → +3 클립.
    # 레벨 원값(100~126) 분포 기준이었다면 z가 큰 음수가 됨 → 구분 확실.
    assert z.mom == pytest.approx(Z_CLIP)


def test_level_qual_stays_none():
    values = _monthly(list(np.linspace(1, 40, 40)))
    hists = axis_signal_histories(values, "level")
    assert hists["qual"] is None
    z = normalize_signals(AxisSignals(mom=1.0, acc=0.0, qual=None, cyc=0.1), hists)
    assert z.qual is None


def test_growth_histories_from_precomputed():
    rng = np.random.default_rng(7)
    ma3 = _monthly(rng.normal(10, 5, 40).tolist())
    vol = _monthly(rng.normal(8, 4, 40).tolist())
    prc = _monthly(rng.normal(2, 3, 40).tolist())
    vals = _monthly((100 * np.cumprod(1 + rng.normal(0.01, 0.02, 40))).tolist())
    hists = axis_signal_histories(vals, "growth", ma3_yoy_hist=ma3,
                                  volume_yoy_hist=vol, price_yoy_hist=prc)
    assert all(hists[k] is not None for k in ("mom", "acc", "qual", "cyc"))
    raw = AxisSignals(mom=float(ma3.iloc[-1]), acc=1.0, qual=6.0, cyc=0.05)
    z = normalize_signals(raw, hists)
    assert all(getattr(z, a) is not None for a in ("mom", "acc", "qual", "cyc"))
    assert all(-Z_CLIP <= getattr(z, a) <= Z_CLIP for a in ("mom", "acc", "qual", "cyc"))


def test_growth_derives_ma3_hist_from_values():
    vals = _monthly((100 * 1.02 ** np.arange(40)).tolist())
    hists = axis_signal_histories(vals, "growth")
    assert hists["mom"] is not None and hists["acc"] is not None
    assert hists["qual"] is None                     # vol/price 이력 없으면 qual 이력 없음


def test_raw_none_stays_none():
    vals = _monthly(list(np.linspace(1, 40, 40)))
    hists = axis_signal_histories(vals, "level")
    z = normalize_signals(AxisSignals(mom=None, acc=None, qual=None, cyc=None), hists)
    assert z.mom is None and z.acc is None and z.qual is None and z.cyc is None


def test_rolling_runrate_gap_denominator_guard():
    # 0 근처를 오가는 스프레드: 분모(24M평균)≈0 구간은 NaN이어야(발산 금지)
    vals = _monthly(([1.0, -1.0] * 15))
    gap = rolling_runrate_gap(vals)
    assert gap.tail(6).isna().all()


def test_unknown_series_type_raises():
    with pytest.raises(ValueError):
        axis_signal_histories(_monthly([1.0] * 20), "price")
