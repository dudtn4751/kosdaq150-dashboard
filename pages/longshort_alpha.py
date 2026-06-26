"""롱숏 알파 스코어 — 섹터 내 종목 매수강도 순위 → 섹터 상세 → 개별 근거.

섹터 중립 롱숏 운용 흐름:
  ① 섹터 내 매수 강도 종목 순위(섹터별 롱/숏 후보) → ② 섹터 전체 종목 + 매크로/플레이북 → ③ 개별 종목 근거·페어.
섹터 간 우열(섹터 강도 랭킹)은 보지 않음 — 같은 섹터 내 상대 우열로 매매·페어 구성.
페어는 단순 과거 주가 상관이 아니라 동일 섹터(비즈니스 모델) + 펀더멘탈 프로파일 유사도까지 반영.
데이터: data/alpha.json (+ consensus·research·etf_flow), scripts/update_alpha.py, 매일 05:00 KST.
"""

import json
import os
import sys
from pathlib import Path

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from style import COLORS, now_kst  # noqa: E402

DATA = Path(__file__).parent.parent / "data"
UP, DOWN, MUT, ACC = COLORS["kr_up"], COLORS["kr_down"], COLORS["text_muted"], COLORS["accent"]


@st.cache_data(ttl=3600, show_spinner=False)
def _load(name):
    p = DATA / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def sc(v):
    return UP if v > 0 else (DOWN if v < 0 else MUT)


def won(v, eok_suffix="억"):
    """억 단위 값 → 조/억 표기."""
    if v is None:
        return "—"
    return f"{v/1e4:+,.1f}조" if abs(v) >= 1e4 else f"{v:+,.0f}{eok_suffix}"


def mini_line(values, color, key):
    """컨센서스 추정치 추이 미니 스파크라인 (None 제외)."""
    xs = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(xs) < 3:
        return None
    fig = go.Figure(go.Scatter(x=[x for x, _ in xs], y=[v for _, v in xs], mode="lines+markers",
                               line=dict(color=color, width=2), marker=dict(size=4, color=color)))
    fig.update_layout(height=90, margin=dict(l=4, r=4, t=4, b=4),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis=dict(visible=False), showlegend=False, hovermode=False,
                      yaxis=dict(showgrid=True, gridcolor="rgba(0,0,0,0.06)", showticklabels=False, zeroline=False))
    return fig


def fin_table(fin):
    """연간 실적 추이 테이블 (매출·영업이익·OPM·순이익, 추정연도 E 강조)."""
    yrs = fin.get("years") or []
    rev, op, npv = fin.get("rev") or [], fin.get("op") or [], fin.get("np") or []
    if not yrs or not op:
        return ""

    def fmt(v):
        if v is None or v != v:
            return "—"
        return f"{v/1e4:,.1f}조" if abs(v) >= 1e4 else f"{v:,.0f}억"

    def head():
        cells = '<th style="text-align:left; color:#7E8896; font-weight:700; padding:3px 6px;">연간(억)</th>'
        for y in yrs:
            e = str(y).endswith("E")
            c = ACC if e else "#16202E"
            bg = f"background:{ACC}0f;" if e else ""
            cells += f'<th style="text-align:right; color:{c}; font-weight:800; padding:3px 6px; {bg}">{str(y)[:4]}{"E" if e else ""}</th>'
        return f"<tr>{cells}</tr>"

    def rowh(label, arr, strong=False):
        cells = f'<td style="text-align:left; color:{MUT}; font-weight:700; padding:3px 6px;">{label}</td>'
        for i, v in enumerate(arr):
            e = i < len(yrs) and str(yrs[i]).endswith("E")
            bg = f"background:{ACC}0f;" if e else ""
            col = "#0B0F14" if strong else "#16202E"
            cells += f'<td style="text-align:right; color:{col}; font-weight:{800 if strong else 600}; padding:3px 6px; {bg}">{v}</td>'
        return f"<tr>{cells}</tr>"

    opm = [round(op[i] / rev[i] * 100, 1) if (i < len(rev) and rev[i]) else None for i in range(len(op))]
    rows = head()
    rows += rowh("매출액", [fmt(v) for v in rev])
    rows += rowh("영업이익", [fmt(v) for v in op], strong=True)
    rows += rowh("영업이익률", [f"{v:.1f}%" if v is not None else "—" for v in opm])
    rows += rowh("순이익", [fmt(v) for v in npv])
    return (f'<table style="width:100%; border-collapse:collapse; font-size:0.8rem; margin-top:6px; '
            f'border:1px solid {COLORS["border"]}; border-radius:8px; overflow:hidden;">{rows}</table>')


def sec_header(en, ko):
    st.markdown(
        f'<div style="margin:6px 0 10px;">'
        f'<div style="color:{ACC}; font-size:0.72rem; font-weight:700; letter-spacing:0.14em;">{en}</div>'
        f'<div style="color:#0B0F14; font-size:1.4rem; font-weight:800; letter-spacing:-0.02em;">{ko}</div></div>',
        unsafe_allow_html=True)


def strength_bar(v, h=12):
    """-100~+100 종합점수 → 중앙 기준 좌/우 막대."""
    w = min(abs(v), 100) / 2
    side = "left:50%;" if v >= 0 else "right:50%;"
    c = sc(v)
    return (f'<div style="position:relative; height:{h}px; background:{COLORS["bg_card_hover"]}; border-radius:{h//2}px;">'
            f'<div style="position:absolute; {side} width:{w}%; height:100%; background:{c}; border-radius:{h//2}px;"></div>'
            f'<div style="position:absolute; left:50%; top:-1px; width:1px; height:{h+2}px; background:{COLORS["border"]};"></div></div>')


def factor_bar(label, v):
    w = min(abs(v), 100) / 2
    side = "left:50%;" if v >= 0 else "right:50%;"
    c = sc(v)
    return (f'<div style="display:flex; align-items:center; gap:8px; margin:3px 0;">'
            f'<span style="width:48px; color:{MUT}; font-size:0.8rem; font-weight:700;">{label}</span>'
            f'<div style="flex:1; position:relative; height:10px; background:{COLORS["bg_card_hover"]}; border-radius:5px;">'
            f'<div style="position:absolute; {side} width:{w}%; height:100%; background:{c}; border-radius:5px;"></div>'
            f'<div style="position:absolute; left:50%; top:-1px; width:1px; height:12px; background:{COLORS["border"]};"></div></div>'
            f'<span style="width:40px; text-align:right; color:{c}; font-size:0.86rem; font-weight:800;">{v:+.0f}</span></div>')


def price_volume_fig(ohlc):
    """실제 증권 차트 — 캔들(상승 빨강·하락 파랑) + 거래대금 막대. 가격축 자동 범위(괴리 없음)."""
    d = ohlc.get("d", [])
    o, h, l, c = ohlc.get("o", []), ohlc.get("h", []), ohlc.get("l", []), ohlc.get("c", [])
    amt = ohlc.get("amt", [])
    n = len(c)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04,
                        row_heights=[0.72, 0.28])
    fig.add_trace(go.Candlestick(
        x=d, open=o, high=h, low=l, close=c, name="",
        increasing=dict(line=dict(color=UP, width=1), fillcolor=UP),
        decreasing=dict(line=dict(color=DOWN, width=1), fillcolor=DOWN),
        whiskerwidth=0.4, showlegend=False), row=1, col=1)
    if amt and len(amt) == n:
        vcol = [UP if (i == 0 or c[i] >= c[i - 1]) else DOWN for i in range(n)]
        fig.add_trace(go.Bar(x=d, y=amt, marker_color=vcol, marker_line_width=0,
                             name="", showlegend=False, hovertemplate="%{y:,.0f}억<extra></extra>"),
                      row=2, col=1)
    # x축: 영업일만(주말 갭 제거) → category, 날짜 라벨 일부만
    step = max(1, n // 6)
    ticks = list(range(0, n, step))
    fig.update_xaxes(type="category", showgrid=False, row=1, col=1, showticklabels=False,
                     rangeslider_visible=False)
    fig.update_xaxes(type="category", showgrid=False, row=2, col=1,
                     tickmode="array", tickvals=[d[i] for i in ticks] if d else [],
                     tickfont=dict(size=10, color=MUT), tickangle=0)
    fig.update_yaxes(side="right", showgrid=True, gridcolor="rgba(0,0,0,0.06)",
                     tickfont=dict(size=10, color=MUT), tickformat=",d", row=1, col=1)
    fig.update_yaxes(side="right", showgrid=False, tickfont=dict(size=9, color=MUT),
                     tickformat=",d", title=None, row=2, col=1)
    fig.update_layout(height=430, margin=dict(l=4, r=8, t=8, b=4),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      showlegend=False, hovermode="x unified", bargap=0.25,
                      dragmode=False)
    return fig


# ── 데이터 ──
alpha = _load("alpha.json")
sec_header("LONG-SHORT ALPHA", "롱숏 알파 스코어")
if not alpha or not alpha.get("ranked"):
    st.warning("알파 데이터가 없습니다. `python3 scripts/update_alpha.py` 실행이 필요합니다.")
    st.stop()

ranked = alpha["ranked"]
sectors = alpha.get("sectors") or []
by_code = {s["code"]: s for s in ranked}
by_name = {s["name"]: s for s in ranked}
rank_of = {s["code"]: i + 1 for i, s in enumerate(ranked)}
N = len(ranked)
cov = alpha.get("coverage_pct", 0)
consensus = {s["code"]: s for s in (_load("consensus.json").get("stocks") or [])}
research = _load("research_reports.json")
reports_by_code = {}
for r in research.get("reports", []):
    reports_by_code.setdefault(r.get("code"), []).append(r)
etf_flow = _load("etf_flow.json")
pressure_by_code = {p["code"]: p for p in etf_flow.get("pressure", [])}
drivers_data = _load("market_drivers.json")
sector_macro = drivers_data.get("sector_signals", {})


@st.cache_data(ttl=3600, show_spinner=False)
def _load_json_root(fname, key):
    try:
        p = Path(__file__).parent.parent / fname
        return json.loads(p.read_text(encoding="utf-8")).get(key, {})
    except Exception:
        return {}


playbook = _load_json_root("sector_playbook.json", "playbook")
exposure = _load_json_root("sector_exposure.json", "exposures")


def macro_chip(sec):
    """섹터 매크로 환경 칩 (HTML). 없으면 빈 문자열."""
    m = sector_macro.get(sec)
    if not m:
        return ""
    sig = m["signal"]
    c = UP if sig >= 0.5 else (DOWN if sig <= -0.5 else MUT)
    return (f'<span style="background:{c}1a; color:{c}; font-weight:800; font-size:0.72rem; '
            f'padding:1px 8px; border-radius:999px;">매크로 {m["label"]} {sig:+.1f}</span>')

st.markdown(
    f'<div style="color:{MUT}; font-size:0.86rem; font-weight:600; margin-bottom:10px;">'
    f'기준일 <b style="color:#16202E;">{alpha.get("date","-")}</b> · 유니버스 {N}종목(시총≥3천억) · {len(sectors)}개 섹터 · 커버리지 '
    f'<b style="color:{ACC};">{cov}%</b> · 점수 기준 <b style="color:#16202E;">섹터별</b> (비중·컷) '
    f'<span style="font-size:0.8rem;">— 활성: EPS·상대강도·이벤트·퀄리티 / 대기: 대체데이터(수출·인바운드, 키 필요)</span></div>',
    unsafe_allow_html=True)

# ── 내비게이션 상태 ──
st.session_state.setdefault("ls_sector", None)
st.session_state.setdefault("ls_stock", None)


def go_home():
    st.session_state.ls_sector = None
    st.session_state.ls_stock = None
    st.session_state.search_box = ""


def go_sector(sec):
    st.session_state.ls_sector = sec
    st.session_state.ls_stock = None


def go_stock(code):
    st.session_state.ls_stock = code
    if by_code.get(code):
        st.session_state.ls_sector = by_code[code]["sector"]


def on_search():
    nm = st.session_state.search_box
    if nm and nm in by_name:
        go_stock(by_name[nm]["code"])


# 빠른 검색 (어느 화면에서든 종목 점프)
st.selectbox("빠른 검색 (종목명)", [""] + [s["name"] for s in ranked],
             key="search_box", on_change=on_search, placeholder="종목명을 입력하면 바로 이동")


sector_meta = {s["sector"]: s for s in sectors}


# ── 화면 1: 섹터 내 매수 강도 종목 순위 (섹터 중립 롱숏) ──
def render_landing():
    sec_header("WITHIN-SECTOR STRENGTH", "섹터 내 매수 강도 종목 순위")
    st.caption("각 섹터 안에서 종합점수 상위=롱 후보 / 하위=숏 후보. 섹터 중립 롱숏 — 같은 섹터 내 상대 우열로 매매·페어를 구성. (섹터 간 우열은 보지 않음)")
    by_sec = {}
    for x in ranked:
        by_sec.setdefault(x["sector"], []).append(x)
    order = sorted(by_sec.keys(), key=lambda k: -len(by_sec[k]))  # 종목수 많은 섹터부터(강도순 아님)

    def stock_btn(x, side_col, key_prefix):
        score = x["score"]
        st.button(f"{x['name']}   {score:+.0f}", key=f"{key_prefix}_{x['code']}",
                  on_click=go_stock, args=(x["code"],), use_container_width=True)

    for sec in order:
        rows = sorted(by_sec[sec], key=lambda x: x["score"], reverse=True)
        meta = sector_meta.get(sec, {})
        lc, scut = meta.get("long_cut", 20), meta.get("short_cut", -20)
        longs = [x for x in rows if x["score"] >= lc][:5] or rows[:3]
        long_codes = {x["code"] for x in longs}
        rest = [x for x in rows if x["code"] not in long_codes]
        qual_short = [x for x in rest if x["score"] <= scut]
        shorts = sorted(qual_short, key=lambda x: x["score"])[:5] if qual_short \
            else sorted(rest, key=lambda x: x["score"])[:3]
        with st.container(border=True):
            hc1, hc2 = st.columns([3, 1])
            with hc1:
                st.markdown(
                    f'<div style="display:flex; align-items:baseline; gap:8px;">'
                    f'<span style="font-size:1.12rem; font-weight:800; color:#16202E;">{sec}</span>'
                    f'<span style="color:{MUT}; font-size:0.8rem;">{len(rows)}종목 · 롱 {meta.get("long_n",0)}/숏 {meta.get("short_n",0)}</span>'
                    f'<span style="margin-left:8px;">{macro_chip(sec)}</span></div>'
                    + (f'<div style="font-size:0.76rem; color:{MUT}; margin-top:2px;">📌 {meta.get("drivers","")}</div>' if meta.get("drivers") else ""),
                    unsafe_allow_html=True)
            with hc2:
                st.button(f"전체 {len(rows)} →", key=f"sec_{sec}", on_click=go_sector, args=(sec,),
                          use_container_width=True)
            lcol, scol = st.columns(2)
            with lcol:
                st.markdown(f'<div style="color:{UP}; font-weight:800; font-size:0.84rem; margin:2px 0;">롱 후보 (강도 상위)</div>',
                            unsafe_allow_html=True)
                for x in longs:
                    stock_btn(x, UP, "L")
            with scol:
                st.markdown(f'<div style="color:{DOWN}; font-weight:800; font-size:0.84rem; margin:2px 0;">숏 후보 (강도 하위)</div>',
                            unsafe_allow_html=True)
                for x in shorts:
                    stock_btn(x, DOWN, "S")


# ── 화면 2: 섹터 내 종목 스코어 ──
def render_sector_stocks(sec):
    cb = st.columns([1, 6])[0]
    cb.button("← 처음으로", on_click=go_home, use_container_width=True)
    meta = next((x for x in sectors if x["sector"] == sec), None)
    sec_header("SECTOR", f"{sec} — 종목 매수 강도")
    if meta:
        st.markdown(
            f'<div style="color:#16202E; font-size:0.92rem; margin-bottom:6px;">'
            f'섹터 매수 강도 <b style="color:{sc(meta["avg_score"])}; font-size:1.05rem;">{meta["avg_score"]:+.1f}</b> · '
            f'<span style="color:{UP};">롱 후보 {meta["long_n"]}</span> / <span style="color:{DOWN};">숏 후보 {meta["short_n"]}</span> · '
            f'외국인·기관 수급 <b style="color:{sc(meta["net_flow"])};">{won(meta["net_flow"])}</b></div>',
            unsafe_allow_html=True)
    if meta:
        w = meta.get("weights", {})
        st.markdown(
            f'<div style="background:{COLORS["bg_card_hover"]}; border-radius:8px; padding:8px 12px; margin:2px 0 8px; font-size:0.82rem; color:#16202E;">'
            f'<b style="color:{ACC};">섹터 점수 기준</b> · 비중 EPS×{w.get("eps","-")} / 상대강도×{w.get("rs","-")} / 이벤트×{w.get("event","-")} / 퀄리티×{w.get("quality","-")} · '
            f'판정 컷 <b>롱 ≥ {meta.get("long_cut")}</b> / <b>숏 ≤ {meta.get("short_cut")}</b>'
            + (f'<br><span style="color:{MUT};">핵심 지표: {meta.get("drivers","")} · 밸류 {meta.get("valuation","")} — {meta.get("note","")}</span>' if meta.get("drivers") else "")
            + '</div>', unsafe_allow_html=True)
    # 매크로/스프레드 드라이버 환경 + 플레이북
    mac = sector_macro.get(sec)
    pb = playbook.get(sec)
    if mac or pb:
        mc1, mc2 = st.columns([1, 1])
        with mc1:
            with st.container(border=True):
                if mac:
                    sig = mac["signal"]
                    c = UP if sig >= 0.5 else (DOWN if sig <= -0.5 else MUT)
                    st.markdown(
                        f'<div style="font-weight:800; color:#16202E; font-size:0.95rem;">매크로/스프레드 환경 '
                        f'<span style="color:{c};">{mac["label"]} {sig:+.1f}</span></div>',
                        unsafe_allow_html=True)
                    for d in mac["drivers"][:6]:
                        dc = UP if d["contrib"] > 0.15 else (DOWN if d["contrib"] < -0.15 else MUT)
                        st.markdown(
                            f'<div style="font-size:0.84rem; padding:1px 0; color:#16202E;">'
                            f'{d["name"]} <b style="color:{sc(d["trend_z"])};">{d["updown"]} z{d["trend_z"]:+.1f}</b> '
                            f'<span style="color:{MUT};">→</span> <b style="color:{dc};">{d["side"]}</b></div>',
                            unsafe_allow_html=True)
                    st.caption("드라이버 추세 × 섹터 영향 = 매크로 환경. 섹터 전체에 작용(구성원 균일).")
                else:
                    st.caption("이 섹터의 매크로 드라이버 신호 없음 (이벤트/펀더 기반).")
        with mc2:
            with st.container(border=True):
                if pb:
                    def _li(items, lab, col):
                        if not items:
                            return ""
                        return (f'<div style="font-size:0.8rem; margin-top:4px;"><b style="color:{col};">{lab}</b> '
                                f'<span style="color:#16202E;">{" · ".join(items[:4])}</span></div>')
                    st.markdown(
                        f'<div style="font-weight:800; color:#16202E; font-size:0.95rem;">플레이북 '
                        f'<span style="color:{MUT}; font-size:0.78rem; font-weight:600;">{pb.get("sub","")}</span></div>'
                        + _li(pb.get("key_spreads"), "핵심 스프레드", ACC)
                        + _li(pb.get("long_signals"), "롱 시그널", UP)
                        + _li(pb.get("short_signals"), "숏 시그널", DOWN)
                        + _li(pb.get("pair_points"), "페어 포인트", "#16202E"),
                        unsafe_allow_html=True)
                    st.caption("섹터 내 상대강도 차등은 기업별 익스포저(고도화율·수출비중 등, 2차 레이어).")

    rows, _seen = [], set()
    for x in ranked:
        if x["sector"] == sec and x["code"] not in _seen:
            _seen.add(x["code"])
            rows.append(x)
    rows.sort(key=lambda x: x["score"], reverse=True)
    st.caption(f"{len(rows)}종목 · 종합점수 내림차순 (상위=롱 후보 / 하위=숏 후보). 종목을 누르면 근거·페어가 펼쳐집니다.")
    for ri, x in enumerate(rows):
        score = x["score"]
        lc, scut = x.get("long_cut", 20), x.get("short_cut", -20)
        verdict, vcol = ("롱", UP) if score >= lc else (("숏", DOWN) if score <= scut else ("중립", MUT))
        with st.container(border=True):
            c1, c2, c3 = st.columns([2.7, 2.4, 0.9])
            with c1:
                st.markdown(
                    f'<div style="display:flex; align-items:baseline; gap:8px;">'
                    f'<span style="font-size:1.05rem; font-weight:800; color:#16202E;">{x["name"]}</span>'
                    f'<span style="color:{MUT}; font-size:0.78rem;">{x["code"]}</span>'
                    f'<span style="margin-left:auto; font-size:1.15rem; font-weight:900; color:{sc(score)};">{score:+.0f}</span></div>'
                    + strength_bar(score, 10),
                    unsafe_allow_html=True)
            with c2:
                st.markdown(
                    f'<span style="background:{vcol}1a; color:{vcol}; font-weight:800; font-size:0.8rem; padding:2px 10px; border-radius:999px;">{verdict}</span> '
                    f'<span style="color:{MUT}; font-size:0.78rem;">랭킹 {rank_of[x["code"]]}/{N}</span>'
                    f'<div style="font-size:0.78rem; color:{MUT}; margin-top:4px;">EPS {x["eps"]:+.0f} · 상대강도 {x["rs"]:+.0f} · 이벤트 {x["event"]:+.0f}</div>',
                    unsafe_allow_html=True)
            with c3:
                st.button("스코어 →", key=f"st_{x['code']}_{ri}", on_click=go_stock, args=(x["code"],),
                          use_container_width=True)


# ── 화면 3: 개별 종목 근거 ──
def render_stock_detail(s):
    score = s["score"]
    lc, scut = s.get("long_cut", 20), s.get("short_cut", -20)
    verdict, vcolor = ("롱 후보", UP) if score >= lc else (("숏 후보", DOWN) if score <= scut else ("중립", MUT))

    cbs = st.columns([1, 1, 4])
    cbs[0].button("← 처음으로", on_click=go_home, use_container_width=True)
    cbs[1].button(f"← {s['sector']}", on_click=go_sector, args=(s["sector"],), use_container_width=True)

    # 스코어 카드
    with st.container(border=True):
        cL, cR = st.columns([1, 1.3])
        with cL:
            st.markdown(
                f'<div style="font-size:1.2rem; font-weight:800; color:#16202E;">{s["name"]} '
                f'<span style="color:{MUT}; font-size:0.85rem; font-weight:600;">{s["code"]} · {s["sector"]}</span></div>'
                f'<div style="font-size:3.2rem; font-weight:900; color:{sc(score)}; line-height:1.1; margin-top:4px;">{score:+.0f}</div>'
                f'<div><span style="background:{vcolor}1a; color:{vcolor}; font-weight:800; font-size:1.0rem; '
                f'padding:3px 12px; border-radius:999px;">{verdict}</span> '
                f'<span style="color:{MUT}; font-size:0.85rem;">랭킹 {rank_of[s["code"]]}/{N}</span></div>',
                unsafe_allow_html=True)
        with cR:
            w = s.get("weights", {"eps": 30, "rs": 15, "event": 10, "quality": 20})
            eps_note = "" if s.get("has_eps", True) else " · EPS 미커버→타팩터로 산출"
            st.markdown('<div style="padding-top:8px;">'
                        + factor_bar("EPS", s["eps"]) + factor_bar("상대강도", s["rs"])
                        + factor_bar("이벤트", s["event"]) + factor_bar("퀄리티", s.get("quality", 0))
                        + f'<div style="color:{MUT}; font-size:0.76rem; margin-top:6px;">종합 = '
                        f'EPS×{w.get("eps","-")} + 상대강도×{w.get("rs","-")} + 이벤트×{w.get("event","-")} + 퀄리티×{w.get("quality","-")} '
                        f'· <b style="color:#16202E;">{s["sector"]}</b> 기준 (롱≥{lc}/숏≤{scut}){eps_note}</div></div>',
                        unsafe_allow_html=True)

    # 차트 — 실제 증권 차트 (캔들 + 거래대금)
    ohlc = s.get("ohlc") or {}
    if ohlc.get("c"):
        with st.container(border=True):
            last = ohlc["c"][-1]
            chg = (last / ohlc["c"][-2] - 1) * 100 if len(ohlc["c"]) > 1 else 0
            st.markdown(
                f'<div style="display:flex; align-items:baseline; gap:10px;">'
                f'<span style="font-weight:700; color:#16202E; font-size:0.92rem;">가격 · 거래대금 (60거래일)</span>'
                f'<span style="font-size:1.0rem; font-weight:800; color:#16202E;">{last:,.0f}원</span>'
                f'<span style="font-size:0.86rem; font-weight:700; color:{sc(chg)};">{chg:+.1f}%</span>'
                f'<span style="margin-left:auto; color:{MUT}; font-size:0.74rem;">상승 빨강 · 하락 파랑 · 하단 거래대금(억)</span></div>',
                unsafe_allow_html=True)
            st.plotly_chart(price_volume_fig(ohlc), use_container_width=True,
                            config={"displayModeBar": False}, key="pv")

    # 근거 자료
    sec_header("EVIDENCE", "근거 자료")

    # 1) EPS Revision
    with st.container(border=True):
        c = consensus.get(s["code"], {})
        rev, yoy, op = s.get("rev_3m"), s.get("yoy"), c.get("op_est")
        st.markdown(f'<div style="font-weight:800; color:#16202E; font-size:1.02rem;">① EPS Revision '
                    f'<span style="color:{sc(s["eps"])}; font-size:0.9rem;">{s["eps"]:+.0f}점</span></div>',
                    unsafe_allow_html=True)

        # EPS Revision 3레이어 모듈(섹터상대) — 실현/모멘텀/포워드 분해 + 인사이트
        er = s.get("eps_rev")
        if er and er.get("score") is not None:
            lay = er.get("layers") or {}

            def _lay(key, label):
                v = lay.get(key)
                if v is None:
                    return f'<span style="color:{MUT}; font-size:0.82rem;">{label} —</span>'
                return f'<span style="font-size:0.82rem;">{label} <b style="color:{sc(v)};">{v:+.2f}</b></span>'
            conf = er.get("confidence", 1.0)
            st.markdown(
                f'<div style="background:{ACC}0f; border:1px solid {ACC}33; border-radius:8px; padding:8px 11px; margin:6px 0;">'
                f'<div style="display:flex; align-items:baseline; gap:10px;">'
                f'<span style="color:{ACC}; font-weight:800; font-size:0.82rem;">3레이어 리비전(섹터상대)</span>'
                f'<span style="font-size:1.05rem; font-weight:900; color:{sc(er["score"])};">{er["score"]:+.0f}</span>'
                f'<span style="margin-left:auto; color:{MUT}; font-size:0.78rem;">신뢰도 {conf*100:.0f}%</span></div>'
                f'<div style="display:flex; gap:16px; margin-top:4px;">'
                f'{_lay("realized","실현")} {_lay("momentum","모멘텀")} {_lay("forward","포워드")}</div>'
                + (f'<div style="font-size:0.84rem; color:#16202E; margin-top:6px;">💡 {er.get("insight","")}</div>' if er.get("insight") else "")
                + (f'<div style="font-size:0.78rem; color:{DOWN}; margin-top:3px;">⚠ {"; ".join(er["flags"])}</div>' if er.get("flags") else "")
                + '</div>',
                unsafe_allow_html=True)

        st.markdown(f'<div style="color:{ACC}; font-size:0.8rem; font-weight:700; margin-top:6px;">미래 예상 컨센서스 변화 (원천)</div>',
                    unsafe_allow_html=True)
        bits = []
        if rev is not None:
            bits.append(f'영업이익 컨센서스 <b style="color:{sc(rev)};">3개월 {rev:+.1f}%</b> 리비전')
        if op:
            bits.append(f'예상 영업이익 <b>{op/1e4:,.1f}조</b>' if op >= 1e4 else f'예상 영업이익 <b>{op:,.0f}억</b>')
        if yoy is not None:
            bits.append(f'전년대비 <b style="color:{sc(yoy)};">{yoy:+.1f}%</b>')
        st.markdown(f'<div style="color:#16202E; font-size:0.92rem; margin:4px 0;">{" · ".join(bits) or "컨센서스 데이터 없음"}</div>',
                    unsafe_allow_html=True)

        # 컨센서스 추정치 추이 (EPS·목표주가) — 누적 스냅샷
        eh = c.get("est_hist") or {}
        eps_series = eh.get("eps") or []
        valid = [v for v in eps_series if v is not None]
        if len(valid) >= 3:
            ec = UP if valid[-1] >= valid[0] else DOWN
            cE = st.columns([1, 2])[0]
            with cE:
                st.markdown(f'<div style="color:{MUT}; font-size:0.78rem; font-weight:700;">예상 EPS 컨센서스 추이</div>', unsafe_allow_html=True)
                fig = mini_line(eps_series, ec, "epstrend")
                if fig:
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, key="epstrend")
        elif rev is not None:
            st.caption("예상 EPS 컨센서스 추이는 매일 스냅샷으로 누적 중 — 현재는 3개월 리비전(위)으로 변화 판단.")

        # FnGuide 실제 컨센서스 — 목표주가·투자의견·EPS + 변화(리비전)
        tp, opin, neps = s.get("tp"), s.get("opinion"), s.get("eps_est")
        if tp or opin or neps:
            def delta(v, suf="%"):
                if v is None:
                    return ""
                return f' <b style="color:{sc(v)};">({v:+.1f}{suf})</b>'
            cb = []
            if tp:
                ups = s.get("tp_upside")
                up_s = f' · 상승여력 <b style="color:{sc(ups)};">{ups:+.0f}%</b>' if ups is not None else ""
                cb.append(f'목표주가 <b>{tp:,.0f}원</b>{delta(s.get("tp_chg"))}{up_s}')
            if opin is not None:
                oc = s.get("opinion_chg")
                oc_s = f' <b style="color:{sc(oc)};">({oc:+.2f})</b>' if oc else ""
                cb.append(f'투자의견 <b>{opin:.1f}</b>{oc_s}')
            if neps:
                cb.append(f'EPS <b>{neps:,.0f}원</b>{delta(s.get("eps_chg"))}')
            if s.get("n_est"):
                cb.append(f'추정 <b>{s["n_est"]}개사</b>')
            st.markdown(
                f'<div style="background:{COLORS["bg_card_hover"]}; border-radius:8px; padding:7px 11px; margin:6px 0; font-size:0.86rem; color:#16202E;">'
                f'<span style="color:{ACC}; font-weight:700;">FnGuide 컨센서스</span> · ' + " · ".join(cb) + '</div>',
                unsafe_allow_html=True)

        # 과거 실적 추이 테이블 (보고 기준 — 컨센서스 변화의 베이스라인)
        fin = c.get("fin")
        if fin and fin.get("op"):
            st.markdown(f'<div style="color:{MUT}; font-size:0.82rem; font-weight:700; margin-top:8px;">과거 실적 추이 (보고 기준 · 베이스라인)</div>'
                        + fin_table(fin), unsafe_allow_html=True)

        # 증권사 목표주가 컨센서스 + 직전 대비 변동률 (TP 리비전, wisereport)
        bt = c.get("broker_tp")
        if bt and bt.get("recent"):
            ac = bt.get("avg_chg")
            ac_s = f'<b style="color:{sc(ac)};">{ac:+.1f}%</b>' if ac is not None else "—"
            st.markdown(
                f'<div style="color:{MUT}; font-size:0.82rem; font-weight:700; margin-top:8px;">증권사 목표주가 (직전 대비 · {bt.get("n")}개사)</div>'
                f'<div style="font-size:0.88rem; color:#16202E; margin:3px 0;">평균 <b>{bt.get("tp_avg"):,}원</b> · '
                f'<span style="color:{UP};">상향 {bt.get("up",0)}</span> / <span style="color:{DOWN};">하향 {bt.get("down",0)}</span> · 평균 변동 {ac_s}</div>',
                unsafe_allow_html=True)
            for r in bt["recent"][:5]:
                chg = r.get("chg")
                tag = (f'<span style="color:{UP}; font-weight:800;">▲{chg:+.0f}%</span>' if chg and chg > 0
                       else (f'<span style="color:{DOWN}; font-weight:800;">▼{chg:+.0f}%</span>' if chg and chg < 0
                             else '<span style="color:#7E8896;">─</span>'))
                prev_s = f'{r["prev"]:,}→' if r.get("prev") else ""
                st.markdown(
                    f'<div style="font-size:0.84rem; padding:1px 0;">{tag} <b>{r.get("broker","")}</b> '
                    f'<span style="color:{MUT};">{prev_s}</span>{r.get("tp"):,}원 · {r.get("opinion","")} '
                    f'<span style="color:{MUT}; font-size:0.78rem;">{r.get("date","")}</span></div>',
                    unsafe_allow_html=True)

        reps = reports_by_code.get(s["code"], [])
        if reps:
            st.markdown(f'<div style="color:{MUT}; font-size:0.82rem; font-weight:700; margin-top:6px;">관련 증권사 리포트</div>',
                        unsafe_allow_html=True)
            for r in reps[:5]:
                d = r.get("direction")
                tag = (f'<span style="color:{UP}; font-weight:800;">TP▲</span>' if d == "up"
                       else (f'<span style="color:{DOWN}; font-weight:800;">TP▼</span>' if d == "down" else ""))
                st.markdown(
                    f'<div style="font-size:0.86rem; padding:2px 0;">{tag} <b>{r.get("broker","")}</b> '
                    f'목표가 {r.get("tp"):,}원 · {r.get("opinion","")} '
                    f'<span style="color:{MUT};">— {r.get("title","")}</span></div>'
                    if r.get("tp") else
                    f'<div style="font-size:0.86rem; padding:2px 0;">{tag} <b>{r.get("broker","")}</b> '
                    f'<span style="color:{MUT};">{r.get("title","")}</span></div>',
                    unsafe_allow_html=True)
        # 뉴스 심리 (KR-FinBERT)
        ns = s.get("news_sent")
        if ns is not None:
            nc = UP if ns > 0.15 else (DOWN if ns < -0.15 else MUT)
            lab = "긍정" if ns > 0.15 else ("부정" if ns < -0.15 else "중립")
            st.markdown(
                f'<div style="color:{MUT}; font-size:0.82rem; font-weight:700; margin-top:8px;">뉴스 심리 '
                f'<span style="color:{MUT}; font-weight:600;">(KR-FinBERT)</span> '
                f'<b style="color:{nc};">{lab} {ns:+.2f}</b></div>',
                unsafe_allow_html=True)
            for nr in (s.get("news_recent") or [])[:3]:
                sc_v = nr.get("s", 0)
                emo = "▲" if sc_v > 0.15 else ("▼" if sc_v < -0.15 else "·")
                st.markdown(
                    f'<div style="font-size:0.82rem; padding:1px 0; color:#16202E;">'
                    f'<span style="color:{sc(sc_v)}; font-weight:800;">{emo}</span> {nr.get("title","")[:48]}</div>',
                    unsafe_allow_html=True)
        st.caption("점수 = 미래 컨센서스 변화(영업이익 3M 리비전·증권사 TP 변동률·EPS 변화)를 핵심으로, 과거 실적을 베이스라인으로 결합. 컨센서스 상향 = 롱.")

    # 2) 상대강도
    with st.container(border=True):
        st.markdown(f'<div style="font-weight:800; color:#16202E; font-size:1.02rem;">② 상대강도 '
                    f'<span style="color:{sc(s["rs"])}; font-size:0.9rem;">{s["rs"]:+.0f}점</span></div>',
                    unsafe_allow_html=True)

        def r_s(v, suf="%"):
            return f'<b style="color:{sc(v)};">{v:+.1f}{suf}</b>' if v is not None else "—"
        st.markdown(
            f'<div style="display:flex; gap:24px; margin:6px 0; font-size:0.92rem; color:#16202E;">'
            f'<span>5일 {r_s(s.get("ret_5"))}</span><span>20일 {r_s(s.get("ret_20"))}</span>'
            f'<span>60일 {r_s(s.get("ret_60"))}</span>'
            f'<span style="border-left:1px solid {COLORS["border"]}; padding-left:24px;">업종 대비(RS) {r_s(s.get("rs_20"),"%p")}</span></div>',
            unsafe_allow_html=True)

        def flow_s(v):
            return f'<b style="color:{sc(v)};">{won(v)}</b>' if v is not None else "—"
        f20, i20 = s.get("frgn_20"), s.get("inst_20")
        if f20 is not None or i20 is not None:
            hold = s.get("frgn_hold")
            hold_s = f' · 외국인 보유율 <b>{hold:.1f}%</b>' if hold is not None else ""
            st.markdown(
                f'<div style="color:{MUT}; font-size:0.82rem; font-weight:700; margin-top:8px;">외국인/기관 수급 (20일 누적 순매수)</div>'
                f'<div style="display:flex; gap:24px; margin:3px 0; font-size:0.92rem; color:#16202E;">'
                f'<span>외국인 {flow_s(f20)}</span><span>기관 {flow_s(i20)}</span>'
                f'<span style="color:{MUT}; font-size:0.85rem;">{hold_s}</span></div>'
                f'<div style="color:{MUT}; font-size:0.78rem;">5일 — 외국인 {flow_s(s.get("frgn_5"))} · 기관 {flow_s(s.get("inst_5"))}</div>',
                unsafe_allow_html=True)
        st.caption("RS = 종목 20일−업종 평균. 외국인·기관 순매수 유입(+) = 수급 우위 → 롱 / 유출(−) → 숏.")

    # 3) 이벤트
    with st.container(border=True):
        st.markdown(f'<div style="font-weight:800; color:#16202E; font-size:1.02rem;">③ 이벤트 '
                    f'<span style="color:{sc(s["event"])}; font-size:0.9rem;">{s["event"]:+.0f}점</span></div>',
                    unsafe_allow_html=True)
        ev_bits = []
        if s.get("index_event") == "add":
            ev_bits.append(f'<b style="color:{UP};">코스닥150 신규 편입 예상</b> (패시브 매수 유입)')
        elif s.get("index_event") == "remove":
            ev_bits.append(f'<b style="color:{DOWN};">코스닥150 편출 예상</b> (패시브 매도)')
        pr = pressure_by_code.get(s["code"])
        if pr:
            etfs = " · ".join(f'{e["etf"]}({e["weight"]:.0f}%)' for e in pr.get("top_etfs", [])[:3])
            ev_bits.append(f'ETF 매수압력 <b>{pr["pressure_eok"]/1e4:,.1f}조</b> ({pr["etf_count"]}개 ETF 보유)')
            st.markdown(f'<div style="color:#16202E; font-size:0.92rem; margin:4px 0;">{"<br>".join(ev_bits)}</div>'
                        f'<div style="color:{MUT}; font-size:0.82rem;">주요 보유 ETF: {etfs}</div>',
                        unsafe_allow_html=True)
        elif ev_bits:
            st.markdown(f'<div style="color:#16202E; font-size:0.92rem; margin:4px 0;">{"<br>".join(ev_bits)}</div>',
                        unsafe_allow_html=True)
        else:
            st.markdown(f'<div style="color:{MUT}; font-size:0.9rem;">감지된 지수편입·ETF 수급 이벤트 없음</div>',
                        unsafe_allow_html=True)
        st.caption("지수 편입 예상·ETF 매수압력 클러스터링 = 수급 유입(롱) 근거 / 편출 = 매도(숏).")

    # 4) 퀄리티/저베타
    with st.container(border=True):
        st.markdown(f'<div style="font-weight:800; color:#16202E; font-size:1.02rem;">④ 퀄리티/저베타 '
                    f'<span style="color:{sc(s.get("quality",0))}; font-size:0.9rem;">{s.get("quality",0):+.0f}점</span></div>',
                    unsafe_allow_html=True)
        beta, vol, margin = s.get("beta"), s.get("vol"), s.get("margin")
        if beta is not None or margin is not None:
            # 저베타·저변동·고마진이 퀄리티(롱). 색: 마진 높을수록·베타/변동 낮을수록 우호.
            beta_c = UP if (beta is not None and beta < 0.9) else (DOWN if (beta is not None and beta > 1.1) else MUT)
            vol_c = UP if (vol is not None and vol < 35) else (DOWN if (vol is not None and vol > 55) else MUT)
            margin_s = (f'<b style="color:{sc(margin)};">{margin:+.2f}%</b>' if margin is not None
                        else '<b style="color:#7E8896;">—</b>')
            st.markdown(
                f'<div style="display:flex; gap:24px; margin:6px 0; font-size:0.92rem; color:#16202E;">'
                f'<span>영업이익/시총 {margin_s}</span>'
                f'<span style="border-left:1px solid {COLORS["border"]}; padding-left:24px;">베타 <b style="color:{beta_c};">{beta if beta is not None else "—"}</b></span>'
                f'<span>연변동성 <b style="color:{vol_c};">{f"{vol:.0f}%" if vol is not None else "—"}</b></span></div>',
                unsafe_allow_html=True)
        else:
            st.markdown(f'<div style="color:{MUT}; font-size:0.9rem;">퀄리티 데이터 없음(가격·컨센서스 부족)</div>',
                        unsafe_allow_html=True)
        st.caption("고마진(이익수익률)·저베타·저변동 = 퀄리티(롱) / 저마진·고베타·고변동 = 숏. 문서 퀄리티/저베타 팩터(20%).")

    # 5) 기업 익스포저 (애널 자료 기반 — 섹터 내 차등)
    exp = exposure.get(s["code"])
    if exp:
        with st.container(border=True):
            st.markdown(f'<div style="font-weight:800; color:#16202E; font-size:1.02rem;">⑤ 기업 익스포저 '
                        f'<span style="color:{MUT}; font-size:0.8rem; font-weight:600;">{exp.get("theme","")} · 애널 자료</span></div>',
                        unsafe_allow_html=True)

            def chips(items, col):
                return " ".join(f'<span style="background:{col}14; color:{col}; font-size:0.8rem; '
                                f'padding:2px 9px; border-radius:999px; margin-right:4px; display:inline-block; margin-bottom:3px;">{x}</span>'
                                for x in (items or []))
            if exp.get("end_market"):
                st.markdown(f'<div style="font-size:0.8rem; color:{MUT}; font-weight:700; margin-top:4px;">전방시장</div>'
                            f'<div style="margin:2px 0;">{chips(exp["end_market"], ACC)}</div>', unsafe_allow_html=True)
            if exp.get("cost"):
                st.markdown(f'<div style="font-size:0.8rem; color:{MUT}; font-weight:700; margin-top:4px;">원가 노출</div>'
                            f'<div style="margin:2px 0;">{chips(exp["cost"], DOWN)}</div>', unsafe_allow_html=True)
            meta_bits = []
            if exp.get("util"):
                meta_bits.append(f'가동률 <b>{exp["util"]}</b>')
            if exp.get("product"):
                meta_bits.append(" · ".join(exp["product"]))
            if meta_bits:
                st.markdown(f'<div style="font-size:0.84rem; color:#16202E; margin-top:6px;">{" · ".join(meta_bits)}</div>',
                            unsafe_allow_html=True)
            if exp.get("key"):
                st.markdown(f'<div style="font-size:0.86rem; color:#16202E; margin-top:6px; padding:6px 10px; '
                            f'background:{COLORS["bg_card_hover"]}; border-radius:8px;">📌 {exp["key"]}</div>',
                            unsafe_allow_html=True)
        st.caption("매크로 드라이버는 섹터 전체에 작용 — 이 익스포저 차이가 섹터 내 상대강도(승자/패자)를 가른다. 자료 누적 시 점수 차등에 반영.")

    # 추천 페어 (동일 섹터·펀더멘탈 + 상관 헤지)
    cp = s.get("pair")
    with st.container(border=True):
        sec_header("PAIR", "추천 페어 (섹터·펀더멘탈 헤지)")
        if not cp:
            st.caption("적합한 페어 없음 (헤지 가능 상관 0.3↑ + 반대 점수 필요).")
        else:
            my_side = "롱" if score >= 0 else "숏"
            cp_side = "숏" if score >= 0 else "롱"
            ms, cs = (s["name"], cp["name"]) if score >= 0 else (cp["name"], s["name"])
            msc, csc = (score, cp["score"]) if score >= 0 else (cp["score"], score)
            biz = "동일 섹터 (비즈니스 모델 일치)" if cp.get("same_sector") else "교차 섹터 (매크로 헤지)"
            fs = cp.get("fund_sim")
            fs_pct = f'{fs*100:.0f}%' if fs is not None else "—"
            note = cp.get("fund_note", "")
            st.markdown(
                f'<div style="font-size:1.0rem; color:#16202E; line-height:1.7;">'
                f'<span style="color:{UP}; font-weight:800;">롱 {ms}</span> '
                f'<span style="color:{sc(msc)};">({msc:+.0f})</span> ↔ '
                f'<span style="color:{DOWN}; font-weight:800;">숏 {cs}</span> '
                f'<span style="color:{sc(csc)};">({csc:+.0f})</span></div>'
                f'<div style="display:flex; flex-wrap:wrap; gap:18px; margin-top:8px; font-size:0.9rem; color:#16202E;">'
                f'<span>상관(헤지) <b style="color:{ACC};">{cp["corr"]:.2f}</b></span>'
                f'<span>점수 스프레드 <b style="color:{ACC};">{cp["spread"]:.0f}</b></span>'
                f'<span>펀더멘탈 유사도 <b style="color:{ACC};">{fs_pct}</b></span></div>'
                f'<div style="margin-top:6px; font-size:0.85rem; color:{MUT};">'
                f'<b style="color:#16202E;">{biz}</b>{" · " + note if note else ""}</div>',
                unsafe_allow_html=True)
            st.caption("동일 섹터·유사 펀더멘탈일수록 시장/업종 베타가 상쇄되어 종목 고유 알파만 남습니다. "
                       f"{s['name']}을(를) {my_side}, {cp['name']}을(를) {cp_side}으로.")


# ── 라우팅 ──
if st.session_state.get("ls_stock") and by_code.get(st.session_state["ls_stock"]):
    render_stock_detail(by_code[st.session_state["ls_stock"]])
elif st.session_state.get("ls_sector"):
    render_sector_stocks(st.session_state["ls_sector"])
else:
    render_landing()

st.divider()
# ── 참고: 펀더멘탈 페어 · 롱/숏 후보 ──
with st.expander("참고 — 정밀 페어 (섹터·펀더멘탈 헤지) / 롱·숏 후보 랭킹"):
    pairs = alpha.get("pairs") or []
    if pairs:
        st.markdown("**정밀 페어 (품질 = 상관 × 스프레드 × 펀더멘탈 유사도)**")
        for p in pairs[:12]:
            fs = p.get("fund_sim")
            fs_s = f"펀더 {fs*100:.0f}%" if fs is not None else ""
            st.markdown(f'<div style="font-size:0.88rem; padding:2px 0;">'
                        f'L <b>{p["long"]["name"]}</b>({p["long"]["score"]:+.0f}) ↔ '
                        f'S <b>{p["short"]["name"]}</b>({p["short"]["score"]:+.0f}) · '
                        f'상관 {p["corr"]:.2f} · 스프레드 {p["spread"]:.0f} · {fs_s} '
                        f'<span style="color:{MUT};">{"동일섹터" if p.get("same_sector") else "교차"}</span></div>',
                        unsafe_allow_html=True)
    cc1, cc2 = st.columns(2)
    cc1.markdown("**롱 후보** " + " · ".join(f'{x["name"]}({x["score"]:+.0f})' for x in alpha.get("longs", [])[:10]))
    cc2.markdown("**숏 후보** " + " · ".join(f'{x["name"]}({x["score"]:+.0f})' for x in alpha.get("shorts", [])[:10]))

with st.expander("매크로/스프레드 드라이버 (yfinance, 일일)"):
    drv = drivers_data.get("drivers", {})
    if not drv:
        st.caption("드라이버 데이터 없음. `python3 scripts/update_drivers.py` 실행 필요.")
    else:
        st.caption(f"{drivers_data.get('driver_count', len(drv))}개 드라이버 · 추세 z-스코어(60일 분포 내 위치) · 기준일 {drivers_data.get('date','-')}")
        items = sorted(drv.items(), key=lambda kv: abs(kv[1].get("trend_z", 0)), reverse=True)
        for k, v in items:
            z = v.get("trend_z", 0)
            chg = v.get("chg_20d")
            chg_s = f' · 20일 <b style="color:{sc(chg)};">{chg:+.1f}%</b>' if chg is not None else ""
            affects = " · ".join(f'{a["sector"]}({"+" if a["effect"]>0 else ""}{a["effect"]})' for a in v.get("affects", [])[:4])
            st.markdown(
                f'<div style="font-size:0.85rem; padding:2px 0; border-bottom:1px solid {COLORS["border"]};">'
                f'<b style="color:#16202E;">{v["name"]}</b> {v.get("last","")}{v.get("unit","")} '
                f'<b style="color:{sc(z)};">z{z:+.1f}</b>{chg_s} '
                f'<span style="color:{MUT};">{("→ " + affects) if affects else ""}</span></div>',
                unsafe_allow_html=True)

with st.expander("섹터별 점수 기준 (팩터 비중 · 판정 컷)"):
    st.caption("섹터 특성에 맞춰 팩터 비중과 롱/숏 판정 컷을 별도 적용. GICS 사전값 — 섹터 세미나 자료로 갱신.")
    for s in sectors:
        w = s.get("weights", {})
        st.markdown(
            f'<div style="font-size:0.86rem; padding:3px 0; border-bottom:1px solid {COLORS["border"]};">'
            f'<b style="color:#16202E;">{s["sector"]}</b> — 비중 EPS×{w.get("eps","-")}/상대강도×{w.get("rs","-")}/이벤트×{w.get("event","-")}/퀄리티×{w.get("quality","-")} · '
            f'컷 롱≥{s.get("long_cut")}/숏≤{s.get("short_cut")} '
            f'<span style="color:{MUT};">· {s.get("drivers","")} (밸류 {s.get("valuation","")})</span></div>',
            unsafe_allow_html=True)

with st.expander("리스크 관리 규칙 (문서 기준 가이드)"):
    st.markdown("""
**노출**: Gross 100→150% / Net ±5~10% / 단일종목 8%
**MDD(-3% 목표)**: 2일 −100bp→Gross−20% / 3일 −150bp→−30% / 4일 −200bp→−50%
**Loss-cut**: 숏 −10/−15/−20%→20/50/70% · 롱 −15/−20/−25%→30/50/70% (페어 동반)
**Thesis Break**: 롱 EPS 하향전환·숏 대형수주 등 논리 훼손 시 손실률 무관 청산
""")

st.caption(f"멀티팩터 알파(1단계) · 화면 로드 {now_kst()} (KST) · 매일 05:00 KST 자동 갱신")
