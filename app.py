"""
ARK IMPACT 분석 대시보드 - 메인 앱
"""

import streamlit as st
from style import inject_css

# --- 페이지 설정 ---
st.set_page_config(
    page_title="ARK IMPACT 분석 대시보드",
    page_icon="assets/ark_logo.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- 공통 스타일 주입 ---
inject_css()

# --- 네비게이션 (아이콘 없이 깔끔하게) ---
home = st.Page("pages/home.py", title="대시보드 홈", default=True)
kosdaq150 = st.Page("pages/kosdaq150.py", title="코스닥 150 분석")
inbound = st.Page("pages/inbound.py", title="인바운드 데이터 분석")
macro = st.Page("pages/macro.py", title="매크로 분석")
pair_finder = st.Page("pages/pair_finder.py", title="롱숏 페어 파인더")
market_signal = st.Page("pages/market_signal.py", title="시장 시그널")
us_kr_link = st.Page("pages/us_kr_link.py", title="모닝 마켓 체크")
sector_consensus = st.Page("pages/sector_consensus.py", title="섹터 이익 컨센서스")

nav = st.navigation(
    {
        "메인": [home],
        "분석 도구": [us_kr_link, sector_consensus, kosdaq150, inbound, macro, pair_finder, market_signal],
    }
)

nav.run()
