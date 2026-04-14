"""
시장 시그널 — 당일 52주 신고가/신저가 + 급등 종목
"""

import os
import sys
import warnings
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FT

import pandas as pd
import streamlit as st
import FinanceDataReader as fdr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from style import COLORS, styled_plotly, now_kst

warnings.filterwarnings("ignore")

# ── 데이터 로딩 ───────────────────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def load_today_market():
    """당일 KOSPI+KOSDAQ 전 종목 시세"""
    kospi = fdr.StockListing("KOSPI")
    kosdaq = fdr.StockListing("KOSDAQ")
    kospi["market"] = "KOSPI"
    kosdaq["market"] = "KOSDAQ"
    df = pd.concat([kospi, kosdaq], ignore_index=True)
    df = df.rename(columns={"Code": "code", "Name": "name", "Marcap": "marcap",
                            "ChagesRatio": "change_pct", "Close": "close",
                            "Open": "open", "High": "high", "Low": "low",
                            "Volume": "volume"})
    df = df[df["close"] > 0].copy()
    return df


def _fetch_52w(code, start_date):
    """단일 종목 52주 고가/저가"""
    try:
        hist = fdr.DataReader(code, start_date)
        if hist is not None and not hist.empty:
            return code, hist["High"].max(), hist["Low"].min()
    except Exception:
        pass
    return code, None, None


@st.cache_data(ttl=600, show_spinner=False)
def load_52w_data(codes):
    """종목 리스트의 52주 고가/저가 (병렬)"""
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    results = {}
    batch_size = 30

    for b in range(0, len(codes), batch_size):
        batch = codes[b:b + batch_size]
        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = {ex.submit(_fetch_52w, c, start_date): c for c in batch}
            for fut in futures:
                try:
                    code, h52, l52 = fut.result(timeout=15)
                    if h52 is not None:
                        results[code] = {"high_52w": h52, "low_52w": l52}
                except (FT, Exception):
                    pass

    return results


def fmt_cap(val):
    if pd.isna(val) or val == 0:
        return "-"
    if val >= 1e12:
        return f"{val/1e12:.1f}조"
    if val >= 1e8:
        return f"{val/1e8:.0f}억"
    return f"{val:,.0f}"


def fmt_price(val):
    if pd.isna(val):
        return "-"
    return f"{int(val):,}"


def change_color(v):
    if v > 0:
        return COLORS["accent_red"]
    elif v < 0:
        return "#4dabf7"
    return COLORS["text"]


# ── 메인 페이지 ───────────────────────────────────────
st.markdown(f"""
<div class="ark-hero" style="padding: 32px 40px; margin-bottom: 24px;">
    <h1 style="font-size: 2rem; margin-bottom: 4px;">📡 시장 시그널</h1>
    <div class="subtitle">당일 52주 신고가 / 신저가 / 급등 종목</div>
</div>
""", unsafe_allow_html=True)

# 데이터 로딩
with st.spinner("시세 로딩 중..."):
    today_df = load_today_market()

# 설정
ctrl1, ctrl2 = st.columns(2)
with ctrl1:
    min_cap_opt = {"전체": 0, "500억+": 5e10, "1000억+": 1e11, "3000억+": 3e11, "5000억+": 5e11, "1조+": 1e12}
    cap_label = st.selectbox("최소 시총", list(min_cap_opt.keys()), index=3)
    min_cap = min_cap_opt[cap_label]
with ctrl2:
    surge_pct = st.selectbox("급등 기준", ["5% 이상", "7% 이상", "10% 이상", "15% 이상"], index=1)
    surge_thresh = float(surge_pct.replace("% 이상", ""))

# 필터링
filtered = today_df.copy()
if min_cap > 0:
    filtered = filtered[filtered["marcap"] >= min_cap]

st.caption(f"분석 대상: {len(filtered):,}종목 | 기준: {now_kst()}")
st.markdown("---")

# ── 1. 급등 종목 ──────────────────────────────────────
st.markdown(f'<div class="section-header">종가 기준 {surge_pct} 급등</div>', unsafe_allow_html=True)

surge = filtered[filtered["change_pct"] >= surge_thresh].sort_values("change_pct", ascending=False).copy()

if surge.empty:
    st.info(f"오늘 {surge_pct} 급등 종목이 없습니다.")
else:
    surge_display = []
    for _, r in surge.iterrows():
        surge_display.append({
            "코드": r["code"],
            "종목명": r["name"],
            "시장": r["market"],
            "종가": fmt_price(r["close"]),
            "등락률": f"+{r['change_pct']:.1f}%",
            "거래대금": fmt_cap(r.get("amount", 0) if pd.notna(r.get("amount")) else 0),
            "시가총액": fmt_cap(r["marcap"]),
        })
    sdf = pd.DataFrame(surge_display)
    st.dataframe(
        sdf.style.applymap(
            lambda v: f"color: {COLORS['accent_red']}; font-weight: 700"
            if isinstance(v, str) and v.startswith("+") else "",
            subset=["등락률"],
        ),
        use_container_width=True,
        height=min(500, 35 * len(sdf) + 38),
        hide_index=True,
    )
    st.caption(f"총 {len(surge)}종목")

st.markdown("---")

# ── 2. 52주 신고가 / 신저가 ───────────────────────────
st.markdown(f'<div class="section-header">52주 신고가 / 신저가</div>', unsafe_allow_html=True)

codes = filtered["code"].tolist()

with st.spinner(f"52주 데이터 로딩 중 ({len(codes)}종목)..."):
    w52_data = load_52w_data(tuple(codes))

# 신고가/신저가 판별
new_highs = []
new_lows = []
for _, r in filtered.iterrows():
    w52 = w52_data.get(r["code"])
    if not w52:
        continue
    if r["high"] >= w52["high_52w"]:
        new_highs.append({
            "코드": r["code"],
            "종목명": r["name"],
            "시장": r["market"],
            "종가": fmt_price(r["close"]),
            "등락률": f"{r['change_pct']:+.1f}%",
            "52주 고가": fmt_price(w52["high_52w"]),
            "시가총액": fmt_cap(r["marcap"]),
        })
    if r["low"] <= w52["low_52w"]:
        new_lows.append({
            "코드": r["code"],
            "종목명": r["name"],
            "시장": r["market"],
            "종가": fmt_price(r["close"]),
            "등락률": f"{r['change_pct']:+.1f}%",
            "52주 저가": fmt_price(w52["low_52w"]),
            "시가총액": fmt_cap(r["marcap"]),
        })

col_high, col_low = st.columns(2)

with col_high:
    st.markdown(
        f'<div style="color:{COLORS["accent_red"]}; font-size:1.1rem; font-weight:700; '
        f'margin-bottom:12px;">52주 신고가 ({len(new_highs)}종목)</div>',
        unsafe_allow_html=True,
    )
    if new_highs:
        hdf = pd.DataFrame(new_highs)
        st.dataframe(
            hdf.style.applymap(
                lambda v: f"color: {COLORS['accent_red']}; font-weight: 600"
                if isinstance(v, str) and v.startswith("+") else "",
                subset=["등락률"],
            ),
            use_container_width=True,
            height=min(500, 35 * len(hdf) + 38),
            hide_index=True,
        )
    else:
        st.info("52주 신고가 종목이 없습니다.")

with col_low:
    st.markdown(
        f'<div style="color:#4dabf7; font-size:1.1rem; font-weight:700; '
        f'margin-bottom:12px;">52주 신저가 ({len(new_lows)}종목)</div>',
        unsafe_allow_html=True,
    )
    if new_lows:
        ldf = pd.DataFrame(new_lows)
        st.dataframe(
            ldf.style.applymap(
                lambda v: "color: #4dabf7; font-weight: 600"
                if isinstance(v, str) and "-" in v and "%" in v else "",
                subset=["등락률"],
            ),
            use_container_width=True,
            height=min(500, 35 * len(ldf) + 38),
            hide_index=True,
        )
    else:
        st.info("52주 신저가 종목이 없습니다.")

# ── 3. 급락 종목 ──────────────────────────────────────
st.markdown("---")
st.markdown(f'<div class="section-header">종가 기준 {surge_pct} 급락</div>', unsafe_allow_html=True)

plunge = filtered[filtered["change_pct"] <= -surge_thresh].sort_values("change_pct").copy()

if plunge.empty:
    st.info(f"오늘 {surge_pct} 급락 종목이 없습니다.")
else:
    plunge_display = []
    for _, r in plunge.iterrows():
        plunge_display.append({
            "코드": r["code"],
            "종목명": r["name"],
            "시장": r["market"],
            "종가": fmt_price(r["close"]),
            "등락률": f"{r['change_pct']:.1f}%",
            "거래대금": fmt_cap(r.get("amount", 0) if pd.notna(r.get("amount")) else 0),
            "시가총액": fmt_cap(r["marcap"]),
        })
    pdf = pd.DataFrame(plunge_display)
    st.dataframe(
        pdf.style.applymap(
            lambda v: "color: #4dabf7; font-weight: 700"
            if isinstance(v, str) and v.startswith("-") else "",
            subset=["등락률"],
        ),
        use_container_width=True,
        height=min(500, 35 * len(pdf) + 38),
        hide_index=True,
    )
    st.caption(f"총 {len(plunge)}종목")

# ── 푸터 ──
st.markdown(f"""
<div class="ark-footer">
    ARK IMPACT 분석 대시보드 · 시장 시그널 · 데이터: FinanceDataReader · {now_kst()}
</div>
""", unsafe_allow_html=True)
