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

# KR 마켓 라이브 계산 (앱에서 직접 호출 → 10분 갱신, git 의존 X)
try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
    from update_kr_market import compute_kr_market
    HAS_KR_COMPUTE = True
except Exception:
    HAS_KR_COMPUTE = False

# 주요 ETF 추이 (사용자 제공 트래커 경량 버전)
try:
    from etf_track import load_etf_table, sector_summary, BUCKET_LEGEND
    HAS_ETF = True
except Exception:
    HAS_ETF = False

# 10분 자동 새로고침 (세션 유지)
try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except Exception:
    HAS_AUTOREFRESH = False

REFRESH_SEC = 600  # 10분

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


@st.cache_data(ttl=REFRESH_SEC, show_spinner=False)
def load_kr_market_live():
    """KR 마켓을 라이브 계산(10분 캐시). 실패 시 커밋된 JSON 폴백."""
    if HAS_KR_COMPUTE:
        try:
            return compute_kr_market(verbose=False)
        except Exception:
            pass
    return load_json_safe(str(DATA / "kr_market.json"))


# 간밤 시장 스냅샷 티커 (지수·변동성·환율)
SNAPSHOT_TICKERS = [
    ("^GSPC", "S&P 500", "index"),
    ("^IXIC", "나스닥", "index"),
    ("^DJI", "다우", "index"),
    ("^RUT", "러셀 2000", "index"),
    ("^VIX", "VIX", "vix"),
    ("DX-Y.NYB", "달러인덱스", "level"),
]

# 매크로 — 금리 (美 국채 수익률 2/5/10/30년)
RATE_TICKERS = [
    ("2YY=F", "미 2년물", "yield"),
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


def _fetch_usdkrw():
    """원/달러는 fdr USD/KRW로 (한국 데이터 소스 일관성)."""
    try:
        df = fdr.DataReader("USD/KRW", (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d"))
        if df is None or len(df) < 2:
            return None
        last = float(df["Close"].iloc[-1]); prev = float(df["Close"].iloc[-2])
        chg = last - prev
        return {"name": "원/달러", "kind": "fx", "last": last, "chg": chg,
                "pct": (chg / prev * 100) if prev else 0.0}
    except Exception:
        return None


@st.cache_data(ttl=REFRESH_SEC, show_spinner=False)
def load_market_snapshot():
    q = _fetch_quotes(SNAPSHOT_TICKERS)
    fx = _fetch_usdkrw()
    if fx:
        q.append(fx)
    return q


@st.cache_data(ttl=REFRESH_SEC, show_spinner=False)
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
    fig.update_layout(
        title=dict(text=""),
        yaxis=dict(ticksuffix="%"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    title=dict(text=""), font=dict(size=11)),
        hovermode="x unified",
    )
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


@st.cache_data(ttl=REFRESH_SEC, show_spinner=False)
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


@st.cache_data(ttl=REFRESH_SEC, show_spinner=False)
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
    c = COLORS["kr_up"] if updown == "up" else COLORS["kr_down"]
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
    c = COLORS["kr_up"] if ret >= 0 else COLORS["kr_down"]
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


def kr_sparkline(spark, color=None, height=90):
    # 레퍼런스식: 파란 라인 + 옅은 영역 채움 + 가로 눈금선
    fig = go.Figure(go.Scatter(
        y=spark, mode="lines",
        line=dict(color="#2563EB", width=2, shape="spline"),
        fill="tozeroy", fillcolor="rgba(37,99,235,0.08)", hoverinfo="skip"))
    lo, hi = min(spark), max(spark)
    pad = (hi - lo) * 0.18 or 1
    fig.update_layout(height=height, margin=dict(l=0, r=2, t=4, b=2), showlegend=False,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis=dict(visible=False),
                      yaxis=dict(showgrid=True, gridcolor="rgba(0,0,0,0.08)", showticklabels=False,
                                 zeroline=False, range=[lo - pad, hi + pad], nticks=4),
                      hovermode=False)
    return fig


def render_index_head(name, idx):
    c = COLORS["kr_up"] if idx["change_pct"] >= 0 else COLORS["kr_down"]
    arrow = "▲" if idx["change"] >= 0 else "▼"
    return (
        f'<div style="display:flex; align-items:baseline; gap:10px;">'
        f'<span style="color:{COLORS["text_muted"]}; font-size:0.8rem; font-weight:600;">{name}</span>'
        f'<span style="color:#16202E; font-size:1.5rem; font-weight:800;">{idx["close"]:,.2f}</span>'
        f'<span style="color:{c}; font-size:0.9rem; font-weight:700;">{arrow} {idx["change"]:+,.2f} ({idx["change_pct"]:+.2f}%)</span>'
        f'</div>'
    )


def render_breadth(br):
    up, fl, dn = br.get("up", 0), br.get("flat", 0), br.get("down", 0)
    tot = (up + fl + dn) or 1
    up_pct, dn_pct = up / tot * 100, dn / tot * 100
    net = (dn - up) / tot * 100
    ratio = dn / up if up else 0
    lu, ld = br.get("limit_up"), br.get("limit_down")
    lim = f"{lu}/{ld}" if lu is not None else "—"
    # 한국 관례: 상승=빨강, 하락=파랑
    g, y, r = COLORS["kr_up"], COLORS["text_muted"], COLORS["kr_down"]
    direction = "하락 우위" if net > 0 else ("상승 우위" if net < 0 else "중립")
    dir_color = r if net > 0 else (g if net < 0 else y)

    def box(label, val, vc, flex=1):
        return (f'<div style="flex:{flex}; background:{COLORS["bg_card_hover"]}; border:1px solid {COLORS["border"]}; '
                f'border-radius:9px; padding:9px 6px; text-align:center;">'
                f'<div style="color:{COLORS["text_muted"]}; font-size:0.72rem; margin-bottom:3px;">{label}</div>'
                f'<div style="color:{vc}; font-size:1.1rem; font-weight:800; white-space:nowrap;">{val}</div></div>')

    return (
        '<div style="display:flex; flex-direction:column; gap:11px; height:100%;">'
        f'<div style="color:#16202E; font-size:1.08rem; font-weight:800;">상승/하락 '
        f'<span style="color:{COLORS["text_muted"]}; font-weight:500; font-size:0.78rem;">({tot:,}종목)</span></div>'
        # 큰 카운트
        f'<div style="display:flex; justify-content:space-between; font-size:1.2rem; font-weight:800;">'
        f'<span style="color:{g};">상승 {up:,}</span><span style="color:{y};">보합 {fl:,}</span>'
        f'<span style="color:{r};">하락 {dn:,}</span></div>'
        # 비중 바
        f'<div style="display:flex; height:12px; border-radius:6px; overflow:hidden; background:{COLORS["bg_card_hover"]};">'
        f'<div style="width:{up_pct}%; background:{g};"></div>'
        f'<div style="width:{fl/tot*100}%; background:{y};"></div>'
        f'<div style="width:{dn_pct}%; background:{r};"></div></div>'
        # 3 박스: 상승비중 / 하락비중 / 상하한
        f'<div style="display:flex; gap:7px;">'
        f'{box("상승비중", f"{up_pct:.1f}%", g)}{box("하락비중", f"{dn_pct:.1f}%", r)}{box("상/하한가", lim, "#16202E")}</div>'
        # 2 박스: 시장 방향 / 배율
        f'<div style="display:flex; gap:7px;">'
        f'{box("시장 방향", f"{direction} {abs(net):.0f}%p", dir_color, flex=1.3)}'
        f'{box("하락/상승 배율", f"{ratio:.2f}배", "#16202E")}</div>'
        '</div>'
    )


def render_index_detail(flow, br):
    """레퍼런스식 2열: 좌=수급(개인/외국인/기관, 억), 우=상승/보합/하락(상/하한 괄호).
    각 열은 라벨(좌)·값(우측 정렬), 값은 크게 강조."""
    f = flow or {}
    mut = COLORS["text_muted"]
    lu, ld = br.get("limit_up"), br.get("limit_down")
    paren = lambda n: (f'<span style="color:{mut}; font-size:0.72rem; font-weight:500;">({n})</span>' if n is not None else '')
    up_s = f'{br.get("up", 0):,}' + paren(lu)
    dn_s = f'{br.get("down", 0):,}' + paren(ld)

    def half(label, val, vc):
        return (f'<div style="flex:1; display:flex; justify-content:space-between; align-items:baseline; gap:6px;">'
                f'<span style="color:#4B5563; font-size:0.92rem; font-weight:600;">{label}</span>'
                f'<span style="color:{vc}; font-weight:800; font-size:1.0rem;">{val}</span></div>')

    def sv(v):
        if v is None:
            return ("—", mut)
        return (f'{v:+,}', COLORS["kr_up"] if v >= 0 else COLORS["kr_down"])

    rows = [
        (("개인",) + sv(f.get("개인")), ("상승", up_s, COLORS["kr_up"])),
        (("외국인",) + sv(f.get("외국인")), ("보합", f'{br.get("flat", 0):,}', mut)),
        (("기관",) + sv(f.get("기관")), ("하락", dn_s, COLORS["kr_down"])),
    ]
    html = '<div style="margin-top:10px;">'
    for (ll, lv, lc), (rl, rv, rc) in rows:
        html += (f'<div style="display:flex; gap:18px; padding:3px 0;">'
                 f'{half(ll, lv, lc)}{half(rl, rv, rc)}</div>')
    return html + '</div>'


def render_ranking_table(rows):
    if not rows:
        return f'<div style="color:{COLORS["text_muted"]}; font-size:0.9rem; padding:14px;">데이터 준비중</div>'
    mut = COLORS["text_muted"]
    head = (
        f'<tr style="border-bottom:2px solid {COLORS["border"]}; color:{mut}; font-size:0.8rem; font-weight:600; text-align:right;">'
        f'<th style="text-align:left; padding:9px 10px;">#</th><th style="text-align:left;">종목명</th>'
        f'<th>현재가</th><th>전일대비</th><th>거래량</th><th>거래대금</th><th style="padding-right:10px;">시가총액</th></tr>'
    )
    trs = ""
    for x in rows:
        cp = x.get("change_pct", 0)
        c = COLORS["kr_up"] if cp > 0 else (COLORS["kr_down"] if cp < 0 else mut)
        close = x.get("close", 0)
        prev = close / (1 + cp / 100) if cp not in (0, -100) else close
        won = close - prev
        vol = x.get("volume")
        vol_s = f'{int(vol):,}' if vol else "—"
        amt_s = x.get("amount_str", "—")
        mc_s = x.get("marcap_str", "—")
        trs += (
            f'<tr style="border-bottom:1px solid {COLORS["border"]}; font-size:0.9rem; text-align:right;">'
            f'<td style="text-align:left; padding:9px 10px; color:{mut};">{x.get("rank","")}</td>'
            f'<td style="text-align:left; line-height:1.3;"><b style="color:#16202E; font-size:1.12rem; font-weight:800;">{x.get("name","")}</b><br>'
            f'<span style="color:{mut}; font-size:0.74rem;">{x.get("code","")} · {x.get("market","")}</span></td>'
            f'<td style="color:#16202E; font-weight:700;">{close:,.0f}</td>'
            f'<td style="color:{c}; font-weight:700; line-height:1.3;">{won:+,.0f}<br>{cp:+.2f}%</td>'
            f'<td style="color:{mut};">{vol_s}</td>'
            f'<td style="color:#16202E; font-weight:600;">{amt_s}</td>'
            f'<td style="color:{mut}; padding-right:10px;">{mc_s}</td></tr>'
        )
    return (
        f'<table style="width:100%; border-collapse:collapse; background:transparent; '
        f'border:none;">{head}{trs}</table>'
    )


def render_etf_track_table(rows):
    """미국 ETF 추이 표 (글로벌 표준: 상승 초록/하락 빨강, 세로줄 없음)."""
    if not rows:
        return f'<div style="color:{COLORS["text_muted"]}; font-size:0.9rem; padding:14px;">ETF 데이터 없음</div>'
    mut = COLORS["text_muted"]; gp = COLORS["accent_green"]; rp = COLORS["accent_red"]

    def col(v):
        if v is None or (isinstance(v, float) and v != v):
            return mut
        return gp if v > 0 else (rp if v < 0 else mut)

    def fp(v):
        if v is None or (isinstance(v, float) and v != v):
            return "-"
        return f"{v:+.2f}%"

    head = (
        f'<tr style="border-bottom:2px solid {COLORS["border"]}; color:{mut}; font-size:0.8rem; font-weight:600; text-align:right;">'
        f'<th style="text-align:left; padding:9px 10px;">#</th><th style="text-align:left;">ETF</th>'
        f'<th>1D</th><th>5D</th><th>20D</th><th>60D</th><th>SPY대비</th><th>거래대금</th>'
        f'<th style="padding-right:10px;">신호</th></tr>'
    )
    trs = ""
    for i, x in enumerate(rows, 1):
        trs += (
            f'<tr style="border-bottom:1px solid {COLORS["border"]}; font-size:0.9rem; text-align:right;">'
            f'<td style="text-align:left; padding:9px 10px; color:{mut};">{i}</td>'
            f'<td style="text-align:left; line-height:1.3;"><b style="color:#16202E; font-size:1.05rem; font-weight:800;">{x["etf"]}</b><br>'
            f'<span style="color:{mut}; font-size:0.74rem;">{x["group"]} · {x["industry"]}</span></td>'
            f'<td style="color:{col(x["d1"])}; font-weight:700;">{fp(x["d1"])}</td>'
            f'<td style="color:{col(x["d5"])}; font-weight:700;">{fp(x["d5"])}</td>'
            f'<td style="color:{col(x["d20"])}; font-weight:700;">{fp(x["d20"])}</td>'
            f'<td style="color:{col(x["d60"])}; font-weight:700;">{fp(x["d60"])}</td>'
            f'<td style="color:{col(x["rel20"])}; font-weight:800;">{fp(x["rel20"])}</td>'
            f'<td style="color:{col(x["tvchg"])};">{fp(x["tvchg"])}</td>'
            f'<td style="padding-right:10px;"><span style="background:rgba(21,101,192,0.08); color:{COLORS["text"]}; '
            f'font-size:0.72rem; font-weight:700; padding:3px 8px; border-radius:999px; white-space:nowrap;">{x["signal"]}</span></td>'
            f'</tr>'
        )
    return (f'<table style="width:100%; border-collapse:collapse; background:transparent; border:none;">'
            f'{head}{trs}</table>')


def render_sector_cards(summary, legend):
    """섹터별 평균 1일 수익률 분포 카드 + 색상 범례 (상단 테두리=버킷색)."""
    mut = COLORS["text_muted"]; gp = COLORS["accent_green"]; rp = COLORS["accent_red"]

    def fp(v):
        if v is None or (isinstance(v, float) and v != v):
            return "n/a"
        return f"{v:+.2f}%"

    def col(v):
        if v is None or (isinstance(v, float) and v != v):
            return mut
        return gp if v > 0 else (rp if v < 0 else mut)

    legend_html = "".join(
        f'<span style="display:inline-flex; align-items:center; gap:6px; font-size:0.78rem; font-weight:700; color:{COLORS["text"]};">'
        f'<span style="width:13px; height:13px; border-radius:4px; background:{c}; display:inline-block;"></span>{lab}</span>'
        for lab, c in legend
    )
    cards = "".join(
        f'<div style="background:#FFFFFF; border:1px solid {COLORS["border"]}; border-top:5px solid {s["color"]}; '
        f'border-radius:10px; padding:14px 15px 13px; min-height:128px;">'
        f'<div style="color:#0B0F14; font-weight:800; font-size:0.95rem; min-height:36px; line-height:1.25;">{s["group"]}</div>'
        f'<div style="font-weight:900; font-size:1.8rem; margin-top:6px; color:{col(s["avg"])};">{fp(s["avg"])}</div>'
        f'<div style="color:{mut}; font-size:0.74rem; font-weight:700; margin-top:5px;">평균 1일 수익률</div>'
        f'<div style="color:{mut}; font-size:0.74rem; font-weight:700; margin-top:3px;">최저 {s["worst_etf"]} {fp(s["worst"])}</div>'
        f'<div style="color:{mut}; font-size:0.74rem; font-weight:700; margin-top:3px;">{s["count"]} ETFs</div>'
        f'</div>'
        for s in summary
    )
    return (
        f'<div style="display:flex; flex-wrap:wrap; gap:12px 20px; margin:4px 0 16px;">{legend_html}</div>'
        f'<div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(165px, 1fr)); gap:12px;">{cards}</div>'
    )


# ── 글로벌 매크로 스코어보드 ──────────────────────
def _clamp(x, lo=0, hi=100):
    return max(lo, min(hi, x))


def compute_macro_scoreboard(snap, rates, comms, inflation_path):
    sm = {it["name"]: it for it in (snap or [])}
    rm = {it["name"]: it for it in (rates or [])}
    cm = {it["name"]: it for it in (comms or [])}
    cats = []
    eq = [sm[x]["pct"] for x in ["S&P 500", "나스닥", "다우", "러셀 2000"] if x in sm]
    if eq:
        avg = sum(eq) / len(eq)
        cats.append({"name": "글로벌주식", "score": round(_clamp(50 + avg * 6)), "detail": f"지수 평균 {avg:+.2f}%"})
    if "미 10년물" in rm:
        y = rm["미 10년물"]["last"]
        cats.append({"name": "금리", "score": round(_clamp(50 - (y - 4.0) * 12)), "detail": f"美 10Y {y:.2f}%"})
    if "VIX" in sm:
        v = sm["VIX"]["last"]
        cats.append({"name": "변동성", "score": round(_clamp(50 - (v - 18) * 2.5)), "detail": f"VIX {v:.1f}"})
    if "원/달러" in sm:
        fx = sm["원/달러"]["last"]
        cats.append({"name": "환율", "score": round(_clamp(50 - (fx - 1300) / 8)), "detail": f"원/달러 {fx:,.0f}"})
    if "WTI" in cm:
        w = cm["WTI"]["pct"]
        cats.append({"name": "원자재", "score": round(_clamp(50 - w * 2.5)), "detail": f"WTI {w:+.1f}%"})
    try:
        with open(inflation_path, encoding="utf-8") as f:
            cpi = json.load(f)["data"][-1]["CPI_YoY"]
        cats.append({"name": "인플레이션", "score": round(_clamp(50 - (cpi - 2.0) * 18)), "detail": f"CPI YoY {cpi:.1f}%"})
    except Exception:
        pass
    if not cats:
        return None
    return {"composite": round(sum(c["score"] for c in cats) / len(cats)), "categories": cats}


def render_macro_scoreboard(sb):
    comp = sb["composite"]
    cc = _score_color(comp)
    lbl = "우호 Favorable" if comp >= 60 else ("중립 Mixed" if comp >= 40 else "부정 Stress")
    cards = ""
    for c in sb["categories"]:
        s = c["score"]
        sc = _score_color(s)
        cards += (
            f'<div style="flex:1; min-width:115px; background:{COLORS["bg_card"]}; border:1px solid {COLORS["border"]}; '
            f'border-top:3px solid {sc}; border-radius:8px; padding:10px 12px;">'
            f'<div style="display:flex; justify-content:space-between; align-items:baseline;">'
            f'<span style="color:{COLORS["text"]}; font-size:0.82rem; font-weight:600;">{c["name"]}</span>'
            f'<span style="color:{sc}; font-size:1.1rem; font-weight:800;">{s}</span></div>'
            f'<div style="background:{COLORS["bg_card_hover"]}; border-radius:4px; height:6px; margin:6px 0 4px; overflow:hidden;">'
            f'<div style="width:{s}%; height:100%; background:{sc};"></div></div>'
            f'<div style="color:{COLORS["text_muted"]}; font-size:0.72rem;">{c["detail"]}</div></div>'
        )
    return (
        f'<div style="background:{COLORS["bg_card"]}; border:1px solid {COLORS["border"]}; border-left:6px solid {cc}; '
        f'border-radius:0 12px 12px 0; padding:16px 20px; margin-bottom:8px;">'
        f'<div style="display:flex; align-items:center; gap:18px; margin-bottom:12px;">'
        f'<div style="text-align:center; min-width:60px;"><div style="font-size:2.3rem; font-weight:800; color:{cc}; line-height:1;">{comp}</div>'
        f'<div style="color:{COLORS["text_muted"]}; font-size:0.68rem;">/ 100</div></div>'
        f'<div><div style="font-size:1.2rem; font-weight:800; color:{cc};">{lbl}</div>'
        f'<div style="color:{COLORS["text_muted"]}; font-size:0.76rem;">한국 증시 매크로 우호도 · 높을수록 우호</div></div></div>'
        f'<div style="display:flex; flex-wrap:wrap; gap:8px;">{cards}</div></div>'
    )


def section_header(en, ko):
    """레퍼런스식 섹션 헤더: 영문 eyebrow + 한글 타이틀."""
    st.markdown(
        f'<div class="sec-wrap"><div class="sec-eyebrow">{en}</div>'
        f'<div class="sec-title">{ko}</div></div>',
        unsafe_allow_html=True,
    )


# ════════════════════ 페이지 ════════════════════
# 10분 자동 새로고침 (세션·필터 선택 유지). 미설치 시 수동 새로고침만.
if HAS_AUTOREFRESH:
    st_autorefresh(interval=REFRESH_SEC * 1000, key="auto_refresh_10m")

# 갱신 상태 + 수동 새로고침
_rc1, _rc2 = st.columns([4, 1])
with _rc1:
    auto_txt = "🔄 10분마다 자동 갱신" if HAS_AUTOREFRESH else "수동 새로고침 (streamlit-autorefresh 미설치)"
    st.markdown(
        f'<div style="color:{COLORS["text_muted"]}; font-size:0.8rem;">{auto_txt} · 시세 갱신 {now_kst()} (KST)</div>',
        unsafe_allow_html=True)
with _rc2:
    if st.button("지금 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

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
    f'<div style="color:{COLORS["text_muted"]}; font-size:0.98rem; margin:0 0 6px; font-weight:600;">'
    f'기준일 <b style="color:#16202E; font-size:1.08rem;">{date}</b> · '
    f'최종 갱신 <b style="color:#16202E; font-size:1.05rem;">{updated} (KST)</b> · '
    f'<span style="font-size:0.85rem;">미국 티커 {events_data.get("ticker_count",0)}개 / 이벤트 {events_data.get("event_count",0)}건</span></div>',
    unsafe_allow_html=True,
)

# ── 0) 한국 시장 데이터 로드 ──
km = load_kr_market_live()

# ── 한국 시장 현황 ──────────────────────────
if km:
    section_header("KOREA MARKET", "한국 시장 현황")
    flows = km.get("flows") or {}
    breadth_km = km.get("breadth", {})
    k_cols = st.columns(4)
    # 이 행의 4개 카드 동일 높이 (가로 블록 stretch + 테두리 컨테이너 100% 채움)
    _S = 'div[data-testid="stHorizontalBlock"]:has(.kr-eq-marker)'
    st.markdown(
        '<style>'
        f'{_S}{{align-items:stretch;flex-wrap:nowrap;}}'
        f'{_S} > div[data-testid="stColumn"] > div[data-testid="stVerticalBlock"]{{height:100%;}}'
        f'{_S} > div[data-testid="stColumn"] > div[data-testid="stVerticalBlock"] > div[data-testid="stLayoutWrapper"]{{height:100%;}}'
        f'{_S} > div[data-testid="stColumn"] > div[data-testid="stVerticalBlock"] > div[data-testid="stLayoutWrapper"] > div[data-testid="stVerticalBlock"]{{height:100%;}}'
        # 폴백: 테두리 컨테이너 자체도 100% (testid/구조 변동 대비)
        f'{_S} div[data-testid="stVerticalBlockBorderWrapper"]{{height:100%;}}'
        # 거래대금(마지막) 카드: 마크다운이 카드 높이를 채우도록
        f'{_S} > div[data-testid="stColumn"]:last-child div[data-testid="stElementContainer"]{{height:100%;}}'
        f'{_S} > div[data-testid="stColumn"]:last-child div[data-testid="stMarkdown"]{{height:100%;}}'
        f'{_S} > div[data-testid="stColumn"]:last-child div[data-testid="stMarkdownContainer"]{{height:100%;}}'
        '</style>', unsafe_allow_html=True)

    # 1·2번째 카드: 코스피 / 코스닥 (레퍼런스 카드 형식)
    for i, (nm, key) in enumerate([("코스피", "kospi"), ("코스닥", "kosdaq")]):
        ix = km.get(key)
        with k_cols[i]:
            with st.container(border=True):
                if ix:
                    c = COLORS["kr_up"] if ix["change_pct"] >= 0 else COLORS["kr_down"]
                    arrow = "▲" if ix["change"] >= 0 else "▼"
                    st.markdown(
                        f'<div style="font-size:1.08rem; font-weight:800; color:#16202E; margin-bottom:3px;">'
                        f'<span class="kr-eq-marker"></span>🇰🇷 {nm} '
                        f'<span style="color:{COLORS["text_muted"]}; font-weight:400; font-size:0.74rem;">· 장마감</span></div>'
                        f'<div style="display:flex; align-items:baseline; gap:8px; flex-wrap:wrap;">'
                        f'<span style="font-size:1.4rem; font-weight:800; color:#16202E;">{ix["close"]:,.2f}</span>'
                        f'<span style="color:{c}; font-size:0.82rem; font-weight:700;">{arrow} {ix["change"]:+,.2f}({ix["change_pct"]:+.2f}%)</span>'
                        f'</div>', unsafe_allow_html=True)
                    st.plotly_chart(kr_sparkline(ix["spark"], height=96), use_container_width=True,
                                    config={"displayModeBar": False})
                    st.markdown(render_index_detail(flows.get(key), breadth_km.get(key, {})),
                                unsafe_allow_html=True)

    # 3번째 카드: 상승/하락 (전체)
    with k_cols[2]:
        with st.container(border=True):
            st.markdown(render_breadth(breadth_km.get("total", {})), unsafe_allow_html=True)

    # 4번째 카드: 거래대금 (코스피·코스닥·합계 박스 + 전일대비%)
    with k_cols[3]:
        with st.container(border=True):
            def _amt(key):
                ix = km.get(key) or {}
                a = ix.get("amount")
                if not a:
                    a = (km.get("value", {}) or {}).get(key) or 0
                return a, ix.get("amount_prev")
            ka, kp = _amt("kospi")
            qa, qp = _amt("kosdaq")
            ta = ka + qa
            tp = (kp + qp) if (kp and qp) else None

            def chg_html(amt, prev, size="0.85rem"):
                if not (amt and prev):
                    return ""
                chg = (amt - prev) / prev * 100
                c = "#15803D" if chg >= 0 else "#B91C1C"  # +초록 / -어두운 빨강
                return (f'<span style="color:{c}; font-size:{size}; font-weight:700; '
                        f'margin-left:6px;">{chg:+.1f}%</span>')

            def vrow(label, amt, prev):  # 코스피/코스닥: 박스 없이 한 줄, 숫자 크게
                jo = amt / 1e12
                return (f'<div style="display:flex; justify-content:space-between; align-items:baseline;">'
                        f'<span style="color:{COLORS["text_muted"]}; font-size:0.95rem; font-weight:600;">{label}</span>'
                        f'<span><b style="color:#16202E; font-size:1.6rem; font-weight:800; '
                        f'letter-spacing:-0.02em;">{jo:,.1f}조</b>{chg_html(amt, prev)}</span></div>')

            total_box = (f'<div style="background:rgba(21,101,192,0.06); border:1px solid {COLORS["accent"]}55; '
                         f'border-radius:9px; padding:12px 14px;">'
                         f'<div style="color:{COLORS["text_muted"]}; font-size:0.82rem; font-weight:600;">합계</div>'
                         f'<div style="color:#16202E; font-size:1.95rem; font-weight:800; line-height:1.15; '
                         f'letter-spacing:-0.02em;">{ta/1e12:,.1f}조{chg_html(ta, tp, size="0.95rem")}</div></div>')

            st.markdown(
                '<div style="display:flex; flex-direction:column; height:100%;">'
                '<div style="color:#16202E; font-size:1.08rem; font-weight:800; margin-bottom:4px;">거래대금</div>'
                '<div style="display:flex; flex-direction:column; justify-content:space-around; flex:1; gap:6px;">'
                + vrow("코스피", ka, kp) + vrow("코스닥", qa, qp) + total_box
                + '</div></div>',
                unsafe_allow_html=True)

    # 시장 랭킹 (큰 카드 안, 레퍼런스식 pill 필터 세로 배치 + 확장 테이블)
    st.write("")
    with st.container(border=True):
        section_header("MARKET RANKING", "시장 랭킹")
        rks = km.get("rankings", {})
        asset = st.segmented_control("자산", ["주식", "ETF"], default="주식",
                                     key="rk_asset", label_visibility="collapsed") or "주식"
        mkt = st.segmented_control("시장", ["전체", "코스피", "코스닥"], default="전체",
                                   key="rk_mkt", label_visibility="collapsed") or "전체"
        CRIT = ["시가총액", "거래대금 상위", "상승", "하락", "거래량 상위", "52주 최고", "52주 최저"]
        crit = st.pills("기준", CRIT, default="시가총액", key="rk_crit", label_visibility="collapsed") or "시가총액"

        CMAP = {"시가총액": "시가총액", "거래대금 상위": "거래대금", "상승": "상승",
                "하락": "하락", "거래량 상위": "거래량"}
        rows = []
        if crit in CMAP:
            lookup_mkt = mkt if asset == "주식" else "전체"
            adata = rks.get(asset)
            rows = ((adata or {}).get(lookup_mkt, {}) or {}).get(CMAP[crit], [])
        elif crit in ("52주 최고", "52주 최저"):
            sig = load_json_safe(str(MARKET_SIGNAL_PATH)) or {}
            items = sig.get("new_high" if crit == "52주 최고" else "new_low", [])
            if mkt in ("코스피", "코스닥"):
                mk = "KOSPI" if mkt == "코스피" else "KOSDAQ"
                items = [it for it in items if it.get("market") == mk]
            rows = [{"rank": i + 1, **it} for i, it in enumerate(items[:20])]
        if asset == "ETF" and mkt != "전체":
            st.caption("ETF는 시장 구분 없이 전체 기준입니다.")
        st.markdown(render_ranking_table(rows), unsafe_allow_html=True)

# ── 3) 간밤 글로벌 스냅샷 ──────────────────────────
with st.container(border=True):
    section_header("US MARKET", "미국 시장")
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

# ── 주요 ETF 추이 ──────────────────────
if HAS_ETF:
    st.write("")
    with st.container(border=True):
        section_header("ETF TREND", "주요 ETF 추이")
        with st.spinner("주요 ETF 시세..."):
            etf_rows = load_etf_table("6mo")
        if etf_rows:
            # ── 섹터 1일 수익률 분포 ──
            st.markdown(f'<div style="color:{COLORS["accent"]}; font-weight:800; font-size:0.98rem; margin:2px 0 8px;">섹터 평균 1일 수익률</div>', unsafe_allow_html=True)
            sec_sum = sector_summary(etf_rows)
            sec_sort = st.segmented_control("섹터 정렬", ["평균 수익률순", "섹터명순", "최저 종목순"],
                                            default="평균 수익률순", key="etf_sec_sort",
                                            label_visibility="collapsed") or "평균 수익률순"
            if sec_sort == "최저 종목순":
                sec_sum = sorted(sec_sum, key=lambda s: (s["worst"] if s["worst"] == s["worst"] else 1e18))
            elif sec_sort == "섹터명순":
                sec_sum = sorted(sec_sum, key=lambda s: s["group"])
            else:
                sec_sum = sorted(sec_sum, key=lambda s: (s["avg"] if s["avg"] == s["avg"] else -1e18), reverse=True)
            st.markdown(render_sector_cards(sec_sum, BUCKET_LEGEND), unsafe_allow_html=True)
            st.caption("섹터별 구성 ETF의 평균 1일 수익률 · 카드 상단 색상은 수익률 구간 · 상승 초록/하락 빨강(미국 ETF)")
            st.write("")

            # ── ETF별 상세 표 ──
            st.markdown(f'<div style="color:{COLORS["accent"]}; font-weight:800; font-size:0.98rem; margin:6px 0 8px;">ETF별 상세</div>', unsafe_allow_html=True)
            _SK = {"SPY 상대강도": "rel20", "1D": "d1", "5D": "d5", "20D": "d20",
                   "60D": "d60", "거래대금": "tvchg"}
            etf_sort = st.pills("정렬", list(_SK), default="SPY 상대강도", key="etf_sort",
                                label_visibility="collapsed") or "SPY 상대강도"
            sk = _SK[etf_sort]
            srows = sorted(etf_rows,
                           key=lambda r: (r.get(sk) if r.get(sk) == r.get(sk) else -1e18),
                           reverse=True)
            st.markdown(render_etf_track_table(srows), unsafe_allow_html=True)
            st.caption("SPY 대비 20일 상대강도·거래대금 변화 기준 · 1D/5D/20D/60D 수익률 · 상승 초록/하락 빨강(미국 ETF)")
        else:
            st.caption("ETF 데이터 로딩 실패")

# ── 1-b) 매크로 — 금리 & 원자재 ──────────────────
with st.container(border=True):
    section_header("RATES &amp; COMMODITIES", "금리 · 원자재")
    with st.spinner("금리·원자재 시세..."):
        rates_df = load_macro_history("rates")
        comm_df = load_macro_history("commodities")
    rates = quotes_from_df(rates_df, RATE_TICKERS)
    comms = quotes_from_df(comm_df, COMMODITY_TICKERS)
    mc1, mc2 = st.columns([1, 1.4])
    with mc1:
        st.markdown(f'<div style="color:{COLORS["accent"]}; font-weight:700; font-size:0.85rem; margin-bottom:6px;">美 국채 수익률 (2·5·10·30년)</div>', unsafe_allow_html=True)
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

    # 매크로 이슈 분석 (매크로·지수 대주제를 상단으로 분리)
    macro_grp = next((g for g in (groups_list or []) if g.get("id") == "macro_index"), None)
    if macro_grp:
        st.markdown(f'<div style="color:{COLORS["text_muted"]}; font-size:0.8rem; margin:12px 0 6px;">어제 매크로 이슈 (금리·고용·환율·정책)</div>', unsafe_allow_html=True)
        st.markdown(render_group_card(macro_grp), unsafe_allow_html=True)

# ── 오늘의 논점 ──────────────────────────────
with st.container(border=True):
    brief = events_data.get("brief")
    section_header("TODAY'S BRIEFING", "오늘의 논점")
    if brief and brief.get("talking_points"):
        st.markdown(render_brief(brief), unsafe_allow_html=True)
    else:
        st.info("오늘의 논점이 아직 생성되지 않았습니다. `python3 scripts/update_us_events.py` 재실행 시 생성됩니다.")

# ── 3) 대주제별 심층 ────────────────────────────
with st.container(border=True):
    section_header("US SECTORS", "대주제별 심층 분석")

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
with st.container(border=True):
    section_header("US SECTOR ETF", "미국 섹터 ETF · 전일")
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
with st.container(border=True):
    section_header("KOREA ADR / GDR", "해외 상장 한국주 · 간밤")
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
with st.container(border=True):
    section_header("CALENDAR", "오늘 · 금주 일정")
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
with st.container(border=True):
    section_header("KOREA MOVERS", "한국 수급 · 특징주 · 전일")
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
            _bh = (f'<tr style="border-bottom:2px solid {COLORS["border"]}; color:{COLORS["text_muted"]}; '
                   f'font-size:0.82rem; text-align:right;"><th style="text-align:left; padding:7px 10px;">코드</th>'
                   f'<th style="text-align:left;">종목명</th><th>β</th><th style="padding-right:10px;">60일 상관</th></tr>')
            _br = "".join(
                f'<tr style="border-bottom:1px solid {COLORS["border"]}; font-size:0.88rem; text-align:right;">'
                f'<td style="text-align:left; padding:7px 10px; color:{COLORS["text_muted"]};">{r["코드"]}</td>'
                f'<td style="text-align:left; color:#16202E; font-weight:600;">{r["종목명"]}</td>'
                f'<td style="color:#16202E;">{r["β"]}</td>'
                f'<td style="color:#16202E; padding-right:10px;">{r["60일 상관"]}</td></tr>'
                for r in rows)
            st.markdown(f'<table style="width:100%; border-collapse:collapse; border:none;">{_bh}{_br}</table>',
                        unsafe_allow_html=True)
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
