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


SECTOR_ETFS = {
    "Technology": {"etf": "XLK", "top": ["AAPL", "MSFT", "NVDA"]},
    "Healthcare": {"etf": "XLV", "top": ["UNH", "LLY", "JNJ"]},
    "Financials": {"etf": "XLF", "top": ["BRK-B", "JPM", "V"]},
    "Consumer Disc.": {"etf": "XLY", "top": ["AMZN", "TSLA", "HD"]},
    "Communication": {"etf": "XLC", "top": ["META", "GOOGL", "NFLX"]},
    "Industrials": {"etf": "XLI", "top": ["GE", "CAT", "RTX"]},
    "Consumer Staples": {"etf": "XLP", "top": ["PG", "KO", "PEP"]},
    "Energy": {"etf": "XLE", "top": ["XOM", "CVX", "COP"]},
    "Utilities": {"etf": "XLU", "top": ["NEE", "DUK", "SO"]},
    "Real Estate": {"etf": "XLRE", "top": ["PLD", "AMT", "EQIX"]},
    "Materials": {"etf": "XLB", "top": ["LIN", "APD", "SHW"]},
}


@st.cache_data(ttl=900, show_spinner=False)
def load_us_sector_data():
    """미국 섹터별 일간 수익률 + 대표 종목 + 뉴스"""
    if not HAS_YF:
        return None

    sectors = []
    for sector, info in SECTOR_ETFS.items():
        try:
            t = yf.Ticker(info["etf"])
            h = t.history(period="5d")
            if len(h) < 2:
                continue
            ret = (h["Close"].iloc[-1] / h["Close"].iloc[-2] - 1) * 100

            # 대표 종목 수익률
            top_results = []
            for s in info["top"]:
                try:
                    st_h = yf.Ticker(s).history(period="5d")
                    if len(st_h) >= 2:
                        s_ret = (st_h["Close"].iloc[-1] / st_h["Close"].iloc[-2] - 1) * 100
                        top_results.append({"ticker": s, "return": round(s_ret, 2)})
                except Exception:
                    pass

            # 급등/급락 시 뉴스 가져오기
            news_titles = []
            if abs(ret) >= 1.0:
                try:
                    raw_news = t.news or []
                    for n in raw_news[:3]:
                        title = n.get("content", {}).get("title", "") if isinstance(n.get("content"), dict) else n.get("title", "")
                        if title:
                            news_titles.append(title)
                except Exception:
                    pass

            sectors.append({
                "sector": sector,
                "etf": info["etf"],
                "return": round(ret, 2),
                "top_stocks": top_results,
                "news": news_titles,
            })
        except Exception:
            pass

    sectors.sort(key=lambda x: x["return"], reverse=True)
    return sectors


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
    f'<div style="margin-bottom:32px; padding:20px 0;">'
    f'<h1 style="color:#FFFFFF; font-size:2.2rem; font-weight:800; margin:0; line-height:1.2;">'
    f'ARK IMPACT 분석 대시보드</h1>'
    f'<p style="color:{COLORS["accent"]}; font-size:1rem; font-weight:500;'
    f'letter-spacing:0.02em; margin:4px 0 0 0;">'
    f'금융 데이터 분석 · 지수 예측 · 투자 인사이트</p>'
    f'</div>',
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

    from style import now_kst
    st.markdown(
        f'<div style="color:{COLORS["text_muted"]}; font-size:0.78rem; margin-top:8px;">'
        f'15분 간격 자동 갱신 · 최근 업데이트: {now_kst()} (KST) · Source: Yahoo Finance'
        f'</div>',
        unsafe_allow_html=True,
    )
else:
    st.info("매크로 지표를 불러오는 중... yfinance 설치가 필요합니다.")

st.markdown("")

# ──────────────────────────────────────────────
# 2. 전일 미국 시장 현황
# ──────────────────────────────────────────────
section_header("전일 미국 시장 현황")

us_sectors = load_us_sector_data()

if us_sectors:
    TC = COLORS["text"]
    TM = COLORS["text_muted"]
    AC = COLORS["accent"]
    BD = COLORS["border"]
    BG = COLORS["bg_card"]
    GR = COLORS["accent_green"]
    RD = COLORS["accent_red"]

    # 급등/급락 섹터 하이라이트
    hot_sectors = [s for s in us_sectors if abs(s["return"]) >= 1.5]
    if hot_sectors:
        cards = ""
        for s in hot_sectors:
            color = GR if s["return"] > 0 else RD
            arrow = "▲" if s["return"] > 0 else "▼"
            label = "급등" if s["return"] > 0 else "급락"
            cards += (
                f'<div style="background:{BG}; border:2px solid {color}; border-radius:12px; '
                f'padding:16px; flex:1; min-width:200px;">'
                f'<div style="color:{color}; font-size:0.78rem; font-weight:600;">{label}</div>'
                f'<div style="color:#FFFFFF; font-size:1.05rem; font-weight:700; margin:4px 0;">'
                f'{s["sector"]} ({s["etf"]})</div>'
                f'<div style="color:{color}; font-size:1.3rem; font-weight:800;">'
                f'{arrow} {s["return"]:+.2f}%</div>'
            )
            # 뉴스
            if s["news"]:
                cards += f'<div style="margin-top:10px; border-top:1px solid {BD}; padding-top:8px;">'
                for title in s["news"][:2]:
                    cards += (
                        f'<div style="color:{TM}; font-size:0.75rem; margin-bottom:4px; '
                        f'line-height:1.4;">• {title[:80]}</div>'
                    )
                cards += '</div>'
            cards += '</div>'

        st.markdown(
            f'<div style="display:flex; gap:12px; flex-wrap:wrap; margin-bottom:16px;">{cards}</div>',
            unsafe_allow_html=True,
        )

    # 섹터별 수익률 히트맵 (가로 바)
    import plotly.graph_objects as go

    sectors_sorted = sorted(us_sectors, key=lambda x: x["return"])
    fig_sector = go.Figure(go.Bar(
        x=[s["return"] for s in sectors_sorted],
        y=[f'{s["sector"]}' for s in sectors_sorted],
        orientation="h",
        marker_color=[GR if s["return"] >= 0 else RD for s in sectors_sorted],
        text=[f'{s["return"]:+.2f}%' for s in sectors_sorted],
        textposition="outside",
        textfont=dict(color="#FFFFFF", size=11),
    ))
    fig_sector.update_layout(
        title="S&P 500 섹터별 일간 수익률",
        xaxis_title="%",
        height=380,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TM, size=12),
        title_font=dict(color=TC, size=16),
        xaxis=dict(gridcolor=BD, zerolinecolor=BD),
        yaxis=dict(gridcolor=BD),
        margin=dict(l=20, r=20, t=50, b=20),
    )
    fig_sector.add_vline(x=0, line_color=BD)
    st.plotly_chart(fig_sector, use_container_width=True)

    # 대표 종목 수익률 테이블
    with st.expander("섹터별 대표 종목 수익률 상세"):
        for s in us_sectors:
            color = GR if s["return"] >= 0 else RD
            stocks_html = ""
            for ts in s["top_stocks"]:
                ts_color = GR if ts["return"] >= 0 else RD
                stocks_html += (
                    f'<span style="margin-right:16px;">'
                    f'<span style="color:#FFFFFF; font-weight:500;">{ts["ticker"]}</span> '
                    f'<span style="color:{ts_color}; font-weight:600;">{ts["return"]:+.2f}%</span>'
                    f'</span>'
                )
            st.markdown(
                f'<div style="padding:8px 0; border-bottom:1px solid {BD};">'
                f'<span style="color:{color}; font-weight:700; min-width:140px; display:inline-block;">'
                f'{s["sector"]} {s["return"]:+.2f}%</span>'
                f'{stocks_html}</div>',
                unsafe_allow_html=True,
            )

    from style import now_kst
    st.markdown(
        f'<div style="color:{TM}; font-size:0.78rem; margin-top:8px;">'
        f'전일 종가 기준 · 최근 업데이트: {now_kst()} (KST) · Source: Yahoo Finance</div>',
        unsafe_allow_html=True,
    )

st.markdown("")

# ──────────────────────────────────────────────
# 3. 금주 / 차주 주요 일정
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

# 시스템 상태
status_path = os.path.join(PROJECT_ROOT, "data", "healthcheck_status.json")
try:
    with open(status_path, "r", encoding="utf-8") as f:
        hc_status = json.load(f)
    last_check = hc_status.get("last_check", "-")
    all_pass = hc_status.get("all_pass", False)
    status_icon = "✅" if all_pass else "⚠️"
    status_text = "정상" if all_pass else "일부 오류"
    st.markdown(
        f'<div style="color:{COLORS["text_muted"]}; font-size:0.78rem; margin-top:20px; text-align:center;">'
        f'{status_icon} 시스템 상태: {status_text} · 최근 점검: {last_check}'
        f'</div>',
        unsafe_allow_html=True,
    )
except Exception:
    pass

# 푸터
st.markdown(
    '<div class="ark-footer">'
    "ARK IMPACT 분석 대시보드 v1.1 · Powered by Streamlit & Plotly"
    "</div>",
    unsafe_allow_html=True,
)
