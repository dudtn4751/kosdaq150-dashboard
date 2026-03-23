"""
코스닥 150 편입/편출 예측 분석 페이지
5개 섹션: 현재 구성종목 / 향후 예상 / 편입 원인 / 편출 원인 / 방법론
"""

import sys
import os

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_collector import collect_all
from selection_engine import predict_changes, build_eligible_stocks, select_kosdaq150
from style import COLORS, SECTOR_COLORS, PLOTLY_LAYOUT, styled_plotly


# ──────────────────────────────────────────────
# 데이터 수집 & 분석 (캐싱)
# ──────────────────────────────────────────────
@st.cache_data(show_spinner=False, ttl=3600)
def run_analysis(skip_daily: bool):
    import traceback as tb
    try:
        data = collect_all(skip_daily=skip_daily)
    except Exception as e:
        st.error(f"데이터 수집 중 오류: {e}\n\n{tb.format_exc()}")
        st.stop()

    kosdaq = data["kosdaq_listing"]
    gics_map = data["gics_map"]
    current_150 = data["current_150"]
    avg_data = data.get("avg_data")

    # 디버그 로그
    print(f"[DEBUG] kosdaq={len(kosdaq)}, gics={len(gics_map)}, current_150={len(current_150)}")

    eligible = build_eligible_stocks(kosdaq, gics_map, avg_data)
    eligible = eligible.sort_values("avg_marcap", ascending=False).reset_index(drop=True)
    eligible["전체순위"] = range(1, len(eligible) + 1)
    eligible["섹터내순위"] = eligible.groupby("sector")["avg_marcap"].rank(
        ascending=False, method="first"
    ).astype(int)
    sector_counts = eligible.groupby("sector")["code"].count().to_dict()
    eligible["섹터종목수"] = eligible["sector"].map(sector_counts)

    result = predict_changes(kosdaq, gics_map, current_150, avg_data)

    current_details = []
    for code in current_150:
        info = kosdaq[kosdaq["code"] == code]
        e_row = eligible[eligible["code"] == code]
        if info.empty:
            continue
        r = info.iloc[0]
        sector = gics_map.get(code, "미분류")
        sector_total = int(e_row.iloc[0]["섹터종목수"]) if not e_row.empty else 0
        current_details.append({
            "종목코드": code, "종목명": r["name"],
            "섹터": sector,
            "시가총액": r["marcap"], "거래대금": r["amount"],
            "전체순위": int(e_row.iloc[0]["전체순위"]) if not e_row.empty else 0,
            "섹터내순위": int(e_row.iloc[0]["섹터내순위"]) if not e_row.empty else 0,
            "섹터종목수": sector_total,
        })
    current_df = pd.DataFrame(current_details)
    if not current_df.empty:
        current_df = current_df.sort_values("시가총액", ascending=False)

    predicted_details = []
    for code in result["new_selected"]:
        info = kosdaq[kosdaq["code"] == code]
        e_row = eligible[eligible["code"] == code]
        if info.empty:
            continue
        r = info.iloc[0]
        status = "유지" if code in set(current_150) else "신규편입"
        sector = gics_map.get(code, "미분류")
        sector_total = int(e_row.iloc[0]["섹터종목수"]) if not e_row.empty else 0
        predicted_details.append({
            "종목코드": code, "종목명": r["name"],
            "섹터": sector,
            "시가총액": r["marcap"], "거래대금": r["amount"],
            "전체순위": int(e_row.iloc[0]["전체순위"]) if not e_row.empty else 0,
            "섹터내순위": int(e_row.iloc[0]["섹터내순위"]) if not e_row.empty else 0,
            "섹터종목수": sector_total,
            "상태": status,
        })
    predicted_df = pd.DataFrame(predicted_details)
    if not predicted_df.empty:
        predicted_df = predicted_df.sort_values("시가총액", ascending=False)

    return {
        "kosdaq": kosdaq, "gics_map": gics_map,
        "current_150": current_150, "current_df": current_df,
        "predicted_df": predicted_df, "eligible": eligible,
        "result": result,
    }


# ──────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────
def fmt_억(v):
    if v >= 1e12:
        return f"{v/1e12:.2f}조"
    return f"{v/1e8:,.0f}억"


def section_header(text):
    st.markdown(f'<div class="section-header">{text}</div>', unsafe_allow_html=True)
    st.markdown("")


def _hex_to_rgb(hex_color):
    """#RRGGBB → 'R,G,B' 문자열 변환"""
    h = hex_color.lstrip("#")
    return ",".join(str(int(h[i:i+2], 16)) for i in (0, 2, 4))


def get_sector_color_list(sectors):
    return [SECTOR_COLORS.get(s, "#636EFA") for s in sectors]


# ──────────────────────────────────────────────
# 사이드바
# ──────────────────────────────────────────────
st.sidebar.markdown("### ⚙️ 분석 설정")
st.sidebar.markdown("")

mode = st.sidebar.radio(
    "분석 모드",
    ["빠른 분석 (당일 스냅샷)", "정밀 분석 (6개월 평균)"],
    index=0,
)
skip_daily = mode.startswith("빠른")

st.sidebar.markdown("")
run_button = st.sidebar.button("분석 실행", type="primary", use_container_width=True)

st.sidebar.markdown("---")
st.sidebar.markdown(
    f"""
    <div style="color: {COLORS['text_muted']}; font-size: 0.82rem; line-height: 1.8;">
    <strong>KRX 방법론 기반</strong> 코스닥 150<br>
    구성종목 편입/편출 예측 시스템<br><br>
    <strong>빠른 분석</strong> — 당일 시가총액/거래대금<br>
    <strong>정밀 분석</strong> — 6개월 일평균 (시간 소요)
    </div>
    """,
    unsafe_allow_html=True,
)


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
st.markdown("""
<div class="ark-hero" style="padding: 32px 36px;">
    <h1 style="font-size: 1.9rem;">📊 코스닥 150 분석</h1>
    <p class="subtitle">KRX 방법론 기반 편입/편출 예측 시스템</p>
</div>
""", unsafe_allow_html=True)

if run_button or "kosdaq150_analysis" in st.session_state:
    if run_button:
        with st.spinner("데이터 수집 및 분석 중... (최초 실행 시 1~2분 소요)"):
            st.session_state["kosdaq150_analysis"] = run_analysis(skip_daily)

    a = st.session_state["kosdaq150_analysis"]
    result = a["result"]
    current_df = a["current_df"]
    predicted_df = a["predicted_df"]
    eligible = a["eligible"]
    current_150 = a["current_150"]
    gics_map = a["gics_map"]

    if not current_150:
        st.error("현재 코스닥 150 구성종목을 가져오지 못했습니다. 잠시 후 다시 시도해주세요.")
        st.stop()

    if current_df.empty or predicted_df.empty:
        st.error("데이터 분석 중 오류가 발생했습니다. GICS 분류 데이터를 가져오지 못했을 수 있습니다. 잠시 후 다시 시도해주세요.")
        st.stop()

    # ── 상단 메트릭 ──
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("현재 구성종목", f"{len(current_150)}종목")
    c2.metric("유지", f"{result['retained']}종목")
    c3.metric("신규 편입 예상", f"{len(result['additions'])}종목",
              delta=f"+{len(result['additions'])}")
    c4.metric("편출 예상", f"{len(result['removals'])}종목",
              delta=f"-{len(result['removals'])}", delta_color="inverse")

    st.markdown("")

    # ══════════════════════════════════════════
    # 5개 탭
    # ══════════════════════════════════════════
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "  현재 구성 종목  ",
        "  향후 예상 구성 종목  ",
        "  신규 편입 원인 분석  ",
        "  신규 편출 원인 분석  ",
        "  분석 기준 (방법론)  ",
    ])

    # ──────────────────────────────────────
    # 탭 1: 현재 구성 종목
    # ──────────────────────────────────────
    with tab1:
        section_header("현재 코스닥 150 구성종목")
        st.caption("investing.com 기준 현재 코스닥 150 지수 편입 종목입니다.")

        cur_sector = current_df.groupby("섹터").agg(
            종목수=("종목코드", "count"),
            시가총액합=("시가총액", "sum"),
        ).sort_values("시가총액합", ascending=False).reset_index()
        cur_sector["시가총액(조)"] = (cur_sector["시가총액합"] / 1e12).round(1)

        col_pie, col_bar = st.columns([1, 1])
        with col_pie:
            fig = px.pie(
                cur_sector, values="종목수", names="섹터",
                title="섹터별 종목 수 비중", hole=0.45, height=420,
                color="섹터", color_discrete_map=SECTOR_COLORS,
            )
            fig.update_traces(
                textposition="inside", textinfo="label+percent",
                textfont_size=11,
            )
            st.plotly_chart(styled_plotly(fig), use_container_width=True)

        with col_bar:
            sorted_sec = cur_sector.sort_values("시가총액(조)", ascending=True)
            fig = go.Figure(go.Bar(
                x=sorted_sec["시가총액(조)"], y=sorted_sec["섹터"],
                orientation="h",
                marker=dict(
                    color=get_sector_color_list(sorted_sec["섹터"]),
                    line=dict(width=0),
                ),
                text=sorted_sec["시가총액(조)"].apply(lambda x: f"{x}조"),
                textposition="outside",
                textfont=dict(color=COLORS["text_muted"], size=11),
            ))
            fig.update_layout(title="섹터별 시가총액 (조원)")
            st.plotly_chart(styled_plotly(fig, 420), use_container_width=True)

        # 트리맵
        tree_df = current_df.head(30).copy()
        tree_df["시가총액(억)"] = (tree_df["시가총액"] / 1e8).round(0).astype(int)
        tree_df["라벨"] = tree_df["종목명"] + "<br>" + tree_df["시가총액(억)"].apply(lambda x: f"{x:,}억")
        fig_tree = px.treemap(
            tree_df, path=["섹터", "라벨"], values="시가총액(억)",
            color="섹터", color_discrete_map=SECTOR_COLORS,
            title="시가총액 Top 30 트리맵",
        )
        fig_tree.update_traces(
            marker=dict(
                line=dict(color="#0E1117", width=2),
                cornerradius=4,
            ),
            textfont=dict(color="white", size=13, family="sans-serif"),
            textposition="middle center",
        )
        # 섹터(부모) 레벨 스타일
        fig_tree.update_layout(
            treemapcolorway=[
                "#1A6FB5", "#C0392B", "#1ABC9C", "#8E44AD", "#E67E22",
                "#2EC4D6", "#E84393", "#A3CB38", "#D35400", "#F9CA24", "#6C8EAD",
            ],
        )
        st.plotly_chart(styled_plotly(fig_tree, 560), use_container_width=True)

        # 종목 테이블
        section_header("전체 종목 리스트")
        all_sectors = ["전체"] + sorted(current_df["섹터"].unique().tolist())
        sel_sector = st.selectbox("섹터 필터", all_sectors, key="tab1_sector")

        show_df = current_df.copy()
        if sel_sector != "전체":
            show_df = show_df[show_df["섹터"] == sel_sector]

        show_df["시가총액(억)"] = (show_df["시가총액"] / 1e8).round(0).astype(int)
        show_df["거래대금(억)"] = (show_df["거래대금"] / 1e8).round(0).astype(int)
        show_df["섹터내순위(전체)"] = show_df.apply(
            lambda r: f"{r['섹터내순위']}위 / {r['섹터종목수']}종목", axis=1)
        show_df.index = range(1, len(show_df) + 1)
        st.dataframe(
            show_df[["종목코드", "종목명", "섹터", "시가총액(억)", "거래대금(억)",
                      "전체순위", "섹터내순위(전체)"]],
            use_container_width=True, height=600,
        )

    # ──────────────────────────────────────
    # 탭 2: 향후 예상 구성 종목
    # ──────────────────────────────────────
    with tab2:
        section_header("향후 예상 코스닥 150 구성종목")
        st.caption("KRX 방법론 시뮬레이션 기반 예측 결과입니다.")

        status_count = predicted_df["상태"].value_counts()
        col_m1, col_m2 = st.columns(2)
        col_m1.metric("유지 종목", f"{status_count.get('유지', 0)}종목")
        col_m2.metric("신규 편입", f"{status_count.get('신규편입', 0)}종목")

        st.markdown("")
        section_header("섹터별 구성 변동")

        cur_sec = current_df.groupby("섹터")["종목코드"].count().rename("현재")
        pred_sec = predicted_df.groupby("섹터")["종목코드"].count().rename("예상")
        compare = pd.concat([cur_sec, pred_sec], axis=1).fillna(0).astype(int)
        compare["변동"] = compare["예상"] - compare["현재"]
        compare = compare.sort_values("예상", ascending=False).reset_index()
        compare.columns = ["섹터", "현재", "예상", "변동"]

        fig_compare = go.Figure()
        fig_compare.add_trace(go.Bar(
            x=compare["섹터"], y=compare["현재"],
            name="현재", marker_color="rgba(99, 110, 250, 0.5)",
            marker_line=dict(color="rgba(99, 110, 250, 0.8)", width=1),
        ))
        fig_compare.add_trace(go.Bar(
            x=compare["섹터"], y=compare["예상"],
            name="예상", marker_color=COLORS["accent"],
            marker_line=dict(color=COLORS["accent"], width=1),
        ))
        fig_compare.update_layout(
            barmode="group", title="섹터별 종목 수 (현재 vs 예상)",
        )
        st.plotly_chart(styled_plotly(fig_compare, 420), use_container_width=True)

        st.dataframe(compare, use_container_width=True)

        st.markdown("")
        section_header("예상 구성종목 전체 리스트")

        p_show = predicted_df.copy()
        p_show["시가총액(억)"] = (p_show["시가총액"] / 1e8).round(0).astype(int)
        p_show["거래대금(억)"] = (p_show["거래대금"] / 1e8).round(0).astype(int)
        p_show["섹터내순위(전체)"] = p_show.apply(
            lambda r: f"{r['섹터내순위']}위 / {r['섹터종목수']}종목", axis=1)
        p_show.index = range(1, len(p_show) + 1)

        def highlight_new(row):
            if row["상태"] == "신규편입":
                return [
                    "background-color: rgba(0, 210, 255, 0.15); "
                    "color: #00D2FF; font-weight: 600"
                ] * len(row)
            return [""] * len(row)

        st.dataframe(
            p_show[["종목코드", "종목명", "섹터", "시가총액(억)", "거래대금(억)",
                     "전체순위", "섹터내순위(전체)", "상태"]].style.apply(highlight_new, axis=1),
            use_container_width=True, height=600,
        )

    # ──────────────────────────────────────
    # 탭 3: 신규 편입 원인 분석
    # ──────────────────────────────────────
    with tab3:
        section_header("신규 편입 예상 종목 원인 분석")
        st.caption("왜 이 종목들이 새로 편입될 것으로 예상되는지 분석합니다.")

        additions = result["additions"]
        if not additions:
            st.info("신규 편입 예상 종목이 없습니다.")
        else:
            add_details = []
            current_set = set(current_150)
            for s in additions:
                code = s["code"]
                e_row = eligible[eligible["code"] == code]
                if e_row.empty:
                    continue
                er = e_row.iloc[0]
                sector = s["sector"]
                sector_current = [c for c in current_set if gics_map.get(c) == sector]
                n_sector_current = len(sector_current)
                new_threshold = max(int(n_sector_current * 0.8), 1)

                reasons = []
                overall_rank = int(er["전체순위"])
                sector_rank = int(er["섹터내순위"])

                if overall_rank <= 50:
                    reasons.append(f"코스닥 전체 시가총액 {overall_rank}위 (대형주 특례)")
                if sector_rank <= new_threshold:
                    reasons.append(f"섹터 내 시총 {sector_rank}위 (신규편입 기준 {new_threshold}위 이내 충족)")
                if not reasons:
                    reasons.append("3차 선정에서 잔여 종목 중 시총 상위로 150종목 충원")

                add_details.append({
                    "종목코드": code, "종목명": s["name"], "섹터": sector,
                    "시가총액": s["marcap"], "전체순위": overall_rank,
                    "섹터내순위": sector_rank, "섹터기존종목수": n_sector_current,
                    "신규편입기준": f"{new_threshold}위 이내",
                    "편입사유": " / ".join(reasons),
                })

            add_detail_df = pd.DataFrame(add_details)

            col_a1, col_a2 = st.columns([1, 1])
            with col_a1:
                top20 = add_detail_df.sort_values("시가총액", ascending=False).head(20)
                fig = go.Figure(go.Bar(
                    x=top20["전체순위"], y=top20["종목명"],
                    orientation="h",
                    marker=dict(
                        color=get_sector_color_list(top20["섹터"]),
                        line=dict(width=0),
                    ),
                    text=top20["전체순위"].apply(lambda x: f"{x}위"),
                    textposition="outside",
                    textfont=dict(color=COLORS["text_muted"], size=10),
                ))
                fig.update_layout(
                    title="편입 예상 종목 전체 시총 순위 TOP 20",
                    xaxis_title="전체 시총 순위 (낮을수록 상위)",
                    yaxis=dict(autorange="reversed"),
                )
                st.plotly_chart(styled_plotly(fig, 500), use_container_width=True)

            with col_a2:
                sec_add = add_detail_df.groupby("섹터")["종목코드"].count().reset_index()
                sec_add.columns = ["섹터", "편입종목수"]
                sec_add = sec_add.sort_values("편입종목수", ascending=True)
                fig = go.Figure(go.Bar(
                    x=sec_add["편입종목수"], y=sec_add["섹터"],
                    orientation="h",
                    marker=dict(
                        color=COLORS["accent_green"],
                        line=dict(width=0),
                    ),
                    text=sec_add["편입종목수"],
                    textposition="outside",
                    textfont=dict(color=COLORS["text_muted"], size=11),
                ))
                fig.update_layout(title="섹터별 신규 편입 종목 수")
                st.plotly_chart(styled_plotly(fig, 500), use_container_width=True)

            section_header("종목별 편입 사유 상세")
            show_add = add_detail_df.copy()
            show_add["시가총액(억)"] = (show_add["시가총액"] / 1e8).round(0).astype(int)
            show_add.index = range(1, len(show_add) + 1)
            st.dataframe(
                show_add[["종목코드", "종목명", "섹터", "시가총액(억)",
                           "전체순위", "섹터내순위", "섹터기존종목수",
                           "신규편입기준", "편입사유"]],
                use_container_width=True, height=500,
            )

            st.markdown("")
            section_header("주요 편입 종목 상세")
            for i, row in add_detail_df.head(10).iterrows():
                with st.expander(
                    f"**{row['종목명']}** ({row['종목코드']}) — "
                    f"{fmt_억(row['시가총액'])} · {row['섹터']}"
                ):
                    cc1, cc2, cc3 = st.columns(3)
                    cc1.metric("전체 시총 순위", f"{row['전체순위']}위")
                    cc2.metric("섹터 내 순위", f"{row['섹터내순위']}위 / {row['섹터기존종목수']}종목")
                    cc3.metric("신규편입 기준", row["신규편입기준"])
                    st.markdown(f"**편입 사유:** {row['편입사유']}")

    # ──────────────────────────────────────
    # 탭 4: 신규 편출 원인 분석
    # ──────────────────────────────────────
    with tab4:
        section_header("신규 편출 예상 종목 원인 분석")
        st.caption("왜 이 종목들이 편출될 것으로 예상되는지 분석합니다.")

        removals = result["removals"]
        if not removals:
            st.info("편출 예상 종목이 없습니다.")
        else:
            rem_details = []
            current_set = set(current_150)
            for s in removals:
                code = s["code"]
                e_row = eligible[eligible["code"] == code]
                sector = s["sector"]
                sector_current = [c for c in current_set if gics_map.get(c) == sector]
                n_sector_current = len(sector_current)
                keep_threshold = max(int(n_sector_current * 1.2), 1)

                overall_rank = int(e_row.iloc[0]["전체순위"]) if not e_row.empty else 9999
                sector_rank = int(e_row.iloc[0]["섹터내순위"]) if not e_row.empty else 9999

                sector_eligible = eligible[eligible["sector"] == sector]
                sector_total = len(sector_eligible)
                liquidity_threshold = max(int(sector_total * 0.8), 1)
                amount_rank_in_sector = int(
                    sector_eligible.sort_values("avg_amount", ascending=False)
                    .reset_index(drop=True)
                    .index[sector_eligible.sort_values("avg_amount", ascending=False)
                           ["code"] == code]
                    .values[0] + 1
                ) if not e_row.empty else 9999
                liquidity_ok = amount_rank_in_sector <= liquidity_threshold

                reasons = []
                if sector_rank > keep_threshold:
                    reasons.append(f"섹터 내 시총 {sector_rank}위 (기존유지 기준 {keep_threshold}위 이내 미충족)")
                if not liquidity_ok:
                    reasons.append(f"유동성 미달 — 섹터 내 거래대금 {amount_rank_in_sector}위 (기준 {liquidity_threshold}위 이내)")
                if overall_rank > 300:
                    reasons.append(f"전체 시총 {overall_rank}위 (소형주 제외 기준 300위 초과)")
                if not reasons:
                    reasons.append("150종목 충원 과정에서 시총 하위로 밀려남")

                rem_details.append({
                    "종목코드": code, "종목명": s["name"], "섹터": sector,
                    "시가총액": s["marcap"], "전체순위": overall_rank,
                    "섹터내순위": sector_rank, "섹터기존종목수": n_sector_current,
                    "기존유지기준": f"{keep_threshold}위 이내",
                    "유동성충족": "충족" if liquidity_ok else "미달",
                    "편출사유": " / ".join(reasons),
                })

            rem_detail_df = pd.DataFrame(rem_details)

            col_r1, col_r2 = st.columns([1, 1])
            with col_r1:
                fig = go.Figure(go.Bar(
                    x=rem_detail_df["전체순위"],
                    y=rem_detail_df["종목명"],
                    orientation="h",
                    marker=dict(
                        color=get_sector_color_list(rem_detail_df["섹터"]),
                        line=dict(width=0),
                    ),
                    text=rem_detail_df["전체순위"].apply(lambda x: f"{x}위"),
                    textposition="outside",
                    textfont=dict(color=COLORS["text_muted"], size=10),
                ))
                fig.update_layout(
                    title="편출 예상 종목의 전체 시총 순위",
                    xaxis_title="전체 시총 순위",
                    yaxis=dict(autorange="reversed"),
                )
                st.plotly_chart(styled_plotly(fig, 500), use_container_width=True)

            with col_r2:
                sec_rem = rem_detail_df.groupby("섹터")["종목코드"].count().reset_index()
                sec_rem.columns = ["섹터", "편출종목수"]
                sec_rem = sec_rem.sort_values("편출종목수", ascending=True)
                fig = go.Figure(go.Bar(
                    x=sec_rem["편출종목수"], y=sec_rem["섹터"],
                    orientation="h",
                    marker=dict(color=COLORS["accent_red"], line=dict(width=0)),
                    text=sec_rem["편출종목수"],
                    textposition="outside",
                    textfont=dict(color=COLORS["text_muted"], size=11),
                ))
                fig.update_layout(title="섹터별 편출 종목 수")
                st.plotly_chart(styled_plotly(fig, 500), use_container_width=True)

            # 편출 사유 분류
            section_header("편출 사유 분류")
            reason_cats = {"시총순위 하락": 0, "유동성 미달": 0, "소형주 제외": 0, "기타": 0}
            for _, row in rem_detail_df.iterrows():
                reason = row["편출사유"]
                if "미충족" in reason:
                    reason_cats["시총순위 하락"] += 1
                if "유동성" in reason:
                    reason_cats["유동성 미달"] += 1
                if "소형주" in reason:
                    reason_cats["소형주 제외"] += 1
                if "밀려남" in reason:
                    reason_cats["기타"] += 1

            reason_df = pd.DataFrame(
                [{"사유": k, "종목수": v} for k, v in reason_cats.items() if v > 0]
            )
            if not reason_df.empty:
                reason_colors = {
                    "시총순위 하락": COLORS["accent_red"],
                    "유동성 미달": COLORS["accent_yellow"],
                    "소형주 제외": "#AB63FA",
                    "기타": COLORS["text_muted"],
                }
                fig = px.pie(
                    reason_df, values="종목수", names="사유",
                    title="편출 사유 비중", hole=0.45, height=380,
                    color="사유",
                    color_discrete_map=reason_colors,
                )
                fig.update_traces(textposition="inside", textinfo="label+value",
                                  textfont_size=12)
                st.plotly_chart(styled_plotly(fig), use_container_width=True)

            section_header("종목별 편출 사유 상세")
            show_rem = rem_detail_df.copy()
            show_rem["시가총액(억)"] = (show_rem["시가총액"] / 1e8).round(0).astype(int)
            show_rem.index = range(1, len(show_rem) + 1)
            st.dataframe(
                show_rem[["종목코드", "종목명", "섹터", "시가총액(억)",
                           "전체순위", "섹터내순위", "섹터기존종목수",
                           "기존유지기준", "유동성충족", "편출사유"]],
                use_container_width=True, height=500,
            )

            st.markdown("")
            section_header("주요 편출 종목 상세")
            for i, row in rem_detail_df.head(10).iterrows():
                with st.expander(
                    f"**{row['종목명']}** ({row['종목코드']}) — "
                    f"{fmt_억(row['시가총액'])} · {row['섹터']}"
                ):
                    cc1, cc2, cc3 = st.columns(3)
                    cc1.metric("전체 시총 순위", f"{row['전체순위']}위")
                    cc2.metric("섹터 내 순위", f"{row['섹터내순위']}위 / {row['섹터기존종목수']}종목")
                    cc3.metric("유동성", row["유동성충족"])
                    st.markdown(f"**편출 사유:** {row['편출사유']}")

    # ──────────────────────────────────────
    # 탭 5: 분석 기준 (방법론)
    # ──────────────────────────────────────
    with tab5:
        section_header("분석 기준 (KRX 코스닥 150 지수 방법론)")

        TC = COLORS["text"]       # 밝은 텍스트
        TM = COLORS["text_muted"] # 보조 텍스트
        AC = COLORS["accent"]     # 악센트 시안
        BD = COLORS["border"]     # 테두리
        BG = COLORS["bg_card"]    # 카드 배경

        def method_card(title, body):
            st.markdown(f"""
            <div style="background:{BG}; border:1px solid {BD}; border-radius:12px;
                        padding:28px 32px; margin-bottom:24px;">
                <h4 style="color:{AC}; margin:0 0 16px 0; font-size:1.15rem;">{title}</h4>
                <div style="color:{TC}; font-size:0.95rem; line-height:1.85;">{body}</div>
            </div>
            """, unsafe_allow_html=True)

        def method_table(headers, rows):
            hdr = "".join(f'<th style="background:#1A2744; color:{AC}; padding:10px 14px; text-align:left; font-weight:600; border-bottom:2px solid {BD};">{h}</th>' for h in headers)
            body = ""
            for row in rows:
                cells = "".join(f'<td style="padding:10px 14px; color:{TC}; border-bottom:1px solid {BD};">{c}</td>' for c in row)
                body += f"<tr>{cells}</tr>"
            return f'<table style="width:100%; border-collapse:collapse; margin:12px 0;"><thead><tr>{hdr}</tr></thead><tbody>{body}</tbody></table>'

        # ── 1. 지수 개요 ──
        method_card("1. 지수 개요", method_table(
            ["항목", "내용"],
            [
                ["지수명", "코스닥 150 (KOSDAQ 150)"],
                ["산출기관", "한국거래소 (KRX)"],
                ["기산일", "2010년 1월 4일 (기준지수 1,000p)"],
                ["산출방식", "유동시가총액 가중방식 (Free-float Market Cap Weighted)"],
                ["구성종목 수", "<strong>150종목</strong> (코스닥 대표 우량주)"],
                ["목적", "코스닥 시장 벤치마크 지수, ETF·파생상품 기초자산"],
                ["관련 ETF", "KODEX 코스닥150, TIGER 코스닥150, KBSTAR 코스닥150 등"],
            ]
        ))

        # ── 2. 리밸런싱 ──
        method_card("2. 정기변경 (리밸런싱) 일정",
            f"""<p>코스닥 150 지수는 <strong style="color:{AC};">연 1회</strong> 정기적으로 구성종목을 변경합니다.</p>"""
            + method_table(
                ["항목", "내용"],
                [
                    ["정기변경 주기", "연 1회 (매년 6월)"],
                    ["심사기준일", "매년 <strong>5월 마지막 영업일</strong>"],
                    ["변경 적용일", "매년 <strong>6월 두 번째 목요일의 익영업일</strong>"],
                    ["심사 데이터 기간", "심사기준일 직전 <strong>6개월</strong> (약 120거래일)"],
                    ["사전 공시", "변경 적용일로부터 약 <strong>2주 전</strong> KRX 공시"],
                ]
            )
            + f"""
            <div style="margin-top:16px; padding:12px 16px; background:rgba(0,210,255,0.08); border-left:3px solid {AC}; border-radius:6px;">
                <strong style="color:{AC};">수시변경 (특별 편출)</strong><br>
                <span style="color:{TM};">상장폐지, 관리종목 지정, 기업분할 등의 사유 발생 시 수시 편출<br>
                수시 편출 시 대체 종목은 차순위 종목으로 즉시 편입</span>
            </div>
            """
        )

        st.info("2026년 정기변경 예상 일정: 심사기준일 2026년 5월 29일(금) / 변경 적용일 2026년 6월 12일(금) 전후")

        # ── 3. 심사대상 ──
        method_card("3. 심사대상종목 구성",
            f"<p>코스닥 시장에 상장된 <strong>보통주 전체</strong>가 심사 대상이며, 다음 종목은 제외됩니다.</p>"
            + method_table(
                ["제외 사유", "상세 기준"],
                [
                    ["관리종목", "심사기준일 현재 관리종목으로 지정된 종목"],
                    ["정리매매종목", "상장폐지가 결정되어 정리매매 중인 종목"],
                    ["SPAC", "기업인수목적회사 (Special Purpose Acquisition Company)"],
                    ["유동주식비율 미달", "유동주식비율이 <strong>10% 미만</strong>인 종목"],
                    ["상장일수 부족", "심사기준일 기준 상장 후 <strong>6개월 미만</strong> 경과 종목"],
                    ["거래정지", "심사기준일 현재 매매거래가 정지된 종목"],
                    ["투자유의", "투자유의종목으로 지정된 종목"],
                ]
            )
        )

        # ── 4. GICS ──
        method_card("4. GICS 산업군 분류", method_table(
            ["GICS 코드", "산업군", "영문명", "대표 업종 예시"],
            [
                ["G10", "에너지", "Energy", "석유·가스, 에너지장비"],
                ["G15", "소재", "Materials", "화학, 금속, 2차전지소재"],
                ["G20", "산업재", "Industrials", "기계, 건설, 로봇, 방산"],
                ["G25", "자유소비재", "Consumer Disc.", "자동차, 의류, 미디어"],
                ["G30", "필수소비재", "Consumer Staples", "식품, 음료, 가정용품"],
                ["G35", "헬스케어", "Health Care", "제약, 바이오, 의료기기"],
                ["G40", "금융", "Financials", "은행, 보험, 증권, 캐피탈"],
                ["G45", "정보기술", "Info. Technology", "반도체, 소프트웨어, IT서비스"],
                ["G50", "커뮤니케이션", "Comm. Services", "통신, 게임, 엔터"],
                ["G55", "유틸리티", "Utilities", "전력, 가스, 수도"],
                ["G60", "부동산", "Real Estate", "REITs, 부동산개발"],
            ]
        ) + f'<p style="color:{TM}; margin-top:8px; font-size:0.85rem;">※ 산업군 시가총액이 코스닥 전체의 1% 미만인 경우 해당 산업군은 선정에서 제외됩니다.</p>')

        # ── 5. 선정 절차 ──
        def step_box(step_num, title, color, content):
            return f"""
            <div style="background:{BG}; border:1px solid {BD}; border-left:4px solid {color};
                        border-radius:0 12px 12px 0; padding:20px 24px; margin-bottom:16px;">
                <div style="color:{color}; font-weight:700; font-size:0.85rem; margin-bottom:6px;">STEP {step_num}</div>
                <div style="color:{TC}; font-weight:600; font-size:1.05rem; margin-bottom:12px;">{title}</div>
                <div style="color:{TM}; font-size:0.92rem; line-height:1.8;">{content}</div>
            </div>"""

        method_card("5. 구성종목 선정 절차",
            f'<p style="color:{TM}; margin-bottom:20px;">선정은 <strong style="color:{TC};">3단계</strong>로 진행되며, 이후 특례/제외 규정이 적용됩니다.</p>'
            + step_box("01", "1차 선정 — 산업군별 핵심 종목", "#636EFA",
                f"""• 산업군 내 <strong style="color:{TC};">일평균시가총액</strong> 순으로 정렬<br>
                • 상위 종목부터 누적하여 산업군 총 시가총액의 <strong style="color:{AC};">60%</strong> 도달 시까지 선정<br>
                • <strong style="color:{TC};">유동성 기준:</strong> 산업군 내 거래대금 순위가 전체 종목수의 상위 <strong style="color:{AC};">80%</strong> 이내""")
            + step_box("02", "2차 선정 — 기존 종목 버퍼링", "#00E396",
                f"""• <strong style="color:{TC};">기존 종목 유지:</strong> 섹터 내 시총 순위 ≤ 기존 종목수 × <strong style="color:{AC};">120%</strong> (완화)<br>
                • <strong style="color:{TC};">신규 종목 편입:</strong> 섹터 내 시총 순위 ≤ 기존 종목수 × <strong style="color:{AC};">80%</strong> (엄격)<br>
                • 비대칭 버퍼로 매년 교체 종목 수를 제한 (보통 10~30종목)""")
            + step_box("03", "3차 선정 — 150종목 맞추기", "#FEB019",
                f"""• <strong style="color:{TC};">미달 시:</strong> 미선정 종목 중 시총 상위 순으로 추가 (유동성 충족 필요)<br>
                • <strong style="color:{TC};">초과 시:</strong> 선정 종목 중 시총 최하위 종목부터 제외""")
        )

        # ── 6. 특례/제외 ──
        method_card("6. 특례 및 제외 규정",
            f"""
            <div style="display:flex; gap:16px; flex-wrap:wrap;">
                <div style="flex:1; min-width:250px; background:rgba(0,227,150,0.08); border:1px solid rgba(0,227,150,0.3);
                            border-radius:10px; padding:18px;">
                    <div style="color:{COLORS['accent_green']}; font-weight:700; margin-bottom:8px;">대형주 특례 (6.4.4)</div>
                    <div style="color:{TM}; font-size:0.9rem; line-height:1.7;">
                        코스닥 전체 시총 <strong style="color:{TC};">상위 50위</strong> 이내 종목<br>
                        산업군 무관 <strong style="color:{TC};">무조건 편입</strong> 가능<br>
                        기존 선정 종목 중 시총 최하위 대체
                    </div>
                </div>
                <div style="flex:1; min-width:250px; background:rgba(255,69,96,0.08); border:1px solid rgba(255,69,96,0.3);
                            border-radius:10px; padding:18px;">
                    <div style="color:{COLORS['accent_red']}; font-weight:700; margin-bottom:8px;">소형주 제외 (6.4.5)</div>
                    <div style="color:{TM}; font-size:0.9rem; line-height:1.7;">
                        코스닥 전체 시총 <strong style="color:{TC};">300위 밖</strong> 종목<br>
                        선정되어도 <strong style="color:{TC};">강제 제외</strong> 처리<br>
                        유동성 충족 잔여 종목 중 시총 최상위로 대체
                    </div>
                </div>
            </div>
            """ + "<div style='margin-top:20px;'>" + method_table(
                ["구분", "산출 기준"],
                [
                    ["일평균시가총액", "심사기간(6개월) 각 거래일의 종가 × 상장주식수의 산술평균"],
                    ["일평균거래대금", "심사기간(6개월) 각 거래일의 거래대금의 산술평균"],
                    ["유동시가총액", "일평균시가총액 × 유동주식비율 (지수 산출 시)"],
                ]
            ) + "</div>"
        )

        # ── 7. 흐름도 ──
        def flow_node(num, title, desc, color, is_start=False, is_end=False):
            """흐름도 단계 노드"""
            if is_start:
                bg = f"linear-gradient(135deg, #1A2744 0%, #1E3050 100%)"
                border = f"2px solid {AC}"
                radius = "14px"
                num_badge = ""
            elif is_end:
                bg = f"linear-gradient(135deg, #0D4A8B 0%, #0984e3 100%)"
                border = f"2px solid {AC}"
                radius = "14px"
                num_badge = ""
            else:
                bg = f"linear-gradient(135deg, rgba({_hex_to_rgb(color)},0.08) 0%, rgba({_hex_to_rgb(color)},0.03) 100%)"
                border = f"2px solid {color}"
                radius = "12px"
                num_badge = f'<span style="display:inline-block; background:{color}; color:#fff; font-size:0.7rem; font-weight:700; padding:2px 10px; border-radius:20px; margin-bottom:8px;">{num}</span><br>'

            return f"""
            <div style="background:{bg}; border:{border}; border-radius:{radius};
                        padding:18px 32px; text-align:center; width:100%; max-width:480px;">
                {num_badge}
                <div style="color:{'#FFFFFF' if is_end else TC}; font-weight:{'800' if is_end else '700'}; font-size:{'1.15rem' if is_end else '1rem'}; margin-bottom:4px;">{title}</div>
                <div style="color:{'rgba(255,255,255,0.7)' if is_end else TM}; font-size:0.84rem; line-height:1.5;">{desc}</div>
            </div>"""

        def flow_arrow(color=None):
            c = color or AC
            return f"""
            <div style="display:flex; flex-direction:column; align-items:center; margin:2px 0;">
                <div style="width:2px; height:16px; background:{c};"></div>
                <div style="width:0; height:0; border-left:8px solid transparent; border-right:8px solid transparent; border-top:10px solid {c};"></div>
            </div>"""

        st.markdown(f"""
        <div style="background:{BG}; border:1px solid {BD}; border-radius:12px;
                    padding:32px; margin-bottom:24px;">
            <h4 style="color:{AC}; margin:0 0 24px 0; font-size:1.15rem;">7. 선정 절차 흐름도</h4>
            <div style="display:flex; flex-direction:column; align-items:center; gap:0;">
                {flow_node("", "코스닥 시장 전체 종목", "약 1,800개 보통주", AC, is_start=True)}
                {flow_arrow()}
                {flow_node("사전 필터", "부적격 종목 제외", "관리종목 · SPAC · 유동주식비율 10% 미만 · 상장 6개월 미만 · 거래정지", "#8B95A5")}
                {flow_arrow()}
                {flow_node("분류", "GICS 11개 산업군 배정", "산업군 시가총액 비중 1% 미만인 산업군은 심사 제외", "#8B95A5")}
                {flow_arrow("#636EFA")}
                {flow_node("STEP 1", "1차 선정 — 산업군별 핵심 종목", "각 산업군 내 시가총액 상위 종목을 누적 시총 60% 도달까지 선정<br>거래대금 상위 80% 이내인 종목만 선정 가능 (유동성 기준)", "#636EFA")}
                {flow_arrow("#00E396")}
                {flow_node("STEP 2", "2차 선정 — 기존 종목 버퍼링", "기존 편입 종목: 시총 순위 ≤ 기존 종목수 × 120% 이면 유지 (완화)<br>신규 편입 후보: 시총 순위 ≤ 기존 종목수 × 80% 이면 편입 (엄격)", "#00E396")}
                {flow_arrow("#FEB019")}
                {flow_node("STEP 3", "3차 선정 — 150종목 조정", "150종목 미달 시 → 유동성 충족 잔여 종목 중 시총 상위 순 추가<br>150종목 초과 시 → 선정 종목 중 시총 최하위부터 제외", "#FEB019")}
                {flow_arrow("#AB63FA")}
                {flow_node("보정", "특례 · 제외 규정 적용", "대형주 특례: 시총 상위 50위 이내 종목 무조건 편입<br>소형주 제외: 시총 300위 밖 종목 강제 제외 후 대체 편입", "#AB63FA")}
                {flow_arrow()}
                {flow_node("", "코스닥 150 지수 구성종목 확정", "최종 150종목", AC, is_end=True)}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── 8. 분석 모드 비교 ──
        method_card("8. 본 시스템의 분석 모드 비교", method_table(
            ["항목", "빠른 분석", "정밀 분석", "KRX 실제 심사"],
            [
                ["시가총액 기준", "당일 종가 스냅샷", "6개월 일평균", "6개월 일평균"],
                ["거래대금 기준", "당일 거래대금", "6개월 일평균", "6개월 일평균"],
                ["관리종목 필터", "미반영", "미반영", "반영"],
                ["유동주식비율", "미반영", "미반영", "반영 (10%)"],
                ["GICS 분류", "WISE Index", "WISE Index", "KRX 자체"],
                ["소요시간", "~1분", "~30분", "—"],
                ["활용 용도", "빠른 트렌드 파악", "정기변경 예측", "공식 결과"],
            ]
        ))

        # ── 9. 유의사항 ──
        st.warning("**투자 참고용 시뮬레이션입니다. 실제 KRX 정기변경 결과와 차이가 발생할 수 있습니다.**")
        method_card("9. 유의사항 및 한계",
            f'<ol style="color:{TM}; line-height:2; padding-left:20px;">'
            f'<li><strong style="color:{TC};">관리종목·투자유의종목 필터 미반영</strong> — 해당 종목이 심사대상에 포함되어 결과에 영향</li>'
            f'<li><strong style="color:{TC};">유동주식비율 미반영</strong> — 대주주 지분이 높은 종목이 과대 반영될 가능성</li>'
            f'<li><strong style="color:{TC};">GICS 분류 차이</strong> — WISE Index API와 KRX 자체 분류 간 일부 차이 가능</li>'
            f'<li><strong style="color:{TC};">빠른 분석 모드의 한계</strong> — 당일 스냅샷은 단기 변동에 민감</li>'
            f'</ol>'
        )

        # ── 10. 데이터 소스 ──
        method_card("10. 데이터 소스", method_table(
            ["데이터", "소스", "수집 방법", "용도"],
            [
                ["코스닥 전체 종목", "FinanceDataReader", "Python API", "종목코드, 시가총액, 거래대금"],
                ["일별 OHLCV", "FinanceDataReader", "Python API", "6개월 일평균 산출"],
                ["GICS 산업군 분류", "WISE Index", "REST API", "11개 산업군별 종목 매핑"],
                ["코스닥150 구성종목", "정적 데이터", "JSON 파일", "현재 편입 종목 기준선"],
            ]
        ))

    # ── 페이지 푸터 ──
    st.markdown(
        '<div class="ark-footer">'
        'ARK IMPACT 분석 대시보드 · 코스닥 150 분석 · Powered by Streamlit & Plotly'
        '</div>',
        unsafe_allow_html=True,
    )

else:
    # 실행 전 안내
    st.markdown(
        '<div class="ark-card" style="max-width: 700px;">'
        '<h3>사용 방법</h3>'
        '<p>1. 왼쪽 사이드바에서 <strong>분석 모드</strong>를 선택하세요.</p>'
        '<p>2. <strong>분석 실행</strong> 버튼을 클릭하면 데이터를 수집하고 분석을 시작합니다.</p>'
        '<br><h3>5개 분석 섹션</h3><ul>'
        '<li><strong>현재 구성 종목</strong> — 현재 코스닥 150 종목, 섹터별 분포, 트리맵</li>'
        '<li><strong>향후 예상 구성 종목</strong> — 시뮬레이션 결과, 현재 vs 예상 비교</li>'
        '<li><strong>신규 편입 원인 분석</strong> — 편입 예상 종목별 사유, 섹터 내 순위</li>'
        '<li><strong>신규 편출 원인 분석</strong> — 편출 예상 종목별 사유, 유동성 분석</li>'
        '<li><strong>분석 기준 (방법론)</strong> — KRX 선정 방법론 상세 설명</li>'
        '</ul></div>',
        unsafe_allow_html=True,
    )
