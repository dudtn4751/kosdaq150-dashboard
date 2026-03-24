"""
대시보드 홈 페이지 — 매크로 대시보드 + 분석 도구
"""

import os
import json
import streamlit as st
import pandas as pd

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from style import COLORS, PLOTLY_LAYOUT, styled_plotly
import plotly.graph_objects as go

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ──────────────────────────────────────────────
# 매크로 지표 로드
# ──────────────────────────────────────────────
MACRO_TICKERS = {
    "S&P 500": {"ticker": "^GSPC", "fmt": ",.0f", "unit": ""},
    "NASDAQ": {"ticker": "^IXIC", "fmt": ",.0f", "unit": ""},
    "Dow Jones": {"ticker": "^DJI", "fmt": ",.0f", "unit": ""},
    "US 10Y 금리": {"ticker": "^TNX", "fmt": ".2f", "unit": "%"},
    "USD/KRW": {"ticker": "KRW=X", "fmt": ",.0f", "unit": "원"},
    "WTI 유가": {"ticker": "CL=F", "fmt": ".1f", "unit": "$"},
    "금": {"ticker": "GC=F", "fmt": ",.0f", "unit": "$"},
    "달러 인덱스": {"ticker": "DX-Y.NYB", "fmt": ".1f", "unit": ""},
}


@st.cache_data(ttl=900, show_spinner=False)
def load_macro_data():
    """yfinance에서 매크로 지표 조회 (15분 캐시)"""
    if not HAS_YF:
        return {}

    results = {}
    for name, info in MACRO_TICKERS.items():
        try:
            t = yf.Ticker(info["ticker"])
            hist = t.history(period="5d")
            if hist.empty:
                continue
            last = hist["Close"].iloc[-1]
            prev = hist["Close"].iloc[-2] if len(hist) > 1 else last
            chg = (last - prev) / prev * 100 if prev != 0 else 0
            results[name] = {
                "value": last,
                "change": chg,
                "fmt": info["fmt"],
                "unit": info["unit"],
            }
        except Exception:
            pass
    return results


def load_macro_calendar():
    """매크로 일정 JSON 로드"""
    path = os.path.join(PROJECT_ROOT, "data", "macro_calendar.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
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
# 히어로 헤더
# ──────────────────────────────────────────────
st.markdown(
    '<div class="ark-hero">'
    '<h1 style="font-size: 2.2rem;">🚢 ARK IMPACT 분석 대시보드</h1>'
    '<p class="subtitle">금융 데이터 분석 · 지수 예측 · 투자 인사이트</p>'
    "</div>",
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────
# 1. 매크로 지표
# ──────────────────────────────────────────────
section_header("주요 매크로 지표")

macro = load_macro_data()

if macro:
    TC = COLORS["text"]
    TM = COLORS["text_muted"]
    AC = COLORS["accent"]
    BD = COLORS["border"]
    BG = COLORS["bg_card"]
    GR = COLORS["accent_green"]
    RD = COLORS["accent_red"]

    # 4열 그리드
    cols = st.columns(4)
    for i, (name, data) in enumerate(macro.items()):
        col = cols[i % 4]
        val = data["value"]
        chg = data["change"]
        fmt = data["fmt"]
        unit = data["unit"]
        formatted = f"{val:{fmt}}"

        chg_color = GR if chg >= 0 else RD
        chg_arrow = "▲" if chg >= 0 else "▼"

        col.markdown(
            f'<div style="background:{BG}; border:1px solid {BD}; border-radius:10px; '
            f'padding:16px; margin-bottom:12px;">'
            f'<div style="color:{TM}; font-size:0.78rem; font-weight:500; margin-bottom:6px;">{name}</div>'
            f'<div style="color:{TC}; font-size:1.35rem; font-weight:700;">{formatted}<span style="font-size:0.75rem; color:{TM};"> {unit}</span></div>'
            f'<div style="color:{chg_color}; font-size:0.82rem; font-weight:600;">{chg_arrow} {chg:+.2f}%</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        f'<div style="color:#FFFFFF; font-size:0.8rem; font-weight:500; margin-top:8px;">'
        f'15분 간격 자동 갱신 · Source: Yahoo Finance'
        f'</div>',
        unsafe_allow_html=True,
    )
else:
    st.info("매크로 지표를 불러오는 중... yfinance 설치가 필요합니다.")

st.markdown("")

# ──────────────────────────────────────────────
# 2. 금주 / 차주 주요 일정
# ──────────────────────────────────────────────
calendar = load_macro_calendar()

if calendar:
    TC = COLORS["text"]
    TM = COLORS["text_muted"]
    AC = COLORS["accent"]
    BD = COLORS["border"]
    BG = COLORS["bg_card"]

    importance_colors = {
        "high": COLORS["accent_red"],
        "medium": COLORS["accent_yellow"],
        "low": TM,
    }
    importance_labels = {
        "high": "●",
        "medium": "●",
        "low": "●",
    }

    def render_calendar_card(title, week_data):
        # 테이블 헤더
        events_html = (
            f'<div style="display:flex; padding:8px 0; border-bottom:2px solid {BD}; margin-bottom:4px;">'
            f'<span style="color:{AC}; min-width:80px; font-size:0.75rem; font-weight:600;">날짜</span>'
            f'<span style="color:{AC}; flex:1; font-size:0.75rem; font-weight:600;">이벤트</span>'
            f'<span style="color:{AC}; min-width:70px; font-size:0.75rem; font-weight:600; text-align:right;">컨센서스</span>'
            f'<span style="color:{AC}; min-width:70px; font-size:0.75rem; font-weight:600; text-align:right;">이전</span>'
            f'</div>'
        )

        for ev in week_data.get("events", []):
            imp = ev.get("importance", "low")
            dot_color = importance_colors.get(imp, TM)
            cons = ev.get("consensus", "-")
            prev = ev.get("previous", "-")
            if not cons:
                cons = "-"
            if not prev:
                prev = "-"

            events_html += (
                f'<div style="display:flex; align-items:center; padding:7px 0; '
                f'border-bottom:1px solid {BD};">'
                f'<span style="color:{dot_color}; margin-right:6px; font-size:0.6rem;">●</span>'
                f'<span style="color:{TM}; min-width:74px; font-size:0.82rem;">{ev["date"]}</span>'
                f'<span style="color:#FFFFFF; flex:1; font-size:0.85rem; font-weight:{"600" if imp == "high" else "400"};">{ev["event"]}</span>'
                f'<span style="color:#FFFFFF; min-width:70px; font-size:0.82rem; text-align:right; font-weight:500;">{cons}</span>'
                f'<span style="color:{TM}; min-width:70px; font-size:0.82rem; text-align:right;">{prev}</span>'
                f'</div>'
            )

        st.markdown(
            f'<div style="background:{BG}; border:1px solid {BD}; border-radius:12px; '
            f'padding:24px; height:100%;">'
            f'<div style="color:{AC}; font-size:1rem; font-weight:700; margin-bottom:4px;">{title}</div>'
            f'<div style="color:{TM}; font-size:0.8rem; margin-bottom:16px;">{week_data.get("label", "")}</div>'
            f'{events_html}'
            f'<div style="margin-top:14px; display:flex; gap:16px; font-size:0.75rem; color:#FFFFFF;">'
            f'<span><span style="color:{importance_colors["high"]};">●</span> 중요</span>'
            f'<span><span style="color:{importance_colors["medium"]};">●</span> 보통</span>'
            f'<span><span style="color:{importance_colors["low"]};">●</span> 참고</span>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    col_this, col_next = st.columns(2)
    with col_this:
        section_header("금주 주요 매크로 일정")
        render_calendar_card("This Week", calendar.get("this_week", {}))
    with col_next:
        section_header("차주 주요 매크로 일정")
        render_calendar_card("Next Week", calendar.get("next_week", {}))

    st.markdown(
        f'<div style="color:#FFFFFF; font-size:0.8rem; font-weight:500; margin-top:12px;">'
        f'매일 오전 07:00 자동 업데이트 · 최종 갱신: {calendar.get("updated", "-")}'
        f' · Source: investing.com Economic Calendar'
        f'</div>',
        unsafe_allow_html=True,
    )

st.markdown("")

# ──────────────────────────────────────────────
# 3. 분석 도구 카드
# ──────────────────────────────────────────────
section_header("분석 도구")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown(
        '<div class="ark-card">'
        '<div class="card-icon">📊</div>'
        "<h3>코스닥 150 분석</h3>"
        "<p>KRX 방법론 기반으로 코스닥 150 지수의 편입/편출 종목을 예측합니다.</p>"
        "<ul>"
        "<li>편입/편출 예상 종목</li>"
        "<li>섹터별 심층 분석</li>"
        "<li>편입/편출 원인 진단</li>"
        "<li>KRX 방법론 가이드</li>"
        "</ul></div>",
        unsafe_allow_html=True,
    )

with col2:
    st.markdown(
        '<div class="ark-card">'
        '<div class="card-icon">🛬</div>'
        "<h3>인바운드 데이터 분석</h3>"
        "<p>인바운드 관광 및 카지노 산업 데이터를 모니터링합니다.</p>"
        "<ul>"
        "<li>입국자 추이 (전체/일본/중국)</li>"
        "<li>카지노 산업 합산/기업별</li>"
        "<li>제주 입도객 · 롯데관광</li>"
        "<li>월별 업데이트</li>"
        "</ul></div>",
        unsafe_allow_html=True,
    )

with col3:
    st.markdown(
        '<div class="ark-card" style="opacity: 0.5;">'
        '<div class="card-icon">🔍</div>'
        "<h3>종목 스크리너</h3>"
        "<p>다양한 조건으로 종목을 필터링하고 비교 분석합니다.</p>"
        "<ul>"
        "<li>재무 지표 필터</li>"
        "<li>기술적 분석</li>"
        "<li>밸류에이션 비교</li>"
        "<li><em>준비 중</em></li>"
        "</ul></div>",
        unsafe_allow_html=True,
    )

# 푸터
st.markdown(
    '<div class="ark-footer">'
    "ARK IMPACT 분석 대시보드 v1.1 · Powered by Streamlit & Plotly"
    "</div>",
    unsafe_allow_html=True,
)
