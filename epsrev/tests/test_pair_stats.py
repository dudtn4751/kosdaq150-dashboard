"""pair_stats: compute_pair_stats(정상/무상관/결측) + rank_pair_score 단위테스트."""
import numpy as np
import pandas as pd

from epsrev.pair_stats import compute_pair_stats, rank_pair_score


def _df(closes, start="2024-01-01"):
    dates = pd.date_range(start, periods=len(closes)).strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "close": list(closes), "value": [1e5] * len(closes)})


def _cointegrated(n=250, seed=42):
    rng = np.random.RandomState(seed)
    walk = 100 + np.cumsum(rng.normal(0, 1, n))
    cl = walk + rng.normal(0, 0.4, n) + 10     # log(cl/cs) 정상(평균회귀)
    cs = walk
    return _df(cl), _df(cs)


def _uncorrelated(n=250, seed=7):
    rng = np.random.RandomState(seed)
    a = 100 + np.cumsum(rng.normal(0, 1, n))
    b = 100 + np.cumsum(rng.normal(0, 1, n + 1)[1:])   # 독립 랜덤워크
    return _df(a), _df(b)


def test_stats_cointegrated_pair():
    dl, ds = _cointegrated()
    s = compute_pair_stats(dl, ds, lookback=60)
    assert s["corr"] is not None and s["corr"] > 0.3       # 공통 트렌드 → 상관 높음
    assert s["coint_p"] is not None and s["coint_p"] < 0.3  # 코인테그 강함
    assert s["adf_p"] is not None                            # 스프레드 ADF 산출
    assert s["zscore"] is not None and s["beta"] is not None


def test_stats_uncorrelated_weaker():
    dl, ds = _cointegrated()
    ul, us = _uncorrelated()
    sc = compute_pair_stats(dl, ds)
    su = compute_pair_stats(ul, us)
    # 무상관 페어의 코인테그 p-value가 코인테그 페어보다 크다(약함)
    assert su["coint_p"] is None or sc["coint_p"] is None or su["coint_p"] > sc["coint_p"]


def test_stats_missing_graceful():
    s = compute_pair_stats(None, None)
    assert all(s[k] is None for k in ("corr", "coint_p", "adf_p", "half_life", "zscore", "beta"))
    # 데이터 너무 짧음
    s2 = compute_pair_stats(_df([1, 2, 3]), _df([2, 3, 4]))
    assert s2["coint_p"] is None and s2["adf_p"] is None


def test_rank_score_axes():
    good = {"corr": 0.9, "coint_p": 0.01, "adf_p": 0.02, "half_life": 5, "zscore": 2.5, "beta": 1.0}
    bad = {"corr": 0.1, "coint_p": 0.9, "adf_p": 0.8, "half_life": 55, "zscore": 0.2, "beta": 1.0}
    sg = rank_pair_score(good, eps_spread=120)
    sb = rank_pair_score(bad, eps_spread=-120)
    assert 0 <= sb < sg <= 100
    # None 축 가중제외: 통계만 있어도 점수 산출
    only_stat = rank_pair_score({"corr": 0.8, "coint_p": None, "adf_p": None,
                                 "half_life": None, "zscore": None, "beta": None}, eps_spread=None)
    assert only_stat is not None
    # 전부 None → None
    assert rank_pair_score({"corr": None, "coint_p": None, "adf_p": None,
                            "half_life": None, "zscore": None, "beta": None}, None) is None
