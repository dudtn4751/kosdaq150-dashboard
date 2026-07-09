"""epsrev/pages/5_trade_inspect.py — 수출입 데이터(외부 연계) 점검 페이지.

trade_link 로더가 읽는 stock_trade_map / trade_monthly / company_exports / meta를
개요·커버리지·검색·품목 시계열·품질 관점으로 점검하는 QA 도구.
"""
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from epsrev.ui.sidebar import render_sidebar
from epsrev.data.trade_link import (load_stock_trade_map, load_trade_monthly,
                                    load_company_exports, load_meta, base_url)
from epsrev.data.dashboard_data import CO, SECTORS

render_sidebar()

st.markdown("## 📦 수출입 데이터 점검")
st.caption(f"소스: {base_url()}")

smap = load_stock_trade_map()
monthly = load_trade_monthly()
comp = load_company_exports()
meta = load_meta()

if smap is None:
    st.error("수출입 데이터를 불러오지 못했습니다 — 소스 URL/네트워크/브랜치를 확인하세요.")
    st.stop()

smap = smap.copy()
smap["종목코드"] = smap["종목코드"].astype(str).str.zfill(6)

tabs = st.tabs(["개요·커버리지", "종목 매핑 검색", "품목(HS) 시계열", "기업 수출", "데이터 품질"])

# ── 개요·커버리지 ─────────────────────────────────────────────────────────────
with tabs[0]:
    if meta:
        rc = meta.get("row_counts", {})
        c = st.columns(4)
        c[0].metric("생성 시각", meta.get("generated_at", "—"))
        c[1].metric("데이터 기준", meta.get("data_through", "—"))
        c[2].metric("매핑 행(meta)", f"{rc.get('stock_trade_map', 0):,}")
        c[3].metric("월별 행(meta)", f"{rc.get('trade_monthly', 0):,}")

    st.markdown("**로드된 데이터 요약**")
    m = st.columns(4)
    m[0].metric("종목 수", smap["종목코드"].nunique())
    m[1].metric("HS 코드 수", smap["hs코드"].nunique())
    m[2].metric("월별 시계열", f"{len(monthly):,}" if monthly is not None else "—")
    m[3].metric("연월 범위",
                f"{monthly['연월'].min()}~{monthly['연월'].max()}" if monthly is not None else "—")

    uni = {CO[x["t"]]["t"] for sec in SECTORS for x in sec.get("cos", [])}
    mapped = set(smap["종목코드"])
    covered = uni & mapped
    st.markdown(f"**유니버스 커버리지 — {len(covered)}/{len(uni)}종목 매핑 "
                f"({len(covered) / len(uni) * 100:.0f}%)**")
    unmapped = sorted(uni - mapped)
    with st.expander(f"매핑 안 된 유니버스 종목 {len(unmapped)}개"):
        st.dataframe(pd.DataFrame(
            [{"종목코드": u, "종목명": CO[u]["n"], "섹터": CO[u].get("secName", "")} for u in unmapped]),
            hide_index=True, use_container_width=True)
    extra = sorted(mapped - uni)
    st.caption(f"※ 매핑엔 있으나 유니버스 밖 종목: {len(extra)}개")

    st.markdown("**카테고리별 종목 수**")
    cat = smap.groupby("카테고리")["종목코드"].nunique().sort_values(ascending=False)
    _fc = go.Figure(go.Bar(x=cat.index.tolist(), y=cat.values.tolist(), marker_color="#4f8bf9"))
    _fc.update_layout(height=300, template="plotly_white", margin=dict(l=40, r=20, t=8, b=90),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    _fc.update_xaxes(tickangle=-40, tickfont=dict(size=9))
    st.plotly_chart(_fc, use_container_width=True, config={"displayModeBar": False})

# ── 종목 매핑 검색 ─────────────────────────────────────────────────────────────
with tabs[1]:
    q = st.text_input("종목명 · 종목코드 검색", key="ti_q")
    fc1, fc2 = st.columns(2)
    with fc1:
        cats = ["(전체)"] + sorted(smap["카테고리"].dropna().unique())
        fc = st.selectbox("카테고리", cats)
    with fc2:
        fr = st.selectbox("관계유형", ["(전체)", "주력품목", "관련품목"])
    d = smap
    if q:
        d = d[d["종목명"].str.contains(q, na=False) | d["종목코드"].str.contains(q, na=False)]
    if fc != "(전체)":
        d = d[d["카테고리"] == fc]
    if fr != "(전체)":
        d = d[d["관계유형"] == fr]
    st.caption(f"{len(d)}행")
    st.dataframe(d, hide_index=True, use_container_width=True)

# ── 품목(HS) 시계열 ───────────────────────────────────────────────────────────
with tabs[2]:
    if monthly is None:
        st.info("월별 데이터가 없습니다.")
    else:
        pairs = smap[["hs코드", "품목명"]].drop_duplicates()
        hs_opts = {f"{r['품목명']} · {r['hs코드']}": str(r["hs코드"]) for _, r in pairs.iterrows()}
        pick = st.selectbox("품목(HS) 선택", list(hs_opts))
        hs = hs_opts[pick]
        sub = monthly[monthly["hs코드"].astype(str) == hs].sort_values("연월")
        if sub.empty:
            st.warning("이 HS의 월별 데이터가 없습니다.")
        else:
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(go.Bar(x=sub["연월"], y=pd.to_numeric(sub["수출금액_usd"], errors="coerce"),
                                 name="수출금액(USD)", marker_color="#4f8bf9"), secondary_y=False)
            fig.add_trace(go.Scatter(x=sub["연월"], y=pd.to_numeric(sub["수출yoy"], errors="coerce"),
                                     name="YoY(%)", line=dict(color="#f59e0b", width=2)), secondary_y=True)
            fig.update_layout(height=340, template="plotly_white", bargap=0.4,
                              margin=dict(l=50, r=40, t=10, b=30), hovermode="x unified",
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            fig.update_yaxes(tickformat="~s", secondary_y=False)
            fig.update_yaxes(ticksuffix="%", secondary_y=True)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            st.markdown("**이 품목 매핑 종목**")
            st.dataframe(smap[smap["hs코드"].astype(str) == hs][["종목명", "종목코드", "관계유형", "비고"]],
                         hide_index=True, use_container_width=True)
            with st.expander("월별 원자료"):
                st.dataframe(sub, hide_index=True, use_container_width=True)

# ── 기업 수출 ─────────────────────────────────────────────────────────────────
with tabs[3]:
    if comp is None:
        st.info("company_exports가 없습니다(선택 파일).")
    else:
        filled = comp["종목코드"].notna().mean() * 100
        cc = st.columns(3)
        cc[0].metric("행 수", f"{len(comp):,}")
        cc[1].metric("종목코드 채워짐", f"{filled:.1f}%")
        cc[2].metric("품목 수", comp["품목명"].nunique())
        st.caption("상위 500행")
        st.dataframe(comp.head(500), hide_index=True, use_container_width=True)

# ── 데이터 품질 ───────────────────────────────────────────────────────────────
with tabs[4]:
    map_hs = set(smap["hs코드"].astype(str))
    mon_hs = set(monthly["hs코드"].astype(str)) if monthly is not None else set()
    st.markdown(f"- 매핑엔 있으나 **월별데이터 없는 HS**: **{len(map_hs - mon_hs)}개**")
    st.markdown(f"- 월별데이터엔 있으나 **매핑 없는 HS**: **{len(mon_hs - map_hs)}개**")
    if monthly is not None:
        na = pd.to_numeric(monthly["수출yoy"], errors="coerce").isna().sum()
        st.markdown(f"- 수출YoY 결측: **{na:,}/{len(monthly):,}행** ({na / len(monthly) * 100:.1f}%)")
    miss = sorted(map_hs - mon_hs)
    if miss:
        with st.expander(f"월별데이터 없는 HS {len(miss)}개"):
            mp = smap[smap["hs코드"].astype(str).isin(miss)][["품목명", "hs코드", "종목명"]].drop_duplicates()
            st.dataframe(mp, hide_index=True, use_container_width=True)
    st.markdown("**종목당 매핑 품목 수 분포**")
    cnt = smap.groupby("종목코드").size().value_counts().sort_index()
    _fn = go.Figure(go.Bar(x=[f"{i}개" for i in cnt.index], y=cnt.values.tolist(), marker_color="#4f8bf9"))
    _fn.update_layout(height=260, template="plotly_white", margin=dict(l=40, r=20, t=8, b=30),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(_fn, use_container_width=True, config={"displayModeBar": False})
