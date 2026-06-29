"""
data/scorer.py
==============
compute_eps_revision_score() 래퍼 — 18종목 배치 처리 후 DataFrame으로 가공.
Streamlit 환경에서는 @st.cache_data(ttl=3600) 캐싱 적용.
standalone 실행(python data/scorer.py) 시에는 캐시 없이 동작.
"""
import sys, os, logging
# Streamlit standalone 실행 시 불필요한 runtime 경고 억제
logging.getLogger("streamlit").setLevel(logging.ERROR)

import pandas as pd
from collections import defaultdict

# Streamlit 캐시 데코레이터 — standalone 실행 시 no-op fallback
try:
    import streamlit as st
    def _cache(func):
        return st.cache_data(ttl=3600)(func)
except Exception:
    def _cache(func):
        return func

from epsrev.eps_revision_score import compute_eps_revision_score
from epsrev.data.dummy import DUMMY_STOCKS

# ticker → 종목명 매핑 (전체 유니버스)
NAME_MAP: dict[str, str] = {s.ticker: name for s, name, _ in DUMMY_STOCKS}


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _run_batch() -> list[dict]:
    """섹터별 배치 처리. 각 종목의 sector_dist = 동일 섹터 나머지 종목."""
    sector_groups: dict[str, list] = defaultdict(list)
    for stock_input, name, sector in DUMMY_STOCKS:
        sector_groups[sector].append((stock_input, name))

    rows = []
    for sector, items in sector_groups.items():
        for i, (s, name) in enumerate(items):
            sector_dist = [x for j, (x, _) in enumerate(items) if j != i]
            res = compute_eps_revision_score(s, sector_dist=sector_dist)
            rows.append({
                "ticker":     s.ticker,
                "name":       name,
                "sector":     sector,
                "eps_score":  res["eps_score"],
                "confidence": res["confidence"],
                "realized":   res["layers"].get("realized"),
                "momentum":   res["layers"].get("momentum"),
                "forward":    res["layers"].get("forward"),
                "insight":    res["insight"],
                "flags":      "; ".join(res["flags"]) if res["flags"] else "",
            })
    return rows


# ── 공개 API ─────────────────────────────────────────────────────────────────

@_cache
def score_all_stocks() -> pd.DataFrame:
    """
    18종목 배치 EPS 리비전 점수 계산.

    컬럼: ticker, name, sector, eps_score, confidence,
          realized, momentum, forward, insight, flags
    섹터 내 상대 백분위(-100~+100) 기준 정렬.
    """
    rows = _run_batch()
    df = pd.DataFrame(rows)
    return (
        df.sort_values(["sector", "eps_score"], ascending=[True, False])
        .reset_index(drop=True)
    )


@_cache
def get_sector_summary() -> pd.DataFrame:
    """
    섹터별 요약.

    컬럼: sector, avg_score, top_ticker, bottom_ticker
    avg_score = 섹터 내 eps_score 평균, 내림차순 정렬.
    """
    df = score_all_stocks()
    rows = []
    for sector, grp in df.groupby("sector", sort=False):
        rows.append({
            "sector":       sector,
            "avg_score":    round(float(grp["eps_score"].mean()), 1),
            "top_ticker":   grp.loc[grp["eps_score"].idxmax(), "ticker"],
            "bottom_ticker":grp.loc[grp["eps_score"].idxmin(), "ticker"],
        })
    return (
        pd.DataFrame(rows)
        .sort_values("avg_score", ascending=False)
        .reset_index(drop=True)
    )


@_cache
def get_stock_detail(ticker: str) -> dict:
    """
    단일 종목 전체 상세.
    반환: compute_eps_revision_score() 전체 dict + "name" 키 추가.
    """
    entry = next(
        ((s, name, sec) for s, name, sec in DUMMY_STOCKS if s.ticker == ticker),
        None,
    )
    if entry is None:
        raise ValueError(f"종목 없음: {ticker!r}")

    stock_input, name, sector = entry
    sector_dist = [
        s for s, _, sec in DUMMY_STOCKS
        if sec == sector and s.ticker != ticker
    ]
    res = compute_eps_revision_score(stock_input, sector_dist=sector_dist)
    return {"name": name, **res}


# ── standalone 실행 ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import warnings, logging
    logging.getLogger("streamlit").setLevel(logging.ERROR)
    warnings.filterwarnings("ignore")
    sys.stdout.reconfigure(encoding="utf-8")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 160)
    pd.set_option("display.float_format", "{:.2f}".format)

    print("=" * 80)
    print("score_all_stocks() — head(18)")
    print("=" * 80)
    df = score_all_stocks()
    print(df.head(18).to_string(index=True))

    print()
    print("=" * 80)
    print("get_sector_summary()")
    print("=" * 80)
    print(get_sector_summary().to_string(index=False))

    print()
    print("=" * 80)
    print("get_stock_detail('005930')")
    print("=" * 80)
    import pprint
    pprint.pprint(get_stock_detail("005930"))


# ── 일봉 어댑터 (pair_panel·pair_tech_panel 용) ──────────────────────────────
from datetime import datetime, timedelta

def get_price_df(ticker: str):
    """종목 코드 → 일봉 DataFrame(date, close, value). 없으면 None."""
    df = _load_daily(str(ticker).zfill(6))
    if df is None or df.empty:
        return None
    return df

def _load_daily(ticker: str):
    """yfinance로 최근 280일 일봉 로드 (KOSPI→.KS, KOSDAQ→.KQ 순 시도). 실패 시 None."""
    try:
        import yfinance as yf
        end   = datetime.today()
        start = end - timedelta(days=280)
        s, e  = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
        for suffix in [".KS", ".KQ"]:
            df = yf.download(ticker + suffix, start=s, end=e,
                             progress=False, auto_adjust=True)
            if df is not None and not df.empty:
                df = df.reset_index()
                # yfinance 0.2.x: MultiIndex 컬럼 평탄화
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                df = df.rename(columns={"Date": "date", "Close": "close", "Volume": "volume"})
                df["close"]  = pd.to_numeric(df["close"],  errors="coerce")
                df["volume"] = pd.to_numeric(df.get("volume"), errors="coerce")
                df["value"]  = df["close"] * df["volume"] / 1e8   # 거래대금(억)
                df["date"]   = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                out = df[["date", "close", "value"]].dropna(subset=["close"])
                if not out.empty:
                    return out
        return None
    except Exception:
        return None