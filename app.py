"""
ARK IMPACT 분석 대시보드 - 메인 앱
"""

import streamlit as st

# --- 페이지 설정 ---
st.set_page_config(
    page_title="ARK IMPACT 분석 대시보드",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- 네비게이션 ---
home = st.Page("pages/home.py", title="대시보드 홈", icon="🏠", default=True)
kosdaq150 = st.Page("pages/kosdaq150.py", title="코스닥 150 분석", icon="📊")

nav = st.navigation(
    {
        "메인": [home],
        "분석 도구": [kosdaq150],
    }
)

nav.run()
