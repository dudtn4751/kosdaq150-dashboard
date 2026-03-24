"""
매크로 분석 대시보드
1) 주요 물가 추이 (CPI, PCE 등)
2) 주요 채권 금리
3) 금리 인하 확률 (CME FedWatch)
"""

import sys
import os
import json

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from style import COLORS, styled_plotly

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ──────────────────────────────────────────────
# 데이터 로드
# ──────────────────────────────────────────────
BOND_TICKERS = {
    "US 3M": "^IRX",
    "US 2Y": "2YY=F",
    "US 5Y": "^FVX",
    "US 10Y": "^TNX",
    "US 30Y": "^TYX",
}

# 물가 지표는 FRED 데이터를 정적 JSON으로 관리 (월별 업데이트)
INFLATION_PATH = os.path.join(PROJECT_ROOT, "data", "inflation_data.json")

# Fed Funds Futures (FOMC 회의별)
FOMC_FUTURES = [
    {"meeting": "2026년 5월", "ticker": "ZQK26.CBT"},
    {"meeting": "2026년 6월", "ticker": "ZQM26.CBT"},
    {"meeting": "2026년 7월", "ticker": "ZQN26.CBT"},
    {"meeting": "2026년 9월", "ticker": "ZQU26.CBT"},
    {"meeting": "2026년 12월", "ticker": "ZQZ26.CBT"},
]

CURRENT_FED_RATE = 4.25  # 현재 기준금리 (수동 갱신)


@st.cache_data(ttl=900, show_spinner=False)
def load_bond_yields():
    """채권 금리 시계열 (1년)"""
    if not HAS_YF:
        return {}
    results = {}
    for name, ticker in BOND_TICKERS.items():
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="1y")
            if not hist.empty:
                results[name] = hist[["Close"]].rename(columns={"Close": name})
        except Exception:
            pass
    return results


@st.cache_data(ttl=900, show_spinner=False)
def load_fedwatch():
    """CME FedWatch 스타일 금리 인하 확률 계산"""
    if not HAS_YF:
        return []

    results = []
    for item in FOMC_FUTURES:
        try:
            t = yf.Ticker(item["ticker"])
            hist = t.history(period="5d")
            if hist.empty:
                continue
            price = hist["Close"].iloc[-1]
            implied_rate = 100 - price
            expected_cuts = (CURRENT_FED_RATE - implied_rate) / 0.25
            cut_bp = (CURRENT_FED_RATE - implied_rate) * 100

            results.append({
                "meeting": item["meeting"],
                "implied_rate": round(implied_rate, 3),
                "expected_cuts": round(expected_cuts, 1),
                "cut_bp": round(cut_bp, 0),
                "target_range": f"{implied_rate - 0.125:.2f}% - {implied_rate + 0.125:.2f}%",
            })
        except Exception:
            pass
    return results


def load_inflation_data():
    """물가 지표 로드 (정적 JSON)"""
    try:
        with open(INFLATION_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def section_header(text):
    st.markdown(
        f'<div class="section-header">{text}</div>',
        unsafe_allow_html=True,
    )
    st.markdown("")


# ──────────────────────────────────────────────
# 사이드바
# ──────────────────────────────────────────────
st.sidebar.markdown("### 매크로 설정")
st.sidebar.markdown("")
st.sidebar.markdown(
    f'<div style="color: #FFFFFF; font-size: 0.82rem; line-height: 1.8;">'
    f"채권 금리 · 물가 · 금리 전망<br>"
    f"15분 간격 자동 갱신"
    f"</div>",
    unsafe_allow_html=True,
)


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
st.markdown(
    '<div class="ark-hero" style="padding: 32px 36px;">'
    '<h1 style="font-size: 1.9rem;">📉 매크로 분석</h1>'
    '<p class="subtitle">물가 · 금리 · 통화정책 전망</p>'
    "</div>",
    unsafe_allow_html=True,
)

tab1, tab2, tab3 = st.tabs([
    "  주요 물가 추이  ",
    "  채권 금리  ",
    "  금리 인하 확률 (FedWatch)  ",
])

# ──────────────────────────────────────
# 탭 1: 주요 물가 추이
# ──────────────────────────────────────
with tab1:
    section_header("주요 물가 지표 추이")

    inflation = load_inflation_data()

    if inflation is None:
        st.info("물가 데이터를 준비 중입니다. data/inflation_data.json을 업데이트해주세요.")

        st.markdown(
            '<div style="color:#FFFFFF; font-size:0.9rem; line-height:1.8; margin-top:16px;">'
            "<strong>포함 지표:</strong><br>"
            "• CPI (소비자물가지수) YoY<br>"
            "• Core CPI (근원 소비자물가) YoY<br>"
            "• PCE (개인소비지출) YoY<br>"
            "• Core PCE (근원 PCE) YoY<br>"
            "• PPI (생산자물가지수) YoY"
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        df = pd.DataFrame(inflation["data"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")

        # 최근 메트릭
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest

        cols = st.columns(4)
        for i, col_name in enumerate(["CPI_YoY", "Core_CPI_YoY", "PCE_YoY", "Core_PCE_YoY"]):
            labels = {
                "CPI_YoY": "CPI (YoY)",
                "Core_CPI_YoY": "Core CPI (YoY)",
                "PCE_YoY": "PCE (YoY)",
                "Core_PCE_YoY": "Core PCE (YoY)",
            }
            if col_name in latest:
                val = latest[col_name]
                prev_val = prev[col_name] if col_name in prev else val
                cols[i].metric(
                    labels[col_name],
                    f"{val:.1f}%",
                    delta=f"{val - prev_val:+.1f}%p",
                    delta_color="inverse",
                )

        st.markdown("")

        # 물가 추이 차트
        fig = go.Figure()
        chart_cols = {
            "CPI_YoY": ("CPI YoY", COLORS["accent"]),
            "Core_CPI_YoY": ("Core CPI YoY", "#FF6692"),
            "PCE_YoY": ("PCE YoY", "#00E396"),
            "Core_PCE_YoY": ("Core PCE YoY", "#FEB019"),
        }
        for col_name, (label, color) in chart_cols.items():
            if col_name in df.columns:
                fig.add_trace(go.Scatter(
                    x=df["date"], y=df[col_name],
                    mode="lines", name=label,
                    line=dict(color=color, width=2),
                ))

        # Fed 목표 2% 라인
        fig.add_hline(y=2.0, line_dash="dash", line_color=COLORS["accent_red"],
                      annotation_text="Fed Target 2%",
                      annotation_font_color=COLORS["accent_red"])

        fig.update_layout(title="주요 물가지표 추이 (YoY %)", yaxis_title="%")
        st.plotly_chart(styled_plotly(fig, 450), use_container_width=True)

        # 테이블
        section_header("물가 지표 상세")
        show = df.copy()
        show["date"] = show["date"].dt.strftime("%Y-%m")
        st.dataframe(show.tail(24), use_container_width=True, height=400)


# ──────────────────────────────────────
# 탭 2: 채권 금리
# ──────────────────────────────────────
with tab2:
    section_header("미국 국채 금리 추이")

    bonds = load_bond_yields()

    if not bonds:
        st.info("채권 금리 데이터를 불러오는 중...")
    else:
        # 현재 금리 메트릭
        cols = st.columns(len(bonds))
        for i, (name, df_bond) in enumerate(bonds.items()):
            last = df_bond.iloc[-1].values[0]
            prev = df_bond.iloc[-2].values[0] if len(df_bond) > 1 else last
            cols[i].metric(name, f"{last:.2f}%", delta=f"{last - prev:+.2f}%p")

        st.markdown("")

        # 금리 추이 차트
        fig_y = go.Figure()
        colors = [COLORS["accent"], "#FF6692", "#00E396", "#FEB019", "#AB63FA"]
        for i, (name, df_bond) in enumerate(bonds.items()):
            fig_y.add_trace(go.Scatter(
                x=df_bond.index, y=df_bond[name],
                mode="lines", name=name,
                line=dict(color=colors[i % len(colors)], width=2),
            ))
        fig_y.update_layout(title="미국 국채 금리 추이 (1년)", yaxis_title="%")
        st.plotly_chart(styled_plotly(fig_y, 450), use_container_width=True)

        # 수익률 곡선 (Yield Curve)
        section_header("수익률 곡선 (Yield Curve)")
        maturities = list(bonds.keys())
        current_yields = [bonds[m].iloc[-1].values[0] for m in maturities]
        prev_yields = [bonds[m].iloc[-22].values[0] if len(bonds[m]) > 22 else bonds[m].iloc[0].values[0] for m in maturities]

        fig_yc = go.Figure()
        fig_yc.add_trace(go.Scatter(
            x=maturities, y=current_yields,
            mode="lines+markers", name="현재",
            line=dict(color=COLORS["accent"], width=3),
            marker=dict(size=10),
        ))
        fig_yc.add_trace(go.Scatter(
            x=maturities, y=prev_yields,
            mode="lines+markers", name="1개월 전",
            line=dict(color=COLORS["text_muted"], width=2, dash="dash"),
            marker=dict(size=7),
        ))
        fig_yc.update_layout(title="미국 국채 수익률 곡선", yaxis_title="%")
        st.plotly_chart(styled_plotly(fig_yc, 400), use_container_width=True)

        # 10Y-2Y 스프레드
        if "US 10Y" in bonds and "US 2Y" in bonds:
            section_header("장단기 금리차 (10Y - 2Y)")
            df_10y = bonds["US 10Y"].copy()
            df_2y = bonds["US 2Y"].copy()
            merged = df_10y.join(df_2y, how="inner")
            merged["Spread"] = merged["US 10Y"] - merged["US 2Y"]

            fig_sp = go.Figure()
            fig_sp.add_trace(go.Scatter(
                x=merged.index, y=merged["Spread"],
                mode="lines", name="10Y-2Y Spread",
                line=dict(color=COLORS["accent"], width=2),
                fill="tozeroy",
                fillcolor="rgba(0,210,255,0.08)",
            ))
            fig_sp.add_hline(y=0, line_dash="dash", line_color=COLORS["accent_red"],
                             annotation_text="역전 기준선",
                             annotation_font_color=COLORS["accent_red"])
            fig_sp.update_layout(title="장단기 금리차 (10Y-2Y)", yaxis_title="%p")
            st.plotly_chart(styled_plotly(fig_sp, 380), use_container_width=True)

    st.markdown(
        '<div style="color:#FFFFFF; font-size:0.8rem; margin-top:8px;">'
        "15분 간격 자동 갱신 · Source: Yahoo Finance"
        "</div>",
        unsafe_allow_html=True,
    )


# ──────────────────────────────────────
# 탭 3: 금리 인하 확률 (FedWatch)
# ──────────────────────────────────────
with tab3:
    section_header("CME FedWatch — 금리 인하 전망")

    st.markdown(
        f'<div style="color:#FFFFFF; font-size:0.9rem; margin-bottom:16px;">'
        f"현재 기준금리: <strong>{CURRENT_FED_RATE:.2f}%</strong> "
        f"(목표범위 {CURRENT_FED_RATE - 0.25:.2f}% - {CURRENT_FED_RATE:.2f}%)"
        f"</div>",
        unsafe_allow_html=True,
    )

    fedwatch = load_fedwatch()

    if not fedwatch:
        st.info("FedWatch 데이터를 불러오는 중...")
    else:
        # 메트릭: 연말 예상 인하 횟수
        last_meeting = fedwatch[-1]
        st.markdown(
            f'<div style="background:{COLORS["bg_card"]}; border:1px solid {COLORS["border"]}; '
            f'border-radius:12px; padding:20px; margin-bottom:20px;">'
            f'<div style="color:{COLORS["text_muted"]}; font-size:0.85rem;">연말({last_meeting["meeting"]}) 예상 누적 인하</div>'
            f'<div style="color:#FFFFFF; font-size:2rem; font-weight:800;">'
            f'{last_meeting["expected_cuts"]:.1f}회 ({last_meeting["cut_bp"]:.0f}bp)</div>'
            f'<div style="color:{COLORS["text_muted"]}; font-size:0.85rem;">'
            f'예상 금리: {last_meeting["implied_rate"]:.3f}%</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # FOMC 회의별 차트
        df_fw = pd.DataFrame(fedwatch)

        fig_fw = go.Figure()
        fig_fw.add_trace(go.Bar(
            x=df_fw["meeting"],
            y=df_fw["implied_rate"],
            marker_color=COLORS["accent"],
            text=df_fw["implied_rate"].apply(lambda x: f"{x:.3f}%"),
            textposition="outside",
            textfont=dict(color="#FFFFFF", size=12),
        ))
        fig_fw.add_hline(
            y=CURRENT_FED_RATE,
            line_dash="dash", line_color=COLORS["accent_red"],
            annotation_text=f"현재 {CURRENT_FED_RATE}%",
            annotation_font_color=COLORS["accent_red"],
        )
        fig_fw.update_layout(
            title="FOMC 회의별 내재 기준금리",
            yaxis_title="내재 금리 (%)",
            yaxis_range=[min(df_fw["implied_rate"]) - 0.2, CURRENT_FED_RATE + 0.3],
        )
        st.plotly_chart(styled_plotly(fig_fw, 420), use_container_width=True)

        # 누적 인하 횟수 차트
        fig_cuts = go.Figure()
        fig_cuts.add_trace(go.Scatter(
            x=df_fw["meeting"],
            y=df_fw["expected_cuts"],
            mode="lines+markers+text",
            line=dict(color="#00E396", width=3),
            marker=dict(size=10),
            text=df_fw["expected_cuts"].apply(lambda x: f"{x:.1f}회"),
            textposition="top center",
            textfont=dict(color="#FFFFFF", size=11),
        ))
        fig_cuts.update_layout(
            title="FOMC 회의별 누적 인하 예상 횟수",
            yaxis_title="인하 횟수",
        )
        st.plotly_chart(styled_plotly(fig_cuts, 380), use_container_width=True)

        # 상세 테이블
        section_header("FOMC 회의별 상세")
        show_fw = df_fw.copy()
        show_fw.columns = ["FOMC 회의", "내재 금리(%)", "예상 인하 횟수", "인하폭(bp)", "예상 목표범위"]
        st.dataframe(show_fw, use_container_width=True)

    st.markdown(
        '<div style="color:#FFFFFF; font-size:0.8rem; margin-top:8px;">'
        "Fed Funds Futures 기반 산출 · 15분 간격 자동 갱신 · Source: CME via Yahoo Finance"
        "</div>",
        unsafe_allow_html=True,
    )

# 푸터
st.markdown(
    '<div class="ark-footer">'
    "ARK IMPACT 분석 대시보드 · 매크로 분석 · Powered by Streamlit & Plotly"
    "</div>",
    unsafe_allow_html=True,
)
