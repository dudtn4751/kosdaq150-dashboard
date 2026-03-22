"""
대시보드 홈 페이지
"""

import streamlit as st

# ── 히어로 헤더 ──
st.markdown("""
<div class="ark-hero">
    <h1>🚢 ARK IMPACT 분석 대시보드</h1>
    <p class="subtitle">금융 데이터 분석 · 지수 예측 · 투자 인사이트</p>
</div>
""", unsafe_allow_html=True)

# ── 분석 도구 카드 ──
st.markdown('<div class="section-header">분석 도구</div>', unsafe_allow_html=True)
st.markdown("")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("""
    <div class="ark-card">
        <div class="card-icon">📊</div>
        <h3>코스닥 150 분석</h3>
        <p>KRX 방법론 기반으로 코스닥 150 지수의 편입/편출 종목을 예측합니다.</p>
        <ul>
            <li>편입/편출 예상 종목</li>
            <li>섹터별 심층 분석</li>
            <li>편입/편출 원인 진단</li>
            <li>KRX 방법론 가이드</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown("""
    <div class="ark-card" style="opacity: 0.5;">
        <div class="card-icon">📈</div>
        <h3>시장 모멘텀 분석</h3>
        <p>코스피/코스닥 시장의 모멘텀과 자금 흐름을 추적합니다.</p>
        <ul>
            <li>업종별 자금 흐름</li>
            <li>외국인/기관 수급</li>
            <li>시장 센티먼트</li>
            <li><em>준비 중</em></li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown("""
    <div class="ark-card" style="opacity: 0.5;">
        <div class="card-icon">🔍</div>
        <h3>종목 스크리너</h3>
        <p>다양한 조건으로 종목을 필터링하고 비교 분석합니다.</p>
        <ul>
            <li>재무 지표 필터</li>
            <li>기술적 분석</li>
            <li>밸류에이션 비교</li>
            <li><em>준비 중</em></li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

# ── 푸터 ──
st.markdown("""
<div class="ark-footer">
    ARK IMPACT 분석 대시보드 v1.0 · Powered by Streamlit & Plotly
</div>
""", unsafe_allow_html=True)
