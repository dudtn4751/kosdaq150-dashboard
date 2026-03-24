"""
매크로 분석 대시보드
1) 물가 지표 (CPI, PCE 등)
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

# Fed Funds Futures
# 현재월 선물 = 현재 EFFR 근사치
CURRENT_MONTH_TICKER = "ZQH26.CBT"  # 2026년 3월

FOMC_FUTURES = [
    {"meeting": "2026년 5월 FOMC", "ticker": "ZQK26.CBT"},
    {"meeting": "2026년 6월 FOMC", "ticker": "ZQM26.CBT"},
    {"meeting": "2026년 7월 FOMC", "ticker": "ZQN26.CBT"},
    {"meeting": "2026년 9월 FOMC", "ticker": "ZQU26.CBT"},
    {"meeting": "2026년 12월 FOMC", "ticker": "ZQZ26.CBT"},
]


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
    """CME FedWatch — 선물 기반 금리 전망 계산

    현재월 선물에서 현재 EFFR을 추출하고,
    각 FOMC 회의월 선물과 비교하여 변동 예상을 산출합니다.
    """
    if not HAS_YF:
        return None, []

    # 1. 현재 실효 금리 추출 (현재월 선물)
    current_effr = None
    try:
        t = yf.Ticker(CURRENT_MONTH_TICKER)
        h = t.history(period="5d")
        if not h.empty:
            current_effr = round(100 - h["Close"].iloc[-1], 4)
    except Exception:
        pass

    if current_effr is None:
        return None, []

    # 현재 목표범위 추정 (25bp 단위)
    target_lower = round(round(current_effr / 0.25) * 0.25 - 0.25, 2)
    target_upper = target_lower + 0.25

    # 2. 각 FOMC 회의별 내재 금리
    results = []
    for item in FOMC_FUTURES:
        try:
            t = yf.Ticker(item["ticker"])
            h = t.history(period="5d")
            if h.empty:
                continue
            price = h["Close"].iloc[-1]
            implied = round(100 - price, 4)
            change_bp = round((implied - current_effr) * 100, 1)

            # 25bp 기준 인하/인상 횟수
            cuts = round((current_effr - implied) / 0.25, 1)

            results.append({
                "meeting": item["meeting"],
                "implied_rate": implied,
                "change_bp": change_bp,
                "cuts": cuts,
            })
        except Exception:
            pass

    current_info = {
        "effr": current_effr,
        "target_lower": target_lower,
        "target_upper": target_upper,
    }
    return current_info, results


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
    "  물가 지표  ",
    "  채권 금리  ",
    "  금리 인하 확률 (FedWatch)  ",
])

# ──────────────────────────────────────
# 탭 1: 물가 지표
# ──────────────────────────────────────
with tab1:
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

        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest

        def _get_latest_val(col_name):
            """최신 값이 없으면 직전 데이터 사용, (값, 비교값) 반환"""
            val, val_row = None, latest
            if col_name in latest and pd.notna(latest[col_name]):
                val = latest[col_name]
            elif col_name in prev and pd.notna(prev[col_name]):
                val = prev[col_name]
                val_row = prev
            if val is None:
                return None, None
            val_idx = df.index.get_loc(val_row.name)
            prev2 = df.iloc[val_idx - 1] if val_idx > 0 else val_row
            prev_val = prev2[col_name] if col_name in prev2 and pd.notna(prev2[col_name]) else val
            return val, prev_val

        # ── 소비자 물가 ──
        section_header("소비자 물가 (CPI / PCE)")

        cols = st.columns(4)
        for i, (col_name, label) in enumerate([
            ("CPI_YoY", "CPI (YoY)"), ("Core_CPI_YoY", "Core CPI (YoY)"),
            ("PCE_YoY", "PCE (YoY)"), ("Core_PCE_YoY", "Core PCE (YoY)"),
        ]):
            val, prev_val = _get_latest_val(col_name)
            if val is not None:
                cols[i].metric(label, f"{val:.1f}%",
                               delta=f"{val - prev_val:+.1f}%p", delta_color="inverse")

        fig_cpi = go.Figure()
        for col_name, label, color in [
            ("CPI_YoY", "CPI YoY", COLORS["accent"]),
            ("Core_CPI_YoY", "Core CPI YoY", "#FF6692"),
            ("PCE_YoY", "PCE YoY", "#00E396"),
            ("Core_PCE_YoY", "Core PCE YoY", "#FEB019"),
        ]:
            if col_name in df.columns:
                fig_cpi.add_trace(go.Scatter(
                    x=df["date"], y=df[col_name],
                    mode="lines", name=label,
                    line=dict(color=color, width=2),
                ))
        fig_cpi.add_hline(y=2.0, line_dash="dash", line_color=COLORS["accent_red"],
                          annotation_text="Fed Target 2%",
                          annotation_font_color=COLORS["accent_red"])
        fig_cpi.update_layout(title="소비자 물가지표 추이 (YoY %)", yaxis_title="%")
        st.plotly_chart(styled_plotly(fig_cpi, 420), use_container_width=True)

        last_date = df["date"].iloc[-1].strftime("%Y년 %m월")
        st.markdown(
            f'<div style="color:{COLORS["text_muted"]}; font-size:0.78rem; margin-top:-8px; margin-bottom:24px;">'
            f'최근 발표: {last_date} 기준 · 업데이트: {inflation.get("updated", "-")} · Source: BLS, BEA</div>',
            unsafe_allow_html=True,
        )

        # ── 생산자 물가 ──
        section_header("생산자 물가 (PPI)")

        cols2 = st.columns(2)
        for i, (col_name, label) in enumerate([
            ("PPI_YoY", "PPI (YoY)"), ("Core_PPI_YoY", "Core PPI (YoY)"),
        ]):
            val, prev_val = _get_latest_val(col_name)
            if val is not None:
                cols2[i].metric(label, f"{val:.1f}%",
                                delta=f"{val - prev_val:+.1f}%p", delta_color="inverse")

        fig_ppi = go.Figure()
        for col_name, label, color in [
            ("PPI_YoY", "PPI YoY", "#AB63FA"),
            ("Core_PPI_YoY", "Core PPI YoY", "#19D3F3"),
        ]:
            if col_name in df.columns:
                fig_ppi.add_trace(go.Scatter(
                    x=df["date"], y=df[col_name],
                    mode="lines", name=label,
                    line=dict(color=color, width=2),
                ))
        fig_ppi.add_hline(y=2.0, line_dash="dash", line_color=COLORS["accent_red"],
                          annotation_text="Fed Target 2%",
                          annotation_font_color=COLORS["accent_red"])
        fig_ppi.update_layout(title="생산자 물가지표 추이 (YoY %)", yaxis_title="%")
        st.plotly_chart(styled_plotly(fig_ppi, 420), use_container_width=True)

        st.markdown(
            f'<div style="color:{COLORS["text_muted"]}; font-size:0.78rem; margin-top:-8px; margin-bottom:24px;">'
            f'최근 발표: {last_date} 기준 · 업데이트: {inflation.get("updated", "-")} · Source: BLS</div>',
            unsafe_allow_html=True,
        )

        # ── 상세 테이블 ──
        section_header("물가 지표 상세")
        show = df.copy()
        show["date"] = show["date"].dt.strftime("%Y-%m")
        display_cols = ["date",
                        "CPI_release", "CPI_YoY", "Core_CPI_YoY",
                        "PCE_release", "PCE_YoY", "Core_PCE_YoY",
                        "PPI_release", "PPI_YoY", "Core_PPI_YoY"]
        display_cols = [c for c in display_cols if c in show.columns]
        rename = {
            "date": "대상월",
            "CPI_release": "CPI 발표일", "CPI_YoY": "CPI(%)", "Core_CPI_YoY": "Core CPI(%)",
            "PCE_release": "PCE 발표일", "PCE_YoY": "PCE(%)", "Core_PCE_YoY": "Core PCE(%)",
            "PPI_release": "PPI 발표일", "PPI_YoY": "PPI(%)", "Core_PPI_YoY": "Core PPI(%)",
        }
        st.dataframe(
            show[display_cols].rename(columns=rename).tail(24),
            use_container_width=True, height=400,
        )


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

    from style import now_kst as _nk1
    st.markdown(
        f'<div style="color:{COLORS["text_muted"]}; font-size:0.78rem; margin-top:8px;">'
        f"15분 간격 자동 갱신 · 최근 업데이트: {_nk1()} (KST) · Source: Yahoo Finance"
        f"</div>",
        unsafe_allow_html=True,
    )


# ──────────────────────────────────────
# 탭 3: 금리 인하 확률 (FedWatch)
# ──────────────────────────────────────
with tab3:
    section_header("CME FedWatch — 금리 전망")

    current_info, fedwatch = load_fedwatch()

    if current_info is None or not fedwatch:
        st.info("FedWatch 데이터를 불러오는 중...")
    else:
        effr = current_info["effr"]
        tgt_lo = current_info["target_lower"]
        tgt_hi = current_info["target_upper"]

        # 현재 금리
        st.markdown(
            f'<div style="background:{COLORS["bg_card"]}; border:1px solid {COLORS["border"]}; '
            f'border-radius:12px; padding:20px; margin-bottom:20px;">'
            f'<div style="color:{COLORS["text_muted"]}; font-size:0.85rem;">현재 기준금리 (목표범위)</div>'
            f'<div style="color:#FFFFFF; font-size:2rem; font-weight:800;">{tgt_lo:.2f}% - {tgt_hi:.2f}%</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # 각 FOMC 회의별 누적 인하/인상 횟수 계산
        meetings_display = []
        for r in fedwatch:
            cum_bp = round((effr - r["implied_rate"]) * 100, 1)
            cum_cuts = round(cum_bp / 25, 1)

            # 예상 목표범위 (25bp 단위 반올림)
            steps = round(cum_bp / 25)
            expected_upper = tgt_hi - steps * 0.25
            expected_lower = expected_upper - 0.25

            meetings_display.append({
                "meeting": r["meeting"],
                "cum_cuts": cum_cuts,
                "cum_bp": cum_bp,
                "expected_lower": expected_lower,
                "expected_upper": expected_upper,
            })

        # 연말 요약
        last = meetings_display[-1]
        total_cuts = round(last["cum_bp"] / 25)
        if total_cuts > 0:
            summary = f'{total_cuts}회 인하'
            summary_color = COLORS["accent_green"]
        elif total_cuts < 0:
            summary = f'{abs(total_cuts)}회 인상'
            summary_color = COLORS["accent_red"]
        else:
            summary = "0회 (금리 동결)"
            summary_color = COLORS["accent"]

        c1, c2 = st.columns(2)
        c1.metric("연말 예상 인하 횟수", summary)
        c2.metric("연말 예상 금리", f"{last['expected_lower']:.2f}% - {last['expected_upper']:.2f}%")

        # FOMC 회의별 카드
        section_header("FOMC 회의별 예상")

        BG = COLORS["bg_card"]
        BD = COLORS["border"]
        cards_html = '<div style="display:flex; flex-wrap:wrap; gap:12px;">'
        prev_expected_upper = tgt_hi
        for m in meetings_display:
            # 이전 회의 대비 변동으로 해당 회의의 결정 판별
            step = round((prev_expected_upper - m["expected_upper"]) / 0.25)
            if step > 0:
                label = f'25bp 인하'
                color = COLORS["accent_green"]
            elif step < 0:
                label = f'25bp 인상'
                color = COLORS["accent_red"]
            else:
                label = '동결'
                color = COLORS["text_muted"]
            prev_expected_upper = m["expected_upper"]

            cards_html += (
                f'<div style="background:{BG}; border:1px solid {BD}; border-radius:10px; '
                f'padding:16px; flex:1; min-width:150px; text-align:center;">'
                f'<div style="color:{COLORS["text_muted"]}; font-size:0.78rem; margin-bottom:8px;">{m["meeting"]}</div>'
                f'<div style="color:{color}; font-size:1.15rem; font-weight:700;">{label}</div>'
                f'<div style="color:#FFFFFF; font-size:0.82rem; margin-top:6px;">'
                f'{m["expected_lower"]:.2f}% - {m["expected_upper"]:.2f}%</div>'
                f'</div>'
            )
        cards_html += '</div>'
        st.markdown(cards_html, unsafe_allow_html=True)

        st.markdown("")

        # 예상 금리 경로 차트
        section_header("예상 금리 경로")
        df_fw = pd.DataFrame(meetings_display)
        meetings_x = ["현재"] + df_fw["meeting"].tolist()
        upper_y = [tgt_hi] + df_fw["expected_upper"].tolist()
        lower_y = [tgt_lo] + df_fw["expected_lower"].tolist()

        fig_path = go.Figure()
        fig_path.add_trace(go.Scatter(
            x=meetings_x, y=upper_y,
            mode="lines+markers+text",
            line=dict(color=COLORS["accent"], width=3),
            marker=dict(size=8),
            text=[f"{r:.2f}%" for r in upper_y],
            textposition="top center",
            textfont=dict(color="#FFFFFF", size=11),
            name="목표범위 상단",
        ))
        fig_path.add_trace(go.Scatter(
            x=meetings_x, y=lower_y,
            mode="lines+markers",
            line=dict(color=COLORS["accent"], width=3, dash="dot"),
            marker=dict(size=8),
            name="목표범위 하단",
            fill="tonexty",
            fillcolor="rgba(0,210,255,0.08)",
        ))
        fig_path.update_layout(
            title="기준금리 목표범위 예상 경로",
            yaxis_title="기준금리 (%)",
        )
        st.plotly_chart(styled_plotly(fig_path, 400), use_container_width=True)

    from style import now_kst as _nk2
    st.markdown(
        f'<div style="color:{COLORS["text_muted"]}; font-size:0.78rem; margin-top:8px;">'
        f"Fed Funds Futures 기반 산출 · 15분 간격 자동 갱신 · 최근 업데이트: {_nk2()} (KST) · Source: CME via Yahoo Finance"
        f"</div>",
        unsafe_allow_html=True,
    )

# 푸터
st.markdown(
    '<div class="ark-footer">'
    "ARK IMPACT 분석 대시보드 · 매크로 분석 · Powered by Streamlit & Plotly"
    "</div>",
    unsafe_allow_html=True,
)
