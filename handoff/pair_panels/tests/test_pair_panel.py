"""pair_ratio_panel 단위테스트 — 정상 페어 / 상관 붕괴 / 짧은 데이터."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pair_panel import pair_ratio_panel

Z_STATES = {"중립", "롱레그 과열·추격주의", "스프레드 과도 역행·역진입 기회"}
TREND_STATES = {"중립", "롱 우위 추세", "숏 우위 추세"}


def _df(close, start="2026-01-01"):
    n = len(close)
    return pd.DataFrame({
        "date": pd.date_range(start, periods=n, freq="B"),
        "close": close,
        "value": np.full(n, 1000.0),
    })


# ── (1) 정상 페어: 높은 상관 + 롱 우위 추세 ───────────────────────────────
def test_normal_pair():
    rng = np.random.default_rng(1)
    n = 100
    common = rng.normal(0, 0.01, n)                     # 공통 시장요인 → 높은 상관
    ret_l = common + 0.002 + rng.normal(0, 0.003, n)    # 드리프트(+) → 롱 우위 추세
    ret_s = common + rng.normal(0, 0.003, n)
    cl = 100 * np.exp(np.cumsum(ret_l))
    cs = 100 * np.exp(np.cumsum(ret_s))

    r = pair_ratio_panel(_df(cl), _df(cs), lookback=60)

    assert len(r["series"]["date"]) == n
    assert all(len(r["series"][k]) == n for k in ("log_ratio", "ma20", "ma60", "zscore", "roll_corr"))
    assert r["current"]["roll_corr"] is not None and r["current"]["roll_corr"] >= 0.5
    assert r["flags"]["corr_ok"] is True
    assert r["flags"]["trend_state"] == "롱 우위 추세"      # slope60 > 0
    assert r["current"]["zscore"] is not None
    assert r["current"]["slope60"] is not None and r["current"]["slope60"] > 0
    assert r["flags"]["z_state"] in Z_STATES
    assert r["flags"]["trend_state"] in TREND_STATES
    # half_life는 None 또는 양수
    assert r["current"]["half_life"] is None or r["current"]["half_life"] > 0


# ── (2) 상관 붕괴: 독립 랜덤워크 → corr < 0.5 ─────────────────────────────
def test_correlation_breakdown():
    rng = np.random.default_rng(7)
    n = 120
    cl = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    cs = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))   # 독립

    r = pair_ratio_panel(_df(cl), _df(cs), lookback=60)

    assert r["current"]["roll_corr"] is not None
    assert r["current"]["roll_corr"] < 0.5
    assert r["flags"]["corr_ok"] is False                 # 페어 논리 약화 경고


# ── (3) 짧은 데이터(윈도우 미만): 그레이스풀 ──────────────────────────────
def test_short_data():
    rng = np.random.default_rng(3)
    n = 30                                                 # lookback 60 미만
    cl = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    cs = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))

    r = pair_ratio_panel(_df(cl), _df(cs), lookback=60)

    assert len(r["series"]["date"]) == n                   # 시리즈는 보존
    assert r["current"]["zscore"] is None                  # 윈도우 미만 → None
    assert r["current"]["roll_corr"] is None
    assert r["flags"]["corr_ok"] is False
    assert r["flags"]["z_state"] == "중립"                  # 크래시 없음


# ── 가드: 빈/결측 입력 ────────────────────────────────────────────────────
def test_guards_empty_and_missing():
    empty = pair_ratio_panel(pd.DataFrame(), pd.DataFrame(), lookback=60)
    assert empty["series"]["date"] == [] and empty["flags"]["corr_ok"] is False
    # close 컬럼 없음
    bad = pair_ratio_panel(pd.DataFrame({"date": ["2026-01-01"]}), _df([100, 101, 102]))
    assert bad["current"]["zscore"] is None
    # 분모 0(숏 close 0) 섞여도 크래시 없음
    dfl = _df([100, 101, 102, 103, 104])
    dfs = _df([10, 0, 11, 0, 12])
    r = pair_ratio_panel(dfl, dfs, lookback=3)
    assert isinstance(r["series"]["date"], list)           # 0 행 제거 후에도 안전
