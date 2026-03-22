"""
대시보드 홈 페이지
"""

import streamlit as st

st.title("🏠 ARK IMPACT 분석 대시보드")

st.markdown(
    """
    ARK IMPACT의 다양한 금융 데이터 분석 도구를 한곳에서 사용할 수 있는 대시보드입니다.
    왼쪽 사이드바에서 원하는 분석 도구를 선택하세요.
    """
)

st.markdown("---")

# 분석 도구 카드
st.markdown("## 분석 도구")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown(
        """
        ### 📊 코스닥 150 분석
        KRX 방법론 기반으로 코스닥 150 지수의
        편입/편출 종목을 예측합니다.

        - 편입/편출 예상 종목
        - 섹터별 분석
        - 시가총액 분포
        - 현재 구성종목 조회
        """
    )

with col2:
    st.markdown(
        """
        ### 🔧 준비 중
        새로운 분석 도구가 추가될 예정입니다.

        &nbsp;

        &nbsp;

        &nbsp;
        """
    )

with col3:
    st.markdown(
        """
        ### 🔧 준비 중
        새로운 분석 도구가 추가될 예정입니다.

        &nbsp;

        &nbsp;

        &nbsp;
        """
    )

st.markdown("---")
st.caption("ARK IMPACT 분석 대시보드 v1.0")
