"""롱숏 페어 '비율선 패널' 계산 — 순수 함수.

방향(롱/숏 레그)은 알파 스코어가 이미 확정. 이 패널은 **진입 타이밍 + 헤지 건전성**만 본다.
입력 일봉으로 비율(log)·이동평균·z-score·롤링상관/베타·추세기울기·반감기를 계산해 dict 반환.
※ 차트/렌더 코드 없음 — 화면은 이 dict만 소비.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_SERIES_KEYS = ("date", "log_ratio", "ma20", "ma60", "zscore", "roll_corr")


def _empty():
    return {
        "series": {k: [] for k in _SERIES_KEYS},
        "current": {"zscore": None, "roll_corr": None, "slope60": None,
                    "half_life": None, "roll_beta": None},
        "flags": {"corr_ok": False, "z_state": "중립", "trend_state": "중립"},
    }


def _clean(df):
    """date·close만 정제: datetime·숫자화·결측제거·정렬. 실패 시 None."""
    if df is None or len(df) == 0 or "date" not in df.columns or "close" not in df.columns:
        return None
    d = df[["date", "close"]].copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    d = d.dropna(subset=["date", "close"]).sort_values("date")
    return d if len(d) else None


def _slope(y):
    """시계열 y(시간 0..n-1)에 대한 OLS 기울기. 유효점 2개 미만/분모0이면 None."""
    y = np.asarray([v for v in y if v == v], dtype=float)
    if len(y) < 2:
        return None
    x = np.arange(len(y), dtype=float)
    xm = x - x.mean()
    denom = float((xm ** 2).sum())
    if denom == 0:
        return None
    return float((xm * (y - y.mean())).sum() / denom)


def _half_life(log_ratio):
    """log_ratio 평균회귀 반감기(OU/AR(1)). Δy = a + b·y_lag, half_life = -ln2/b (b<0)."""
    y = log_ratio.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)
    if len(y) < 20:
        return None
    d = pd.concat([(y - y.shift(1)), y.shift(1)], axis=1).dropna()
    if len(d) < 10:
        return None
    Y = d.iloc[:, 0].to_numpy(dtype=float)   # Δy
    X = d.iloc[:, 1].to_numpy(dtype=float)    # y_lag
    xm = X - X.mean()
    denom = float((xm ** 2).sum())
    if denom == 0:
        return None
    b = float((xm * (Y - Y.mean())).sum() / denom)
    if b >= 0:                                # 평균회귀 아님 → 반감기 정의 안 됨
        return None
    hl = -np.log(2) / b
    return float(hl) if (np.isfinite(hl) and hl > 0) else None


def _last_finite(s):
    s2 = s.replace([np.inf, -np.inf], np.nan).dropna()
    return float(s2.iloc[-1]) if len(s2) else None


def _ser(s):
    """Series → JSON 안전 리스트(NaN/inf→None, 6자리 반올림)."""
    out = []
    for v in s:
        if v is None or (isinstance(v, float) and (v != v or v in (np.inf, -np.inf))):
            out.append(None)
        else:
            out.append(round(float(v), 6))
    return out


def pair_ratio_panel(df_long, df_short, lookback: int = 60) -> dict:
    """롱/숏 일봉 → 비율선 패널 dict.

    입력: df_long, df_short = (date, close, value) 일봉. lookback = z/상관 윈도우(기본 60).
    출력: {"series":{...}, "current":{...}, "flags":{...}}  (차트 코드 없음)
    결측·분모0·짧은 데이터 가드 포함.
    """
    L, S = _clean(df_long), _clean(df_short)
    if L is None or S is None:
        return _empty()
    m = pd.merge(L.rename(columns={"close": "cl"}), S.rename(columns={"close": "cs"}),
                 on="date", how="inner").sort_values("date")
    m = m[(m["cl"] > 0) & (m["cs"] > 0)].dropna(subset=["cl", "cs"]).reset_index(drop=True)
    if len(m) == 0:
        return _empty()

    cl, cs = m["cl"], m["cs"]
    dates = m["date"].dt.strftime("%Y-%m-%d").tolist()

    log_ratio = np.log(cl / cs)
    ma20 = log_ratio.rolling(20).mean()
    ma60 = log_ratio.rolling(60).mean()

    roll_std = log_ratio.rolling(lookback).std().replace(0, np.nan)
    zscore = ((log_ratio - log_ratio.rolling(lookback).mean()) / roll_std).replace([np.inf, -np.inf], np.nan)

    ret_l, ret_s = cl.pct_change(), cs.pct_change()
    roll_corr = ret_l.rolling(lookback).corr(ret_s).replace([np.inf, -np.inf], np.nan)
    var_s = ret_s.rolling(lookback).var().replace(0, np.nan)
    roll_beta = (ret_l.rolling(lookback).cov(ret_s) / var_s).replace([np.inf, -np.inf], np.nan)

    slope60 = _slope(log_ratio.replace([np.inf, -np.inf], np.nan).dropna().tail(60).to_numpy())
    half_life = _half_life(log_ratio)

    cur_z = _last_finite(zscore)
    cur_corr = _last_finite(roll_corr)
    cur_beta = _last_finite(roll_beta)

    corr_ok = cur_corr is not None and cur_corr >= 0.5
    if cur_z is None:
        z_state = "중립"
    elif cur_z >= 2:
        z_state = "롱레그 과열·추격주의"
    elif cur_z <= -2:
        z_state = "스프레드 과도 역행·역진입 기회"
    else:
        z_state = "중립"
    if slope60 is None or slope60 == 0:
        trend_state = "중립"
    elif slope60 > 0:
        trend_state = "롱 우위 추세"
    else:
        trend_state = "숏 우위 추세"

    return {
        "series": {"date": dates, "log_ratio": _ser(log_ratio), "ma20": _ser(ma20),
                   "ma60": _ser(ma60), "zscore": _ser(zscore), "roll_corr": _ser(roll_corr)},
        "current": {
            "zscore": None if cur_z is None else round(cur_z, 4),
            "roll_corr": None if cur_corr is None else round(cur_corr, 4),
            "slope60": None if slope60 is None else round(slope60, 8),
            "half_life": None if half_life is None else round(half_life, 2),
            "roll_beta": None if cur_beta is None else round(cur_beta, 4),
        },
        "flags": {"corr_ok": bool(corr_ok), "z_state": z_state, "trend_state": trend_state},
    }
