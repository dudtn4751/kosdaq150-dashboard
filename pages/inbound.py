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
DROPBOX_BASE = os.path.expanduser(
    "~/Library/CloudStorage/Dropbox-아크임팩트자산운용"
    "/상장주식/ARK_2025/(Monthly) 인바운드 데이터"
)


# ──────────────────────────────────────────────
# 데이터 로딩 함수
# ──────────────────────────────────────────────
def find_latest_file(keyword):
    """드롭박스에서 keyword를 포함하는 최신 파일 경로 반환"""
    import unicodedata
    try:
        all_files = os.listdir(DROPBOX_BASE)
        kw = unicodedata.normalize("NFC", keyword)
        matched = [
            os.path.join(DROPBOX_BASE, f)
            for f in sorted(all_files)
            if kw in unicodedata.normalize("NFC", f) and f.endswith(".xlsx")
        ]
        return matched[-1] if matched else None
    except FileNotFoundError:
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


def load_casino_industry():
    """카지노 산업 데이터 로드 (외국인/내국인 매출)"""
    path = find_latest_file("입국자")
    if not path:
        return None

    df = pd.read_excel(path, sheet_name="랜딩카지노", header=None)

    # row 4: 헤더 (기업명, 지점명, 연도별 매출)
    # row 5~20: 개별 카지노 데이터
    # row 22: 분기 헤더
    # row 23: 외국인카지노 합계
    # row 24: 내국인카지노 합계

    # 연도별 총 매출 (외국인)
    header_row = df.iloc[4].tolist()
    years = []
    for i in range(4, len(header_row)):
        val = header_row[i]
        if pd.notna(val):
            try:
                y = int(float(val))
                if 2005 <= y <= 2030:
                    years.append((i, y))
            except (ValueError, TypeError):
                pass

    # 개별 카지노 매출 합산 (외국인 카지노: row 5~20)
    yearly_foreign = {}
    for col_idx, year in years:
        total = 0
        for row_idx in range(5, 22):  # row 5~21 (내국인 제외)
            val = df.iloc[row_idx, col_idx]
            if pd.notna(val):
                try:
                    total += float(val)
                except (ValueError, TypeError):
                    pass
        if total > 0:
            yearly_foreign[year] = total

    # 내국인 카지노 (row 21: 강원랜드)
    yearly_domestic = {}
    for col_idx, year in years:
        val = df.iloc[21, col_idx]
        if pd.notna(val):
            try:
                yearly_domestic[year] = float(val)
            except (ValueError, TypeError):
                pass

    records = []
    all_years = sorted(set(list(yearly_foreign.keys()) + list(yearly_domestic.keys())))
    for y in all_years:
        records.append({
            "연도": y,
            "외국인카지노": yearly_foreign.get(y, 0),
            "내국인카지노": yearly_domestic.get(y, 0),
            "합계": yearly_foreign.get(y, 0) + yearly_domestic.get(y, 0),
        })

    return pd.DataFrame(records)


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
casino = load_casino_industry()

if visitors is None or visitors.empty:
    st.error("인바운드 데이터 파일을 찾을 수 없거나 데이터가 비어있습니다.")
    st.markdown(f"경로: `{DROPBOX_BASE}`")
    st.stop()

# 파일 정보 표시
st.caption(f"데이터 소스: {filename}")

# ══════════════════════════════════════════
# 2개 탭
# ══════════════════════════════════════════
tab1, tab2 = st.tabs(["  입국자 데이터  ", "  카지노 산업 데이터  "])

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
# 탭 2: 카지노 산업 데이터
# ──────────────────────────────────────
with tab2:
    section_header("카지노 산업 매출 추이")

    if casino is None or casino.empty:
        st.info("카지노 산업 데이터를 로드하지 못했습니다.")
    else:
        # 최근 메트릭
        recent_casino = casino[casino["연도"] >= 2019]
        if not recent_casino.empty:
            latest_c = recent_casino.iloc[-1]
            prev_c = recent_casino.iloc[-2] if len(recent_casino) > 1 else latest_c

            c1, c2, c3 = st.columns(3)
            c1.metric(
                "외국인 카지노 매출",
                f"{latest_c['외국인카지노']/1000:.0f}십억원",
                delta=f"{(latest_c['외국인카지노']-prev_c['외국인카지노'])/1000:+.0f}십억원",
            )
            c2.metric(
                "내국인 카지노 매출",
                f"{latest_c['내국인카지노']/1000:.0f}십억원",
                delta=f"{(latest_c['내국인카지노']-prev_c['내국인카지노'])/1000:+.0f}십억원",
            )
            c3.metric(
                "합계",
                f"{latest_c['합계']/1000:.0f}십억원",
                delta=f"{(latest_c['합계']-prev_c['합계'])/1000:+.0f}십억원",
            )

        st.markdown("")

        # 매출 추이 차트
        fig_c = go.Figure()
        fig_c.add_trace(go.Bar(
            x=casino["연도"], y=casino["외국인카지노"],
            name="외국인 카지노", marker_color=COLORS["accent"],
        ))
        fig_c.add_trace(go.Bar(
            x=casino["연도"], y=casino["내국인카지노"],
            name="내국인 카지노 (강원랜드)", marker_color="#AB63FA",
        ))
        fig_c.update_layout(
            barmode="stack",
            title="연도별 카지노 산업 매출 (백만원)",
            yaxis_title="매출 (백만원)",
        )
        st.plotly_chart(styled_plotly(fig_c, 450), use_container_width=True)

        # 외국인 카지노 매출 비중
        casino_show = casino[casino["연도"] >= 2010].copy()
        casino_show["외국인비중(%)"] = (
            casino_show["외국인카지노"] / casino_show["합계"] * 100
        ).round(1)

        fig_ratio = go.Figure()
        fig_ratio.add_trace(go.Scatter(
            x=casino_show["연도"], y=casino_show["외국인비중(%)"],
            mode="lines+markers", name="외국인 비중",
            line=dict(color=COLORS["accent"], width=2.5),
            marker=dict(size=6),
        ))
        fig_ratio.update_layout(
            title="외국인 카지노 매출 비중 추이",
            yaxis_title="비중 (%)",
            yaxis_range=[0, 100],
        )
        st.plotly_chart(styled_plotly(fig_ratio, 380), use_container_width=True)

        # 테이블
        section_header("연도별 카지노 매출 요약")
        c_summary = casino[casino["연도"] >= 2010].copy()
        c_summary["외국인(억원)"] = (c_summary["외국인카지노"] / 100).round(0).astype(int)
        c_summary["내국인(억원)"] = (c_summary["내국인카지노"] / 100).round(0).astype(int)
        c_summary["합계(억원)"] = (c_summary["합계"] / 100).round(0).astype(int)
        st.dataframe(
            c_summary[["연도", "외국인(억원)", "내국인(억원)", "합계(억원)"]],
            use_container_width=True,
        )

# 푸터
st.markdown(
    '<div class="ark-footer">'
    "ARK IMPACT 분석 대시보드 · 인바운드 데이터 분석 · Powered by Streamlit & Plotly"
    "</div>",
    unsafe_allow_html=True,
)
