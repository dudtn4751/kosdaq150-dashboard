"""epsrev/ui/trade_section.py — 종목 상세 '수출입 데이터' 섹션(라이트).

수출입 대시보드(외부) 연계: 품목 요약 + 월 수출YoY 시계열 + 관련 수출입 종목 + 딥링크.
로드 실패/매핑 없음은 graceful.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from epsrev.data.trade_link import (get_stock_trade_data, get_related_stocks_by_trade,
                                    _item_yoy, trade_dashboard_url)

TXT, MUTE, BORDER, ROWLN = "#1a1f36", "#8a93a6", "#e5e8ef", "#eef0f4"
POS, NEG = "#16a34a", "#dc2626"


def _yoy_html(v):
    if not isinstance(v, (int, float)) or (isinstance(v, float) and v != v):
        return f"<span style='color:{MUTE}'>—</span>"
    return f"<span style='color:{POS if v >= 0 else NEG};font-weight:700'>{v:+.1f}%</span>"


def render_trade_section(stock_code: str):
    d = get_stock_trade_data(stock_code)
    items, monthly, company, meta = d["items"], d["monthly"], d["company"], (d["meta"] or {})
    tdu = trade_dashboard_url()

    with st.container(border=True):
        dt = meta.get("data_through", "—")
        st.markdown(f"<div style='display:flex;justify-content:space-between;align-items:center'>"
                    f"<span style='font-size:1rem;font-weight:800;color:{TXT}'>📦 수출입 데이터</span>"
                    f"<span style='font-size:0.7rem;color:{MUTE}'>데이터 기준 {dt} · 관세청/EPIC</span></div>",
                    unsafe_allow_html=True)

        if items is None:
            st.caption("수출입 연계 데이터를 불러오지 못했습니다")
            return
        if items.empty:
            st.info("수출입 매핑이 등록되지 않은 종목입니다")
            return

        # ── 품목 요약 테이블(주력품목 상단) ──
        rows = []
        for _, r in items.iterrows():
            yy = _item_yoy(monthly, r["hs코드"])
            rows.append({"품목명": r["품목명"], "hs코드": str(r["hs코드"]),
                         "관계유형": str(r.get("관계유형", "")),
                         "_o": 0 if str(r.get("관계유형", "")) == "주력품목" else 1, **yy})
        rows.sort(key=lambda x: (x["_o"], x["품목명"]))

        heads = ["품목명", "hs코드", "관계유형", "최신월 YoY", "3M평균", "12M평균"]
        th = "<tr style='color:#8a93a6;border-bottom:1px solid #e5e8ef'>"
        for h in heads:
            al = "left" if h in ("품목명", "hs코드", "관계유형") else "right"
            th += f"<th style='text-align:{al};padding:6px 8px;font-size:0.7rem'>{h}</th>"
        if tdu:
            th += "<th></th>"
        th += "</tr>"
        body = ""
        for x in rows:
            wt = 700 if x["_o"] == 0 else 500
            link = (f"<a href='{tdu}?hs={x['hs코드']}' target='_blank' "
                    f"style='font-size:0.7rem;color:#4f8bf9;text-decoration:none'>보기 →</a>") if tdu else ""
            body += (f"<tr style='border-bottom:1px solid {ROWLN}'>"
                     f"<td style='padding:7px 8px;font-weight:{wt};color:{TXT}'>{x['품목명']}</td>"
                     f"<td style='padding:7px 8px;color:{MUTE};font-size:0.76rem'>{x['hs코드']}</td>"
                     f"<td style='padding:7px 8px;color:{MUTE};font-size:0.76rem'>{x['관계유형']}</td>"
                     f"<td style='padding:7px 8px;text-align:right'>{_yoy_html(x['yoy_latest'])}</td>"
                     f"<td style='padding:7px 8px;text-align:right'>{_yoy_html(x['yoy_3m'])}</td>"
                     f"<td style='padding:7px 8px;text-align:right'>{_yoy_html(x['yoy_12m'])}</td>")
            if tdu:
                body += f"<td style='padding:7px 8px;text-align:right'>{link}</td>"
            body += "</tr>"
        st.markdown(f"<div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse;"
                    f"font-variant-numeric:tabular-nums'>{th}{body}</table></div>", unsafe_allow_html=True)

        # ── 월 수출YoY 시계열(최근 24개월, 품목별 라인) ──
        if monthly is not None and not monthly.empty:
            _ts_chart(stock_code, monthly, company)

        # ── 관련 수출입 종목 ──
        _related(stock_code)


def _ts_chart(stock_code, monthly, company):
    st.markdown(f"<div style='font-size:0.82rem;font-weight:700;margin:12px 0 2px;color:{TXT}'>"
                "품목별 월 수출 YoY <span style='font-size:0.68rem;color:#8a93a6;font-weight:400'>"
                "(최근 24개월, %)</span></div>", unsafe_allow_html=True)
    use_company = False
    if company is not None and not company.empty:
        mode = st.radio("소스", ["품목 전체", "이 기업 수출"], horizontal=True,
                        key=f"trade_src_{stock_code}", label_visibility="collapsed")
        use_company = (mode == "이 기업 수출")

    fig = go.Figure()
    recent = sorted(monthly["연월"].unique())[-24:]
    if use_company:
        src = company[company["연월"].isin(sorted(company["연월"].unique())[-24:])]
        for pum, sub in src.groupby("품목명"):
            sub = sub.sort_values("연월")
            fig.add_trace(go.Scatter(x=sub["연월"], y=pd.to_numeric(sub["수출금액_usd"], errors="coerce"),
                                     name=str(pum)[:20], mode="lines", line=dict(width=2)))
        fig.update_yaxes(tickformat="~s")
        yttl = "(기업 수출 USD)"
    else:
        for pum, sub in monthly[monthly["연월"].isin(recent)].groupby("품목명"):
            sub = sub.sort_values("연월")
            fig.add_trace(go.Scatter(x=sub["연월"], y=pd.to_numeric(sub["수출yoy"], errors="coerce"),
                                     name=str(pum)[:20], mode="lines", line=dict(width=2)))
        fig.update_yaxes(ticksuffix="%")
        yttl = "(YoY %)"
    fig.update_layout(template="plotly_white", height=300, margin=dict(l=44, r=20, t=8, b=28),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", hovermode="x unified",
                      legend=dict(orientation="h", y=-0.22, x=0.5, xanchor="center", font=dict(size=9, color=MUTE)),
                      font=dict(size=10, color="#556677"))
    fig.update_yaxes(gridcolor=ROWLN, tickfont=dict(size=9, color=MUTE), title=dict(text=yttl, font=dict(size=9, color=MUTE)))
    fig.update_xaxes(showgrid=False, tickfont=dict(size=9, color=MUTE))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _related(stock_code):
    rel = get_related_stocks_by_trade(stock_code)
    if rel is None or rel.empty:
        return
    from epsrev.data.dashboard_data import CO
    d = rel.copy()
    d["종합점수"] = d["종목코드"].map(lambda c: (CO.get(str(c).zfill(6)) or {}).get("total"))
    d = d.sort_values("최신월 수출yoy", ascending=False, na_position="last")
    disp = pd.DataFrame({
        "종목명": d["종목명"].values,
        "종목코드": d["종목코드"].values,
        "공유 품목": d["공유 품목명"].values,
        "최신월 YoY(%)": d["최신월 수출yoy"].values,
        "종합점수": [int(s) if pd.notna(pd.to_numeric(s, errors="coerce")) else "" for s in d["종합점수"].values],
    })
    st.markdown(f"<div style='font-size:0.82rem;font-weight:700;margin:10px 0 4px;color:{TXT}'>"
                f"🔗 관련 수출입 종목 <span style='font-size:0.68rem;color:#8a93a6;font-weight:400'>"
                f"(동일 품목 수출)</span></div>", unsafe_allow_html=True)
    st.dataframe(disp, hide_index=True, use_container_width=True)
