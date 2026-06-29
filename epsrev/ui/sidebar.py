import streamlit as st
from datetime import datetime


def render_sidebar() -> None:
    """모든 페이지 상단에서 호출. 공통 사이드바를 렌더한다."""
    with st.sidebar:
        st.markdown("## 📊 KR Equity Research")
        st.markdown("**EPS Revision Dashboard**")
        st.divider()

        # (페이지 이동은 상단 st.navigation이 자동 제공 — 중복 링크 제거)
        st.markdown("**데이터 상태**")
        st.markdown("✅ 더미 데이터 활성")
        st.markdown("⬜ FnSpace API (미연결)")
        st.markdown("⬜ KRX API (미연결)")
        st.markdown("⬜ KITA API (미연결)")

        st.divider()

        st.caption(f"마지막 업데이트\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
