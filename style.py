"""
ARK IMPACT 분석 대시보드 — 공통 스타일 & 테마
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.io as pio

# ── 컬러 팔레트 ──
COLORS = {
    "primary": "#1B2A4A",
    "primary_light": "#2D4A7A",
    "accent": "#00D2FF",
    "accent_green": "#00E396",
    "accent_red": "#FF4560",
    "accent_yellow": "#FEB019",
    "bg_dark": "#0E1117",
    "bg_card": "#1E2530",
    "bg_card_hover": "#263040",
    "text": "#E8ECF1",
    "text_muted": "#8B95A5",
    "border": "#2D3748",
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
        /* ── 전체 배경 & 폰트 ── */
        .stApp {{
            background: linear-gradient(180deg, #0E1117 0%, #1A1F2E 100%);
        }}

        /* ── 전역 텍스트 흰색 (inline style 색상은 보존) ── */
        .stApp p, .stApp li, .stApp td, .stApp th,
        .stApp label, .stApp .stMarkdown {{
            color: #E8ECF1;
        }}
        .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6 {{
            color: #FFFFFF;
        }}
        .stApp [data-testid="stCaptionContainer"] {{
            color: #B0B8C8;
        }}

        /* ── 사이드바 ── */
        section[data-testid="stSidebar"] {{
            background: linear-gradient(180deg, {COLORS['primary']} 0%, #0D1B2A 100%);
            border-right: 1px solid {COLORS['border']};
        }}
        section[data-testid="stSidebar"] .stMarkdown p,
        section[data-testid="stSidebar"] .stMarkdown li {{
            color: {COLORS['text_muted']};
        }}
        /* 사이드바 네비게이션 링크 */
        section[data-testid="stSidebar"] a {{
            color: #FFFFFF !important;
        }}
        section[data-testid="stSidebar"] a span {{
            color: #FFFFFF !important;
        }}
        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a {{
            color: #FFFFFF !important;
        }}
        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] span {{
            color: #FFFFFF !important;
            font-weight: 500;
        }}
        /* 사이드바 라디오/라벨 */
        section[data-testid="stSidebar"] .stRadio label {{
            color: #FFFFFF !important;
        }}
        section[data-testid="stSidebar"] .stRadio p {{
            color: #FFFFFF !important;
        }}
        section[data-testid="stSidebar"] label {{
            color: #FFFFFF !important;
        }}
        section[data-testid="stSidebar"] .stMarkdown h3 {{
            color: #FFFFFF !important;
        }}
        /* 사이드바 섹션 헤더 (메인, 분석 도구 등) */
        section[data-testid="stSidebar"] p {{
            color: #E8ECF1 !important;
        }}

        /* ── 메트릭 카드 ── */
        div[data-testid="stMetric"] {{
            background: linear-gradient(135deg, {COLORS['bg_card']} 0%, {COLORS['bg_card_hover']} 100%);
            border: 1px solid {COLORS['border']};
            border-radius: 12px;
            padding: 20px 16px;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
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
            background: #1A2744 !important;
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
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
            transition: all 0.3s ease;
            height: 100%;
        }}
        .ark-card:hover {{
            border-color: {COLORS['accent']};
            box-shadow: 0 8px 32px rgba(0, 210, 255, 0.15);
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
            background: linear-gradient(135deg, {COLORS['primary']} 0%, {COLORS['primary_light']} 50%, #1A3A6A 100%);
            border: 1px solid {COLORS['border']};
            border-radius: 20px;
            padding: 48px 40px;
            margin-bottom: 32px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
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
            background: radial-gradient(circle, rgba(0, 210, 255, 0.08) 0%, transparent 70%);
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
            font-size: 1.4rem;
            font-weight: 700;
            padding-bottom: 8px;
            border-bottom: 2px solid {COLORS['accent']};
            margin-bottom: 20px;
            display: inline-block;
        }}

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
    font=dict(color=COLORS["text_muted"], size=12),
    title_font=dict(color=COLORS["text"], size=16, family="sans-serif"),
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
