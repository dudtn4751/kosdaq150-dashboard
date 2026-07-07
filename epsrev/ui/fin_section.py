"""epsrev/ui/fin_section.py — 빅파이낸스 요약 재무제표 스타일 '실적 추이' 섹션.

좌: 지표(매출액/영업이익/당기순이익) 스텝 차트(주가 없음).
우: 요약 재무제표 표(기간=열, 지표=행, PBR까지).
데이터는 get_fin_timeseries(ticker)에서 주입. 없으면 경고 배너 + '—'.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from epsrev.data.financials import get_fin_timeseries

# 차트 지표 탭 (라벨, 스키마키) — 매출/영업익/당기순익만
CHART_METRICS = [("매출액", "rev"), ("영업이익", "op"), ("당기순이익", "ni")]
_PERIOD_YEARS = {"1Y": 1, "3Y": 3, "5Y": 5, "All": 99}

_BLUE = "#1565C0"
_POS, _NEG, _MUTE = "#0a8f3c", "#d32f2f", "#94a3b8"


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


def _yoy(rows, i, key):
    """rows[i]의 key값 %YoY. 분기=4기 전, 연도=1기 전. 값 없으면 None."""
    if i is None:
        return None
    step = 4 if ("Q" in rows[i]["period"]) else 1
    if i - step < 0:
        return None
    cur, prev = rows[i].get(key), rows[i - step].get(key)
    if cur is None or prev in (None, 0):
        return None
    return round((cur - prev) / abs(prev) * 100, 1)


# ── 차트 ─────────────────────────────────────────────────────────────────────
def _render_chart(ticker: str, data: dict):
    st.markdown("<div style='font-size:0.9rem;font-weight:700;margin-bottom:6px'>주요 재무 추이 "
                "<span style='font-size:0.72rem;color:#94a3b8;font-weight:400'>(단위: 백만원)</span></div>",
                unsafe_allow_html=True)
    c1, c2 = st.columns([3, 2])
    with c1:
        metric_lbl = st.radio("지표", [m[0] for m in CHART_METRICS], horizontal=True,
                              key=f"finmetric_{ticker}", label_visibility="collapsed")
    with c2:
        period = st.radio("기간", list(_PERIOD_YEARS), horizontal=True, index=2,
                          key=f"finperiod_{ticker}", label_visibility="collapsed")
    mkey = dict(CHART_METRICS)[metric_lbl]

    series = data.get("quarterly") or data.get("annual") or []
    pts = [(_period_to_date(r["period"]), r.get(mkey)) for r in series]
    pts = [(d, v) for d, v in pts if d and v is not None]

    yrs = _PERIOD_YEARS[period]
    if pts and yrs < 99:
        try:
            last = pd.to_datetime(pts[-1][0])
            cutoff = (last - pd.DateOffset(years=yrs)).strftime("%Y-%m-%d")
            pts = [(d, v) for d, v in pts if d >= cutoff]
        except Exception:
            pass

    fig = go.Figure()
    if pts:
        fig.add_trace(go.Scatter(
            x=[d for d, _ in pts], y=[v for _, v in pts], name=metric_lbl, mode="lines",
            line=dict(color=_BLUE, width=2, shape="hv"),
            fill="tozeroy", fillcolor="rgba(21,101,192,0.10)"))
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=8, b=8),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      showlegend=False, font=dict(size=11))
    fig.update_yaxes(showgrid=True, gridcolor="#E8EDF4", tickfont=dict(size=10),
                     zeroline=True, zerolinecolor="#CBD5E1")
    fig.update_xaxes(showgrid=False, tickfont=dict(size=10))
    if not pts:
        fig.add_annotation(text="데이터 없음", showarrow=False,
                           font=dict(size=13, color=_MUTE), x=0.5, y=0.5, xref="paper", yref="paper")
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ── 표 (요약 재무제표) ────────────────────────────────────────────────────────
def _amt(v):
    return f"{v:,.0f}" if isinstance(v, (int, float)) else "—"


def _signed(v):
    """+/- 색상 포함 셀 HTML. None → '—'."""
    if not isinstance(v, (int, float)):
        return f"<span style='color:{_MUTE}'>—</span>"
    col = _POS if v >= 0 else _NEG
    return f"<span style='color:{col}'>{v:+.2f}</span>"


def _ratio(v, nd=2):
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else "—"


def _render_table(ticker: str, data: dict):
    st.markdown("<div style='display:flex;justify-content:space-between;align-items:center;"
                "margin-bottom:6px'><span style='font-size:0.9rem;font-weight:700'>요약 재무제표"
                " <span style='font-size:0.72rem;color:#94a3b8;font-weight:400'>(단위: 백만원)</span>"
                "</span></div>", unsafe_allow_html=True)
    mode = st.radio("표", ["연도별", "분기별"], horizontal=True,
                    key=f"fintbl_{ticker}", label_visibility="collapsed")
    if mode == "분기별":
        full = data.get("quarterly") or []
        rows = full[-6:]
    else:
        full = data.get("annual") or []
        rows = full[-5:]
    idx = {r["period"]: i for i, r in enumerate(full)}

    def npm(r):
        return round(r["ni"] / r["rev"] * 100, 1) if (r.get("ni") is not None and r.get("rev")) else None

    # (라벨, 종류, 추출) — 종류: amt/pct/ratio, sub=들여쓴 % 행, div=위 구분선
    SPEC = [
        ("매출액", "amt", lambda r: _amt(r.get("rev")), False, False),
        ("% YoY", "pct", lambda r: _signed(_yoy(full, idx.get(r["period"]), "rev")), True, False),
        ("영업이익", "amt", lambda r: _amt(r.get("op")), False, False),
        ("% 영업이익률", "pct", lambda r: _signed(r.get("opm")), True, False),
        ("당기순이익", "amt", lambda r: _amt(r.get("ni")), False, False),
        ("% 당기순이익률", "pct", lambda r: _signed(npm(r)), True, False),
        ("지배주주 당기순이익", "amt", lambda r: _amt(r.get("ni_ctrl")), False, False),
        ("PER (배)", "ratio", lambda r: _ratio(r.get("per")), False, True),
        ("PBR (배)", "ratio", lambda r: _ratio(r.get("pbr")), False, False),
    ]

    periods = [r["period"] for r in rows]
    ncol = max(len(periods), 1)
    # 균등 컬럼폭(라벨 40% + 나머지 균등) → 숫자 세로 정렬
    colw = round(60 / ncol, 3)
    colgroup = "<col style='width:40%'>" + "".join(f"<col style='width:{colw}%'>" for _ in periods)

    # 헤더
    th = ("<th style='text-align:left;padding:9px 12px;font-weight:700;font-size:0.78rem;"
          "color:#334155;background:#EDF1F7;border-bottom:2px solid #D6DEEA'>&nbsp;</th>")
    for p in periods:
        th += (f"<th style='text-align:right;padding:9px 14px;font-weight:800;font-size:0.82rem;"
               f"color:#0f172a;background:#EDF1F7;border-bottom:2px solid #D6DEEA'>{p}</th>")

    body = ""
    for label, kind, fn, sub, div in SPEC:
        top = "border-top:2px solid #C3CEDE;" if div else ""
        if sub:
            lbl = (f"<td style='text-align:left;padding:6px 12px 6px 24px;font-size:0.8rem;"
                   f"color:#475569;background:#fff;{top}'>{label}</td>")
            vsty = (f"text-align:right;padding:6px 14px;font-size:0.82rem;color:#475569;"
                    f"font-variant-numeric:tabular-nums;{top}")
        else:
            lbl = (f"<td style='text-align:left;padding:9px 12px;font-weight:700;font-size:0.86rem;"
                   f"color:#0f172a;background:#fff;border-bottom:1px solid #EEF2F7;{top}'>{label}</td>")
            vsty = (f"text-align:right;padding:9px 14px;font-weight:700;font-size:0.88rem;color:#0f172a;"
                    f"font-variant-numeric:tabular-nums;border-bottom:1px solid #EEF2F7;{top}")
        cells = "".join(f"<td style='{vsty}'>{fn(r)}</td>" for r in rows)
        body += f"<tr>{lbl}{cells}</tr>"

    st.markdown(
        "<div style='overflow-x:auto;border:1px solid #E2E8F0;border-radius:8px'>"
        "<table style='width:100%;border-collapse:collapse;table-layout:fixed;"
        "font-variant-numeric:tabular-nums'>"
        f"<colgroup>{colgroup}</colgroup>"
        f"<thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True)


# ── 통합 ─────────────────────────────────────────────────────────────────────
def render_fin_section(ticker: str):
    """종목 상세용 '실적 추이' 섹션 — 좌 차트 + 우 요약 재무제표."""
    data = get_fin_timeseries(str(ticker).zfill(6))
    with st.container(border=True):
        st.markdown("**📊 실적 추이**", unsafe_allow_html=True)
        note = data.get("note")
        has_rows = bool(data.get("quarterly") or data.get("annual"))
        if not has_rows:
            st.warning(f"⚠ 실적 데이터를 불러오지 못했습니다 — {note or '원인 미상'}", icon="⚠️")
        left, right = st.columns([1.25, 1], gap="large")
        with left:
            _render_chart(ticker, data)
        with right:
            _render_table(ticker, data)
