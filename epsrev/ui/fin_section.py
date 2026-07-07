"""epsrev/ui/fin_section.py — '실적 추이' 섹션(라이트, 리포트 표 톤과 통일).

좌: 선택 지표 막대그래프(막대 위 수치 라벨).
우: 요약 재무제표 흰 바탕 HTML 표(기간=열, 지표=행, 4개 섹션 그룹).
데이터/스키마(get_fin_timeseries)는 그대로 소비. 없으면 경고 배너 + '—'.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from epsrev.data.financials import get_fin_timeseries

# 라이트 팔레트(리포트 컨센서스 표와 동일 톤)
TXT, MUTE = "#1a1f36", "#8a93a6"
BORDER, ROWLN, GRPLN, HEADBG = "#e5e8ef", "#eef0f4", "#dfe3ea", "#f7f8fa"
POS, NEG, BAR, AXIS = "#16a34a", "#dc2626", "#4f8eff", "#556677"

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
    if hasattr(st, "segmented_control"):
        v = st.segmented_control(label, options, default=default, key=key,
                                 label_visibility="collapsed")
        return v or default
    return st.radio(label, options, index=options.index(default), horizontal=True,
                    key=key, label_visibility="collapsed")


# ── 차트(막대그래프) ──────────────────────────────────────────────────────────
def _render_chart(ticker: str, data: dict):
    st.markdown(f"<div style='font-size:0.9rem;font-weight:700;color:{TXT};margin-bottom:6px'>"
                "주요 재무 추이 "
                f"<span style='font-size:0.7rem;color:{MUTE};font-weight:400'>(단위: 백만원)</span></div>",
                unsafe_allow_html=True)
    metric_lbl = _seg("지표", [m[0] for m in METRICS], "매출액", f"m_{ticker}")
    period = _seg("기간", list(_PERIOD_YEARS), "5Y", f"p_{ticker}")
    mkey = dict(METRICS)[metric_lbl]

    series = data.get("quarterly") or data.get("annual") or []
    rows = [(r["period"], _period_to_date(r["period"]), r.get(mkey)) for r in series]
    rows = [(p, d, v) for p, d, v in rows if d and isinstance(v, (int, float))]
    yrs = _PERIOD_YEARS[period]
    if rows and yrs < 99:
        xmax = max(d for _, d, _ in rows)
        cutoff = (pd.to_datetime(xmax) - pd.DateOffset(years=yrs)).strftime("%Y-%m-%d")
        rows = [(p, d, v) for p, d, v in rows if d >= cutoff]

    labels = [p for p, _, _ in rows]
    vals = [v for _, _, v in rows]

    fig = go.Figure()
    if any(isinstance(v, (int, float)) for v in vals):
        fig.add_trace(go.Bar(
            x=labels, y=vals, marker_color=BAR,
            text=[f"{v:,.0f}" if isinstance(v, (int, float)) else "" for v in vals],
            textposition="outside", textfont=dict(size=9, color=AXIS), cliponaxis=False,
            hovertemplate="%{x}<br>%{y:,.0f} 백만원<extra></extra>"))
        nums = [v for v in vals if isinstance(v, (int, float))]
        lo, hi = min(nums), max(nums)
        span = (hi - lo) or abs(hi) or 1
        fig.update_yaxes(range=[min(0, lo) - span * 0.05, hi + span * 0.20])
    else:
        fig.add_annotation(text="데이터 없음", showarrow=False,
                           font=dict(size=13, color=MUTE), x=0.5, y=0.5, xref="paper", yref="paper")

    fig.update_layout(template="plotly_white", height=400, margin=dict(l=6, r=6, t=24, b=6),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      showlegend=False, bargap=0.28,
                      uniformtext=dict(minsize=8, mode="hide"),
                      font=dict(size=10, color=AXIS))
    fig.update_xaxes(showgrid=False, tickfont=dict(size=9, color=AXIS))
    fig.update_yaxes(gridcolor=ROWLN, tickfont=dict(size=9, color=AXIS),
                     zeroline=True, zerolinecolor=GRPLN)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown(f"<div style='font-size:0.68rem;color:{MUTE};margin-top:-4px'>"
                "· 주가선은 빅파이낸스 시세 연동 후 표시됩니다.</div>", unsafe_allow_html=True)


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
    full = (data.get("quarterly") if mode == "분기별" else data.get("annual")) or []
    idx = {r["period"]: i for i, r in enumerate(full)}   # YoY 룩백용(원본 인덱스)
    disp = [r for r in full if r.get("rev") is not None or r.get("op") is not None]  # 미보고 빈 분기 제외
    rows = disp[-6:] if mode == "분기별" else disp[-4:]   # 분기 최근 6 / 연도 최근 4

    def npm(r):
        return round(r["ni"] / r["rev"] * 100, 1) if (r.get("ni") is not None and r.get("rev")) else None

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
    ]

    periods = [r["period"] for r in rows]
    min_w = 150 + len(periods) * 112   # 항목열 + 값열 폭 → 넘으면 카드내 가로스크롤
    colgroup = "<col style='width:150px'>" + "".join("<col style='width:112px'>" for _ in periods)
    th = (f"<th style='text-align:left;padding:9px 12px;background:{HEADBG};"
          f"border-bottom:1px solid {BORDER}'>&nbsp;</th>")
    for p in periods:
        th += (f"<th style='text-align:right;padding:9px 12px;font-weight:800;font-size:0.8rem;"
               f"color:{TXT};background:{HEADBG};border-bottom:1px solid {BORDER};"
               f"white-space:nowrap'>{p}</th>")

    body = ""
    last = len(SPEC) - 1
    for i, (label, fn, kind, gstart) in enumerate(SPEC):
        gt = f"border-top:1px solid {GRPLN};" if gstart else ""
        bb = "" if i == last else f"border-bottom:1px solid {ROWLN};"   # 마지막 행 밑줄 제거
        if kind == "sub":
            lb = (f"<td style='text-align:left;padding:5px 12px 5px 24px;white-space:nowrap;"
                  f"font-size:0.72rem;color:{MUTE};{gt}'>{label}</td>")
            vs = (f"text-align:right;padding:5px 12px;white-space:nowrap;font-size:0.74rem;"
                  f"font-variant-numeric:tabular-nums;{bb}{gt}")
        elif kind == "main":
            lb = (f"<td style='text-align:left;padding:8px 12px;white-space:nowrap;font-weight:700;"
                  f"font-size:0.84rem;color:{TXT};{gt}'>{label}</td>")
            vs = (f"text-align:right;padding:8px 12px;white-space:nowrap;font-weight:700;"
                  f"font-size:0.85rem;color:{TXT};font-variant-numeric:tabular-nums;{bb}{gt}")
        else:
            lb = (f"<td style='text-align:left;padding:7px 12px;white-space:nowrap;"
                  f"font-size:0.8rem;color:#3f465c;{gt}'>{label}</td>")
            vs = (f"text-align:right;padding:7px 12px;white-space:nowrap;font-size:0.82rem;"
                  f"color:{TXT};font-variant-numeric:tabular-nums;{bb}{gt}")
        body += f"<tr>{lb}" + "".join(f"<td style='{vs}'>{fn(r)}</td>" for r in rows) + "</tr>"

    st.markdown(
        f"<div style='overflow-x:auto;border:1px solid {BORDER};border-radius:10px;background:#fff;"
        "box-shadow:0 1px 3px rgba(16,24,40,0.06);padding:16px'>"
        f"<table style='min-width:{min_w}px;width:100%;border-collapse:collapse;table-layout:fixed;"
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
        left, right = st.columns([1.15, 1], gap="large")
        with left:
            _render_chart(ticker, data)
        with right:
            _render_table(ticker, data)
