"""epsrev/ui/fin_section.py — FnGuide Company Guide 스타일 '실적 추이'(다크).

좌: 주가(파랑, 좌축) + 선택 지표(노랑 계단, 우축) 이중축 콤보 + range slider.
우: 요약 재무제표 HTML 표(기간=열, 지표=행, 4개 섹션 그룹).
데이터/스키마(get_fin_timeseries)는 그대로 소비. 없으면 경고 배너 + '—'.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from epsrev.data.financials import get_fin_timeseries

# 다크 팔레트(company_detail 통일)
TXT, MUTE, LINE, LINE2 = "#dde3f8", "#546080", "#1c2038", "#2a3150"
POS, NEG, BLUE, GOLD = "#00c87a", "#ff4060", "#4f8eff", "#f5c400"

METRICS = [("매출액", "rev"), ("영업이익", "op"), ("당기순이익", "ni"),
           ("자산총계", "assets"), ("부채총계", "liab"), ("자본총계", "equity"),
           ("영업현금흐름", "cf_op")]
_PERIOD_YEARS = {"1Y": 1, "3Y": 3, "5Y": 5, "All": 99}


# ── 유틸 ─────────────────────────────────────────────────────────────────────
def _period_to_date(period: str) -> str:
    try:
        if "Q" in period:
            y, q = period.split(" ")
            end = {"1Q": "03-31", "2Q": "06-30", "3Q": "09-30", "4Q": "12-31"}[q]
            return f"{y}-{end}"
        return f"{period}-12-31"
    except Exception:
        return ""


def _yoy(rows, i, key):
    if i is None:
        return None
    step = 4 if ("Q" in rows[i]["period"]) else 1
    if i - step < 0:
        return None
    cur, prev = rows[i].get(key), rows[i - step].get(key)
    if cur is None or prev in (None, 0):
        return None
    return round((cur - prev) / abs(prev) * 100, 1)


def _seg(label, options, default, key):
    """세그먼트 토글(가능하면 st.segmented_control, 아니면 radio)."""
    if hasattr(st, "segmented_control"):
        v = st.segmented_control(label, options, default=default, key=key,
                                 label_visibility="collapsed")
        return v or default
    return st.radio(label, options, index=options.index(default), horizontal=True,
                    key=key, label_visibility="collapsed")


def _yr(vals, pad=0.08, floor0=False):
    v = [x for x in vals if isinstance(x, (int, float))]
    if not v:
        return None
    lo, hi = min(v), max(v)
    if lo == hi:
        d = abs(lo) * 0.1 or 1
        return [lo - d, hi + d]
    m = (hi - lo) * pad
    lo2 = lo - m
    if floor0 and lo >= 0:
        lo2 = max(0, lo2)
    return [lo2, hi + m]


# ── 차트(주가 + 지표 이중축) ──────────────────────────────────────────────────
def _render_chart(ticker: str, data: dict):
    st.markdown(f"<div style='font-size:0.9rem;font-weight:700;color:{TXT};margin-bottom:6px'>"
                "주요 재무 및 주가 비교 "
                f"<span style='font-size:0.7rem;color:{MUTE};font-weight:400'>(지표: 백만원)</span></div>",
                unsafe_allow_html=True)
    metric_lbl = _seg("지표", [m[0] for m in METRICS], "매출액", f"m_{ticker}")
    period = _seg("기간", list(_PERIOD_YEARS), "5Y", f"p_{ticker}")
    mkey = dict(METRICS)[metric_lbl]

    price = sorted([p for p in (data.get("price") or []) if p.get("date")], key=lambda p: p["date"])
    series = data.get("quarterly") or data.get("annual") or []
    mpts = sorted([(_period_to_date(r["period"]), r.get(mkey)) for r in series
                   if r.get(mkey) is not None and _period_to_date(r["period"])], key=lambda t: t[0])
    has_price = bool(price)

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    alld = [p["date"] for p in price] + [d for d, _ in mpts]
    if not alld:
        fig.add_annotation(text="데이터 없음", showarrow=False,
                           font=dict(size=13, color=MUTE), x=0.5, y=0.5, xref="paper", yref="paper")
    else:
        xmax, xmin = max(alld), min(alld)
        yrs = _PERIOD_YEARS[period]
        x0 = xmin if yrs >= 99 else max(
            xmin, (pd.to_datetime(xmax) - pd.DateOffset(years=yrs)).strftime("%Y-%m-%d"))
        if has_price:
            fig.add_trace(go.Scatter(x=[p["date"] for p in price], y=[p["close"] for p in price],
                                     name="주가", mode="lines",
                                     line=dict(color=BLUE, width=1.4), connectgaps=False),
                          secondary_y=False)
        fig.add_trace(go.Scatter(x=[d for d, _ in mpts], y=[v for _, v in mpts], name=metric_lbl,
                                 mode="lines", line=dict(color=GOLD, width=2, shape="hv"),
                                 fill="tozeroy", fillcolor="rgba(245,196,0,0.12)", connectgaps=False),
                      secondary_y=has_price)
        fig.update_xaxes(range=[x0, xmax])
        mw = [v for d, v in mpts if d >= x0]
        if has_price:
            pr = _yr([p["close"] for p in price if p["date"] >= x0], floor0=True)
            if pr:
                fig.update_yaxes(range=pr, secondary_y=False)
            mr = _yr(mw, floor0=True)
            if mr:
                fig.update_yaxes(range=mr, secondary_y=True)
        else:
            mr = _yr(mw, floor0=True)
            if mr:
                fig.update_yaxes(range=mr, secondary_y=False)

    fig.update_layout(template="plotly_dark", height=400, margin=dict(l=6, r=6, t=28, b=6),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      hovermode="x unified", dragmode="pan",
                      legend=dict(orientation="h", y=1.13, x=0, font=dict(size=10)),
                      font=dict(size=10, color=TXT))
    fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.07,
                                      bgcolor="rgba(255,255,255,0.03)", bordercolor=LINE),
                     gridcolor=LINE, tickfont=dict(size=9), showgrid=True)
    fig.update_yaxes(gridcolor=LINE, tickfont=dict(size=9), secondary_y=False,
                     title_text="주가(원)" if has_price else None, title_font=dict(size=9))
    fig.update_yaxes(gridcolor="rgba(0,0,0,0)", tickfont=dict(size=9), secondary_y=True,
                     title_text="(백만원)" if has_price else None, title_font=dict(size=9))
    st.plotly_chart(fig, use_container_width=True,
                    config={"displayModeBar": False, "scrollZoom": True})
    if not has_price:
        st.markdown(f"<div style='font-size:0.68rem;color:{MUTE};margin-top:-6px'>"
                    "· 주가선은 빅파이낸스 시세 연동 후 표시됩니다(클라우드에선 현재 지표만).</div>",
                    unsafe_allow_html=True)


# ── 표(요약 재무제표) ─────────────────────────────────────────────────────────
def _amt(v):
    return f"{v:,.0f}" if isinstance(v, (int, float)) else "—"


def _sgn(v):
    if not isinstance(v, (int, float)):
        return f"<span style='color:{MUTE}'>—</span>"
    return f"<span style='color:{POS if v >= 0 else NEG}'>{v:+.1f}</span>"


def _ratio(v):
    return f"{v:.2f}" if isinstance(v, (int, float)) else "—"


def _render_table(ticker: str, data: dict):
    st.markdown(f"<div style='display:flex;justify-content:space-between;align-items:center;"
                f"margin-bottom:6px'><span style='font-size:0.9rem;font-weight:700;color:{TXT}'>"
                "요약 재무제표</span>"
                f"<span style='font-size:0.7rem;color:{MUTE}'>(단위: 백만원)</span></div>",
                unsafe_allow_html=True)
    mode = _seg("표", ["연도별", "분기별"], "연도별", f"t_{ticker}")
    if mode == "분기별":
        full = data.get("quarterly") or []
        rows = full[-5:]
    else:
        full = data.get("annual") or []
        rows = full[-4:]
    idx = {r["period"]: i for i, r in enumerate(full)}

    def npm(r):
        return round(r["ni"] / r["rev"] * 100, 1) if (r.get("ni") is not None and r.get("rev")) else None

    # (라벨, 셀함수, 종류) — 종류: main(굵게)/sub(작은뮤트%)/norm(일반). g=그룹 시작(진한 divider)
    SPEC = [
        ("매출액", lambda r: _amt(r.get("rev")), "main", False),
        ("% YoY", lambda r: _sgn(_yoy(full, idx.get(r["period"]), "rev")), "sub", False),
        ("영업이익", lambda r: _amt(r.get("op")), "main", False),
        ("% 영업이익률", lambda r: _sgn(r.get("opm")), "sub", False),
        ("당기순이익", lambda r: _amt(r.get("ni")), "main", False),
        ("% 당기순이익률", lambda r: _sgn(npm(r)), "sub", False),
        ("지배주주 당기순이익", lambda r: _amt(r.get("ni_ctrl")), "main", False),
        ("PER (배)", lambda r: _ratio(r.get("per")), "norm", True),
        ("PBR (배)", lambda r: _ratio(r.get("pbr")), "norm", False),
        ("영업활동현금흐름", lambda r: _amt(r.get("cf_op")), "norm", True),
        ("투자활동현금흐름", lambda r: _amt(r.get("cf_inv")), "norm", False),
        ("재무활동현금흐름", lambda r: _amt(r.get("cf_fin")), "norm", False),
        ("자산총계", lambda r: _amt(r.get("assets")), "main", True),
        ("부채총계", lambda r: _amt(r.get("liab")), "main", False),
        ("자본총계", lambda r: _amt(r.get("equity")), "main", False),
    ]

    periods = [r["period"] for r in rows]
    colgroup = "<col style='width:150px'>" + "".join("<col>" for _ in periods)
    th = (f"<th style='text-align:left;padding:8px 10px;background:#161b2e;"
          f"border-bottom:2px solid {LINE2}'>&nbsp;</th>")
    for p in periods:
        th += (f"<th style='text-align:right;padding:8px 12px;font-weight:800;font-size:0.8rem;"
               f"color:{TXT};background:#161b2e;border-bottom:2px solid {LINE2};"
               f"white-space:nowrap'>{p}</th>")

    body = ""
    for label, fn, kind, gstart in SPEC:
        gt = f"border-top:2px solid {LINE2};" if gstart else ""
        if kind == "sub":
            lb = (f"<td style='text-align:left;padding:5px 10px 5px 22px;white-space:nowrap;"
                  f"font-size:0.72rem;color:{MUTE};{gt}'>{label}</td>")
            vs = (f"text-align:right;padding:5px 12px;white-space:nowrap;font-size:0.74rem;"
                  f"font-variant-numeric:tabular-nums;border-bottom:1px solid #141829;{gt}")
        elif kind == "main":
            lb = (f"<td style='text-align:left;padding:8px 10px;white-space:nowrap;font-weight:700;"
                  f"font-size:0.84rem;color:{TXT};{gt}'>{label}</td>")
            vs = (f"text-align:right;padding:8px 12px;white-space:nowrap;font-weight:700;"
                  f"font-size:0.85rem;color:{TXT};font-variant-numeric:tabular-nums;"
                  f"border-bottom:1px solid {LINE};{gt}")
        else:
            lb = (f"<td style='text-align:left;padding:7px 10px;white-space:nowrap;"
                  f"font-size:0.8rem;color:#b8c2e0;{gt}'>{label}</td>")
            vs = (f"text-align:right;padding:7px 12px;white-space:nowrap;font-size:0.82rem;"
                  f"color:{TXT};font-variant-numeric:tabular-nums;border-bottom:1px solid {LINE};{gt}")
        body += f"<tr>{lb}" + "".join(f"<td style='{vs}'>{fn(r)}</td>" for r in rows) + "</tr>"

    st.markdown(
        f"<div style='overflow-x:auto;border:1px solid {LINE};border-radius:8px;background:#0f1220'>"
        "<table style='width:100%;border-collapse:collapse;table-layout:fixed;"
        "font-variant-numeric:tabular-nums'>"
        f"<colgroup>{colgroup}</colgroup><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True)


# ── 통합 ─────────────────────────────────────────────────────────────────────
def render_fin_section(ticker: str):
    data = get_fin_timeseries(str(ticker).zfill(6))
    with st.container(border=True):
        st.markdown(f"<span style='font-size:1rem;font-weight:800;color:{TXT}'>📊 실적 추이</span>",
                    unsafe_allow_html=True)
        note = data.get("note")
        if not (data.get("quarterly") or data.get("annual")):
            st.warning(f"⚠ 실적 데이터를 불러오지 못했습니다 — {note or '원인 미상'}", icon="⚠️")
        left, right = st.columns([1.3, 1], gap="large")
        with left:
            _render_chart(ticker, data)
        with right:
            _render_table(ticker, data)
