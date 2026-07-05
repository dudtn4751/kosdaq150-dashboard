"""epsrev/ui/fin_section.py — FnGuide Company Guide 스타일 '실적 추이' 섹션.

양식(차트+표)을 전부 완성. 데이터는 get_fin_timeseries(ticker)에서 주입.
데이터/키 없으면 '—'와 '데이터 연동 예정'으로 graceful 렌더.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from epsrev.data.financials import get_fin_timeseries

# 차트 지표 탭 (라벨, 스키마키) — 전부 배치
METRICS = [
    ("매출액", "rev"), ("영업이익", "op"), ("당기순이익", "ni"),
    ("자산총계", "assets"), ("부채총계", "liab"), ("자본총계", "equity"),
    ("영업현금흐름", "cf_op"),
]
_PERIOD_YEARS = {"1Y": 1, "3Y": 3, "5Y": 5, "All": 99}


# ── 유틸 ─────────────────────────────────────────────────────────────────────
def _period_to_date(period: str) -> str:
    """'2025 3Q' → '2025-09-30' / '2025' → '2025-12-31'."""
    try:
        if "Q" in period:
            y, q = period.split(" ")
            end = {"1Q": "03-31", "2Q": "06-30", "3Q": "09-30", "4Q": "12-31"}[q]
            return f"{y}-{end}"
        return f"{period}-12-31"
    except Exception:
        return ""


def _fmt(v, pct=False, signed=False):
    if v is None:
        return "—"
    try:
        if pct:
            return f"{v:+.1f}%" if signed else f"{v:.1f}%"
        return f"{v:,.0f}"
    except Exception:
        return "—"


def _yoy(rows, i, key):
    """rows[i]의 key값 %YoY. 분기=4기 전, 연도=1기 전. 값 없으면 None."""
    step = 4 if ("Q" in rows[i]["period"]) else 1
    if i - step < 0:
        return None
    cur, prev = rows[i].get(key), rows[i - step].get(key)
    if cur is None or prev in (None, 0):
        return None
    return round((cur - prev) / abs(prev) * 100, 1)


# ── STEP 2: 차트 ─────────────────────────────────────────────────────────────
def _render_chart(ticker: str, data: dict):
    c1, c2 = st.columns([3, 2])
    with c1:
        metric_lbl = st.radio("지표", [m[0] for m in METRICS], horizontal=True,
                              key=f"finmetric_{ticker}", label_visibility="collapsed")
    with c2:
        period = st.radio("기간", list(_PERIOD_YEARS), horizontal=True, index=2,
                          key=f"finperiod_{ticker}", label_visibility="collapsed")
    mkey = dict(METRICS)[metric_lbl]

    price = data.get("price") or []
    # 지표 시계열: 분기 우선, 없으면 연도
    series = data.get("quarterly") or data.get("annual") or []
    mpts = [(_period_to_date(r["period"]), r.get(mkey)) for r in series]
    mpts = [(d, v) for d, v in mpts if d and v is not None]

    # 기간 필터
    yrs = _PERIOD_YEARS[period]
    cutoff = None
    if price:
        try:
            last = pd.to_datetime(price[-1]["date"])
            cutoff = (last - pd.DateOffset(years=yrs)).strftime("%Y-%m-%d")
        except Exception:
            cutoff = None
    if cutoff:
        price = [p for p in price if p["date"] >= cutoff]
        mpts = [(d, v) for d, v in mpts if d >= cutoff]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    has = False
    if price:
        fig.add_trace(go.Scatter(x=[p["date"] for p in price], y=[p["close"] for p in price],
                                 name="주가", line=dict(color="#8c9bb5", width=1.3)),
                      secondary_y=False)
        has = True
    if mpts:
        fig.add_trace(go.Scatter(x=[d for d, _ in mpts], y=[v for _, v in mpts],
                                 name=metric_lbl, line=dict(color="#4f8eff", width=2, shape="hv"),
                                 fill="tozeroy", fillcolor="rgba(79,142,255,0.12)"),
                      secondary_y=True)
        has = True

    fig.update_layout(height=300, margin=dict(l=10, r=10, t=24, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h", y=1.12, font=dict(size=10)),
                      font=dict(size=10))
    fig.update_yaxes(title_text="주가(원)", secondary_y=False, showgrid=False, tickfont=dict(size=9))
    fig.update_yaxes(title_text=f"{metric_lbl}(백만원)", secondary_y=True, showgrid=True,
                     gridcolor="rgba(0,0,0,0.06)", tickfont=dict(size=9))
    fig.update_xaxes(showgrid=False, tickfont=dict(size=9))
    if not has:
        fig.add_annotation(text="데이터 연동 예정", showarrow=False,
                           font=dict(size=14, color="#94a3b8"), x=0.5, y=0.5, xref="paper", yref="paper")
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ── STEP 3: 표 ───────────────────────────────────────────────────────────────
def _render_table(ticker: str, data: dict):
    mode = st.radio("표", ["분기", "연도"], horizontal=True,
                    key=f"fintbl_{ticker}", label_visibility="collapsed")
    if mode == "분기":
        rows = (data.get("quarterly") or [])[-6:]
    else:
        rows = (data.get("annual") or [])[-5:]

    # 원본 인덱스 기준 YoY 계산을 위해 전체에서 위치 찾기
    full = data.get("quarterly") if mode == "분기" else data.get("annual")
    full = full or []
    idx_map = {r["period"]: i for i, r in enumerate(full)}

    def yoy_of(r, key):
        i = idx_map.get(r["period"])
        return _yoy(full, i, key) if i is not None else None

    # 행 정의: (라벨, 셀함수)
    def cell(key, pct=False):
        return lambda r: _fmt(r.get(key), pct=pct)

    ROWS = [
        ("매출액", cell("rev")),
        ("  %YoY", lambda r: _fmt(yoy_of(r, "rev"), pct=True, signed=True)),
        ("영업이익", cell("op")),
        ("  영업이익률", cell("opm", pct=True)),
        ("당기순이익", cell("ni")),
        ("  당기순이익률", lambda r: _fmt(
            (round(r["ni"] / r["rev"] * 100, 1) if (r.get("ni") is not None and r.get("rev")) else None),
            pct=True)),
        ("지배주주 당기순이익", cell("ni_ctrl")),
        ("PER", lambda r: _fmt(r.get("per")) if r.get("per") is None else f"{r['per']:.1f}"),
        ("PBR", lambda r: _fmt(r.get("pbr")) if r.get("pbr") is None else f"{r['pbr']:.2f}"),
        ("영업활동현금흐름", cell("cf_op")),
        ("투자활동현금흐름", cell("cf_inv")),
        ("재무활동현금흐름", cell("cf_fin")),
        ("자산총계", cell("assets")),
        ("부채총계", cell("liab")),
        ("자본총계", cell("equity")),
    ]

    cols = [r["period"] for r in rows] if rows else ["—"]
    table = {}
    for label, fn in ROWS:
        table[label] = [fn(r) for r in rows] if rows else ["—"]
    df = pd.DataFrame(table, index=cols).T   # 행=지표, 열=기간
    df.columns = cols

    st.caption("(단위: 백만원)")
    st.dataframe(df, use_container_width=True, height=560)


# ── STEP 4: 통합 ─────────────────────────────────────────────────────────────
def render_fin_section(ticker: str):
    """종목 상세용 '실적 추이' 섹션 — 좌 차트 + 우 표."""
    data = get_fin_timeseries(str(ticker).zfill(6))
    with st.container(border=True):
        st.markdown("**📊 실적 추이** "
                    "<span style='font-size:0.72rem;color:#94a3b8'>FnGuide Company Guide 스타일</span>",
                    unsafe_allow_html=True)
        left, right = st.columns([1.15, 1], gap="medium")
        with left:
            _render_chart(ticker, data)
        with right:
            _render_table(ticker, data)
