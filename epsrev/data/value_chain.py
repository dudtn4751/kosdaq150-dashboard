"""epsrev/data/value_chain.py — 밸류체인 관련 기업 로더/조인.

data/value_chain/vc_nodes.csv(체인 포지션), vc_edges.csv(공급사→고객사) UTF-8-SIG.
유니버스(dashboard_data.CO)와 종목명으로 조인해 종목코드·섹터·시총·종합점수 부착.
CSV 갱신 시 파일 교체만 하면 됨(스키마 불변).
"""
from __future__ import annotations

import os
import re

import pandas as pd

try:
    import streamlit as st
    def _cache(f):
        return st.cache_data(ttl=86400, show_spinner=False)(f)
except Exception:
    def _cache(f):
        return f

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "value_chain")

# CSV표기 → 유니버스표기(구 사명 등). CSV가 대부분 유니버스 표기라 최소만.
NAME_ALIAS = {
    "에이피티씨": "브이엠",
    "STX중공업": "HD현대마린엔진",
    "HSD엔진": "한화엔진",
    "LS일렉트릭": "LS ELECTRIC",
    "포스코홀딩스": "POSCO홀딩스",
}


def normalize_name(s) -> str:
    if s is None or (isinstance(s, float) and s != s):
        return ""
    s = re.sub(r"\s+", " ", str(s)).strip()
    return NAME_ALIAS.get(s, s)


@_cache
def load_vc_nodes() -> pd.DataFrame:
    try:
        df = pd.read_csv(os.path.join(_DIR, "vc_nodes.csv"), encoding="utf-8-sig")
        df["기업명"] = df["기업명"].map(normalize_name)
        return df
    except Exception:
        return pd.DataFrame()


@_cache
def load_vc_edges() -> pd.DataFrame:
    try:
        df = pd.read_csv(os.path.join(_DIR, "vc_edges.csv"), encoding="utf-8-sig")
        df["공급사"] = df["공급사"].map(normalize_name)
        df["고객사"] = df["고객사"].map(normalize_name)
        return df
    except Exception:
        return pd.DataFrame()


@_cache
def _universe_map() -> dict:
    """종목명 → {종목코드, 섹터, 시가총액, 종합점수}."""
    from epsrev.data.dashboard_data import CO, SECTORS
    m = {}
    for sec in SECTORS:
        for x in sec.get("cos", []):
            c = CO.get(x["t"])
            if c:
                m[normalize_name(c["n"])] = {
                    "종목코드": c["t"], "섹터": c.get("secName", ""),
                    "시가총액": c.get("mkt"), "종합점수": c.get("total")}
    return m


def enrich_with_universe(df: pd.DataFrame, name_col: str) -> pd.DataFrame:
    """name_col 종목명 기준 유니버스 정보 부착. 유니버스 밖은 빈칸으로 행 유지."""
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    um = _universe_map()
    df = df.copy()
    for col in ("종목코드", "섹터", "시가총액", "종합점수"):
        df[col] = df[name_col].map(lambda n: (um.get(n) or {}).get(col))
    _dump_unmatched(df, name_col, um)
    return df


def _dump_unmatched(df, name_col, um):
    try:
        unm = sorted({n for n in df[name_col] if n and n not in um})
        if unm and not os.path.exists("/mount/src"):     # 클라우드(읽기전용) 쓰기 스킵
            path = os.path.join(_DIR, "unmatched_names.csv")
            prev = set()
            if os.path.exists(path):
                try:
                    prev = set(pd.read_csv(path, encoding="utf-8-sig")["기업명"].astype(str))
                except Exception:
                    prev = set()
            allnames = sorted(prev | set(unm))
            pd.DataFrame({"기업명": allnames}).to_csv(path, index=False, encoding="utf-8-sig")
    except Exception:
        pass


def get_stock_value_chain(stock_name: str) -> dict:
    """{positions, suppliers, customers, peers} DataFrame 묶음."""
    name = normalize_name(stock_name)
    nodes, edges = load_vc_nodes(), load_vc_edges()
    empty = pd.DataFrame()
    positions = nodes[nodes["기업명"] == name] if not nodes.empty else empty
    suppliers = edges[edges["고객사"] == name] if not edges.empty else empty   # 이 종목에 납품
    customers = edges[edges["공급사"] == name] if not edges.empty else empty   # 이 종목이 납품

    peers = empty
    if not positions.empty and not nodes.empty:
        keys = set(map(tuple, positions[["서브섹터", "체인단계"]].dropna().drop_duplicates().values))
        if keys:
            idx = list(nodes[["서브섹터", "체인단계"]].itertuples(index=False, name=None))
            mask = [t in keys for t in idx]
            peers = nodes[mask]
            peers = peers[peers["기업명"] != name].drop_duplicates(subset=["기업명"])

    return {
        "positions": positions,
        "suppliers": enrich_with_universe(suppliers, "공급사"),
        "customers": enrich_with_universe(customers, "고객사"),
        "peers": enrich_with_universe(peers, "기업명"),
    }
