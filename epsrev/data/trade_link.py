"""epsrev/data/trade_link.py — 수출입 대시보드(외부 리포) 연계 로더.

소스: wowwowwow-sudo/trade-data-dashboard 의 data/interlink/ (raw GitHub).
표시 전용. 404/네트워크 실패 시 예외 삼키고 None → 앱이 죽지 않게.
조인 키는 전부 종목코드(6자리 str). 종목명 조인 금지.

설정(st.secrets 우선, 없으면 상수):
  INTERLINK_BASE_URL: interlink 폴더 raw URL
  TRADE_DASHBOARD_URL: 수출입 대시보드 배포 URL(미배포면 "" → 딥링크 버튼 숨김)
"""
from __future__ import annotations

import pandas as pd

_DEFAULT_BASE = ("https://raw.githubusercontent.com/wowwowwow-sudo/"
                 "trade-data-dashboard/main/data/interlink")


def _secret(key, default):
    try:
        import streamlit as st
        v = st.secrets.get(key)
        return v if v else default
    except Exception:
        return default


def base_url() -> str:
    return str(_secret("INTERLINK_BASE_URL", _DEFAULT_BASE)).rstrip("/")


def trade_dashboard_url() -> str:
    return str(_secret("TRADE_DASHBOARD_URL", "")).rstrip("/")


try:
    import streamlit as st
    def _cache(ttl=3600):
        def deco(f):
            return st.cache_data(ttl=ttl, show_spinner=False)(f)
        return deco
except Exception:
    def _cache(ttl=3600):
        def deco(f):
            return f
        return deco


@_cache()
def load_stock_trade_map():
    try:
        return pd.read_csv(f"{base_url()}/stock_trade_map.csv",
                           dtype={"hs코드": str, "종목코드": str}, encoding="utf-8-sig")
    except Exception:
        return None


@_cache()
def load_trade_monthly():
    try:
        df = pd.read_csv(f"{base_url()}/trade_monthly.csv",
                         dtype={"hs코드": str}, encoding="utf-8-sig")
        return df
    except Exception:
        return None


@_cache()
def load_company_exports():
    try:
        return pd.read_csv(f"{base_url()}/company_exports.csv",
                           dtype={"hs코드": str, "종목코드": str}, encoding="utf-8-sig")
    except Exception:
        return None


@_cache()
def load_meta():
    try:
        import json
        import requests
        r = requests.get(f"{base_url()}/meta.json", timeout=10)
        r.raise_for_status()
        return json.loads(r.content.decode("utf-8-sig"))   # BOM 처리
    except Exception:
        return None


def _pad(code) -> str:
    s = str(code).strip()
    return s.zfill(6) if s and s.isdigit() else s


def _item_yoy(monthly, hs):
    """hs코드 시계열 → {yoy_latest, yoy_3m, yoy_12m}. 없으면 None들."""
    out = {"yoy_latest": None, "yoy_3m": None, "yoy_12m": None}
    if monthly is None or monthly.empty:
        return out
    sub = monthly[monthly["hs코드"].astype(str) == str(hs)].sort_values("연월")
    y = pd.to_numeric(sub["수출yoy"], errors="coerce").dropna()
    if len(y):
        out["yoy_latest"] = round(float(y.iloc[-1]), 1)
        out["yoy_3m"] = round(float(y.tail(3).mean()), 1)
        out["yoy_12m"] = round(float(y.tail(12).mean()), 1)
    return out


def get_stock_trade_data(stock_code: str) -> dict:
    """{items, monthly, company, meta}. 매핑 없으면 items 빈 DF."""
    code = _pad(stock_code)
    smap, monthly = load_stock_trade_map(), load_trade_monthly()
    meta = load_meta()
    if smap is None:
        return {"items": None, "monthly": None, "company": None, "meta": meta}
    items = smap[smap["종목코드"].map(_pad) == code].copy()
    hs_list = list(items["hs코드"].astype(str).unique())
    mon = monthly[monthly["hs코드"].astype(str).isin(hs_list)].copy() if monthly is not None else None
    comp = load_company_exports()
    company = None
    if comp is not None and "종목코드" in comp.columns:
        c = comp[comp["종목코드"].map(_pad) == code].copy()
        company = c if not c.empty else None
    return {"items": items, "monthly": mon, "company": company, "meta": meta}


def get_related_stocks_by_trade(stock_code: str):
    """이 종목 hs코드에 함께 매핑된 다른 종목. DF(종목명·종목코드·공유 품목명·hs코드·관계유형·최신월 수출yoy)."""
    code = _pad(stock_code)
    smap, monthly = load_stock_trade_map(), load_trade_monthly()
    if smap is None:
        return None
    my_hs = set(smap[smap["종목코드"].map(_pad) == code]["hs코드"].astype(str))
    if not my_hs:
        return pd.DataFrame()
    others = smap[smap["hs코드"].astype(str).isin(my_hs) & (smap["종목코드"].map(_pad) != code)].copy()
    if others.empty:
        return others
    others["종목코드"] = others["종목코드"].map(_pad)
    others["최신월 수출yoy"] = others["hs코드"].map(lambda h: _item_yoy(monthly, h)["yoy_latest"])
    out = others.rename(columns={"품목명": "공유 품목명"})[
        ["종목명", "종목코드", "공유 품목명", "hs코드", "관계유형", "최신월 수출yoy"]]
    return out.drop_duplicates().reset_index(drop=True)


def _leg(code, smap, monthly):
    from epsrev.data.dashboard_data import CO
    c = CO.get(_pad(code))
    name = c["n"] if c else _pad(code)
    items = []
    if smap is not None:
        rows = smap[smap["종목코드"].map(_pad) == _pad(code)]
        for _, r in rows.iterrows():
            yy = _item_yoy(monthly, r["hs코드"])
            items.append({"품목명": r["품목명"], "hs코드": str(r["hs코드"]),
                          "관계유형": r.get("관계유형", ""), **yy})
    return {"name": name, "items": items}


def pair_trade_panel(long_code: str, short_code: str):
    """페어 파인더용 순수 함수. dict 또는 None(데이터 없음/실패)."""
    smap, monthly = load_stock_trade_map(), load_trade_monthly()
    if smap is None:
        return None
    lc, sc = _pad(long_code), _pad(short_code)
    long_leg, short_leg = _leg(lc, smap, monthly), _leg(sc, smap, monthly)
    if not long_leg["items"] and not short_leg["items"]:
        return None

    l_hs = {it["hs코드"] for it in long_leg["items"]}
    s_hs = {it["hs코드"] for it in short_leg["items"]}
    shared_hs = l_hs & s_hs
    shared = [{"hs코드": h, "품목명": next(it["품목명"] for it in long_leg["items"] if it["hs코드"] == h)}
              for h in shared_hs]

    # 월별 수출yoy(최근 24개월) 롱포맷 — 레그 구분
    rows = []
    if monthly is not None:
        for leg_name, leg, hset in (("long", long_leg, l_hs), ("short", short_leg, s_hs)):
            sub = monthly[monthly["hs코드"].astype(str).isin(hset)].copy()
            for _, r in sub.iterrows():
                rows.append({"leg": leg_name, "품목명": r["품목명"], "연월": r["연월"],
                             "수출yoy": pd.to_numeric(r["수출yoy"], errors="coerce")})
    mdf = pd.DataFrame(rows)
    if not mdf.empty:
        recent = sorted(mdf["연월"].unique())[-24:]
        mdf = mdf[mdf["연월"].isin(recent)]

    meta = load_meta() or {}
    return {
        "long": long_leg, "short": short_leg,
        "shared_items": shared,
        "related_stocks": {"long": get_related_stocks_by_trade(lc),
                           "short": get_related_stocks_by_trade(sc)},
        "monthly": mdf,
        "meta": {"data_through": meta.get("data_through")},
    }
