"""epsrev/ui/related_panel.py — '핵심/연관 산업지표' 패널 컴포넌트(라이트).

render_industry_panel(title, datasets, ticker):
 - 헤더 바 + 3영역: (좌)데이터명 | (중)상세항목(있을때만) | (우)차트+토글+메타.
 - 토글: 변환(YoY/MoM/YTD, 라인) · 기간(1Y/3Y/5Y/All, 막대).
 - 차트: 이중축 막대(값)+라인(변화율), 라이트. 데이터 없으면 '연동 예정'.
"""
from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from epsrev.data.related_data import get_series, compute_transform

# 라이트 팔레트
TXT, MUTE, BORDER, ROWLN, HEADBG = "#1a1f36", "#8a93a6", "#e5e8ef", "#eef0f4", "#f7f8fa"
BLUE, ORANGE = "#4f8bf9", "#f59e0b"
_PMONTHS = {"1Y": 12, "3Y": 36, "5Y": 60, "All": 100000}


def _seg(options, default, key):
    if hasattr(st, "segmented_control"):
        return st.segmented_control("t", options, default=default, key=key,
                                    label_visibility="collapsed") or default
    return st.radio("t", options, index=options.index(default), horizontal=True,
                    key=key, label_visibility="collapsed")


def _panel_fig(series, line_pct, unit):
    x = [s["m"] for s in series]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=x, y=[s["val"] for s in series], name="값 (좌)",
                         marker_color=BLUE, marker_line_width=0,
                         hovertemplate="%{y:,.0f}<extra></extra>"), secondary_y=False)
    fig.add_trace(go.Scatter(x=x, y=line_pct, name="변화율 (우)",
                             line=dict(color=ORANGE, width=2), mode="lines", connectgaps=False,
                             hovertemplate="%{y:.1f}%<extra></extra>"), secondary_y=True)
    fig.update_layout(template="plotly_white", height=340, bargap=0.55,
                      margin=dict(l=54, r=48, t=12, b=46), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", hovermode="x unified",
                      legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center",
                                  font=dict(size=10, color=MUTE), bgcolor="rgba(0,0,0,0)"),
                      font=dict(size=10, color="#556677"))
    fig.update_xaxes(type="date", tickformat="%y/%m", showgrid=False,
                     tickfont=dict(size=9, color=MUTE))
    fig.update_yaxes(secondary_y=False, gridcolor=ROWLN, tickfont=dict(size=9, color=MUTE),
                     zeroline=False, tickformat="~s",
                     title=dict(text=f"({unit})", font=dict(size=9, color=MUTE)))
    fig.update_yaxes(secondary_y=True, showgrid=False, tickfont=dict(size=9, color=MUTE),
                     ticksuffix="%", zeroline=True, zerolinecolor=ROWLN)
    return fig


def _meta_footer(meta):
    def cell(lbl, val):
        return (f"<div style='flex:1'><div style='font-size:0.62rem;color:{MUTE}'>{lbl}</div>"
                f"<div style='font-size:0.8rem;font-weight:700;color:{TXT}'>{val}</div></div>")
    st.markdown(
        f"<div style='display:flex;gap:10px;border-top:1px solid {ROWLN};margin-top:8px;padding-top:8px'>"
        + cell("Latest", meta.get("latest", "—")) + cell("Frequency", meta.get("frequency", "—"))
        + cell("Unit", meta.get("unit", "—")) + cell("Source", meta.get("source", "—"))
        + "</div>", unsafe_allow_html=True)


def render_industry_panel(title: str, datasets: list[dict], ticker):
    with st.container(border=True):
        st.markdown(f"<div style='background:{HEADBG};margin:-16px -16px 12px;padding:9px 16px;"
                    f"border-bottom:1px solid {BORDER};border-radius:8px 8px 0 0;"
                    f"font-weight:800;font-size:0.92rem;color:{TXT}'>{title}</div>",
                    unsafe_allow_html=True)
        if not datasets:
            st.caption("표시할 데이터가 없습니다.")
            return

        tk = str(ticker)
        names = [d["name"] for d in datasets]
        k_ds = f"rel_ds_{title}_{tk}"
        sel_name = st.session_state.get(k_ds) or names[0]
        if sel_name not in names:
            sel_name = names[0]
        ds = next(d for d in datasets if d["name"] == sel_name)
        details = ds.get("details")

        if details:
            c_ds, c_dt, c_ch = st.columns([1.5, 1.1, 4.2], gap="medium")
        else:
            c_ds, c_ch = st.columns([1.5, 5.3], gap="medium")
            c_dt = None

        with c_ds:
            st.markdown(f"<div style='font-size:0.66rem;color:{MUTE};margin-bottom:4px'>데이터</div>",
                        unsafe_allow_html=True)
            st.radio("데이터", names, key=k_ds, label_visibility="collapsed")

        sel_detail = None
        if details and c_dt is not None:
            with c_dt:
                st.markdown(f"<div style='font-size:0.66rem;color:{MUTE};margin-bottom:4px'>상세항목</div>",
                            unsafe_allow_html=True)
                dlabels = [x["label"] for x in details]
                sel_detail = st.radio("상세", dlabels, key=f"rel_dt_{title}_{tk}_{ds['id']}",
                                      label_visibility="collapsed")

        with c_ch:
            tg1, tg2 = st.columns(2)
            with tg1:
                transform = _seg(["YoY", "MoM", "YTD"], "YoY", f"rel_tf_{title}_{tk}")
            with tg2:
                period = _seg(list(_PMONTHS), "3Y", f"rel_pd_{title}_{tk}")

            res = get_series(ds["id"], sel_detail)
            series, meta, note = res["series"], res["meta"], res["note"]

            if series:
                pct = compute_transform(series, transform)
                n = _PMONTHS[period]
                sser = series if n >= 100000 else series[-n:]
                spct = pct[-len(sser):]
                st.plotly_chart(_panel_fig(sser, spct, meta.get("unit", "")),
                                use_container_width=True, config={"displayModeBar": False})
            else:
                st.markdown(
                    f"<div style='height:300px;display:flex;align-items:center;justify-content:center;"
                    f"color:{MUTE};font-size:0.85rem;text-align:center;line-height:1.8'>🏭 "
                    f"{note or '데이터 없음'}<br><span style='font-size:0.72rem'>"
                    f"{ds['name']} · {meta.get('source', '')}</span></div>",
                    unsafe_allow_html=True)

            _meta_footer(meta)
