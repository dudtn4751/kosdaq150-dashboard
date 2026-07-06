"""롱숏 페어 실측 통계 + 복합 점수 — 순수 함수(가격 df만 입력).

compute_pair_stats: corr·coint_p·adf_p·half_life·zscore·beta
rank_pair_score: 펀더멘털(EPS 스프레드) + 통계(상관·코인테그·정상성·반감기) + 타이밍(|z|) 가중합
결측/실패는 None graceful.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from epsrev.pair_panel import _clean, pair_ratio_panel


def _round(v, n=4):
    if v is None:
        return None
    try:
        f = float(v)
        return None if f != f else round(f, n)
    except (TypeError, ValueError):
        return None


def _merged(df_long, df_short):
    L, S = _clean(df_long), _clean(df_short)
    if L is None or S is None:
        return None
    m = pd.merge(L.rename(columns={"close": "cl"}), S.rename(columns={"close": "cs"}),
                 on="date", how="inner").sort_values("date")
    m = m[(m["cl"] > 0) & (m["cs"] > 0)].dropna(subset=["cl", "cs"]).reset_index(drop=True)
    return m if len(m) else None


def compute_pair_stats(df_long, df_short, lookback: int = 60) -> dict:
    """롱/숏 일봉 → 실측 통계 dict. 실패/결측은 None."""
    out = {"corr": None, "coint_p": None, "adf_p": None,
           "half_life": None, "zscore": None, "beta": None}

    # corr / zscore / half_life / beta 는 검증된 pair_ratio_panel 재사용
    try:
        panel = pair_ratio_panel(df_long, df_short, lookback=lookback)
        cur = panel["current"]
        out["corr"] = cur["roll_corr"]
        out["zscore"] = cur["zscore"]
        out["half_life"] = cur["half_life"]
        out["beta"] = cur["roll_beta"]
    except Exception:
        pass

    m = _merged(df_long, df_short)
    if m is None or len(m) < 30:
        return out
    log_cl, log_cs = np.log(m["cl"].to_numpy()), np.log(m["cs"].to_numpy())

    # Engle-Granger 코인테그레이션 p-value (log 가격)
    try:
        from statsmodels.tsa.stattools import coint
        _, pval, _ = coint(log_cl, log_cs)
        out["coint_p"] = _round(pval)
    except Exception:
        pass

    # 스프레드(log_ratio) 정상성 ADF p-value
    try:
        from statsmodels.tsa.stattools import adfuller
        lr = pd.Series(log_cl - log_cs).replace([np.inf, -np.inf], np.nan).dropna()
        if len(lr) >= 20:
            out["adf_p"] = _round(adfuller(lr.to_numpy(), autolag="AIC")[1])
    except Exception:
        pass

    return out


def _clip01(x):
    return max(0.0, min(1.0, float(x)))


def rank_pair_score(stats: dict, eps_spread) -> float | None:
    """복합 페어 점수(0~100). 축: 펀더멘털0.35·통계0.40·타이밍0.25. None 축은 가중제외 재정규화."""
    axes = {}

    # 펀더멘털: EPS 스코어 스프레드(long_eps - short_eps), 범위 -200~+200 → 0~1
    if eps_spread is not None and eps_spread == eps_spread:
        axes["fund"] = _clip01((float(eps_spread) + 200.0) / 400.0)

    # 통계: 상관 높을수록·coint_p/adf_p 낮을수록·반감기 짧을수록 (서브지표 평균)
    sub = []
    if stats.get("corr") is not None:
        sub.append(_clip01(stats["corr"]))
    if stats.get("coint_p") is not None:
        sub.append(_clip01(1.0 - stats["coint_p"]))
    if stats.get("adf_p") is not None:
        sub.append(_clip01(1.0 - stats["adf_p"]))
    if stats.get("half_life") is not None:
        sub.append(_clip01(1.0 - min(float(stats["half_life"]), 60.0) / 60.0))
    if sub:
        axes["stat"] = sum(sub) / len(sub)

    # 타이밍: |zscore| 클수록(스프레드 벌어짐), 3에서 상한
    if stats.get("zscore") is not None:
        axes["time"] = _clip01(abs(float(stats["zscore"])) / 3.0)

    weights = {"fund": 0.35, "stat": 0.40, "time": 0.25}
    den = sum(weights[k] for k in axes)
    if den == 0:
        return None
    num = sum(axes[k] * weights[k] for k in axes)
    return round(num / den * 100.0, 1)
