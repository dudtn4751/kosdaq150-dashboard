"""섹터 이익 컨센서스 추이 — 전용 페이지.

섹터별 영업이익 컨센서스의 '수준(예상 영업이익)'과 '변화(3개월 리비전·일별 추이)'를 깊이 있게 점검.
데이터: data/consensus.json (scripts/update_consensus.py, 매일 05:00 KST 갱신).
"""

import json
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from style import COLORS, styled_plotly, now_kst  # noqa: E402

DATA = Path(__file__).parent.parent / "data"
UP, DOWN, MUT = COLORS["kr_up"], COLORS["kr_down"], COLORS["text_muted"]


@st.cache_data(ttl=3600, show_spinner=False)
def load_consensus():
    p = DATA / "consensus.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def jo(v):
    """억원 → 조/억 문자열."""
    if v is None:
        return "—"
    return f"{v/1e4:,.1f}조" if abs(v) >= 1e4 else f"{v:,.0f}억"


def sec_header(en, ko):
    st.markdown(
        f'<div style="margin:8px 0 14px;">'
        f'<div style="color:{COLORS["accent"]}; font-size:0.72rem; font-weight:700; letter-spacing:0.14em;">{en}</div>'
        f'<div style="color:#0B0F14; font-size:1.5rem; font-weight:800; letter-spacing:-0.02em;">{ko}</div></div>',
        unsafe_allow_html=True)


data = load_consensus()
sec_header("SECTOR EARNINGS CONSENSUS", "섹터 이익 컨센서스 추이")

if not data or not data.get("sectors"):
    st.warning("컨센서스 데이터가 없습니다. `python3 scripts/update_consensus.py` 실행이 필요합니다.")
    st.stop()

sectors = data["sectors"]
stocks = data.get("stocks", [])
history = data.get("history", {})

st.markdown(
    f'<div style="color:{MUT}; font-size:0.9rem; font-weight:600; margin-bottom:10px;">'
    f'기준일 <b style="color:#16202E;">{data.get("date","-")}</b> · '
    f'KOSPI200+KOSDAQ150 커버 <b style="color:#16202E;">{data.get("covered",0)}</b>/{data.get("universe",0)}종목 · '
    f'3개월 리비전 = 영업이익 컨센서스의 3개월 전 대비 변화율 (상향=빨강/하락=파랑)</div>',
    unsafe_allow_html=True)

# ── 1) 섹터 개요: 3개월 리비전 막대 ──────────────
with st.container(border=True):
    sec_header("OVERVIEW", "섹터별 컨센서스 변화 (3개월 리비전)")
    ss = sorted([s for s in sectors if s.get("avg_rev_3m") is not None],
                key=lambda s: s["avg_rev_3m"])
    names = [s["sector"] for s in ss]
    revs = [s["avg_rev_3m"] for s in ss]
    colors = [UP if r > 0 else (DOWN if r < 0 else MUT) for r in revs]
    fig = go.Figure(go.Bar(
        x=revs, y=names, orientation="h",
        marker_color=colors,
        text=[f"{r:+.1f}%" for r in revs], textposition="outside",
        hovertemplate="%{y}: %{x:+.1f}%<extra></extra>"))
    fig.update_layout(height=max(320, 34 * len(names)),
                      margin=dict(l=10, r=40, t=10, b=10),
                      title=dict(text=""), xaxis_title="3개월 리비전 (%)")
    fig.update_xaxes(zeroline=True, zerolinecolor=COLORS["border"], zerolinewidth=1)
    st.plotly_chart(styled_plotly(fig), use_container_width=True, config={"displayModeBar": False})
    st.caption("막대 길이 = 섹터 평균 영업이익 컨센서스의 3개월 전 대비 변화. 오른쪽(빨강)=상향, 왼쪽(파랑)=하향.")

# ── 2) 섹터 선택 → 추이 + 구성 종목 ──────────────
sec_names_sorted = [s["sector"] for s in sorted(sectors, key=lambda s: -(s.get("avg_rev_3m") or -1e9))]
sel = st.selectbox("섹터 선택", sec_names_sorted, key="sel_sector")
sel_info = next((s for s in sectors if s["sector"] == sel), {})

# 선택 섹터 요약 지표
m1, m2, m3, m4 = st.columns(4)
rev = sel_info.get("avg_rev_3m")
m1.metric("3개월 리비전(평균)", f"{rev:+.1f}%" if rev is not None else "—")
m2.metric("상향 / 하향 종목", f"{sel_info.get('up',0)} / {sel_info.get('down',0)}")
m3.metric("예상 영업이익 합", jo(sel_info.get("op_sum")))
m4.metric("커버 종목", f"{sel_info.get('covered',0)}개")

c1, c2 = st.columns([1.1, 1])

# 2-a) 추이 (history)
with c1:
    with st.container(border=True):
        sec_header("TREND", f"{sel} — 일별 추이")
        h = history.get(sel, [])
        if len(h) >= 2:
            dfh = pd.DataFrame(h)
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=dfh["date"], y=dfh["avg_rev_3m"], mode="lines+markers",
                                      name="3개월 리비전(%)", line=dict(color=COLORS["accent"], width=2)))
            fig2.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                               title=dict(text=""), yaxis_title="리비전 (%)")
            st.plotly_chart(styled_plotly(fig2), use_container_width=True, config={"displayModeBar": False})
            # 예상 영업이익 수준 추이
            fig3 = go.Figure(go.Scatter(x=dfh["date"], y=[v/1e4 for v in dfh["op_sum"]], mode="lines+markers",
                                        name="예상 영업이익(조)", line=dict(color="#16202E", width=2),
                                        fill="tozeroy", fillcolor="rgba(21,101,192,0.06)"))
            fig3.update_layout(height=220, margin=dict(l=10, r=10, t=10, b=10),
                               title=dict(text=""), yaxis_title="예상 영업이익 (조)")
            st.plotly_chart(styled_plotly(fig3), use_container_width=True, config={"displayModeBar": False})
        else:
            st.info(f"추이 데이터가 {len(h)}일치 누적됐습니다. 매일 05:00 KST 갱신마다 1포인트씩 쌓여 "
                    "수준·변화 흐름이 그려집니다. (오늘은 현재 리비전 {0}만 표시)".format(
                        f"{rev:+.1f}%" if rev is not None else "—"))

# 2-b) 팔로우업 종목 (섹터 내 추적 유니버스 전체)
with c2:
    with st.container(border=True):
        sec_header("HOLDINGS", f"{sel} — 팔로우업 종목")
        items = [s for s in stocks if s.get("sector") == sel]
        # 컨센서스 있는 종목 먼저(리비전 내림차순), 그다음 미커버 종목(시총순)
        covered = sorted([s for s in items if s.get("rev_3m") is not None],
                         key=lambda s: -(s.get("rev_3m") or -1e9))
        uncovered = sorted([s for s in items if s.get("rev_3m") is None],
                           key=lambda s: -(s.get("marcap") or 0))
        ordered = covered + uncovered
        if not items:
            st.caption("이 섹터의 팔로우업 종목 없음")
        else:
            st.markdown(
                f'<div style="color:{MUT}; font-size:0.82rem; font-weight:600; margin-bottom:6px;">'
                f'팔로우업 <b style="color:#16202E;">{len(items)}</b>종목 · '
                f'컨센서스 <b style="color:#16202E;">{len(covered)}</b>종목</div>',
                unsafe_allow_html=True)
            head = (f'<tr style="border-bottom:2px solid {COLORS["border"]}; color:{MUT}; font-size:0.82rem; font-weight:700;">'
                    f'<th style="text-align:left; padding:8px 8px;">종목</th>'
                    f'<th style="text-align:right;">예상 영업이익</th>'
                    f'<th style="text-align:right;">3개월 리비전</th>'
                    f'<th style="text-align:right; padding-right:8px;">전년대비</th></tr>')
            trs = ""
            for s in ordered[:40]:
                rv = s.get("rev_3m")
                if rv is None:
                    rev_cell = f'<td style="text-align:right; color:{MUT};">—</td>'
                else:
                    rc = UP if rv > 0 else (DOWN if rv < 0 else MUT)
                    rev_cell = f'<td style="text-align:right; color:{rc}; font-weight:800;">{rv:+.1f}%</td>'
                y = s.get("yoy")
                if y is None:
                    yoy_cell = f'<td style="text-align:right; color:{MUT}; padding-right:8px;">—</td>'
                else:
                    yc = UP if y > 0 else (DOWN if y < 0 else MUT)
                    yoy_cell = (f'<td style="text-align:right; color:{yc}; font-weight:600; '
                                f'padding-right:8px;">{y:+.1f}%</td>')
                mk = f'<span style="color:{MUT}; font-size:0.72rem; font-weight:600;"> {s.get("market","")}</span>'
                trs += (
                    f'<tr style="border-bottom:1px solid {COLORS["border"]}; font-size:0.9rem;">'
                    f'<td style="padding:7px 8px;"><b style="color:#16202E; font-weight:700;">{s["name"]}</b>{mk}</td>'
                    f'<td style="text-align:right; color:#16202E; font-weight:700;">{jo(s.get("op_est"))}</td>'
                    f'{rev_cell}{yoy_cell}</tr>')
            st.markdown(f'<table style="width:100%; border-collapse:collapse; border:none;">{head}{trs}</table>',
                        unsafe_allow_html=True)
            st.caption("컨센서스 보유 종목 먼저(리비전 순)·이후 추적 종목(시총 순). 예상 영업이익 = FnGuide 컨센서스.")

st.caption(f"FnGuide 기업분석 기반 · 화면 로드 {now_kst()} (KST) · 매일 05:00 KST 자동 갱신")
