import sys, os

import streamlit as st
from epsrev.ui.sidebar import render_sidebar


render_sidebar()

# 랜딩 즉시 섹터 그리드로 이동
st.switch_page("epsrev/pages/1_sector_grid.py")
