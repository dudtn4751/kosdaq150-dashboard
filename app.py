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
us_kr_link = st.Page("pages/us_kr_link.py", title="모닝 마켓 체크")
sector_consensus = st.Page("pages/sector_consensus.py", title="섹터 이익 컨센서스")
etf_strategy = st.Page("pages/etf_strategy.py", title="ETF 수급 전략")

# EPS Revision 섹션 (팀원 앱 통합 — epsrev/ 네임스페이스)
epsrev_grid = st.Page("epsrev/pages/1_sector_grid.py", title="섹터 그리드", url_path="epsrev_sector_grid")
epsrev_secdetail = st.Page("epsrev/pages/2_sector_detail.py", title="섹터 상세", url_path="epsrev_sector_detail")
epsrev_codetail = st.Page("epsrev/pages/3_company_detail.py", title="종목 상세", url_path="epsrev_company_detail")
epsrev_pair = st.Page("epsrev/pages/4_pair_finder.py", title="페어 파인더 (EPS)", url_path="epsrev_pair_finder")

nav = st.navigation(
    {
        "메인": [home],
        "분석 도구": [us_kr_link, sector_consensus, etf_strategy, kosdaq150, inbound, macro],
        "종목 스크리닝": [epsrev_grid, epsrev_secdetail, epsrev_codetail, epsrev_pair],
    }
)

nav.run()
