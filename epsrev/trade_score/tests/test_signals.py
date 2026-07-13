"""STEP 1 pytest — 4축 원신호(growth/level) + 월간 리샘플."""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from epsrev.trade_score.preprocess import resample_monthly
from epsrev.trade_score.signals import (growth_signals, level_signals,
                                        compute_signals, growth_accel,
                                        growth_quality, runrate_gap, TROUGH_BONUS)


def _monthly(vals, start="2023-01"):
    idx = pd.period_range(start, periods=len(vals), freq="M").to_timestamp(how="end")
    return pd.Series(vals, index=idx, dtype=float)


# ---------------- growth ----------------
def test_growth_momentum_positive():
    s = growth_signals(ma3_yoy=25.0, ma3_yoy_prev=20.0, volume_yoy=10.0, price_yoy=5.0)
    assert s.mom == 25.0 and s.acc == pytest.approx(5.0)


def test_growth_accel_positive_and_negative():
    assert growth_accel(10.0, 4.0) == pytest.approx(6.0)
    assert growth_accel(4.0, 10.0) == pytest.approx(-6.0)


def test_growth_quality_volume_led_positive():
    # 물량 우세(진짜 성장) → 가점
    assert growth_quality(volume_yoy=20.0, price_yoy=5.0) == pytest.approx(15.0)


def test_growth_quality_price_led_negative():
    # 단가 우세(착시 성장) → 감점
    assert growth_quality(volume_yoy=2.0, price_yoy=18.0) == pytest.approx(-16.0)


def test_growth_trough_rebound_bonus():
    # 음수 저점(-20) 통과 후 개선(-5): 개선폭 15에 보너스 가산
    plain = 15.0
    boosted = growth_accel(-5.0, -20.0)
    assert boosted == pytest.approx(plain * (1 + TROUGH_BONUS))
    # 양수 구간의 동일 개선폭엔 보너스 없음
    assert growth_accel(20.0, 5.0) == pytest.approx(plain)


def test_growth_missing_returns_none():
    s = growth_signals(ma3_yoy=None, ma3_yoy_prev=5.0, volume_yoy=None, price_yoy=3.0)
    assert s.mom is None and s.acc is None and s.qual is None and s.cyc is None


def test_growth_cycle_runrate_gap():
    vals = [100.0] * 23 + [130.0]           # 최근값이 24M평균 대비 상회
    gap = runrate_gap(_monthly(vals))
    assert gap is not None and gap > 0
    assert runrate_gap(_monthly([100.0] * 5)) is None   # 이력<12M 가드


def test_growth_derives_ma3_from_values():
    # 사전계산 지표 없이 values만으로 ma3_yoy 파생(15개월 이상)
    vals = [100 * (1.02 ** i) for i in range(30)]        # 꾸준한 성장
    s = growth_signals(_monthly(vals))
    assert s.mom is not None and s.mom > 0


# ---------------- level ----------------
def test_level_rising_momentum():
    s = level_signals(_monthly([1.0, 1.5, 2.5]))
    assert s.mom == pytest.approx(1.0)       # Δ = 2.5-1.5


def test_level_accel_second_diff():
    # x=[1,2,4]: Δ=[1,2] → 2차차분 = 4-2*2+1 = 1
    s = level_signals(_monthly([1.0, 2.0, 4.0]))
    assert s.acc == pytest.approx(1.0)


def test_level_quality_always_none():
    s = level_signals(_monthly(list(np.linspace(1, 30, 30))))
    assert s.qual is None                    # 품질축 정의상 제외


def test_level_no_yoy_logic():
    # 레벨 3.0→3.3(금리성 시리즈): mom은 Δ(0.3)이어야지 YoY%(10.0)가 아니어야 함
    vals = [3.0] * 12 + [3.3]
    s = level_signals(_monthly(vals))
    assert s.mom == pytest.approx(0.3)
    assert s.mom != pytest.approx(10.0)


def test_level_missing_short_series():
    s = level_signals(_monthly([5.0]))
    assert s.mom is None and s.acc is None and s.cyc is None and s.qual is None


def test_level_cycle_vs_trend():
    vals = [100.0] * 23 + [90.0]
    s = level_signals(_monthly(vals))
    assert s.cyc is not None and s.cyc < 0   # 추세 하회


# ---------------- resample ----------------
def test_resample_daily_to_month_mean():
    idx = pd.date_range("2024-01-01", "2024-02-29", freq="D")
    s = pd.Series([1.0] * 31 + [3.0] * 29, index=idx)     # 1월=1, 2월=3
    out = resample_monthly(s, how="mean", freq="일", series_type="level")
    assert len(out) == 2
    assert out.iloc[0] == pytest.approx(1.0) and out.iloc[1] == pytest.approx(3.0)


def test_resample_auto_daily_level_is_mean():
    idx = pd.date_range("2024-01-01", "2024-01-31", freq="D")
    s = pd.Series(np.linspace(100, 130, 31), index=idx)   # BDI류
    out = resample_monthly(s, how="auto", freq="일", series_type="level")
    assert out.iloc[0] == pytest.approx(s.mean())          # auto→월평균


def test_resample_auto_weekly_growth_is_sum():
    idx = pd.date_range("2024-01-07", periods=8, freq="W")
    s = pd.Series([10.0] * 8, index=idx)
    out = resample_monthly(s, how="auto", freq="주", series_type="growth")
    assert out.iloc[0] == pytest.approx(40.0)              # 1월 4개 관측 합


def test_resample_quarterly_interp_to_monthly():
    idx = pd.to_datetime(["2024-03-31", "2024-06-30"])
    s = pd.Series([100.0, 130.0], index=idx)
    out = resample_monthly(s, how="interp", freq="분기", series_type="growth")
    assert len(out) == 4                                    # 3~6월
    assert out.iloc[1] == pytest.approx(110.0)             # 4월 선형보간
    assert out.iloc[2] == pytest.approx(120.0)             # 5월


def test_resample_monthly_passthrough_yyyymm_index():
    s = pd.Series([1.0, 2.0], index=[202401, 202402])      # YYYYMM 정수 인덱스
    out = resample_monthly(s, how="auto", freq="월", series_type="growth")
    assert len(out) == 2 and out.index[0].month == 1


# ---------------- 통합 진입점 ----------------
def test_compute_signals_dispatch():
    lvl = compute_signals(_monthly([1.0, 2.0, 4.0]), "level", freq="월")
    assert lvl.qual is None and lvl.acc == pytest.approx(1.0)
    grw = compute_signals(None, "growth", ma3_yoy=10.0, ma3_yoy_prev=5.0,
                          volume_yoy=8.0, price_yoy=2.0)
    assert grw.mom == 10.0 and grw.qual == pytest.approx(6.0)
    with pytest.raises(ValueError):
        compute_signals(_monthly([1.0]), "unknown")
