"""
시장 시그널 — 당일 종가 확정 기준 52주 신고가/신저가 + 급등/급락
매일 15:40 장 마감 후 수집된 데이터(market_signal.json) 표시
"""

import os
import json
import sys
import warnings

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from style import COLORS, now_kst

warnings.filterwarnings("ignore")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIGNAL_PATH = os.path.join(PROJECT_ROOT, "data", "market_signal.json")


def load_signal():
    try:
        with open(SIGNAL_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def fmt_price(val):
    if val is None:
        return "-"
    return f"{int(val):,}"


def fmt_cap(val):
    if val is None or val == 0:
        return "-"
    if val >= 1e12:
        return f"{val/1e12:.1f}조"
    if val >= 1e8:
        return f"{val/1e8:.0f}억"
    return f"{val:,.0f}"


# ── 메인 ──────────────────────────────────────────────
st.markdown(f"""
<div class="ark-hero" style="padding: 32px 40px; margin-bottom: 24px;">
    <h1 style="font-size: 2rem; margin-bottom: 4px;">📡 시장 시그널</h1>
    <div class="subtitle">당일 종가 확정 기준 · 52주 신고가/신저가 · 급등/급락</div>
</div>
""", unsafe_allow_html=True)

data = load_signal()

if not data:
    st.warning("시장 시그널 데이터가 없습니다. 장 마감 후(15:40) 자동 수집됩니다.")
    st.stop()

# 헤더 정보
st.markdown(
    f'<div style="background:{COLORS["bg_card"]}; border:1px solid {COLORS["border"]}; '
    f'border-radius:12px; padding:20px; margin-bottom:20px; display:flex; gap:40px;">'
    f'<div><span style="color:{COLORS["text_muted"]}; font-size:0.85rem;">기준일</span>'
    f'<div style="color:#FFFFFF; font-size:1.5rem; font-weight:700;">{data["date"]}</div></div>'
    f'<div><span style="color:{COLORS["text_muted"]}; font-size:0.85rem;">시총 기준</span>'
    f'<div style="color:#FFFFFF; font-size:1.5rem; font-weight:700;">{data["min_cap"]}+</div></div>'
    f'<div><span style="color:{COLORS["text_muted"]}; font-size:0.85rem;">갱신 시각</span>'
    f'<div style="color:#FFFFFF; font-size:1.5rem; font-weight:700;">{data["updated"]}</div></div>'
    f'</div>',
    unsafe_allow_html=True,
)

# 요약 메트릭
m1, m2, m3, m4 = st.columns(4)
m1.metric("52주 신고가", f'{len(data["new_high"])}종목')
m2.metric("52주 신저가", f'{len(data["new_low"])}종목')
m3.metric(f'{data["surge_pct"]}%+ 급등', f'{len(data["surge"])}종목')
m4.metric(f'{data["surge_pct"]}%+ 급락', f'{len(data["plunge"])}종목')

st.markdown("---")

# ── 탭 구성 ───────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    f'📈 52주 신고가 ({len(data["new_high"])})',
    f'📉 52주 신저가 ({len(data["new_low"])})',
    f'🔴 급등 ({len(data["surge"])})',
    f'🔵 급락 ({len(data["plunge"])})',
])

def render_table(items, extra_col=None, color_positive=True):
    if not items:
        st.info("해당 종목이 없습니다.")
        return

    rows = []
    for r in items:
        row = {
            "코드": r["code"],
            "종목명": r["name"],
            "시장": r["market"],
            "종가": fmt_price(r["close"]),
            "등락률": f'{r["change_pct"]:+.1f}%',
            "시가총액": r["marcap_str"],
        }
        if extra_col and extra_col in r:
            row[extra_col] = fmt_price(r[extra_col])
        rows.append(row)

    df = pd.DataFrame(rows)

    if color_positive:
        color = COLORS["accent_red"]
        cond = lambda v: isinstance(v, str) and "+" in v
    else:
        color = "#4dabf7"
        cond = lambda v: isinstance(v, str) and "-" in v and "%" in v

    st.dataframe(
        df.style.map(
            lambda v: f"color: {color}; font-weight: 700" if cond(v) else "",
            subset=["등락률"],
        ),
        use_container_width=True,
        height=min(600, 35 * len(df) + 38),
        hide_index=True,
    )

with tab1:
    st.markdown(
        f'<div style="color:{COLORS["accent_red"]}; font-size:1.1rem; font-weight:700; '
        f'margin-bottom:12px;">당일 고가가 52주 최고가를 갱신한 종목</div>',
        unsafe_allow_html=True,
    )
    render_table(data["new_high"], extra_col="high_52w", color_positive=True)

with tab2:
    st.markdown(
        f'<div style="color:#4dabf7; font-size:1.1rem; font-weight:700; '
        f'margin-bottom:12px;">당일 저가가 52주 최저가를 갱신한 종목</div>',
        unsafe_allow_html=True,
    )
    render_table(data["new_low"], extra_col="low_52w", color_positive=False)

with tab3:
    st.markdown(
        f'<div style="color:{COLORS["accent_red"]}; font-size:1.1rem; font-weight:700; '
        f'margin-bottom:12px;">종가 기준 {data["surge_pct"]}% 이상 상승</div>',
        unsafe_allow_html=True,
    )
    render_table(data["surge"], color_positive=True)

with tab4:
    st.markdown(
        f'<div style="color:#4dabf7; font-size:1.1rem; font-weight:700; '
        f'margin-bottom:12px;">종가 기준 {data["surge_pct"]}% 이상 하락</div>',
        unsafe_allow_html=True,
    )
    render_table(data["plunge"], color_positive=False)

# ── 푸터 ──
st.markdown(f"""
<div class="ark-footer">
    ARK IMPACT 분석 대시보드 · 시장 시그널 · 매일 15:40 장 마감 후 갱신 · {now_kst()}
</div>
""", unsafe_allow_html=True)
