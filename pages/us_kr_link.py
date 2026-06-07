"""
모닝 마켓 체크 — 상장주식 운용팀 모닝미팅용 시장 점검 코크핏

흐름(top-down):
  1) 🌅 간밤 시장 스냅샷  — 지수·금리·환율·유가·금·VIX + 위험선호 판정
  2) 📌 오늘의 논점       — 8개 대주제 종합 AI 브리핑 (오늘 미팅에서 짚을 핵심)
  3) 🇺🇸 대주제별 심층    — 트리거·확산성·지속성 카드 (기존 분석 유지)
  4) 📅 오늘/금주 일정    — 발표 예정 지표·이벤트 (macro_calendar)
  5) 🇰🇷 한국 수급·특징주 — 전일 급등락·신고저가 (market_signal)
  + 보조: β/상관, Raw 이벤트 (expander)
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
import plotly.graph_objects as go

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from style import COLORS, now_kst, styled_plotly

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).parent.parent
DATA = PROJECT_ROOT / "data"
US_EVENTS_PATH = DATA / "us_events.json"
THEMES_PATH = DATA / "themes.json"
US_KR_SECTOR_MAP_PATH = DATA / "us_kr_sector_map.json"
MACRO_CAL_PATH = DATA / "macro_calendar.json"
MARKET_SIGNAL_PATH = DATA / "market_signal.json"

BETA_WINDOW = 90


# ── 데이터 로딩 ─────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def load_events():
    if not US_EVENTS_PATH.exists():
        return None
    with open(US_EVENTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(ttl=86400, show_spinner=False)
def load_themes_file():
    with open(THEMES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(ttl=86400, show_spinner=False)
def load_sector_map():
    if US_KR_SECTOR_MAP_PATH.exists():
        with open(US_KR_SECTOR_MAP_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


@st.cache_data(ttl=600, show_spinner=False)
def load_json_safe(path_str):
    p = Path(path_str)
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# 간밤 시장 스냅샷 티커 (지수·변동성·환율)
SNAPSHOT_TICKERS = [
    ("^GSPC", "S&P 500", "index"),
    ("^IXIC", "나스닥", "index"),
    ("^DJI", "다우", "index"),
    ("^RUT", "러셀 2000", "index"),
    ("^VIX", "VIX", "vix"),
    ("DX-Y.NYB", "달러인덱스", "level"),
    ("KRW=X", "원/달러", "fx"),
]

# 매크로 — 금리 (美 국채 수익률 5/10/30년)
RATE_TICKERS = [
    ("^FVX", "미 5년물", "yield"),
    ("^TNX", "미 10년물", "yield"),
    ("^TYX", "미 30년물", "yield"),
]

# 매크로 — 원자재
COMMODITY_TICKERS = [
    ("CL=F", "WTI", "commodity"),
    ("BZ=F", "브렌트유", "commodity"),
    ("NG=F", "천연가스", "commodity"),
    ("GC=F", "금", "commodity"),
    ("SI=F", "은", "commodity"),
    ("HG=F", "구리", "commodity"),
]


def _fetch_quotes(tickers):
    if not HAS_YF:
        return []
    out = []
    for t, name, kind in tickers:
        try:
            h = yf.Ticker(t).history(period="5d")
            if len(h) < 2:
                continue
            last = float(h["Close"].iloc[-1])
            prev = float(h["Close"].iloc[-2])
            chg = last - prev
            pct = (chg / prev * 100) if prev else 0.0
            out.append({"name": name, "kind": kind, "last": last, "chg": chg, "pct": pct,
                        "as_of": h.index[-1].strftime("%Y-%m-%d")})
        except Exception:
            pass
    return out


@st.cache_data(ttl=1800, show_spinner=False)
def load_market_snapshot():
    return _fetch_quotes(SNAPSHOT_TICKERS)


@st.cache_data(ttl=1800, show_spinner=False)
def load_macro_history(which, period="6mo"):
    """금리/원자재 6개월 종가 히스토리 (카드 + 차트 공용)."""
    tickers = RATE_TICKERS if which == "rates" else COMMODITY_TICKERS
    if not HAS_YF:
        return None
    data = {}
    for t, name, kind in tickers:
        try:
            h = yf.Ticker(t).history(period=period)
            if h.empty:
                continue
            s = h["Close"].copy()
            try:
                s.index = s.index.tz_localize(None)
            except Exception:
                pass
            data[name] = s
        except Exception:
            pass
    if not data:
        return None
    return pd.DataFrame(data)


def quotes_from_df(df, tickers):
    """히스토리 DataFrame에서 카드용 시세(last/prev/chg/pct) 추출."""
    if df is None:
        return []
    out = []
    for t, name, kind in tickers:
        if name not in df.columns:
            continue
        vals = df[name].dropna()
        if len(vals) < 2:
            continue
        last = float(vals.iloc[-1]); prev = float(vals.iloc[-2])
        chg = last - prev; pct = (chg / prev * 100) if prev else 0.0
        out.append({"name": name, "kind": kind, "last": last, "chg": chg, "pct": pct})
    return out


MACRO_PALETTE = [COLORS["accent"], COLORS["accent_green"], COLORS["accent_yellow"],
                 COLORS["accent_red"], "#A78BFA", "#F472B6"]


def build_rate_chart(df):
    fig = go.Figure()
    cols = [n for _, n, _ in RATE_TICKERS if df is not None and n in df.columns]
    for i, name in enumerate(cols):
        s = df[name].dropna()
        fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines", name=name,
                                 line=dict(color=MACRO_PALETTE[i % len(MACRO_PALETTE)], width=2)))
    fig.update_layout(title="美 국채 수익률 추이 (6M)", yaxis_title="%",
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    return fig


# 해외 상장 한국주 (GDR/ADR) — 간밤 외국인 시각 = 한국 개장 선행지표
OVERSEAS_KR = [
    {"ticker": "SMSN.IL", "name": "삼성전자", "kr": "005930", "type": "GDR", "venue": "런던"},
    {"ticker": "SMSD.IL", "name": "삼성전자우", "kr": "005935", "type": "GDR", "venue": "런던"},
    {"ticker": "PKX", "name": "POSCO홀딩스", "kr": "005490", "type": "ADR", "venue": "NYSE"},
    {"ticker": "KB", "name": "KB금융", "kr": "105560", "type": "ADR", "venue": "NYSE"},
    {"ticker": "SHG", "name": "신한지주", "kr": "055550", "type": "ADR", "venue": "NYSE"},
    {"ticker": "WF", "name": "우리금융", "kr": "316140", "type": "ADR", "venue": "NYSE"},
    {"ticker": "LPL", "name": "LG디스플레이", "kr": "034220", "type": "ADR", "venue": "NYSE"},
    {"ticker": "KT", "name": "KT", "kr": "030200", "type": "ADR", "venue": "NYSE"},
    {"ticker": "SKM", "name": "SK텔레콤", "kr": "017670", "type": "ADR", "venue": "NYSE"},
    {"ticker": "KEP", "name": "한국전력", "kr": "015760", "type": "ADR", "venue": "NYSE"},
]


@st.cache_data(ttl=1800, show_spinner=False)
def load_overseas_kr():
    if not HAS_YF:
        return []
    out = []
    for it in OVERSEAS_KR:
        try:
            h = yf.Ticker(it["ticker"]).history(period="5d")
            if len(h) < 2:
                continue
            last = float(h["Close"].iloc[-1])
            prev = float(h["Close"].iloc[-2])
            ret = (last - prev) / prev * 100 if prev else 0.0
            out.append({**it, "last": last, "ret": ret,
                        "asof": h.index[-1].strftime("%m/%d")})
        except Exception:
            pass
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def load_us_etf_change():
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


# ── 라벨/색상 ────────────────────────────────────
SENT_COLOR = {"positive": COLORS["accent_green"], "negative": COLORS["accent_red"],
              "mixed": COLORS["accent_yellow"], "neutral": COLORS["text_muted"]}
SENT_LABEL = {"positive": "긍정", "negative": "부정", "mixed": "혼조", "neutral": "중립"}
IMPACT_COLOR = {"high": COLORS["accent_red"], "medium": COLORS["accent_yellow"], "low": COLORS["text_muted"]}
IMPACT_LABEL = {"high": "강", "medium": "중", "low": "약"}
DIR_COLOR = {"positive": COLORS["accent_green"], "negative": COLORS["accent_red"], "neutral": COLORS["text_muted"]}
DIR_LABEL = {"positive": "수혜", "negative": "피해", "neutral": "중립"}
SPREAD_COLOR = {"대주제확산": COLORS["accent"], "섹터전반": COLORS["accent_yellow"], "종목한정": COLORS["text_muted"]}
PERSIST_COLOR = {"구조적": COLORS["accent_green"], "지속관찰": COLORS["accent_yellow"], "일회성": COLORS["text_muted"]}

RISK_LABEL = {"risk_on": "위험선호 Risk-On", "risk_off": "위험회피 Risk-Off",
              "mixed": "혼조 Mixed", "neutral": "중립 Neutral"}
RISK_COLOR = {"risk_on": COLORS["accent_green"], "risk_off": COLORS["accent_red"],
              "mixed": COLORS["accent_yellow"], "neutral": COLORS["text_muted"]}


def _badge(text, color, filled=False):
    if filled:
        return (f'<span style="display:inline-block; background:{color}22; border:1px solid {color}; '
                f'color:{color}; border-radius:5px; padding:1px 7px; margin-right:5px; font-size:0.68rem; '
                f'font-weight:700; white-space:nowrap;">{text}</span>')
    return (f'<span style="display:inline-block; background:rgba(0,0,0,0.04); '
            f'border:1px solid {COLORS["border"]}; color:{COLORS["text_muted"]}; border-radius:5px; '
            f'padding:1px 7px; margin-right:5px; font-size:0.68rem; white-space:nowrap;">{text}</span>')


# ── 1) 간밤 시장 스냅샷 ──────────────────────────
def _fmt_snapshot(it):
    kind, last, chg, pct = it["kind"], it["last"], it["chg"], it["pct"]
    if kind == "index":
        val = f"{last:,.0f}"; delta = f"{pct:+.2f}%"
    elif kind == "commodity":
        val = f"{last:,.1f}"; delta = f"{pct:+.2f}%"
    elif kind == "vix":
        val = f"{last:.1f}"; delta = f"{pct:+.1f}%"
    elif kind == "yield":
        val = f"{last:.2f}%"; delta = f"{chg*100:+.1f}bp"
    elif kind == "fx":
        val = f"{last:,.1f}"; delta = f"{pct:+.2f}%"
    else:  # level (DXY)
        val = f"{last:.2f}"; delta = f"{pct:+.2f}%"
    return val, delta


def render_snapshot_card(it):
    val, delta = _fmt_snapshot(it)
    # 색상: 지수·원자재는 등락 색상 / 리스크게이지(VIX·금리·달러·환율)는 중립(방향 화살표만)
    if it["kind"] in ("index", "commodity"):
        c = COLORS["accent_green"] if it["pct"] >= 0 else COLORS["accent_red"]
    else:
        c = COLORS["text"]  # 중립 — 해석은 사용자 몫
    arrow = "▲" if it["chg"] >= 0 else "▼"
    return (
        f'<div style="background:{COLORS["bg_card"]}; border:1px solid {COLORS["border"]}; '
        f'border-radius:10px; padding:10px 14px; min-width:120px; flex:1;">'
        f'<div style="color:{COLORS["text_muted"]}; font-size:0.74rem; margin-bottom:2px;">{it["name"]}</div>'
        f'<div style="color:#16202E; font-size:1.15rem; font-weight:700; line-height:1.2;">{val}</div>'
        f'<div style="color:{c}; font-size:0.8rem; font-weight:600;">{arrow} {delta}</div>'
        f'</div>'
    )


# ── 2) 오늘의 논점 (브리핑) ──────────────────────
def render_brief(brief):
    risk = brief.get("risk_sentiment", "neutral")
    rc = RISK_COLOR.get(risk, COLORS["text_muted"])
    rlabel = RISK_LABEL.get(risk, risk)
    read = brief.get("market_read", "")

    html = (
        f'<div style="background:linear-gradient(135deg,{COLORS["bg_card"]}, {COLORS["bg_card_hover"]}); '
        f'border:1px solid {rc}55; border-left:5px solid {rc}; border-radius:0 14px 14px 0; '
        f'padding:18px 22px; margin-bottom:16px;">'
        f'<div style="display:flex; align-items:center; gap:12px; margin-bottom:8px;">'
        f'<span style="color:{rc}; font-weight:800; font-size:0.9rem; border:1px solid {rc}; '
        f'border-radius:6px; padding:2px 10px;">{rlabel}</span>'
        f'</div>'
        f'<div style="color:#16202E; font-size:1.0rem; line-height:1.6;">{read}</div>'
        f'</div>'
    )

    for i, tp in enumerate(brief.get("talking_points", []), 1):
        groups = tp.get("groups", []) or []
        gchips = "".join(_badge(g, COLORS["accent"]) for g in groups)
        watch = tp.get("watch", "")
        watch_html = ""
        if watch:
            watch_html = (
                f'<div style="margin-top:8px; padding:7px 11px; background:rgba(0,210,255,0.06); '
                f'border-radius:7px; color:{COLORS["accent"]}; font-size:0.83rem;">'
                f'👁 <b>오늘 볼 것</b> · {watch}</div>'
            )
        html += (
            f'<div style="background:{COLORS["bg_card"]}; border:1px solid {COLORS["border"]}; '
            f'border-radius:10px; padding:14px 18px; margin-bottom:10px;">'
            f'<div style="display:flex; gap:10px; align-items:baseline;">'
            f'<span style="color:{COLORS["accent"]}; font-weight:800; font-size:1.05rem;">{i}</span>'
            f'<span style="color:#16202E; font-weight:700; font-size:0.98rem;">{tp.get("title","")}</span>'
            f'</div>'
            f'<div style="color:{COLORS["text"]}; font-size:0.9rem; line-height:1.6; margin:6px 0 8px 22px;">'
            f'{tp.get("detail","")}</div>'
            f'<div style="margin-left:22px;">{gchips}</div>'
            f'<div style="margin-left:22px;">{watch_html}</div>'
            f'</div>'
        )
    return html


# ── 3) 대주제 카드 ───────────────────────────────
def render_group_card(group):
    sent = group.get("sentiment", "neutral")
    impact = group.get("impact_strength", "low")
    sect_color = SENT_COLOR.get(sent, COLORS["text_muted"])

    sub_themes = group.get("sub_themes", []) or []
    sub_str = ""
    if sub_themes:
        names = " · ".join(s.get("name", "") if isinstance(s, dict) else str(s) for s in sub_themes)
        sub_str = (f'<div style="color:{COLORS["text_muted"]}; font-size:0.74rem; margin-bottom:10px;">'
                   f'포함: {names}</div>')

    issues_html = ""
    for issue in group.get("key_issues", [])[:5]:
        text = issue.get("text", "")
        srcs = issue.get("source_tickers", []) or []
        trigger = issue.get("trigger", "")
        spread = issue.get("spread", "")
        persist = issue.get("persistence", "")
        badges = ""
        if trigger:
            badges += _badge(trigger, COLORS["accent"], filled=False)
        if spread:
            badges += _badge(f"확산:{spread}", SPREAD_COLOR.get(spread, COLORS["text_muted"]), filled=(spread == "대주제확산"))
        if persist:
            badges += _badge(f"지속:{persist}", PERSIST_COLOR.get(persist, COLORS["text_muted"]), filled=(persist == "구조적"))
        if srcs:
            badges += (f'<span style="color:{COLORS["text_muted"]}; font-size:0.7rem;">[{" · ".join(srcs)}]</span>')
        issues_html += (
            f'<li style="margin:10px 0; line-height:1.55; list-style:none; padding-left:14px; '
            f'border-left:2px solid {COLORS["border"]};">'
            f'<div style="color:#16202E; font-size:0.92rem; margin-bottom:4px;">{text}</div>'
            f'<div>{badges}</div></li>'
        )
    if not issues_html:
        issues_html = (f'<li style="color:{COLORS["text_muted"]}; font-size:0.85rem; list-style:none; '
                       f'padding-left:0;">어제 이 대주제에서 주목할 만한 이슈가 없었습니다.</li>')

    kr_tickers = group.get("kr_tickers", [])[:8]
    kr_chips = ""
    for kt in kr_tickers:
        code = kt.get("code", ""); name = kt.get("name", ""); direction = kt.get("direction", "neutral")
        c = DIR_COLOR.get(direction, COLORS["text_muted"]); dlabel = DIR_LABEL.get(direction, "-")
        kr_chips += (
            f'<span style="display:inline-flex; align-items:center; gap:6px; background:rgba(0,0,0,0.04); '
            f'border:1px solid {c}33; border-left:3px solid {c}; padding:5px 10px; margin:3px; border-radius:6px; '
            f'font-size:0.82rem;">'
            f'<span style="color:{COLORS["text_muted"]}; font-size:0.74rem;">{code}</span>'
            f'<span style="color:#16202E;">{name}</span>'
            f'<span style="color:{c}; font-weight:600; font-size:0.74rem;">{dlabel}</span></span>'
        )

    affected = group.get("affected_kr_sectors", []) or []
    sec_chips = " ".join(
        f'<span style="display:inline-block; background:{COLORS["bg_card"]}; border:1px solid {COLORS["border"]}; '
        f'border-radius:12px; padding:2px 9px; margin:2px; font-size:0.74rem; color:{COLORS["text_muted"]};">{s}</span>'
        for s in affected
    )

    return (
        f'<div style="background:{COLORS["bg_card"]}; border:1px solid {COLORS["border"]}; '
        f'border-left:5px solid {sect_color}; border-radius:0 12px 12px 0; padding:20px 24px; margin-bottom:18px;">'
        f'<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">'
        f'<div><span style="color:#16202E; font-size:1.2rem; font-weight:700;">{group.get("name","")}</span></div>'
        f'<div style="display:flex; gap:10px; align-items:center;">'
        f'<span style="color:{sect_color}; font-weight:700; font-size:0.85rem;">{SENT_LABEL.get(sent,"-")}</span>'
        f'<span style="color:{IMPACT_COLOR.get(impact,COLORS["text_muted"])}; font-weight:700; font-size:0.85rem;">영향 {IMPACT_LABEL.get(impact,"-")}</span>'
        f'<span style="color:{COLORS["text_muted"]}; font-size:0.78rem;">이벤트 {group.get("events_count",0)}건</span>'
        f'</div></div>'
        f'{sub_str}'
        f'<div style="color:#16202E; font-size:0.93rem; line-height:1.65; background:rgba(0,0,0,0.025); '
        f'padding:12px 14px; border-radius:8px; margin-bottom:14px;">{group.get("summary","")}</div>'
        f'<div style="color:{COLORS["accent"]}; font-size:0.82rem; font-weight:700; margin-bottom:6px;">핵심 이슈</div>'
        f'<ul style="margin:0 0 14px 0; padding-left:0;">{issues_html}</ul>'
        f'{("<div style=margin-bottom:10px;>" + sec_chips + "</div>") if sec_chips else ""}'
        f'<div style="color:{COLORS["accent"]}; font-size:0.82rem; font-weight:700; margin:10px 0 6px;">영향 받을 한국 종목</div>'
        f'<div>{kr_chips if kr_chips else "<span style=color:" + COLORS["text_muted"] + "; font-size:0.85rem;>(추천 없음)</span>"}</div>'
        f'</div>'
    )


# ── 5) 한국 수급·특징주 칩 ──────────────────────
def render_kr_chip(item, updown):
    c = COLORS["accent_green"] if updown == "up" else COLORS["accent_red"]
    name = item.get("name", ""); code = item.get("code", "")
    pct = item.get("change_pct", 0); mcap = item.get("marcap_str", "")
    sec = item.get("sector_detail") or item.get("sector", "")
    return (
        f'<div style="display:flex; justify-content:space-between; align-items:center; gap:8px; '
        f'background:rgba(0,0,0,0.03); border-left:3px solid {c}; border-radius:6px; '
        f'padding:5px 10px; margin:3px 0; font-size:0.82rem;">'
        f'<span style="color:#16202E;">{name} <span style="color:{COLORS["text_muted"]}; font-size:0.72rem;">{sec}·{mcap}</span></span>'
        f'<span style="color:{c}; font-weight:700; white-space:nowrap;">{pct:+.1f}%</span>'
        f'</div>'
    )


def render_overseas_row(it):
    ret = it["ret"]
    c = COLORS["accent_green"] if ret >= 0 else COLORS["accent_red"]
    arrow = "▲" if ret >= 0 else "▼"
    tc = COLORS["accent"] if it["type"] == "GDR" else COLORS["text_muted"]
    return (
        f'<div style="display:flex; justify-content:space-between; align-items:center; gap:8px; '
        f'background:rgba(0,0,0,0.03); border-left:3px solid {c}; border-radius:6px; '
        f'padding:6px 11px; margin:3px 0; font-size:0.84rem;">'
        f'<span style="color:#16202E;">{it["name"]} '
        f'<span style="color:{COLORS["text_muted"]}; font-size:0.72rem;">{it["kr"]}</span> '
        f'<span style="color:{tc}; border:1px solid {tc}55; border-radius:4px; padding:0 5px; '
        f'font-size:0.66rem;">{it["type"]}·{it["venue"]}</span></span>'
        f'<span style="white-space:nowrap;">'
        f'<span style="color:{COLORS["text_muted"]}; font-size:0.74rem; margin-right:8px;">${it["last"]:,.2f}</span>'
        f'<span style="color:{c}; font-weight:700;">{arrow} {ret:+.2f}%</span></span>'
        f'</div>'
    )


# ── 시장 레짐 / 한국 시장 현황 렌더 ──────────────
REGIME_LABEL = {"Risk-on": "위험선호 Risk-On", "Neutral": "중립 Neutral", "Risk-off": "위험회피 Risk-Off"}


def _score_color(s):
    if s >= 60:
        return COLORS["accent_green"]
    if s >= 40:
        return COLORS["accent_yellow"]
    return COLORS["accent_red"]


def render_regime(reg):
    label = reg.get("label", "Neutral")
    score = reg.get("score", 50)
    cov = reg.get("coverage", 100)
    comps = reg.get("components", [])
    rc = _score_color(score)
    comp_html = ""
    for c in comps:
        s = c["score"]
        sc = _score_color(s)
        comp_html += (
            f'<div style="display:flex; align-items:center; gap:10px; padding:5px 0; border-bottom:1px solid {COLORS["border"]};">'
            f'<span style="min-width:118px; color:{COLORS["text"]}; font-size:0.8rem; font-weight:600;">{c["name"]}</span>'
            f'<div style="flex:1; max-width:160px; background:{COLORS["bg_card_hover"]}; border-radius:5px; height:8px; overflow:hidden;">'
            f'<div style="width:{s}%; height:100%; background:{sc};"></div></div>'
            f'<span style="min-width:30px; text-align:right; color:{sc}; font-weight:700; font-size:0.84rem;">{int(s)}</span>'
            f'<span style="flex:2; color:{COLORS["text_muted"]}; font-size:0.72rem;">{c["detail"]} · 가중 {c["weight"]}</span>'
            f'</div>'
        )
    note = reg.get("note", "")
    note_html = (f'<div style="color:{COLORS["text_muted"]}; font-size:0.72rem; margin-top:8px;">※ {note}</div>'
                 if note else "")
    return (
        f'<div style="background:{COLORS["bg_card"]}; border:1px solid {COLORS["border"]}; border-left:6px solid {rc}; '
        f'border-radius:0 14px 14px 0; padding:20px 24px; margin-bottom:10px;">'
        f'<div style="display:flex; align-items:center; gap:22px; margin-bottom:14px;">'
        f'<div style="text-align:center; min-width:70px;">'
        f'<div style="font-size:2.8rem; font-weight:800; color:{rc}; line-height:1;">{int(score)}</div>'
        f'<div style="color:{COLORS["text_muted"]}; font-size:0.72rem;">/ 100</div></div>'
        f'<div><div style="font-size:1.5rem; font-weight:800; color:{rc};">{REGIME_LABEL.get(label, label)}</div>'
        f'<div style="color:{COLORS["text_muted"]}; font-size:0.8rem;">한국 증시 시장 레짐 · 커버리지 {cov}% ({len(comps)}/7 지표)</div>'
        f'</div></div>'
        f'<div>{comp_html}</div>{note_html}</div>'
    )


def kr_sparkline(spark, color):
    fig = go.Figure(go.Scatter(y=spark, mode="lines", line=dict(color=color, width=2)))
    lo, hi = min(spark), max(spark)
    pad = (hi - lo) * 0.1 or 1
    fig.update_layout(height=56, margin=dict(l=0, r=0, t=0, b=0), showlegend=False,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis=dict(visible=False),
                      yaxis=dict(visible=False, range=[lo - pad, hi + pad]))
    return fig


def render_index_head(name, idx):
    c = COLORS["accent_green"] if idx["change_pct"] >= 0 else COLORS["accent_red"]
    arrow = "▲" if idx["change"] >= 0 else "▼"
    return (
        f'<div style="display:flex; align-items:baseline; gap:10px;">'
        f'<span style="color:{COLORS["text_muted"]}; font-size:0.8rem; font-weight:600;">{name}</span>'
        f'<span style="color:#16202E; font-size:1.5rem; font-weight:800;">{idx["close"]:,.2f}</span>'
        f'<span style="color:{c}; font-size:0.9rem; font-weight:700;">{arrow} {idx["change"]:+,.2f} ({idx["change_pct"]:+.2f}%)</span>'
        f'</div>'
    )


def render_breadth(br):
    up, fl, dn = br["up"], br["flat"], br["down"]
    tot = max(up + fl + dn, 1)
    g, y, r = COLORS["accent_green"], COLORS["text_muted"], COLORS["accent_red"]
    return (
        f'<div style="color:{COLORS["text_muted"]}; font-size:0.78rem; margin-bottom:4px;">상승/하락</div>'
        f'<div style="display:flex; gap:12px; margin-bottom:6px; font-size:0.92rem; font-weight:700;">'
        f'<span style="color:{g};">상승 {up:,}</span><span style="color:{y};">보합 {fl:,}</span>'
        f'<span style="color:{r};">하락 {dn:,}</span></div>'
        f'<div style="display:flex; height:9px; border-radius:5px; overflow:hidden; background:{COLORS["bg_card_hover"]};">'
        f'<div style="width:{up/tot*100}%; background:{g};"></div>'
        f'<div style="width:{fl/tot*100}%; background:{y};"></div>'
        f'<div style="width:{dn/tot*100}%; background:{r};"></div></div>'
    )


def render_ranking_table(rows):
    if not rows:
        return f'<div style="color:{COLORS["text_muted"]}; font-size:0.85rem;">데이터 없음</div>'
    head = (
        f'<tr style="border-bottom:2px solid {COLORS["border"]}; color:{COLORS["text_muted"]}; font-size:0.74rem; text-align:right;">'
        f'<th style="text-align:left; padding:6px 8px;">#</th><th style="text-align:left;">종목</th>'
        f'<th>현재가</th><th>전일대비</th><th>거래대금</th><th>시총</th></tr>'
    )
    trs = ""
    for x in rows:
        cp = x["change_pct"]
        c = COLORS["accent_green"] if cp > 0 else (COLORS["accent_red"] if cp < 0 else COLORS["text_muted"])
        trs += (
            f'<tr style="border-bottom:1px solid {COLORS["border"]}; font-size:0.82rem; text-align:right;">'
            f'<td style="text-align:left; padding:6px 8px; color:{COLORS["text_muted"]};">{x["rank"]}</td>'
            f'<td style="text-align:left;"><b style="color:#16202E;">{x["name"]}</b> '
            f'<span style="color:{COLORS["text_muted"]}; font-size:0.72rem;">{x["code"]}·{x["market"]}</span></td>'
            f'<td style="color:#16202E;">{x["close"]:,.0f}</td>'
            f'<td style="color:{c}; font-weight:700;">{cp:+.2f}%</td>'
            f'<td style="color:{COLORS["text_muted"]};">{x["amount_str"]}</td>'
            f'<td style="color:{COLORS["text_muted"]};">{x["marcap_str"]}</td></tr>'
        )
    return (
        f'<table style="width:100%; border-collapse:collapse; background:{COLORS["bg_card"]}; '
        f'border:1px solid {COLORS["border"]}; border-radius:10px;">{head}{trs}</table>'
    )


# ════════════════════ 페이지 ════════════════════
st.markdown(f"""
<div class="ark-hero" style="padding: 30px 36px; margin-bottom: 18px;">
    <h1 style="font-size: 1.95rem; margin-bottom: 4px;">🌅 모닝 마켓 체크</h1>
    <div class="subtitle">상장주식 운용팀 모닝미팅 · 간밤 시장부터 오늘의 논점까지</div>
</div>
""", unsafe_allow_html=True)

events_data = load_events()
themes_file = load_themes_file()
group_defs = themes_file.get("groups", [])

if not events_data:
    st.info("데이터가 없습니다. `python3 scripts/update_us_events.py` 실행이 필요합니다.")
    st.stop()

groups_list = events_data.get("groups")
if groups_list is None:
    groups_list = events_data.get("themes", [])
    if groups_list:
        st.warning("구버전 데이터입니다. `python3 scripts/update_us_events.py --reanalyze` 재실행 필요.")

date = events_data.get("date", "-")
updated = events_data.get("updated", "-")
st.markdown(
    f'<div style="color:{COLORS["text_muted"]}; font-size:0.8rem; margin:-6px 0 4px;">'
    f'기준일 <b style="color:#16202E;">{date}</b> · 최종 갱신 {updated} (KST) · 미국 티커 '
    f'{events_data.get("ticker_count",0)}개 / 이벤트 {events_data.get("event_count",0)}건</div>',
    unsafe_allow_html=True,
)

# ── 0) 한국 시장 데이터 로드 ──
km = load_json_safe(str(DATA / "kr_market.json"))

# ── 1) 시장 레짐 ──────────────────────────────
if km and km.get("regime"):
    st.markdown('<div class="section-header">🧭 시장 레짐</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div style="color:{COLORS["text_muted"]}; font-size:0.78rem; margin-bottom:6px;">'
        f'기준일 {km.get("date","-")} · 한국 증시 위험선호 종합 판정 (가중 평균)</div>',
        unsafe_allow_html=True)
    st.markdown(render_regime(km["regime"]), unsafe_allow_html=True)
    st.markdown("---")

# ── 2) 한국 시장 현황 ──────────────────────────
if km:
    st.markdown('<div class="section-header">🇰🇷 한국 시장 현황</div>', unsafe_allow_html=True)
    kc1, kc2, kc3 = st.columns([1.5, 1, 1])
    with kc1:
        for nm, key in [("코스피", "kospi"), ("코스닥", "kosdaq")]:
            ix = km.get(key)
            if ix:
                st.markdown(render_index_head(nm, ix), unsafe_allow_html=True)
                col = COLORS["accent_green"] if ix["change_pct"] >= 0 else COLORS["accent_red"]
                st.plotly_chart(kr_sparkline(ix["spark"], col), use_container_width=True,
                                config={"displayModeBar": False})
    with kc2:
        st.markdown(render_breadth(km["breadth"]["total"]), unsafe_allow_html=True)
        v = km["value"]
        st.markdown(
            f'<div style="margin-top:16px; color:{COLORS["text_muted"]}; font-size:0.78rem;">거래대금</div>'
            f'<div style="color:#16202E; font-size:0.92rem;">KOSPI <b>{v["kospi_str"]}</b> · KOSDAQ <b>{v["kosdaq_str"]}</b></div>',
            unsafe_allow_html=True)
    with kc3:
        c = km["concentration"]
        st.markdown(
            f'<div style="color:{COLORS["text_muted"]}; font-size:0.78rem;">삼성+SK 시총비중</div>'
            f'<div style="color:#16202E; font-size:1.7rem; font-weight:800;">{c["samsung_sk_pct"]:.2f}%</div>'
            f'<div style="color:{COLORS["text_muted"]}; font-size:0.78rem;">삼성 {c["samsung_pct"]:.1f}% · SK {c["sk_pct"]:.1f}%</div>',
            unsafe_allow_html=True)

    # 시장 랭킹 (필터 탭)
    st.markdown(f'<div style="color:{COLORS["accent"]}; font-weight:700; font-size:0.92rem; margin:16px 0 6px;">시장 랭킹</div>',
                unsafe_allow_html=True)
    rks = km.get("rankings", {})
    fa, fb, fc = st.columns([0.9, 1.3, 2.4])
    with fa:
        asset = st.radio("자산", ["주식", "ETF"], horizontal=True, key="rk_asset", label_visibility="collapsed")
    with fb:
        mkt = st.radio("시장", ["전체", "코스피", "코스닥"], horizontal=True, key="rk_mkt", label_visibility="collapsed")
    with fc:
        crit = st.radio("기준", km.get("ranking_criteria", ["시가총액"]), horizontal=True, key="rk_crit",
                        label_visibility="collapsed")
    adata = rks.get(asset)
    lookup_mkt = mkt if asset == "주식" else "전체"
    rows = ((adata or {}).get(lookup_mkt, {}) or {}).get(crit, []) if adata else []
    if asset == "ETF" and mkt != "전체":
        st.caption("ETF는 시장 구분 없이 전체 기준입니다.")
    st.markdown(render_ranking_table(rows), unsafe_allow_html=True)
    st.markdown("---")

# ── 3) 간밤 글로벌 스냅샷 ──────────────────────────
st.markdown(f'<div class="section-header">🌅 간밤 글로벌 스냅샷</div>', unsafe_allow_html=True)
with st.spinner("시장 스냅샷 로딩..."):
    snap = load_market_snapshot()
if snap:
    # 두 줄로 (지수/리스크게이지)
    cards = "".join(render_snapshot_card(it) for it in snap)
    st.markdown(
        f'<div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:6px;">{cards}</div>',
        unsafe_allow_html=True,
    )
    st.caption("지수는 등락 색상, VIX·달러·환율은 중립 표기(방향만). 전일 종가 기준.")
else:
    st.caption("스냅샷 로딩 실패 (yfinance)")

# ── 1-b) 매크로 — 금리 & 원자재 ──────────────────
st.markdown("---")
st.markdown(f'<div class="section-header">🏦 매크로 — 금리 & 원자재</div>', unsafe_allow_html=True)
with st.spinner("금리·원자재 시세..."):
    rates_df = load_macro_history("rates")
    comm_df = load_macro_history("commodities")
rates = quotes_from_df(rates_df, RATE_TICKERS)
comms = quotes_from_df(comm_df, COMMODITY_TICKERS)
mc1, mc2 = st.columns([1, 1.4])
with mc1:
    st.markdown(f'<div style="color:{COLORS["accent"]}; font-weight:700; font-size:0.85rem; margin-bottom:6px;">美 국채 수익률 (5·10·30년)</div>', unsafe_allow_html=True)
    if rates:
        st.markdown(f'<div style="display:flex; flex-wrap:wrap; gap:8px;">{"".join(render_snapshot_card(it) for it in rates)}</div>', unsafe_allow_html=True)
    else:
        st.caption("금리 로딩 실패")
with mc2:
    st.markdown(f'<div style="color:{COLORS["accent"]}; font-weight:700; font-size:0.85rem; margin-bottom:6px;">원자재</div>', unsafe_allow_html=True)
    if comms:
        st.markdown(f'<div style="display:flex; flex-wrap:wrap; gap:8px;">{"".join(render_snapshot_card(it) for it in comms)}</div>', unsafe_allow_html=True)
    else:
        st.caption("원자재 로딩 실패")
st.caption("국채 수익률은 전일 대비 bp 변화(중립 표기). 원자재는 % 등락(상승=초록).")

# 금리 추세 그래프 (원자재 차트는 제외)
if rates_df is not None:
    st.plotly_chart(styled_plotly(build_rate_chart(rates_df), 340), use_container_width=True)
else:
    st.caption("금리 차트 데이터 없음")

# 매크로 이슈 분석 (매크로·지수 대주제를 상단으로 분리)
macro_grp = next((g for g in (groups_list or []) if g.get("id") == "macro_index"), None)
if macro_grp:
    st.markdown(f'<div style="color:{COLORS["text_muted"]}; font-size:0.8rem; margin:12px 0 6px;">어제 매크로 이슈 (금리·고용·환율·정책)</div>', unsafe_allow_html=True)
    st.markdown(render_group_card(macro_grp), unsafe_allow_html=True)

# ── 2) 오늘의 논점 ──────────────────────────────
brief = events_data.get("brief")
st.markdown("---")
st.markdown(f'<div class="section-header">📌 오늘의 논점</div>', unsafe_allow_html=True)
if brief and brief.get("talking_points"):
    st.markdown(render_brief(brief), unsafe_allow_html=True)
else:
    st.info("오늘의 논점이 아직 생성되지 않았습니다. `python3 scripts/update_us_events.py` 재실행 시 생성됩니다.")

# ── 3) 대주제별 심층 ────────────────────────────
st.markdown("---")
st.markdown(f'<div class="section-header">🇺🇸 대주제별 심층 분석</div>', unsafe_allow_html=True)

if not groups_list:
    st.warning("분석 결과가 없습니다. `python3 scripts/update_us_events.py` 실행 또는 ANTHROPIC_API_KEY/크레딧 확인.")
else:
    flt_c1, flt_c2, flt_c3 = st.columns([1, 1, 1])
    with flt_c1:
        sent_flt = st.multiselect("감성", ["긍정", "부정", "혼조", "중립"],
                                  default=["긍정", "부정", "혼조", "중립"], key="grp_sent_flt")
    with flt_c2:
        impact_flt = st.multiselect("영향 강도", ["강", "중", "약"], default=["강", "중", "약"], key="grp_impact_flt")
    with flt_c3:
        only_structural = st.checkbox("구조적·확산 이슈만", value=False, key="grp_struct_only",
                                      help="구조적이거나 대주제로 확산되는 핵심 이슈가 있는 대주제만 표시")

    sent_filter_keys = [k for k, v in SENT_LABEL.items() if v in sent_flt]
    impact_filter_keys = [k for k, v in IMPACT_LABEL.items() if v in impact_flt]
    impact_order = {"high": 0, "medium": 1, "low": 2}
    sent_priority = {"positive": 0, "negative": 0, "mixed": 1, "neutral": 2}
    filtered = [g for g in groups_list
                if g.get("id") != "macro_index"
                and g.get("sentiment") in sent_filter_keys and g.get("impact_strength") in impact_filter_keys]
    if only_structural:
        filtered = [g for g in filtered if any(
            i.get("persistence") == "구조적" or i.get("spread") == "대주제확산"
            for i in g.get("key_issues", []))]
    filtered.sort(key=lambda g: (impact_order.get(g.get("impact_strength"), 9),
                                 sent_priority.get(g.get("sentiment"), 9), -g.get("events_count", 0)))
    if not filtered:
        st.info("조건에 맞는 대주제가 없습니다.")
    else:
        for g in filtered:
            st.markdown(render_group_card(g), unsafe_allow_html=True)

# ── 3-b) 미국 섹터 ETF (섹터 팔로업) ──────────────
st.markdown("---")
st.markdown(f'<div class="section-header">🧭 미국 섹터 ETF (전일)</div>', unsafe_allow_html=True)
with st.spinner("미국 섹터 ETF..."):
    etf_change = load_us_etf_change()
if etf_change:
    sorted_etfs = sorted(etf_change.items(), key=lambda x: x[1]["ret_pct"], reverse=True)
    chips = ""
    for etf, info in sorted_etfs:
        ret = info["ret_pct"]
        c = COLORS["accent_green"] if ret >= 0 else COLORS["accent_red"]
        arrow = "▲" if ret >= 0 else "▼"
        chips += (
            f'<span style="display:inline-flex; gap:5px; align-items:baseline; background:{COLORS["bg_card"]}; '
            f'border:1px solid {COLORS["border"]}; border-radius:7px; padding:5px 11px; margin:3px; font-size:0.8rem;">'
            f'<span style="color:#16202E; font-weight:700;">{etf}</span>'
            f'<span style="color:{COLORS["text_muted"]}; font-size:0.72rem;">{info["name"]}</span>'
            f'<span style="color:{c}; font-weight:700;">{arrow}{ret:+.2f}%</span></span>'
        )
    st.markdown(f'<div>{chips}</div>', unsafe_allow_html=True)
    st.caption("SPDR 11개 섹터 ETF · 전일 등락 내림차순. 강세→약세 섹터 한눈에.")
else:
    st.caption("섹터 ETF 로딩 실패")

# ── 3-c) 해외 상장 한국주 (GDR/ADR) — 간밤 체크 ──
st.markdown("---")
st.markdown(f'<div class="section-header">🌐 해외 상장 한국주 — 간밤 체크 (GDR/ADR)</div>', unsafe_allow_html=True)
with st.spinner("해외 상장 한국주 시세..."):
    overseas = load_overseas_kr()
if overseas:
    overseas_sorted = sorted(overseas, key=lambda x: x["ret"], reverse=True)
    asof = overseas_sorted[0].get("asof", "-")
    st.markdown(
        f'<div style="color:{COLORS["text_muted"]}; font-size:0.76rem; margin-bottom:6px;">'
        f'간밤 종가({asof}) 기준 · 등락 내림차순 · 외국인 시각 → 오늘 한국 개장 선행지표</div>',
        unsafe_allow_html=True,
    )
    half = (len(overseas_sorted) + 1) // 2
    oc1, oc2 = st.columns(2)
    with oc1:
        st.markdown("".join(render_overseas_row(it) for it in overseas_sorted[:half]), unsafe_allow_html=True)
    with oc2:
        st.markdown("".join(render_overseas_row(it) for it in overseas_sorted[half:]), unsafe_allow_html=True)
    st.caption("GDR=런던 / ADR=뉴욕. ※ 환율·현지 수급에 따른 원주 대비 괴리 포함된 참고치(방향성 위주로 해석).")
else:
    st.caption("해외 상장 데이터 로딩 실패")

# ── 4) 오늘/금주 일정 ───────────────────────────
st.markdown("---")
st.markdown(f'<div class="section-header">📅 오늘/금주 일정</div>', unsafe_allow_html=True)
cal = load_json_safe(str(MACRO_CAL_PATH))
if cal and cal.get("this_week", {}).get("events"):
    tw = cal["this_week"]
    now = datetime.now()
    today_md = f"{now.month}/{now.day}"
    IMP_C = {"high": COLORS["accent_red"], "medium": COLORS["accent_yellow"], "low": COLORS["text_muted"]}
    IMP_L = {"high": "★★★", "medium": "★★", "low": "★"}
    rows = ""
    for e in tw["events"]:
        d = e.get("date", "")
        is_today = today_md in d
        imp = e.get("importance", "low")
        ic = IMP_C.get(imp, COLORS["text_muted"])
        bg = "rgba(0,210,255,0.07)" if is_today else "transparent"
        cons = e.get("consensus", "-"); prev = e.get("previous", "-")
        cp = ""
        if cons not in ("-", "", None) or prev not in ("-", "", None):
            cp = (f'<span style="color:{COLORS["text_muted"]}; font-size:0.74rem;">'
                  f'컨센 {cons} / 이전 {prev}</span>')
        rows += (
            f'<div style="display:flex; align-items:center; gap:12px; padding:6px 10px; '
            f'background:{bg}; border-bottom:1px solid {COLORS["border"]};">'
            f'<span style="color:{"#16202E" if is_today else COLORS["text_muted"]}; font-size:0.78rem; '
            f'min-width:70px; font-weight:{"700" if is_today else "400"};">{d}</span>'
            f'<span style="color:{ic}; font-size:0.7rem; min-width:36px;">{IMP_L.get(imp,"")}</span>'
            f'<span style="color:#16202E; font-size:0.86rem; flex:1;">{e.get("event","")}</span>'
            f'{cp}</div>'
        )
    st.markdown(
        f'<div style="color:{COLORS["text_muted"]}; font-size:0.76rem; margin-bottom:6px;">{tw.get("label","")} · 오늘({today_md}) 하이라이트</div>'
        f'<div style="background:{COLORS["bg_card"]}; border:1px solid {COLORS["border"]}; border-radius:10px; overflow:hidden;">{rows}</div>',
        unsafe_allow_html=True,
    )
else:
    st.caption("일정 데이터 없음 (macro_calendar.json)")

# ── 5) 한국 수급·특징주 ─────────────────────────
st.markdown("---")
st.markdown(f'<div class="section-header">🇰🇷 한국 수급·특징주 (전일)</div>', unsafe_allow_html=True)
sig = load_json_safe(str(MARKET_SIGNAL_PATH))
if sig:
    st.markdown(
        f'<div style="color:{COLORS["text_muted"]}; font-size:0.76rem; margin-bottom:8px;">'
        f'{sig.get("date","-")} 기준 · 시총 {sig.get("min_cap","-")} 이상 · 급등락 ±{sig.get("surge_pct","-")}%</div>',
        unsafe_allow_html=True,
    )
    def top_n(key, updown, n=6):
        items = sig.get(key, [])
        items = sorted(items, key=lambda x: abs(x.get("change_pct", 0)), reverse=True)[:n]
        return "".join(render_kr_chip(it, updown) for it in items)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f'<div style="color:{COLORS["accent_green"]}; font-weight:700; font-size:0.85rem; margin-bottom:4px;">📈 신고가 ({len(sig.get("new_high",[]))})</div>', unsafe_allow_html=True)
        st.markdown(top_n("new_high", "up"), unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div style="color:{COLORS["accent_green"]}; font-weight:700; font-size:0.85rem; margin-bottom:4px;">🚀 급등 ({len(sig.get("surge",[]))})</div>', unsafe_allow_html=True)
        st.markdown(top_n("surge", "up"), unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div style="color:{COLORS["accent_red"]}; font-weight:700; font-size:0.85rem; margin-bottom:4px;">💥 급락 ({len(sig.get("plunge",[]))})</div>', unsafe_allow_html=True)
        st.markdown(top_n("plunge", "down"), unsafe_allow_html=True)
    with c4:
        st.markdown(f'<div style="color:{COLORS["accent_red"]}; font-weight:700; font-size:0.85rem; margin-bottom:4px;">📉 신저가 ({len(sig.get("new_low",[]))})</div>', unsafe_allow_html=True)
        st.markdown(top_n("new_low", "down"), unsafe_allow_html=True)
else:
    st.caption("수급 데이터 없음 (market_signal.json)")

# ── 보조: β/상관, Raw ───────────────────────────
st.markdown("---")
with st.expander("선택 대주제의 KR 종목 — β·60일 상관 (US 섹터 ETF 기준)", expanded=False):
    if not group_defs:
        st.caption("대주제 정의 없음")
    else:
        grp_options = {g["id"]: g["name"] for g in group_defs}
        sel_grp_id = st.selectbox("대주제 선택", list(grp_options.keys()),
                                  format_func=lambda x: grp_options[x], key="beta_grp_sel")
        GROUP_TO_ETF = {"macro_index": "SPY", "tech_semi": "XLK", "software_platform": "XLK",
                        "industrial": "XLI", "green_mobility": "XLU", "realestate_dc": "XLRE",
                        "energy_materials": "XLE", "defensive": "XLF"}
        ref_etf = GROUP_TO_ETF.get(sel_grp_id, "SPY")
        st.caption(f"기준 ETF: **{ref_etf}** ({load_sector_map().get(ref_etf, {}).get('name', '시장 전체')})")
        anchors = []; seen = set()
        for th in themes_file.get("themes", []):
            if th.get("group") == sel_grp_id:
                for a in th.get("kr_anchor_tickers", []):
                    if a["code"] not in seen:
                        anchors.append((a["code"], a["name"])); seen.add(a["code"])
        ev_grp = next((g for g in groups_list if g.get("id") == sel_grp_id), None)
        if ev_grp:
            for kt in ev_grp.get("kr_tickers", []):
                code = kt.get("code", "")
                if code and code not in seen:
                    anchors.append((code, kt.get("name", ""))); seen.add(code)
        if anchors:
            with st.spinner("가격 데이터 로딩..."):
                us_series = load_us_etf_history(ref_etf)
                rows = []
                for code, name in anchors:
                    kr_s = load_kr_price(code)
                    beta, corr = calc_beta_corr(kr_s, us_series)
                    rows.append({"코드": code, "종목명": name,
                                 "β": f"{beta:+.2f}" if pd.notna(beta) else "-",
                                 "60일 상관": f"{corr:+.2f}" if pd.notna(corr) else "-"})
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            st.caption(f"β: {ref_etf} 1%p 변동 시 한국 종목 평균 변동폭. 1일 시차 적용 (US t-1 → KR t).")
        else:
            st.caption("이 대주제의 KR 종목 없음")

with st.expander("Raw 이벤트 원본 데이터", expanded=False):
    raw = events_data.get("raw_events", [])
    st.caption(f"전체 {len(raw)}건 — 가격 변동/어닝/뉴스 원본")
    by_ticker = {}
    for e in raw:
        by_ticker.setdefault(e["ticker"], []).append(e)
    for tk in sorted(by_ticker.keys()):
        st.markdown(f"**{tk}** ({len(by_ticker[tk])} events)")
        st.json(by_ticker[tk], expanded=False)

st.markdown(f"""
<div class="ark-footer">
    ARK IMPACT · 모닝 마켓 체크 · yfinance + Claude API + FinanceDataReader · {now_kst()}
</div>
""", unsafe_allow_html=True)
