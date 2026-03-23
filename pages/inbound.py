"""
인바운드 데이터 분석 페이지
- 입국자 데이터 (전체/일본/중국)
- 카지노 산업 데이터 (매출/드롭액 등)
"""

import sys
import os
import glob

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from style import COLORS, PLOTLY_LAYOUT, styled_plotly

# ──────────────────────────────────────────────
# 데이터 경로
# ──────────────────────────────────────────────
PROJECT_DATA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "inbound",
)
DROPBOX_BASE = os.path.expanduser(
    "~/Library/CloudStorage/Dropbox-아크임팩트자산운용"
    "/상장주식/ARK_2025/(Monthly) 인바운드 데이터"
)


# ──────────────────────────────────────────────
# 데이터 로딩 함수
# ──────────────────────────────────────────────
def find_latest_file(keyword):
    """keyword를 포함하는 최신 xlsx 파일 경로 반환 (프로젝트 → 드롭박스 순)"""
    import unicodedata
    kw = unicodedata.normalize("NFC", keyword)

    for base_dir in [PROJECT_DATA, DROPBOX_BASE]:
        try:
            all_files = os.listdir(base_dir)
            matched = [
                os.path.join(base_dir, f)
                for f in sorted(all_files)
                if kw in unicodedata.normalize("NFC", f) and f.endswith(".xlsx")
            ]
            if matched:
                return matched[-1]
        except FileNotFoundError:
            continue
    return None


def load_inbound_visitors():
    """입국자 데이터 로드 (전체/일본/중국 월별)"""
    from datetime import datetime as dt

    path = find_latest_file("입국자")
    if not path:
        return None, None

    df = pd.read_excel(path, sheet_name="In-out", header=None)
    filename = os.path.basename(path)

    # row 20: 날짜 (col 5~), row 21: Total, row 22: Japan, row 36: China
    start_col = 5
    dates_raw = df.iloc[20, start_col:].tolist()
    total_raw = df.iloc[21, start_col:].tolist()
    japan_raw = df.iloc[22, start_col:].tolist()
    china_raw = df.iloc[36, start_col:].tolist()

    records = []
    for i, d in enumerate(dates_raw):
        if pd.isna(d):
            continue
        if isinstance(d, (pd.Timestamp, dt)):
            total_val = total_raw[i] if i < len(total_raw) else None
            japan_val = japan_raw[i] if i < len(japan_raw) else None
            china_val = china_raw[i] if i < len(china_raw) else None
            if pd.notna(total_val) and total_val != 0:
                records.append({
                    "날짜": pd.Timestamp(d),
                    "전체입국자": float(total_val) if pd.notna(total_val) else 0,
                    "일본": float(japan_val) if pd.notna(japan_val) else 0,
                    "중국": float(china_val) if pd.notna(china_val) else 0,
                })

    result = pd.DataFrame(records)
    if not result.empty:
        result = result.sort_values("날짜").reset_index(drop=True)

    return result, filename


def _load_monthly_sheet(path, date_row, data_rows, start_col=5):
    """엑셀 Monthly 시트에서 날짜 행 + 데이터 행들을 월별 DataFrame으로 변환"""
    from datetime import datetime as dt
    df = pd.read_excel(path, sheet_name="Monthly", header=None)
    cols = [(c, df.iloc[date_row, c]) for c in range(start_col, df.shape[1])
            if isinstance(df.iloc[date_row, c], (pd.Timestamp, dt))]
    records = []
    for c, d in cols:
        row = {"날짜": pd.Timestamp(d)}
        for label, r_idx in data_rows.items():
            val = df.iloc[r_idx, c]
            row[label] = float(val) if pd.notna(val) else 0
        records.append(row)
    return pd.DataFrame(records)


def load_casino_monthly():
    """GKL + 파라다이스 + 롯데관광개발 월별 카지노 데이터"""
    from datetime import datetime as dt

    # GKL (단위: 십억원)
    gkl_path = find_latest_file("GKL")
    gkl = None
    if gkl_path:
        gkl = _load_monthly_sheet(gkl_path, date_row=6, data_rows={
            "드롭액": 8, "매출액": 28, "홀드율": 32, "고객수": 35,
        })
        gkl["기업"] = "GKL"

    # 파라다이스 (단위: 십억원)
    para_path = find_latest_file("파라다이스")
    para = None
    if para_path:
        para = _load_monthly_sheet(para_path, date_row=6, data_rows={
            "드롭액": 8, "매출액": 21, "홀드율": 29,
        })
        para["기업"] = "파라다이스"
        para["고객수"] = 0

    # 롯데관광개발 (단위: 백만원 → 십억원 변환)
    lotte_path = find_latest_file("롯데관광개발")
    lotte = None
    if lotte_path:
        df_l = pd.read_excel(lotte_path, sheet_name="DreamtowerCasino", header=None)
        records = []
        for i in range(4, len(df_l)):
            d = df_l.iloc[i, 0]
            if not isinstance(d, (pd.Timestamp, dt)):
                continue
            drop_total = df_l.iloc[i, 3]  # 총계 드롭액
            hold_rate = df_l.iloc[i, 6]   # 총계 홀드율
            ns_total = df_l.iloc[i, 9]    # 총계 순매출
            visitors = df_l.iloc[i, 10] if df_l.shape[1] > 10 else 0
            records.append({
                "날짜": pd.Timestamp(d),
                "드롭액": float(drop_total) / 1000 if pd.notna(drop_total) else 0,
                "매출액": float(ns_total) / 1000 if pd.notna(ns_total) else 0,
                "홀드율": float(hold_rate) * 100 if pd.notna(hold_rate) and float(hold_rate) < 1 else (float(hold_rate) if pd.notna(hold_rate) else 0),
                "고객수": float(visitors) if pd.notna(visitors) else 0,
                "기업": "롯데관광개발",
            })
        lotte = pd.DataFrame(records) if records else None

    # 합치기
    frames = [df for df in [gkl, para, lotte] if df is not None and not df.empty]
    if not frames:
        return None
    all_data = pd.concat(frames, ignore_index=True)
    all_data = all_data.sort_values("날짜").reset_index(drop=True)
    return all_data


def load_jeju_visitors():
    """제주 입도객 데이터 (월별: 전체/내국인/일본/중국)"""
    from datetime import datetime as dt
    path = find_latest_file("입국자")
    if not path:
        return None

    df = pd.read_excel(path, sheet_name="Jeju", header=None)
    # col 3: 날짜, col 4: Total(월), col 5: 내국인, col 6: 일본, col 7: 중국
    def _safe_float(val):
        if pd.isna(val):
            return 0
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0

    records = []
    for i in range(19, len(df)):
        d = df.iloc[i, 3]
        if not isinstance(d, (pd.Timestamp, dt)):
            continue
        records.append({
            "날짜": pd.Timestamp(d),
            "전체": _safe_float(df.iloc[i, 4]),
            "내국인": _safe_float(df.iloc[i, 5]),
            "일본": _safe_float(df.iloc[i, 6]),
            "중국": _safe_float(df.iloc[i, 7]),
        })
    result = pd.DataFrame(records)
    if not result.empty:
        result = result[result["전체"] > 0].sort_values("날짜").reset_index(drop=True)
    return result


def section_header(text):
    st.markdown(
        f'<div class="section-header">{text}</div>',
        unsafe_allow_html=True,
    )
    st.markdown("")


# ──────────────────────────────────────────────
# 사이드바
# ──────────────────────────────────────────────
st.sidebar.markdown("### 데이터 관리")
st.sidebar.markdown("")

update_button = st.sidebar.button(
    "데이터 업데이트", type="primary", use_container_width=True,
)
if update_button:
    st.cache_data.clear()
    st.session_state.pop("inbound_loaded", None)

st.sidebar.markdown("---")
st.sidebar.markdown(
    f'<div style="color: {COLORS["text_muted"]}; font-size: 0.82rem; line-height: 1.8;">'
    f"<strong>데이터 소스</strong><br>"
    f"드롭박스 인바운드 데이터 폴더<br><br>"
    f"매월 파일 업데이트 후<br>"
    f"<strong>데이터 업데이트</strong> 버튼을 클릭하세요."
    f"</div>",
    unsafe_allow_html=True,
)


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
st.markdown(
    '<div class="ark-hero" style="padding: 32px 36px;">'
    '<h1 style="font-size: 1.9rem;">🛬 인바운드 데이터 분석</h1>'
    '<p class="subtitle">입국자 동향 · 카지노 산업 모니터링</p>'
    "</div>",
    unsafe_allow_html=True,
)

# 데이터 로드
visitors, filename = load_inbound_visitors()
casino = load_casino_monthly()
jeju = load_jeju_visitors()

if visitors is None or visitors.empty:
    st.error("인바운드 데이터 파일을 찾을 수 없거나 데이터가 비어있습니다.")
    st.stop()

st.caption(f"데이터 소스: {filename}")

# ══════════════════════════════════════════
# 4개 탭
# ══════════════════════════════════════════
tab1, tab2, tab3, tab4 = st.tabs([
    "  입국자 데이터  ",
    "  카지노 산업 합산  ",
    "  기업별 카지노  ",
    "  제주 입도객 · 롯데관광  ",
])

# ──────────────────────────────────────
# 탭 1: 입국자 데이터
# ──────────────────────────────────────
with tab1:
    section_header("입국자 추이")

    # 최근 데이터 기준 메트릭
    recent = visitors[visitors["날짜"] >= "2019-01-01"].copy()

    if not recent.empty:
        latest = recent.iloc[-1]
        prev = recent.iloc[-2] if len(recent) > 1 else latest

        c1, c2, c3 = st.columns(3)
        c1.metric(
            "전체 입국자",
            f"{latest['전체입국자']/10000:.1f}만명",
            delta=f"{(latest['전체입국자']-prev['전체입국자'])/10000:+.1f}만명",
        )
        c2.metric(
            "일본 입국자",
            f"{latest['일본']/10000:.1f}만명",
            delta=f"{(latest['일본']-prev['일본'])/10000:+.1f}만명",
        )
        c3.metric(
            "중국 입국자",
            f"{latest['중국']/10000:.1f}만명",
            delta=f"{(latest['중국']-prev['중국'])/10000:+.1f}만명",
        )

    st.markdown("")

    # 기간 필터
    year_range = st.slider(
        "분석 기간",
        min_value=int(visitors["날짜"].dt.year.min()),
        max_value=int(visitors["날짜"].dt.year.max()),
        value=(2015, int(visitors["날짜"].dt.year.max())),
        key="visitor_years",
    )
    filtered = visitors[
        (visitors["날짜"].dt.year >= year_range[0])
        & (visitors["날짜"].dt.year <= year_range[1])
    ]

    # 전체 입국자 추이
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=filtered["날짜"], y=filtered["전체입국자"],
        mode="lines", name="전체 입국자",
        line=dict(color=COLORS["accent"], width=2.5),
        fill="tozeroy", fillcolor="rgba(0,210,255,0.08)",
    ))
    fig.update_layout(title="월별 전체 입국자 추이", yaxis_title="입국자 수")
    st.plotly_chart(styled_plotly(fig, 400), use_container_width=True)

    # 일본 vs 중국 비교
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=filtered["날짜"], y=filtered["일본"],
        mode="lines", name="일본",
        line=dict(color="#FF6692", width=2),
    ))
    fig2.add_trace(go.Scatter(
        x=filtered["날짜"], y=filtered["중국"],
        mode="lines", name="중국",
        line=dict(color="#FFA15A", width=2),
    ))
    fig2.update_layout(title="월별 일본 vs 중국 입국자 비교", yaxis_title="입국자 수")
    st.plotly_chart(styled_plotly(fig2, 400), use_container_width=True)

    # 비중 분석
    section_header("국적별 비중 분석")

    # 연도별 비중
    yearly = filtered.copy()
    yearly["연도"] = yearly["날짜"].dt.year
    yearly_agg = yearly.groupby("연도").agg(
        전체=("전체입국자", "sum"),
        일본=("일본", "sum"),
        중국=("중국", "sum"),
    ).reset_index()
    yearly_agg["기타"] = yearly_agg["전체"] - yearly_agg["일본"] - yearly_agg["중국"]
    yearly_agg["일본비중"] = (yearly_agg["일본"] / yearly_agg["전체"] * 100).round(1)
    yearly_agg["중국비중"] = (yearly_agg["중국"] / yearly_agg["전체"] * 100).round(1)

    fig3 = go.Figure()
    fig3.add_trace(go.Bar(
        x=yearly_agg["연도"], y=yearly_agg["일본"],
        name="일본", marker_color="#FF6692",
    ))
    fig3.add_trace(go.Bar(
        x=yearly_agg["연도"], y=yearly_agg["중국"],
        name="중국", marker_color="#FFA15A",
    ))
    fig3.add_trace(go.Bar(
        x=yearly_agg["연도"], y=yearly_agg["기타"],
        name="기타", marker_color="#636EFA",
    ))
    fig3.update_layout(barmode="stack", title="연도별 입국자 국적 구성", yaxis_title="입국자 수")
    st.plotly_chart(styled_plotly(fig3, 420), use_container_width=True)

    # 연도별 테이블
    section_header("연도별 입국자 요약")
    summary = yearly_agg.copy()
    summary["전체(만명)"] = (summary["전체"] / 10000).round(1)
    summary["일본(만명)"] = (summary["일본"] / 10000).round(1)
    summary["중국(만명)"] = (summary["중국"] / 10000).round(1)
    summary["일본비중(%)"] = summary["일본비중"]
    summary["중국비중(%)"] = summary["중국비중"]
    st.dataframe(
        summary[["연도", "전체(만명)", "일본(만명)", "중국(만명)", "일본비중(%)", "중국비중(%)"]],
        use_container_width=True,
    )

# ──────────────────────────────────────
# 헬퍼: 연간/분기/월간 집계 + 성장률
# ──────────────────────────────────────
def _agg_with_growth(df, date_col, val_cols, freq):
    """df를 연간(Y)/분기(Q)/월간(M)으로 집계 후 y-y 성장률 추가"""
    tmp = df.copy()
    tmp[date_col] = pd.to_datetime(tmp[date_col])
    tmp = tmp.set_index(date_col)
    agg = tmp[val_cols].resample(freq).sum().reset_index()
    for col in val_cols:
        if freq == "YE":
            agg[f"{col}_yoy(%)"] = (agg[col].pct_change() * 100).round(1)
        elif freq == "QE":
            agg[f"{col}_yoy(%)"] = (agg[col].pct_change(4) * 100).round(1)
        else:
            agg[f"{col}_yoy(%)"] = (agg[col].pct_change(12) * 100).round(1)
    return agg

# ──────────────────────────────────────
# 탭 2: 카지노 산업 합산
# ──────────────────────────────────────
with tab2:
    section_header("카지노 산업 합산 데이터 (GKL + 파라다이스 + 롯데관광)")

    if casino is None or casino.empty:
        st.info("카지노 데이터를 로드하지 못했습니다.")
    else:
        # 합산 월별
        industry = casino.groupby("날짜").agg(
            드롭액=("드롭액", "sum"),
            매출액=("매출액", "sum"),
        ).reset_index()
        industry = industry[industry["드롭액"] > 0].sort_values("날짜")

        # 홀드율: 매출/드롭 가중평균
        industry["홀드율(%)"] = (industry["매출액"] / industry["드롭액"] * 100).round(2)

        # 연간/분기/월간
        view = st.radio("집계 단위", ["월간", "분기", "연간"], horizontal=True, key="casino_agg")
        freq_map = {"월간": "ME", "분기": "QE", "연간": "YE"}
        agg = _agg_with_growth(industry, "날짜", ["드롭액", "매출액"], freq_map[view])

        # 기간 필터
        agg = agg[agg["날짜"] >= "2015-01-01"]

        # 드롭액 차트
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=agg["날짜"], y=agg["드롭액"],
            name="드롭액", marker_color=COLORS["accent"],
        ))
        fig.add_trace(go.Bar(
            x=agg["날짜"], y=agg["매출액"],
            name="매출액", marker_color="#00E396",
        ))
        fig.update_layout(barmode="group", title=f"{view} 드롭액 · 매출액 (십억원)", yaxis_title="십억원")
        st.plotly_chart(styled_plotly(fig, 420), use_container_width=True)

        # 성장률 차트
        fig_g = go.Figure()
        fig_g.add_trace(go.Scatter(
            x=agg["날짜"], y=agg["드롭액_yoy(%)"],
            mode="lines+markers", name="드롭액 YoY",
            line=dict(color=COLORS["accent"], width=2), marker=dict(size=4),
        ))
        fig_g.add_trace(go.Scatter(
            x=agg["날짜"], y=agg["매출액_yoy(%)"],
            mode="lines+markers", name="매출액 YoY",
            line=dict(color="#00E396", width=2), marker=dict(size=4),
        ))
        fig_g.add_hline(y=0, line_dash="dash", line_color=COLORS["border"])
        fig_g.update_layout(title=f"{view} 성장률 (YoY %)", yaxis_title="%")
        st.plotly_chart(styled_plotly(fig_g, 380), use_container_width=True)

        # 홀드율 추이 (월별만)
        section_header("홀드율 추이 (월별)")
        monthly_hold = industry[industry["날짜"] >= "2015-01-01"]
        fig_h = go.Figure()
        fig_h.add_trace(go.Scatter(
            x=monthly_hold["날짜"], y=monthly_hold["홀드율(%)"],
            mode="lines", name="합산 홀드율",
            line=dict(color="#FEB019", width=2),
        ))
        fig_h.update_layout(title="월별 합산 홀드율 (%)", yaxis_title="%")
        st.plotly_chart(styled_plotly(fig_h, 350), use_container_width=True)

        # 테이블
        section_header("상세 테이블")
        show = agg.copy()
        show["날짜"] = show["날짜"].dt.strftime("%Y-%m")
        show["드롭액"] = show["드롭액"].round(1)
        show["매출액"] = show["매출액"].round(1)
        st.dataframe(show, use_container_width=True, height=400)

# ──────────────────────────────────────
# 탭 3: 기업별 카지노
# ──────────────────────────────────────
with tab3:
    section_header("기업별 카지노 데이터")

    if casino is None or casino.empty:
        st.info("카지노 데이터를 로드하지 못했습니다.")
    else:
        companies = casino["기업"].unique().tolist()
        metric = st.radio("지표", ["드롭액", "매출액", "홀드율"], horizontal=True, key="co_metric")

        # 기업별 월별 비교 차트
        fig_co = go.Figure()
        co_colors = {"GKL": COLORS["accent"], "파라다이스": "#FF6692", "롯데관광개발": "#FEB019"}
        for co in companies:
            co_data = casino[casino["기업"] == co].sort_values("날짜")
            co_data = co_data[co_data["날짜"] >= "2015-01-01"]
            fig_co.add_trace(go.Scatter(
                x=co_data["날짜"], y=co_data[metric],
                mode="lines", name=co,
                line=dict(color=co_colors.get(co, "#636EFA"), width=2),
            ))
        fig_co.update_layout(
            title=f"기업별 {metric} 월별 추이 (십억원)" if metric != "홀드율" else f"기업별 {metric} 월별 추이 (%)",
            yaxis_title="십억원" if metric != "홀드율" else "%",
        )
        st.plotly_chart(styled_plotly(fig_co, 420), use_container_width=True)

        # 기업별 연간 비교
        section_header("기업별 연간 비교")
        casino_yr = casino.copy()
        casino_yr["연도"] = casino_yr["날짜"].dt.year
        yr_agg = casino_yr.groupby(["연도", "기업"]).agg(
            드롭액=("드롭액", "sum"), 매출액=("매출액", "sum"),
        ).reset_index()
        yr_agg = yr_agg[yr_agg["연도"] >= 2015]

        fig_yr = go.Figure()
        for co in companies:
            co_yr = yr_agg[yr_agg["기업"] == co]
            fig_yr.add_trace(go.Bar(
                x=co_yr["연도"], y=co_yr[metric if metric != "홀드율" else "매출액"],
                name=co, marker_color=co_colors.get(co, "#636EFA"),
            ))
        fig_yr.update_layout(barmode="group", title=f"연간 기업별 {metric if metric != '홀드율' else '매출액'}")
        st.plotly_chart(styled_plotly(fig_yr, 400), use_container_width=True)

        # 기업별 최근 12개월 테이블
        section_header("최근 12개월 기업별 데이터")
        for co in companies:
            st.markdown(f"**{co}**")
            co_recent = casino[casino["기업"] == co].sort_values("날짜").tail(12).copy()
            co_recent["날짜"] = co_recent["날짜"].dt.strftime("%Y-%m")
            co_recent["드롭액"] = co_recent["드롭액"].round(1)
            co_recent["매출액"] = co_recent["매출액"].round(1)
            co_recent["홀드율"] = co_recent["홀드율"].round(2)
            st.dataframe(
                co_recent[["날짜", "드롭액", "매출액", "홀드율"]],
                use_container_width=True, height=200,
            )

# ──────────────────────────────────────
# 탭 4: 제주 입도객 · 롯데관광
# ──────────────────────────────────────
with tab4:
    # 제주 입도객
    section_header("제주 입도객 추이")

    if jeju is None or jeju.empty:
        st.info("제주 입도객 데이터를 로드하지 못했습니다.")
    else:
        jeju_f = jeju[jeju["날짜"] >= "2015-01-01"]

        fig_j = go.Figure()
        fig_j.add_trace(go.Scatter(
            x=jeju_f["날짜"], y=jeju_f["전체"],
            mode="lines", name="전체", line=dict(color=COLORS["accent"], width=2.5),
        ))
        fig_j.add_trace(go.Scatter(
            x=jeju_f["날짜"], y=jeju_f["중국"],
            mode="lines", name="중국", line=dict(color="#FFA15A", width=2),
        ))
        fig_j.add_trace(go.Scatter(
            x=jeju_f["날짜"], y=jeju_f["일본"],
            mode="lines", name="일본", line=dict(color="#FF6692", width=2),
        ))
        fig_j.update_layout(title="제주 월별 입도객 추이", yaxis_title="명")
        st.plotly_chart(styled_plotly(fig_j, 420), use_container_width=True)

        # 연간 제주 입도객
        jeju_yr = _agg_with_growth(jeju, "날짜", ["전체", "중국", "일본"], "YE")
        jeju_yr = jeju_yr[jeju_yr["날짜"].dt.year >= 2015]
        jeju_yr["연도"] = jeju_yr["날짜"].dt.year
        jeju_yr["전체(만명)"] = (jeju_yr["전체"] / 10000).round(1)
        jeju_yr["중국(만명)"] = (jeju_yr["중국"] / 10000).round(1)
        jeju_yr["일본(만명)"] = (jeju_yr["일본"] / 10000).round(1)
        st.dataframe(
            jeju_yr[["연도", "전체(만명)", "중국(만명)", "일본(만명)",
                      "전체_yoy(%)", "중국_yoy(%)", "일본_yoy(%)"]],
            use_container_width=True,
        )

    # 롯데관광개발 카지노
    st.markdown("---")
    section_header("롯데관광개발 (드림타워 카지노)")

    if casino is not None:
        lotte_data = casino[casino["기업"] == "롯데관광개발"].sort_values("날짜")
        if lotte_data.empty:
            st.info("롯데관광개발 데이터가 없습니다.")
        else:
            lotte_f = lotte_data[lotte_data["날짜"] >= "2021-06-01"]

            col1, col2 = st.columns(2)
            with col1:
                fig_ld = go.Figure()
                fig_ld.add_trace(go.Bar(
                    x=lotte_f["날짜"], y=lotte_f["드롭액"],
                    name="드롭액", marker_color="#FEB019",
                ))
                fig_ld.update_layout(title="롯데관광 월별 드롭액 (십억원)", yaxis_title="십억원")
                st.plotly_chart(styled_plotly(fig_ld, 380), use_container_width=True)

            with col2:
                fig_ln = go.Figure()
                fig_ln.add_trace(go.Bar(
                    x=lotte_f["날짜"], y=lotte_f["매출액"],
                    name="매출액", marker_color="#00E396",
                ))
                fig_ln.update_layout(title="롯데관광 월별 매출액 (십억원)", yaxis_title="십억원")
                st.plotly_chart(styled_plotly(fig_ln, 380), use_container_width=True)

            section_header("롯데관광 월별 상세")
            lotte_show = lotte_f.copy()
            lotte_show["날짜"] = lotte_show["날짜"].dt.strftime("%Y-%m")
            lotte_show["드롭액"] = lotte_show["드롭액"].round(1)
            lotte_show["매출액"] = lotte_show["매출액"].round(1)
            lotte_show["홀드율"] = lotte_show["홀드율"].round(2)
            st.dataframe(
                lotte_show[["날짜", "드롭액", "매출액", "홀드율", "고객수"]],
                use_container_width=True, height=400,
            )

# 푸터
st.markdown(
    '<div class="ark-footer">'
    "ARK IMPACT 분석 대시보드 · 인바운드 데이터 분석 · Powered by Streamlit & Plotly"
    "</div>",
    unsafe_allow_html=True,
)
