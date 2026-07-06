"""pair_backtest: 반복 회귀 페어 vs 미회귀(발산) 페어."""
import numpy as np
import pandas as pd

from epsrev.pair_backtest import backtest_spread, rebase100


def _df(closes, start="2024-01-01"):
    dates = pd.date_range(start, periods=len(closes)).strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "close": list(closes), "value": [1e5] * len(closes)})


def test_backtest_mean_reverting():
    # log(cl/cs)가 AR(1)(고정 평균 0 평균회귀) → 극단 진입→회귀 청산 승률 높음
    rng = np.random.RandomState(3)
    n = 500
    sp = np.zeros(n)
    for i in range(1, n):
        sp[i] = 0.9 * sp[i - 1] + rng.normal(0, 0.015)
    cs = np.full(n, 100.0)
    cl = 100 * np.exp(sp)
    r = backtest_spread(_df(cl), _df(cs), entry=2.0, exit=0.5, lookback=60)
    assert r["trades"] >= 2
    assert r["win_rate"] is not None and r["win_rate"] >= 55
    assert r["avg_hold"] is not None and r["mdd"] is not None


def test_backtest_diverging():
    # 스프레드가 단조 발산 → 회귀 안 함 → 트레이드 0(청산 미발생)
    n = 300
    cs = np.full(n, 100.0)
    cl = 100 * np.exp(np.linspace(0, 0.5, n))    # 계속 벌어짐
    r = backtest_spread(_df(cl), _df(cs), entry=2.0, exit=0.5, lookback=40)
    assert r["trades"] == 0


def test_backtest_short_data():
    r = backtest_spread(_df([1, 2, 3]), _df([2, 3, 4]))
    assert r["trades"] == 0 and r["win_rate"] is None


def test_rebase100():
    out = rebase100(_df([100, 110, 90]))
    assert out[0]["val"] == 100.0 and out[1]["val"] == 110.0 and out[2]["val"] == 90.0
    assert rebase100(None) == []
