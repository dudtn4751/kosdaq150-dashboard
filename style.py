"""
ARK IMPACT 분석 대시보드 — 공통 스타일 & 테마
"""

from datetime import datetime, timezone, timedelta

import streamlit as st
import plotly.graph_objects as go
import plotly.io as pio

KST = timezone(timedelta(hours=9))


def now_kst():
    """현재 한국시간 문자열 반환 (YYYY-MM-DD HH:MM)"""
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M")

# ── 컬러 팔레트 (라이트 테마: 흰 배경·검은 글씨, 전문 금융 톤) ──
COLORS = {
    "primary": "#1B2A4A",
    "primary_light": "#3A5A8A",
    "accent": "#1565C0",        # 전문 블루 (흰 배경 대비 ↑)
    "accent_green": "#15803D",  # 상승
    "accent_red": "#DC2626",    # 하락
    "accent_yellow": "#B45309", # 경고/중립 (amber)
    "bg_dark": "#F5F7FA",       # 페이지 배경 (아주 옅은 회색)
    "bg_card": "#FFFFFF",       # 카드 흰색
    "bg_card_hover": "#EEF2F7",
    "text": "#16202E",          # 본문 글씨 (거의 검정)
    "text_muted": "#5B6573",    # 보조 글씨 (중간 회색)
    "border": "#E2E6EC",        # 옅은 테두리
}

# 섹터별 컬러 (일관된 색상)
SECTOR_COLORS = {
    "정보기술": "#636EFA",
    "헬스케어": "#EF553B",
    "산업재": "#00CC96",
    "소재": "#AB63FA",
    "커뮤니케이션서비스": "#FFA15A",
    "자유소비재": "#19D3F3",
    "필수소비재": "#FF6692",
    "금융": "#B6E880",
    "에너지": "#FF97FF",
    "유틸리티": "#FECB52",
    "부동산": "#72B7B2",
}


def inject_css():
    """전역 CSS 주입"""
    st.markdown(f"""
    <style>
        @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable.min.css');

        /* ── 폰트 (Pretendard, 금융 대시보드 표준) ── */
        html, body, .stApp, .stApp * {{
            font-family: 'Pretendard Variable', Pretendard, -apple-system, BlinkMacSystemFont,
                         'Segoe UI', Roboto, 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
        }}
        /* 숫자 정렬 (tabular) */
        .stApp, div[data-testid="stMetricValue"], table, .stDataFrame {{
            font-variant-numeric: tabular-nums;
            font-feature-settings: "tnum" 1, "cv01" 1;
        }}

        /* ── 전체 배경 ── */
        .stApp {{
            background: linear-gradient(180deg, #FFFFFF 0%, {COLORS['bg_dark']} 100%);
        }}

        /* ── 전역 텍스트 (어두운 글씨, inline style 색상은 보존) ── */
        .stApp p, .stApp li, .stApp td, .stApp th,
        .stApp label, .stApp .stMarkdown {{
            color: {COLORS['text']};
        }}
        .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6 {{
            color: {COLORS['text']};
        }}
        .stApp [data-testid="stCaptionContainer"] {{
            color: {COLORS['text_muted']};
        }}

        /* ── 사이드바 (라이트) ── */
        section[data-testid="stSidebar"] {{
            background: linear-gradient(180deg, #F0F3F8 0%, #E6ECF4 100%);
            border-right: 1px solid {COLORS['border']};
        }}
        section[data-testid="stSidebar"] .stMarkdown p,
        section[data-testid="stSidebar"] .stMarkdown li {{
            color: {COLORS['text_muted']};
        }}
        /* 사이드바 네비게이션 링크 */
        section[data-testid="stSidebar"] a,
        section[data-testid="stSidebar"] a span,
        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a,
        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] span {{
            color: {COLORS['text']} !important;
            font-weight: 500;
        }}
        /* 사이드바 라디오/라벨/헤더 */
        section[data-testid="stSidebar"] .stRadio label,
        section[data-testid="stSidebar"] .stRadio p,
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] .stMarkdown h3,
        section[data-testid="stSidebar"] p {{
            color: {COLORS['text']} !important;
        }}

        /* ── 메트릭 카드 ── */
        div[data-testid="stMetric"] {{
            background: linear-gradient(135deg, {COLORS['bg_card']} 0%, {COLORS['bg_card_hover']} 100%);
            border: 1px solid {COLORS['border']};
            border-radius: 12px;
            padding: 20px 16px;
            box-shadow: 0 2px 8px rgba(16, 32, 46, 0.06);
        }}
        div[data-testid="stMetric"] label {{
            color: {COLORS['text_muted']} !important;
            font-size: 0.85rem !important;
            font-weight: 500 !important;
            letter-spacing: 0.03em;
        }}
        div[data-testid="stMetric"] div[data-testid="stMetricValue"] {{
            color: {COLORS['text']} !important;
            font-size: 1.8rem !important;
            font-weight: 700 !important;
        }}

        /* ── 탭 스타일 ── */
        .stTabs [data-baseweb="tab-list"] {{
            gap: 0px;
            background: {COLORS['bg_card']};
            border-radius: 12px;
            padding: 4px;
            border: 1px solid {COLORS['border']};
        }}
        .stTabs [data-baseweb="tab"] {{
            border-radius: 8px;
            padding: 10px 20px;
            color: {COLORS['text_muted']};
            font-weight: 500;
            font-size: 0.9rem;
        }}
        .stTabs [aria-selected="true"] {{
            background: {COLORS['primary_light']} !important;
            color: {COLORS['text']} !important;
            font-weight: 600;
        }}

        /* ── 데이터프레임 ── */
        .stDataFrame {{
            border: 1px solid {COLORS['border']};
            border-radius: 10px;
            overflow: hidden;
        }}
        /* 데이터프레임 내부 다크 테마 */
        .stDataFrame [data-testid="stDataFrameResizable"] {{
            background: {COLORS['bg_card']};
        }}
        .stDataFrame th {{
            background: {COLORS['bg_card_hover']} !important;
            color: {COLORS['accent']} !important;
            font-weight: 600 !important;
            border-bottom: 2px solid {COLORS['border']} !important;
        }}
        .stDataFrame td {{
            background: {COLORS['bg_card']} !important;
            color: {COLORS['text']} !important;
            border-bottom: 1px solid {COLORS['border']} !important;
        }}
        .stDataFrame tr:hover td {{
            background: {COLORS['bg_card_hover']} !important;
        }}
        /* glideDataEditor (Streamlit 내장 테이블) */
        [data-testid="glideDataEditor"] {{
            border: 1px solid {COLORS['border']} !important;
            border-radius: 10px !important;
        }}
        [data-testid="glideDataEditor"] .dvn-scroller {{
            background: {COLORS['bg_card']} !important;
        }}

        /* ── Expander ── */
        .streamlit-expanderHeader {{
            background: {COLORS['bg_card']};
            border: 1px solid {COLORS['border']};
            border-radius: 8px;
            color: {COLORS['text']};
            font-weight: 500;
        }}

        /* ── 구분선 ── */
        hr {{
            border-color: {COLORS['border']};
            opacity: 0.5;
        }}

        /* ── 버튼 ── */
        .stButton > button[kind="primary"] {{
            background: linear-gradient(135deg, {COLORS['accent']} 0%, #0090B8 100%);
            border: none;
            border-radius: 8px;
            font-weight: 600;
            letter-spacing: 0.02em;
            transition: all 0.3s ease;
        }}
        .stButton > button[kind="primary"]:hover {{
            box-shadow: 0 4px 20px rgba(0, 210, 255, 0.4);
            transform: translateY(-1px);
        }}

        /* ── selectbox ── */
        .stSelectbox > div > div {{
            background: {COLORS['bg_card']};
            border: 1px solid {COLORS['border']};
            border-radius: 8px;
        }}

        /* ── 카드 컨테이너 ── */
        .ark-card {{
            background: linear-gradient(135deg, {COLORS['bg_card']} 0%, {COLORS['bg_card_hover']} 100%);
            border: 1px solid {COLORS['border']};
            border-radius: 16px;
            padding: 28px;
            box-shadow: 0 2px 12px rgba(16, 32, 46, 0.06);
            transition: all 0.3s ease;
            height: 100%;
        }}
        .ark-card:hover {{
            border-color: {COLORS['accent']};
            box-shadow: 0 6px 24px rgba(21, 101, 192, 0.12);
            transform: translateY(-2px);
        }}
        .ark-card h3 {{
            color: {COLORS['text']};
            margin-bottom: 12px;
            font-size: 1.15rem;
        }}
        .ark-card p, .ark-card li {{
            color: {COLORS['text_muted']};
            font-size: 0.9rem;
            line-height: 1.7;
        }}
        .ark-card .card-icon {{
            font-size: 2.2rem;
            margin-bottom: 12px;
        }}

        /* ── 히어로 헤더 ── */
        .ark-hero {{
            background: linear-gradient(135deg, #FFFFFF 0%, #EEF3FA 100%);
            border: 1px solid {COLORS['border']};
            border-left: 5px solid {COLORS['accent']};
            border-radius: 20px;
            padding: 48px 40px;
            margin-bottom: 32px;
            box-shadow: 0 2px 16px rgba(16, 32, 46, 0.06);
            position: relative;
            overflow: hidden;
        }}
        .ark-hero::before {{
            content: '';
            position: absolute;
            top: -50%;
            right: -20%;
            width: 400px;
            height: 400px;
            background: radial-gradient(circle, rgba(21, 101, 192, 0.06) 0%, transparent 70%);
            border-radius: 50%;
        }}
        .ark-hero h1 {{
            color: {COLORS['text']};
            font-size: 2.4rem;
            font-weight: 800;
            margin-bottom: 8px;
            letter-spacing: -0.01em;
        }}
        .ark-hero .subtitle {{
            color: {COLORS['accent']};
            font-size: 1.05rem;
            font-weight: 500;
            letter-spacing: 0.02em;
        }}

        /* ── 섹션 헤더 ── */
        .section-header {{
            color: {COLORS['text']};
            font-size: 1.25rem;
            font-weight: 700;
            letter-spacing: -0.01em;
            padding-bottom: 6px;
            border-bottom: 2px solid {COLORS['accent']};
            margin-bottom: 18px;
            display: inline-block;
        }}
        /* 레퍼런스식 섹션 헤더 (영문 eyebrow + 한글) */
        .sec-eyebrow {{
            color: {COLORS['accent']};
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.14em;
            text-transform: uppercase;
        }}
        .sec-title {{
            color: {COLORS['text']};
            font-size: 1.3rem;
            font-weight: 700;
            letter-spacing: -0.01em;
            line-height: 1.25;
        }}
        .sec-wrap {{ margin: 10px 0 16px; }}

        /* ── 배지 ── */
        .badge-green {{
            background: rgba(0, 227, 150, 0.15);
            color: {COLORS['accent_green']};
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 600;
        }}
        .badge-red {{
            background: rgba(255, 69, 96, 0.15);
            color: {COLORS['accent_red']};
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 600;
        }}

        /* ── 푸터 ── */
        .ark-footer {{
            text-align: center;
            color: {COLORS['text_muted']};
            font-size: 0.8rem;
            padding: 20px 0;
            border-top: 1px solid {COLORS['border']};
            margin-top: 40px;
        }}
    </style>
    """, unsafe_allow_html=True)


# ── Plotly 공통 레이아웃 ──
PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color=COLORS["text_muted"], size=12, family="Pretendard, -apple-system, sans-serif"),
    title_font=dict(color=COLORS["text"], size=15, family="Pretendard, -apple-system, sans-serif"),
    legend=dict(
        bgcolor="rgba(0,0,0,0)",
        font=dict(color=COLORS["text_muted"], size=11),
    ),
    xaxis=dict(gridcolor=COLORS["border"], zerolinecolor=COLORS["border"]),
    yaxis=dict(gridcolor=COLORS["border"], zerolinecolor=COLORS["border"]),
    margin=dict(l=20, r=20, t=50, b=20),
)


def styled_plotly(fig, height=None):
    """Plotly 차트에 공통 테마 적용"""
    layout_update = dict(PLOTLY_LAYOUT)
    if height:
        layout_update["height"] = height
    fig.update_layout(**layout_update)
    return fig
