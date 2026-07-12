"""숏 후보 스크리너 — Long 티커 입력 → 밸류체인 근접 Short 후보 + 구조점수.

MVP 데이터: 관계 근접성(밸류체인 CSV) + pykrx(가격·ADV20·시총·수급).
EPS Revision/밸류/대차/DART는 stub(미연동) — 구조점수 분모에서 제외되며
coverage_ratio·grade*로 부분 커버리지를 명시한다. 밸류·타이밍(z/half-life/수급)은
구조점수에 미반영(별도 컬럼 표시 전용).
"""

import sys
import os

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from short_finder import find_short_candidates, FACTOR_WEIGHTS  # noqa: E402

st.markdown(
    "<div style='font-size:1.5rem;font-weight:800;margin-bottom:2px'>🎯 숏 후보 스크리너</div>"
    "<div style='font-size:0.8rem;color:#546080;margin-bottom:8px'>"
    "Long 종목 기준 밸류체인 근접 Short 후보 · 구조점수(관계·상관·beta 안정성·유동성) · "
    "타이밍(z-score/half-life)은 점수 미반영 표시 전용</div>",
    unsafe_allow_html=True,
)
st.divider()


@st.cache_data(ttl=3600, show_spinner=False)
def _find(long_ticker: str) -> pd.DataFrame:
    return find_short_candidates(long_ticker, top_n=10)


@st.cache_data(ttl=86400, show_spinner=False)
def _name_index():
    """종목명→티커 (입력 편의용). epsrev CO 재사용."""
    try:
        from epsrev.data.dashboard_data import CO
        return {info["n"]: t for t, info in CO.items()}
    except Exception:
        return {}


c1, c2 = st.columns([3, 1])
with c1:
    raw = st.text_input(
        "Long 종목", placeholder="티커 6자리 또는 종목명 (예: 042700, 한미반도체)",
        label_visibility="collapsed", key="shortscr_query",
    )
with c2:
    run = st.button("숏 후보 탐색", type="primary", width="stretch", key="shortscr_run")

# 딥링크: ?long=<티커|종목명> (다른 페이지에서 링크로 진입 가능)
if not raw:
    qp_long = st.query_params.get("long")
    if qp_long:
        raw = str(qp_long)

if not raw:
    st.caption(
        "Long 종목을 입력하면 밸류체인 CSV(동일 체인단계 > 동일 서브섹터 > 공급-고객 > 동일 대분류) "
        "기준 근접 후보를 찾고, pykrx 시세로 상관·pair beta 안정성·유동성을 계산해 구조점수로 정렬합니다."
    )
    st.stop()

query = raw.strip()
name_map = _name_index()
ticker = None
if query.isdigit():
    ticker = query.zfill(6)
elif query in name_map:
    ticker = name_map[query]
else:
    partial = [n for n in name_map if query in n]
    if len(partial) == 1:
        ticker = name_map[partial[0]]
    elif len(partial) > 1:
        st.warning(f"종목명이 여러 개 매칭됩니다: {', '.join(sorted(partial)[:8])} — 정확한 이름 또는 티커로 입력해주세요.")
        st.stop()

if ticker is None:
    st.error(f"'{query}' 종목을 찾지 못했습니다. 티커 6자리 또는 정확한 종목명으로 입력해주세요.")
    st.stop()

with st.spinner(f"{query} 기준 숏 후보 탐색 중... (pykrx 시세 조회, 최초 1회 30초~1분)"):
    df = _find(ticker)

if df is None or df.empty:
    st.info(
        f"'{query}'({ticker})의 밸류체인 이웃을 찾지 못했습니다 — "
        "data/value_chain/vc_nodes.csv에 등재된 종목만 지원합니다(현재 반도체·2차전지 등 커버리지)."
    )
    st.stop()

# ---- 커버리지 배지 (EPS stub → 분모 제외를 명시) ----
cov = float(df["coverage_ratio"].iloc[0]) if "coverage_ratio" in df.columns else None
if cov is not None and cov < 1.0:
    missing = [k for k in FACTOR_WEIGHTS if k == "eps_gap"]
    st.warning(
        f"⚠️ EPS Revision 미연동(stub) — 해당 가중치({FACTOR_WEIGHTS['eps_gap']:.0%})는 "
        f"0점이 아니라 **분모에서 제외**됩니다. coverage_ratio = {cov:.2f}, grade에 * 표기."
    )

# ---- 표시용 포맷 (None 안전 — stub이 있어도 깨지지 않음) ----
def _fmt(v, pattern="{:.2f}", none="—"):
    return none if v is None or (isinstance(v, float) and pd.isna(v)) else pattern.format(v)


display = pd.DataFrame(
    {
        "티커": df["ticker"],
        "종목명": df["name"],
        "관계": df["relation"],
        "근접성": df["proximity"].map(lambda v: _fmt(v, "{:.1f}")),
        "상관(120d)": df["corr_120d"].map(lambda v: _fmt(v)),
        "pair β": df["pair_beta"].map(lambda v: _fmt(v)),
        "β 안정성(std)": df["beta_stability"].map(lambda v: _fmt(v, "{:.3f}")),
        "ADV20(억)": df["adv20_eok"].map(lambda v: _fmt(v, "{:,.0f}")),
        "시총(억)": df["mktcap_eok"].map(lambda v: _fmt(v, "{:,.0f}")),
        "구조점수": df["structure_score"].map(lambda v: _fmt(v, "{:.1f}")),
        "coverage": df["coverage_ratio"].map(lambda v: _fmt(v, "{:.2f}")),
        "grade": df["grade"],
        "z-score†": df["z_score"].map(lambda v: _fmt(v)),
        "half-life(일)†": df["half_life_d"].map(lambda v: _fmt(v, "{:.0f}")),
        "기관20d(억)†": df["inst_net_20d_eok"].map(lambda v: _fmt(v, "{:,.0f}")),
        "외인20d(억)†": df["forgn_net_20d_eok"].map(lambda v: _fmt(v, "{:,.0f}")),
        "EPS갭": df["eps_gap"].map(lambda v: _fmt(v, none="stub")),
        "FwdPER": df["fwd_per"].map(lambda v: _fmt(v, none="stub")),
        "대차가능": df["borrowable"].map(lambda v: _fmt(v, "{}", none="stub")),
    }
)
st.dataframe(display, hide_index=True, width="stretch")

st.caption(
    "† 타이밍/수급 지표는 구조점수에 **미반영**(표시 전용). "
    "구조점수 = 관계 근접성 30% · 상관 20% · pair β 안정성 15% · 유동성 15% "
    "(+ EPS Revision 20%는 stub → 분모 제외). "
    "β 안정성은 시장 β가 아니라 **두 종목 간 pair return β**의 rolling(60d) 표준편차 기준. "
    "밸류(Fwd PER/PBR)는 점수에 넣지 않음. sizing/hedge β는 미구현(설계상 제외). "
    "'—'는 데이터 미가용(해당 팩터는 분모 제외), 'stub'은 추후 연동 예정 항목."
)

with st.expander("확장 예정 (stub)"):
    st.markdown(
        "- **EPS Revision 갭**: epsrev 스코어 연동 → coverage 1.0으로 상승\n"
        "- **12M Fwd PER/PBR**: 표시 전용 (구조점수 미반영 원칙 유지)\n"
        "- **실제 대차 가능 여부 / 공매도·대차 리스크**: 증권사 API·KRX 공매도 통계\n"
        "- **DART 이벤트**: 유증·CB·소송 등 이벤트 플래그"
    )
