"""
미장 → 국장 연계 분석
- 메인: 산업/테마별 어제 미국 핵심 이슈 + 영향 KR 종목 (Claude 분석)
- 보조: US 섹터 ETF 등락 한 줄, 선택 테마 KR 종목의 β/상관 (expander)
"""

import json
import os
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import FinanceDataReader as fdr

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from style import COLORS, now_kst

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).parent.parent
US_EVENTS_PATH = PROJECT_ROOT / "data" / "us_events.json"
THEMES_PATH = PROJECT_ROOT / "data" / "themes.json"
US_KR_SECTOR_MAP_PATH = PROJECT_ROOT / "data" / "us_kr_sector_map.json"

BETA_WINDOW = 90


# ── 데이터 로딩 ─────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def load_events():
    if not US_EVENTS_PATH.exists():
        return None
    with open(US_EVENTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(ttl=86400, show_spinner=False)
def load_themes_def():
    with open(THEMES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["themes"]


@st.cache_data(ttl=86400, show_spinner=False)
def load_sector_map():
    if US_KR_SECTOR_MAP_PATH.exists():
        with open(US_KR_SECTOR_MAP_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


@st.cache_data(ttl=3600, show_spinner=False)
def load_us_etf_change():
    """전일 미국 섹터 ETF 등락"""
    if not HAS_YF:
        return {}
    sector_map = load_sector_map()
    etfs = [k for k in sector_map.keys() if not k.startswith("_")]
    out = {}
    for etf in etfs:
        try:
            h = yf.Ticker(etf).history(period="5d")
            if len(h) < 2:
                continue
            last = h["Close"].iloc[-1]
            prev = h["Close"].iloc[-2]
            ret = (last - prev) / prev * 100 if prev else 0
            out[etf] = {
                "name": sector_map[etf].get("name_kr", sector_map[etf].get("name", etf)),
                "ret_pct": ret,
                "as_of": h.index[-1].strftime("%Y-%m-%d"),
            }
        except Exception:
            pass
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def load_us_etf_history(etf, days=BETA_WINDOW + 30):
    if not HAS_YF:
        return None
    try:
        h = yf.Ticker(etf).history(period=f"{days}d")
        if h.empty:
            return None
        s = h["Close"]
        s.index = s.index.tz_localize(None).normalize()
        return s
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def load_kr_price(code, days=BETA_WINDOW + 30):
    start = (datetime.now() - timedelta(days=days + 30)).strftime("%Y-%m-%d")
    try:
        df = fdr.DataReader(code, start)
        if df is None or df.empty:
            return None
        s = df["Close"]
        s.index = pd.to_datetime(s.index).normalize()
        return s
    except Exception:
        return None


def calc_beta_corr(kr_s, us_s, window=BETA_WINDOW, lag=1):
    if kr_s is None or us_s is None or kr_s.empty or us_s.empty:
        return (np.nan, np.nan)
    kr_r = kr_s.pct_change().dropna()
    us_r = us_s.pct_change().dropna()
    if lag > 0:
        us_r = us_r.shift(lag).dropna()
    a = pd.concat([kr_r, us_r], axis=1, join="inner").dropna()
    a.columns = ["kr", "us"]
    if len(a) < 20:
        return (np.nan, np.nan)
    a = a.tail(window)
    var_us = a["us"].var()
    if var_us == 0 or pd.isna(var_us):
        return (np.nan, np.nan)
    return (a["kr"].cov(a["us"]) / var_us, a["kr"].corr(a["us"]))


# ── 헬퍼 ────────────────────────────────────────
SENT_COLOR = {
    "positive": COLORS["accent_green"],
    "negative": COLORS["accent_red"],
    "mixed": COLORS["accent_yellow"],
    "neutral": COLORS["text_muted"],
}
SENT_LABEL = {"positive": "긍정", "negative": "부정", "mixed": "혼조", "neutral": "중립"}
IMPACT_COLOR = {
    "high": COLORS["accent_red"],
    "medium": COLORS["accent_yellow"],
    "low": COLORS["text_muted"],
}
IMPACT_LABEL = {"high": "강", "medium": "중", "low": "약"}
DIR_COLOR = {
    "positive": COLORS["accent_green"],
    "negative": COLORS["accent_red"],
    "neutral": COLORS["text_muted"],
}
DIR_LABEL = {"positive": "수혜", "negative": "피해", "neutral": "중립"}


def render_theme_card(theme):
    """단일 테마 카드 HTML"""
    sent = theme.get("sentiment", "neutral")
    impact = theme.get("impact_strength", "low")
    sect_color = SENT_COLOR.get(sent, COLORS["text_muted"])

    # 핵심 이슈 글머리
    issues_html = ""
    for issue in theme.get("key_issues", [])[:5]:
        text = issue.get("text", "")
        srcs = issue.get("source_tickers", []) or []
        src_str = ""
        if srcs:
            src_str = (
                f' <span style="color:{COLORS["text_muted"]}; font-size:0.75rem;">'
                f'[{" · ".join(srcs)}]</span>'
            )
        issues_html += (
            f'<li style="margin:6px 0; line-height:1.55;">'
            f'<span style="color:#FFF; font-size:0.92rem;">{text}</span>{src_str}'
            f'</li>'
        )
    if not issues_html:
        issues_html = (
            f'<li style="color:{COLORS["text_muted"]}; font-size:0.85rem; '
            f'list-style:none; padding-left:0;">'
            f'어제 이 테마에서 주목할 만한 이슈가 없었습니다.</li>'
        )

    # KR 종목
    kr_tickers = theme.get("kr_tickers", [])[:8]
    kr_chips = ""
    for kt in kr_tickers:
        code = kt.get("code", "")
        name = kt.get("name", "")
        direction = kt.get("direction", "neutral")
        c = DIR_COLOR.get(direction, COLORS["text_muted"])
        dlabel = DIR_LABEL.get(direction, "-")
        kr_chips += (
            f'<span style="display:inline-flex; align-items:center; gap:6px; '
            f'background:rgba(255,255,255,0.04); border:1px solid {c}33; '
            f'border-left:3px solid {c}; padding:5px 10px; margin:3px; '
            f'border-radius:6px; font-size:0.82rem;">'
            f'<span style="color:{COLORS["text_muted"]}; font-size:0.74rem;">{code}</span>'
            f'<span style="color:#FFF;">{name}</span>'
            f'<span style="color:{c}; font-weight:600; font-size:0.74rem;">{dlabel}</span>'
            f'</span>'
        )

    # 영향 KR 섹터 chip
    affected = theme.get("affected_kr_sectors", []) or []
    sec_chips = " ".join(
        f'<span style="display:inline-block; background:{COLORS["bg_card"]}; '
        f'border:1px solid {COLORS["border"]}; border-radius:12px; '
        f'padding:2px 9px; margin:2px; font-size:0.74rem; color:{COLORS["text_muted"]};">'
        f'{s}</span>' for s in affected
    )

    html = (
        f'<div style="background:{COLORS["bg_card"]}; border:1px solid {COLORS["border"]}; '
        f'border-left:5px solid {sect_color}; border-radius:0 12px 12px 0; '
        f'padding:20px 24px; margin-bottom:18px;">'
        # 헤더: 이름 + 배지
        f'<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">'
        f'<div>'
        f'<span style="color:#FFF; font-size:1.15rem; font-weight:700;">{theme.get("name", "")}</span>'
        f'</div>'
        f'<div style="display:flex; gap:10px; align-items:center;">'
        f'<span style="color:{sect_color}; font-weight:700; font-size:0.85rem;">{SENT_LABEL.get(sent, "-")}</span>'
        f'<span style="color:{IMPACT_COLOR.get(impact, COLORS["text_muted"])}; '
        f'font-weight:700; font-size:0.85rem;">영향 {IMPACT_LABEL.get(impact, "-")}</span>'
        f'<span style="color:{COLORS["text_muted"]}; font-size:0.78rem;">'
        f'이벤트 {theme.get("events_count", 0)}건</span>'
        f'</div>'
        f'</div>'
        # 설명
        f'<div style="color:{COLORS["text_muted"]}; font-size:0.78rem; margin-bottom:10px;">'
        f'{theme.get("desc", "")}</div>'
        # 요약
        f'<div style="color:#FFF; font-size:0.93rem; line-height:1.65; '
        f'background:rgba(255,255,255,0.025); padding:12px 14px; border-radius:8px; '
        f'margin-bottom:14px;">{theme.get("summary", "")}</div>'
        # 핵심 이슈
        f'<div style="color:{COLORS["accent"]}; font-size:0.82rem; font-weight:700; '
        f'margin-bottom:6px;">핵심 이슈</div>'
        f'<ul style="margin:0 0 14px 0; padding-left:20px;">{issues_html}</ul>'
        # 영향 KR 섹터
        f'{("<div style=margin-bottom:10px;>" + sec_chips + "</div>") if sec_chips else ""}'
        # KR 종목
        f'<div style="color:{COLORS["accent"]}; font-size:0.82rem; font-weight:700; '
        f'margin:10px 0 6px;">영향 받을 한국 종목</div>'
        f'<div>{kr_chips if kr_chips else "<span style=color:" + COLORS["text_muted"] + "; font-size:0.85rem;>(추천 없음)</span>"}</div>'
        f'</div>'
    )
    return html


# ── 메인 페이지 ─────────────────────────────────
st.markdown(f"""
<div class="ark-hero" style="padding: 30px 36px; margin-bottom: 20px;">
    <h1 style="font-size: 1.95rem; margin-bottom: 4px;">🌎 미장 시황</h1>
    <div class="subtitle">산업/테마별 어제 미국 이슈와 한국 영향</div>
</div>
""", unsafe_allow_html=True)

events_data = load_events()
themes_def = load_themes_def()

if not events_data:
    st.info(
        "데이터가 없습니다. 터미널에서 다음 실행:\n\n"
        "```bash\n"
        "cd /Users/yougsu1/kosdaq150_predictor\n"
        "python3 scripts/update_us_events.py\n"
        "```"
    )
    st.stop()

# 헤더 정보
themes_list = events_data.get("themes", [])
date = events_data.get("date", "-")
updated = events_data.get("updated", "-")
ticker_count = events_data.get("ticker_count", 0)
event_count = events_data.get("event_count", 0)

cols = st.columns(4)
cols[0].metric("기준일", date)
cols[1].metric("미국 티커", f"{ticker_count}개")
cols[2].metric("수집 이벤트", f"{event_count}건")
cols[3].metric("분석 테마", f"{len(themes_list)}개")
st.markdown(
    f'<div style="color:{COLORS["text_muted"]}; font-size:0.78rem; margin-top:-6px;">'
    f'최종 갱신: {updated} (KST)</div>',
    unsafe_allow_html=True,
)

# ── 1) 미국 섹터 ETF 한 줄 ──────────────────────
st.markdown("---")
st.markdown(f'<div class="section-header">전일 미국 섹터 ETF</div>', unsafe_allow_html=True)

with st.spinner("미국 섹터 ETF 시세..."):
    etf_change = load_us_etf_change()

if etf_change:
    sorted_etfs = sorted(etf_change.items(), key=lambda x: x[1]["ret_pct"], reverse=True)
    chips = ""
    for etf, info in sorted_etfs:
        ret = info["ret_pct"]
        c = COLORS["accent_green"] if ret >= 0 else COLORS["accent_red"]
        arrow = "▲" if ret >= 0 else "▼"
        chips += (
            f'<span style="display:inline-flex; gap:6px; align-items:baseline; '
            f'background:{COLORS["bg_card"]}; border:1px solid {COLORS["border"]}; '
            f'border-radius:8px; padding:6px 12px; margin:3px; font-size:0.82rem;">'
            f'<span style="color:#FFF; font-weight:700;">{etf}</span>'
            f'<span style="color:{COLORS["text_muted"]}; font-size:0.74rem;">{info["name"]}</span>'
            f'<span style="color:{c}; font-weight:700;">{arrow} {ret:+.2f}%</span>'
            f'</span>'
        )
    st.markdown(f'<div>{chips}</div>', unsafe_allow_html=True)
else:
    st.caption("ETF 시세 로딩 실패")

# ── 2) 테마 카드 그리드 (메인) ───────────────────
st.markdown("---")
st.markdown(f'<div class="section-header">산업/테마별 분석</div>', unsafe_allow_html=True)

if not themes_list:
    st.warning(
        "테마 분석 결과가 없습니다. `python3 scripts/update_us_events.py` 실행 또는 "
        "ANTHROPIC_API_KEY 확인."
    )
else:
    # 필터
    flt_c1, flt_c2 = st.columns([1, 1])
    with flt_c1:
        sent_flt = st.multiselect(
            "감성",
            ["긍정", "부정", "혼조", "중립"],
            default=["긍정", "부정", "혼조", "중립"],
            key="theme_sent_flt",
        )
    with flt_c2:
        impact_flt = st.multiselect(
            "영향 강도",
            ["강", "중", "약"],
            default=["강", "중", "약"],
            key="theme_impact_flt",
        )

    sent_filter_keys = [k for k, v in SENT_LABEL.items() if v in sent_flt]
    impact_filter_keys = [k for k, v in IMPACT_LABEL.items() if v in impact_flt]

    # 정렬: 영향 강 → 감성(긍정/부정 우선) → 이벤트 많은 순
    impact_order = {"high": 0, "medium": 1, "low": 2}
    sent_priority = {"positive": 0, "negative": 0, "mixed": 1, "neutral": 2}
    filtered = [
        t for t in themes_list
        if t.get("sentiment") in sent_filter_keys
        and t.get("impact_strength") in impact_filter_keys
    ]
    filtered.sort(key=lambda t: (
        impact_order.get(t.get("impact_strength"), 9),
        sent_priority.get(t.get("sentiment"), 9),
        -t.get("events_count", 0),
    ))

    if not filtered:
        st.info("필터 조건에 맞는 테마가 없습니다.")
    else:
        for t in filtered:
            st.markdown(render_theme_card(t), unsafe_allow_html=True)

# ── 3) β/상관 분석 (보조, expander) ────────────
st.markdown("---")
with st.expander("선택 테마의 KR 종목 — β·60일 상관 (US 섹터 ETF 기준)", expanded=False):
    theme_options = {t["id"]: t["name"] for t in themes_def}
    sel_theme_id = st.selectbox(
        "테마 선택",
        list(theme_options.keys()),
        format_func=lambda x: theme_options[x],
        key="beta_theme_sel",
    )

    # 테마 → 가장 가까운 US ETF 자동 매칭
    THEME_TO_ETF = {
        "semi_logic_ai": "XLK", "semi_memory": "XLK", "semi_equipment": "XLK",
        "power_grid": "XLI", "industrial_defense": "XLI",
        "ev_battery": "XLY", "solar_renewable": "XLU",
        "real_estate": "XLRE", "platform_bigtech": "XLK",
        "energy_oil": "XLE", "materials_chem": "XLB",
        "healthcare": "XLV", "financial": "XLF", "consumer": "XLP",
    }
    ref_etf = THEME_TO_ETF.get(sel_theme_id, "XLK")
    st.caption(f"기준 ETF: **{ref_etf}** ({load_sector_map().get(ref_etf, {}).get('name', '-')})")

    sel_theme = next((t for t in themes_def if t["id"] == sel_theme_id), None)
    if sel_theme:
        anchors = sel_theme.get("kr_anchor_tickers", [])
        # us_events.json의 같은 테마에서 추가 KR 종목 발견
        ev_theme = next((t for t in themes_list if t.get("id") == sel_theme_id), None)
        extra_codes = set()
        if ev_theme:
            for kt in ev_theme.get("kr_tickers", []):
                code = kt.get("code", "")
                if code and code not in [a["code"] for a in anchors]:
                    extra_codes.add((code, kt.get("name", "")))
        # 합치기
        kr_codes = [(a["code"], a["name"]) for a in anchors] + list(extra_codes)

        if kr_codes:
            with st.spinner("가격 데이터 로딩..."):
                us_series = load_us_etf_history(ref_etf)
                rows = []
                for code, name in kr_codes:
                    kr_s = load_kr_price(code)
                    beta, corr = calc_beta_corr(kr_s, us_series)
                    rows.append({
                        "코드": code, "종목명": name,
                        "β": f"{beta:+.2f}" if pd.notna(beta) else "-",
                        "60일 상관": f"{corr:+.2f}" if pd.notna(corr) else "-",
                    })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            st.caption(
                f"β: {ref_etf} 1%p 변동 시 한국 종목 평균 변동폭. β≥1.5면 매우 민감. "
                f"1일 시차 적용 (US t-1 → KR t)."
            )

# ── 4) Raw 이벤트 (옵션) ────────────────────────
with st.expander("Raw 이벤트 원본 데이터", expanded=False):
    raw = events_data.get("raw_events", [])
    st.caption(f"전체 {len(raw)}건 — 가격 변동/어닝/뉴스 원본")
    # 티커별로 그룹화
    by_ticker = {}
    for e in raw:
        by_ticker.setdefault(e["ticker"], []).append(e)
    for tk in sorted(by_ticker.keys()):
        st.markdown(f"**{tk}** ({len(by_ticker[tk])} events)")
        st.json(by_ticker[tk], expanded=False)

# 푸터
st.markdown(f"""
<div class="ark-footer">
    ARK IMPACT · 미장-국장 연계 분석 · 데이터: yfinance + Claude API + FinanceDataReader · {now_kst()}
</div>
""", unsafe_allow_html=True)
