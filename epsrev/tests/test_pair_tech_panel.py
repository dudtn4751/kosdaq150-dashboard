"""leg_technical_panel 단위테스트 — 이상적 발산 / 동조 / 결측."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from epsrev.pair_tech_panel import leg_technical_panel


def _df(close, value):
    n = len(close)
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=n, freq="B"),
        "close": np.asarray(close, dtype=float),
        "value": np.asarray(value, dtype=float),
    })


# ── (1) 이상적 발산: 롱 강(정배열·상승·유입) / 숏 약(역배열·하락·이탈) ──────
def test_ideal_divergence():
    n = 130
    x = np.arange(n)
    long_close = 100 + 0.6 * x          # 정배열 상승
    long_value = 500 + 5 * x            # 거래대금 증가 → vt>1
    short_close = 260 - 0.6 * x         # 역배열 하락
    short_value = 900 - 4 * x           # 거래대금 감소 → vt<1

    r = leg_technical_panel(_df(long_close, long_value), _df(short_close, short_value))

    assert r["long"]["ma_stack"] == "정배열"
    assert r["short"]["ma_stack"] == "역배열"
    assert "골든" in r["long"]["macd_state"]
    assert "데드" in r["short"]["macd_state"]
    assert r["long"]["rsi14"] > 55 and r["short"]["rsi14"] < 45
    assert r["divergence_score"] >= 40
    assert r["flag"] == "이상적 발산"


# ── (2) 동조: 둘 다 강함 → 발산 0 근처 → 페어 약함 ────────────────────────
def test_concordant_both_strong():
    n = 130
    x = np.arange(n)
    up = 100 + 0.6 * x
    vol = 500 + 5 * x
    r = leg_technical_panel(_df(up, vol), _df(up.copy(), vol.copy()))

    assert r["long"]["ma_stack"] == "정배열"
    assert r["short"]["ma_stack"] == "정배열"
    assert abs(r["divergence_score"]) < 20        # 같은 방향 → 0 근처
    assert r["flag"] == "페어 약함(같은 방향)"


# ── (3) 결측: 빈/짧은 입력 → 그레이스풀 ───────────────────────────────────
def test_missing():
    r = leg_technical_panel(pd.DataFrame(), pd.DataFrame())
    assert set(r) == {"long", "short", "divergence_score", "flag"}
    assert r["divergence_score"] is None
    assert r["flag"] == "보통"
    assert r["long"]["ma_stack"] == "—" and r["long"]["rsi14"] is None

    # close 컬럼 없음 / 한쪽만 결측
    n = 130
    good = _df(100 + 0.6 * np.arange(n), 500 + 5 * np.arange(n))
    r2 = leg_technical_panel(good, pd.DataFrame({"date": ["2026-01-01"]}))
    assert r2["divergence_score"] is None
    assert r2["long"]["ma_stack"] == "정배열"      # 정상 쪽은 계산됨


def test_output_schema():
    n = 130
    x = np.arange(n)
    r = leg_technical_panel(_df(100 + 0.6 * x, 500 + 5 * x), _df(260 - 0.6 * x, 900 - 4 * x))
    for leg in ("long", "short"):
        assert set(r[leg]) >= {"disparity20", "ma_stack", "macd_state", "rsi14", "vol_trend"}
    assert isinstance(r["flag"], str)
    assert r["divergence_score"] is None or isinstance(r["divergence_score"], float)
