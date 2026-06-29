"""롱숏 페어 '레그별 기술적 확인(발산) 패널' — 순수 함수.

좋은 페어는 두 레그의 기술적 그림이 내 방향으로 **발산**해야 한다:
롱 레그는 강하고(정배열·MACD골든·이격 양호·거래대금 유입), 숏 레그는 약해야(역배열·MACD데드·무거래 반등).
둘 다 같은 방향(둘 다 강/약)이면 발산 점수 0 근처 → 페어 약함.
※ 차트/렌더 코드 없음 — 화면은 반환 dict만 소비.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# 레그 강도 가중(합 100): 배열 30 · MACD 30 · 이격 15 · RSI 15 · 거래대금 10
_W = {"stack": 30, "macd": 30, "disp": 15, "rsi": 15, "vol": 10}


def _clip1(x):
    return max(-1.0, min(1.0, float(x)))


def _clean(df):
    if df is None or len(df) == 0 or "date" not in df.columns or "close" not in df.columns:
        return None
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    if "value" in d.columns:
        d["value"] = pd.to_numeric(d["value"], errors="coerce")
    d = d.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    return d if len(d) else None


def _ma_stack(close):
    if len(close) < 20:
        return None
    m20 = close.rolling(20).mean().iloc[-1]
    m60 = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else np.nan
    m120 = close.rolling(120).mean().iloc[-1] if len(close) >= 120 else np.nan
    if any(v != v for v in (m20, m60, m120)):   # 120일 미만 등 → 정/역배열 단정 불가
        return "혼조"
    if m20 > m60 > m120:
        return "정배열"
    if m20 < m60 < m120:
        return "역배열"
    return "혼조"


def _macd(close):
    if len(close) < 35:
        return None
    e12 = close.ewm(span=12, adjust=False).mean()
    e26 = close.ewm(span=26, adjust=False).mean()
    macd_line = e12 - e26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    ml, sg = float(macd_line.iloc[-1]), float(signal.iloc[-1])
    cross = "골든" if ml >= sg else "데드"
    zero = "0선위" if ml >= 0 else "0선아래"
    sign = 0.6 * (1 if ml >= sg else -1) + 0.4 * (1 if ml >= 0 else -1)
    return {"state": f"{cross}·{zero}", "sign": sign}


def _rsi(close, n=14):
    if len(close) < n + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = (100 - 100 / (1 + rs)).fillna(100.0)   # 손실 0 → 100
    v = rsi.iloc[-1]
    return float(v) if v == v else None


def _vol_trend(d):
    if "value" not in d.columns or d["value"].notna().sum() < 20:
        return None
    val = d["value"]
    v5, v20 = val.tail(5).mean(), val.tail(20).mean()
    if v20 in (0, None) or v20 != v20:
        return None
    return float(v5 / v20)


def _leg(d):
    """레그 1개 → (표시용 dict, 강도 -100~+100 또는 None)."""
    close = d["close"]
    last = float(close.iloc[-1])
    m20 = close.rolling(20).mean().iloc[-1] if len(close) >= 20 else np.nan
    m60 = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else np.nan
    disp20 = round(last / m20 * 100, 1) if (m20 == m20 and m20) else None
    disp60 = round(last / m60 * 100, 1) if (m60 == m60 and m60) else None
    stack = _ma_stack(close)
    macd = _macd(close)
    rsi = _rsi(close)
    vt = _vol_trend(d)

    info = {
        "disparity20": disp20, "disparity60": disp60,
        "ma_stack": stack or "—",
        "macd_state": macd["state"] if macd else "—",
        "rsi14": round(rsi, 1) if rsi is not None else None,
        "vol_trend": round(vt, 2) if vt is not None else None,
    }

    comps = []   # (정규화값 -1~1, 가중)
    if stack is not None:
        comps.append(({"정배열": 1.0, "역배열": -1.0}.get(stack, 0.0), _W["stack"]))
    if macd is not None:
        comps.append((_clip1(macd["sign"]), _W["macd"]))
    if disp20 is not None:
        comps.append((_clip1((disp20 - 100) / 8.0), _W["disp"]))          # MA 대비 +8% → +1
    if rsi is not None:
        comps.append((_clip1((rsi - 50) / 25.0), _W["rsi"]))
    if vt is not None:
        comps.append((_clip1((vt - 1.0) / 0.5), _W["vol"]))               # 거래대금 +50% → +1
    if not comps:
        return info, None
    strength = sum(v * w for v, w in comps) / sum(w for _, w in comps) * 100.0
    return info, round(max(-100.0, min(100.0, strength)), 1)


def leg_technical_panel(df_long, df_short) -> dict:
    """롱/숏 일봉 → 레그별 기술 패널 + 발산 점수 dict.

    출력: {"long":{...}, "short":{...}, "divergence_score": float|None, "flag": str}
    divergence_score = (long_strength + short_weakness)/2,  short_weakness = -short_strength.
    결측 가드 포함. 차트 코드 없음.
    """
    L, S = _clean(df_long), _clean(df_short)
    long_info = {"disparity20": None, "disparity60": None, "ma_stack": "—",
                 "macd_state": "—", "rsi14": None, "vol_trend": None}
    short_info = dict(long_info)
    long_str = short_str = None
    if L is not None:
        long_info, long_str = _leg(L)
    if S is not None:
        short_info, short_str = _leg(S)

    if long_str is None or short_str is None:
        return {"long": long_info, "short": short_info,
                "divergence_score": None, "flag": "보통"}

    short_weakness = -short_str
    divergence = round((long_str + short_weakness) / 2.0, 1)
    same_dir = (long_str >= 0) == (short_str >= 0)   # 둘 다 강 or 둘 다 약

    if same_dir:
        flag = "페어 약함(같은 방향)"
    elif divergence >= 40:
        flag = "이상적 발산"
    else:
        flag = "보통"

    return {"long": long_info, "short": short_info,
            "divergence_score": divergence, "flag": flag}
