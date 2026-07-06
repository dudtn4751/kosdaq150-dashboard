"""롱숏 스프레드 백테스트 — 순수 함수(가격 df만 입력).

backtest_spread: ±entry σ 진입 → |z|<=exit 청산 룰의 회귀 승률·평균 보유기간·스프레드 MDD·트레이드 수.
rebase100: 종가를 시작점 100으로 정규화(리베이스 오버레이 차트용, 순수 계산).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from epsrev.pair_stats import _merged


def _empty_bt():
    return {"trades": 0, "win_rate": None, "avg_hold": None, "mdd": None, "avg_pnl": None}


def backtest_spread(df_long, df_short, entry: float = 2.0, exit: float = 0.5,
                    lookback: int = 60) -> dict:
    """스프레드(log_ratio) z 룰 백테스트.
    z>=entry면 스프레드 숏, z<=-entry면 롱, |z|<=exit면 청산. 회귀 승률·평균 보유·MDD·트레이드 수."""
    m = _merged(df_long, df_short)
    if m is None or len(m) < lookback + 5:
        return _empty_bt()

    spread = np.log(m["cl"].to_numpy() / m["cs"].to_numpy())
    s = pd.Series(spread)
    mu = s.rolling(lookback).mean()
    sd = s.rolling(lookback).std().replace(0, np.nan)
    z = ((s - mu) / sd).to_numpy()

    pos = 0            # +1 스프레드 롱, -1 숏, 0 무포지션
    entry_i = None
    entry_spread = None
    trades = []
    eq = 0.0
    equity = [0.0]
    for i in range(len(spread)):
        # 일별 시가평가(보유 중일 때 전일 대비 스프레드 변화)
        if pos != 0 and i > 0:
            eq += pos * (spread[i] - spread[i - 1])
        equity.append(eq)

        zi = z[i]
        if zi != zi:               # NaN(롤링 워밍업)
            continue
        if pos == 0:
            if abs(zi) >= entry:
                pos = -1 if zi > 0 else 1     # 스프레드 벌어진 반대로 진입(회귀 베팅)
                entry_i, entry_spread = i, spread[i]
        else:
            if abs(zi) <= exit:
                pnl = pos * (spread[i] - entry_spread)
                trades.append({"hold": i - entry_i, "pnl": pnl})
                pos, entry_i, entry_spread = 0, None, None

    n = len(trades)
    if n == 0:
        return _empty_bt()
    wins = sum(1 for t in trades if t["pnl"] > 0)
    eq_arr = np.array(equity, dtype=float)
    dd = eq_arr - np.maximum.accumulate(eq_arr)
    return {
        "trades": n,
        "win_rate": round(wins / n * 100.0, 1),
        "avg_hold": round(sum(t["hold"] for t in trades) / n, 1),   # 평균 회귀(보유) 기간(거래일)
        "mdd": round(float(dd.min()), 4),                            # 스프레드 전략 MDD(log 단위)
        "avg_pnl": round(sum(t["pnl"] for t in trades) / n, 4),      # 평균 트레이드 손익(log 스프레드)
    }


def rebase100(df):
    """종가를 시작점 100으로 정규화 → [(date, val)]. 리베이스 오버레이용. 실패 시 []."""
    from epsrev.pair_panel import _clean
    d = _clean(df)
    if d is None:
        return []
    base = d["close"].iloc[0]
    if base == 0:
        return []
    return [{"date": r["date"].strftime("%Y-%m-%d"), "val": round(float(r["close"]) / base * 100.0, 2)}
            for _, r in d.iterrows()]
