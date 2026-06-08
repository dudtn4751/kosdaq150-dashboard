"""주요 ETF 추이 — 가격 모멘텀 / SPY 상대강도 / 거래대금 활동.
모닝 마켓 체크용 경량 버전 (AUM·로테이션맵 제외, 가격은 1회 배치 다운로드 + 캐시).
원본: 사용자 제공 '주요 ETF Tracker'.
"""

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

ETF_MAP = {
    "XME": "Metals & Mining", "GDX": "Gold Miners",
    "AMLP": "MLP / Energy Infrastructure", "ITB": "Homebuilders", "OIH": "Oil Services",
    "KRE": "Regional Banks", "XRT": "Retail", "MOO": "Agribusiness", "FDN": "Internet",
    "IBB": "Biotechnology", "SMH": "Semiconductors", "XOP": "Oil & Gas E&P",
    "PBW": "Clean Energy", "KIE": "Insurance", "PHO": "Water", "IGV": "Software",
    "TAN": "Solar", "JETS": "Airlines", "SHLD": "Defense Tech", "DRAM": "Memory / HBM",
    "EWY": "MSCI South Korea", "NLR": "Uranium & Nuclear", "KORU": "South Korea 3x Bull",
    "SOXX": "Semiconductors",
}
ETF_GROUP = {
    "XME": "Materials / Commodities", "GDX": "Gold / Miners",
    "AMLP": "Energy", "ITB": "Housing", "OIH": "Energy", "KRE": "Financials",
    "XRT": "Consumer", "MOO": "Agriculture", "FDN": "Internet", "IBB": "Biotech",
    "SMH": "Semiconductor / AI", "XOP": "Energy", "PBW": "Clean Energy", "KIE": "Financials",
    "PHO": "Infrastructure", "IGV": "Software", "TAN": "Solar", "JETS": "Transport / Travel",
    "SHLD": "Defense / Aerospace", "DRAM": "Semiconductor / AI", "EWY": "Korea Direct",
    "NLR": "Nuclear / Power", "KORU": "Korea Direct", "SOXX": "Semiconductor / AI",
}
ETF_LIST = list(ETF_MAP)
BASE = "SPY"


def _pct(series, periods):
    s = series.dropna()
    if len(s) <= periods:
        return float("nan")
    return (s.iloc[-1] / s.iloc[-periods - 1] - 1) * 100


def _signal(rel20, r20, vol):
    if pd.isna(rel20) or pd.isna(r20):
        return "중립"
    v = vol if not pd.isna(vol) else 0
    if rel20 > 5 and r20 > 0 and v > 20:
        return "강세+거래급증"
    if rel20 > 2 and r20 > 0:
        return "상대강세"
    if rel20 < -5 and r20 < 0 and v > 20:
        return "약세+거래급증"
    if rel20 < -2:
        return "상대약세"
    return "중립"


# 섹터 1일 수익률 버킷 (색상)
def return_bucket(v):
    if v is None or v != v:
        return ("데이터 없음", "#9AA3AF")
    if v < -20:
        return ("-20% 미만", "#B91C1C")
    if v < -10:
        return ("-10~-20%", "#E06666")
    if v < -5:
        return ("-5~-10%", "#E0A93B")
    if v < 0:
        return ("-5~0%", "#C9CDD3")
    if v < 5:
        return ("0~+5%", "#5BB85C")
    return ("+5% 이상", "#15803D")


BUCKET_LEGEND = [("-20% 미만", "#B91C1C"), ("-10~-20%", "#E06666"), ("-5~-10%", "#E0A93B"),
                 ("-5~0%", "#C9CDD3"), ("0~+5%", "#5BB85C"), ("+5% 이상", "#15803D")]


def sector_summary(rows):
    """ETF rows → 섹터(group)별 평균 1D 수익률 + 최저 종목 + 버킷색."""
    by = {}
    for r in rows:
        by.setdefault(r["group"], []).append(r)
    out = []
    for g, items in by.items():
        vals = [x["d1"] for x in items if x["d1"] == x["d1"]]
        avg = sum(vals) / len(vals) if vals else float("nan")
        worst = min((x for x in items if x["d1"] == x["d1"]), key=lambda x: x["d1"], default=None)
        label, color = return_bucket(avg)
        members = sorted(items, key=lambda x: (x["d1"] if x["d1"] == x["d1"] else -1e18), reverse=True)
        out.append({"group": g, "avg": avg, "count": len(items), "label": label, "color": color,
                    "worst_etf": worst["etf"] if worst else "-",
                    "worst": worst["d1"] if worst else float("nan"),
                    "members": [{"etf": m["etf"], "d1": m["d1"]} for m in members]})
    return out


@st.cache_data(ttl=600, show_spinner=False)
def load_etf_table(period="6mo"):
    """ETF별 1D/5D/20D/60D 수익률 + SPY 상대강도 + 거래대금 변화 + 신호. list[dict] 반환."""
    try:
        data = yf.download(ETF_LIST + [BASE], period=period, interval="1d",
                           auto_adjust=False, group_by="ticker", threads=True, progress=False)
    except Exception:
        return []
    if data is None or data.empty:
        return []

    def frame(t):
        try:
            if isinstance(data.columns, pd.MultiIndex):
                if t not in data.columns.get_level_values(0):
                    return pd.DataFrame()
                return data[t].dropna(how="all")
            return data.dropna(how="all")
        except Exception:
            return pd.DataFrame()

    spy = frame(BASE)
    spy_nav = spy.get("Adj Close", spy.get("Close", pd.Series(dtype=float)))
    spy20 = _pct(spy_nav, 20)

    rows = []
    for t in ETF_LIST:
        f = frame(t)
        if f.empty:
            continue
        close = f.get("Close", pd.Series(dtype=float))
        nav = f.get("Adj Close", close)
        vol = f.get("Volume", pd.Series(dtype=float))
        tv = (close * vol).dropna()
        tv5 = tv.tail(5).mean() if len(tv) >= 5 else float("nan")
        tvprev = tv.iloc[-25:-5].mean() if len(tv) >= 25 else float("nan")
        tvchg = (tv5 / tvprev - 1) * 100 if tvprev and not pd.isna(tvprev) else float("nan")
        r20 = _pct(nav, 20)
        rel = r20 - spy20 if (not pd.isna(r20) and not pd.isna(spy20)) else float("nan")
        rows.append({
            "etf": t, "group": ETF_GROUP[t], "industry": ETF_MAP[t],
            "d1": _pct(nav, 1), "d5": _pct(nav, 5), "d20": r20, "d60": _pct(nav, 60),
            "rel20": rel, "tvchg": tvchg, "signal": _signal(rel, r20, tvchg),
        })
    return rows
