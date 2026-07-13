"""종목 상세 — 수출·산업 모멘텀 스코어 카드 + '점수 산출 방식' 모달 (라이트 테마).

데이터: data/trade_scores.json (recompute 없음). 값 없으면 '—' graceful.
모달은 계산 흐름(축 z→ρπσ 자동가중→percentile) 텍스트·표에 더해, 실제 근거가 된
소스 시계열을 차트로 보여준다:
  - E 렌즈: 그 종목 수출 시계열(기업직접 or 섹터) 막대(수출액)+라인(YoY)
  - I 렌즈: 앱섹터 산업지표들(bf_industry.json) 미니차트(growth=막대+YoY / level=라인)
           + 카드소비(bf_creditcard.json, COMPANY_CREDITCARD 매핑 시)
"""
from __future__ import annotations

import streamlit as st

from epsrev.data.trade_scores import (get_trade_score, get_export_sector,
                                      get_industry_sector, load_trade_scores)
from epsrev.trade_score.pipeline import SECNAME_TO_TRADE_CAT

# 라이트 테마 팔레트(수출입 대시보드와 통일 — 한국 관례: 상승 빨강/하락 파랑)
POS, NEG, MUT = "#DC2626", "#2563EB", "#64748B"
CARD_BG, BORDER, TXT = "#FFFFFF", "#E5E7EB", "#0F172A"
BADGE_BG = "#F3F4F6"
BAR_C, YOY_C, LEVEL_C = "#93B4E8", "#DC2626", "#2563EB"

AXIS_LABELS = [("mom", "모멘텀"), ("acc", "가속"), ("qual", "품질"), ("cyc", "사이클")]
GROWTH_AXES = "모멘텀·가속·품질·사이클"
LEVEL_AXES = "모멘텀(Δ)·가속·사이클 (품질 제외)"
EVIDENCE_MONTHS = 48


def _fmt(v, pattern="{:+.1f}", none="—"):
    return none if v is None else pattern.format(v)


def _color(v):
    if v is None:
        return MUT
    return POS if v > 0 else NEG if v < 0 else MUT


# ═══════════════ 근거 시계열 로더 (모달 열릴 때만 · 캐시) ═══════════════
@st.cache_data(ttl=3600, show_spinner=False)
def _export_evidence(name: str, secname: str):
    """E렌즈 수출 시계열: 기업직접(company_trade_history 이름매칭) 우선, 없으면 섹터."""
    import trade_utils_data as T
    s, src = None, None
    try:
        ch = T.load_company_history()
        if ch is not None and not ch.empty and name:
            rows = ch[ch["company_name"].astype(str).str.contains(name, na=False, regex=False)]
            if not rows.empty:
                s = rows.groupby("date")["export_amount"].sum().sort_index()
                src = f"기업 직접수출 · {name}"
    except Exception:
        pass
    if s is None:
        cat = SECNAME_TO_TRADE_CAT.get(secname)
        if cat:
            try:
                h, _ = T.load_history()
                g = h[h["category"] == cat]
                if not g.empty:
                    s = g.groupby("date")["export_amount"].sum().sort_index()
                    src = f"섹터 수출 · {cat}"
            except Exception:
                pass
    if s is None or s.empty:
        return None
    s = s.tail(EVIDENCE_MONTHS)
    return {"dates": [d.strftime("%Y-%m") for d in s.index],
            "vals": [float(v) for v in s.values], "src": src,
            "latest": s.index.max().strftime("%Y-%m")}


@st.cache_data(ttl=3600, show_spinner=False)
def _industry_evidence(secname: str):
    """I렌즈 산업지표: SECTOR_INDUSTRY[secname] 각 지표 시계열(bf_industry.json)."""
    from epsrev.trade_score.loaders import load_industry_snapshot
    from epsrev.data.industry_config import SECTOR_INDUSTRY
    series = (load_industry_snapshot() or {}).get("series") or {}
    out = []
    for it in SECTOR_INDUSTRY.get(secname, []):
        entry = series.get(f"{it['code']}/{it['sub']}")
        base = {"label": it["label"], "series_type": it["series_type"],
                "src": it.get("src", "industry")}
        if it.get("src", "industry") != "industry":
            out.append({**base, "missing": "trade 소스(연동 예정)"})
        elif not entry or not entry.get("data"):
            out.append({**base, "missing": "—"})
        else:
            data = entry["data"][-EVIDENCE_MONTHS:]
            out.append({**base, "unit": entry.get("unit"), "freq": entry.get("freq"),
                        "dates": [p["m"] for p in data], "vals": [p["val"] for p in data],
                        "latest": data[-1]["m"]})
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def _creditcard_evidence(ticker: str):
    """I렌즈 카드소비: COMPANY_CREDITCARD 매핑 시 bf_creditcard.json 소비 시계열."""
    from epsrev.trade_score.loaders import load_creditcard_snapshot
    c = ((load_creditcard_snapshot() or {}).get("companies") or {}).get(ticker)
    if not c or not c.get("data"):
        return None
    data = c["data"][-EVIDENCE_MONTHS:]
    return {"dates": [p["m"] for p in data], "vals": [float(p["val"]) for p in data],
            "latest": data[-1]["m"]}


# ═══════════════ 차트 (plotly, 라이트) ═══════════════
def _growth_fig(dates, vals, unit=""):
    import pandas as pd
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    yoy = (pd.Series(vals).pct_change(12) * 100).tolist()
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=dates, y=vals, marker_color=BAR_C, name=unit or "값"), secondary_y=False)
    fig.add_trace(go.Scatter(x=dates, y=yoy, mode="lines", line=dict(color=YOY_C, width=1.8),
                             name="YoY%"), secondary_y=True)
    fig.update_layout(height=180, template="plotly_white", showlegend=False,
                      margin=dict(l=4, r=4, t=6, b=4), bargap=0.25,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    fig.update_yaxes(showticklabels=False, secondary_y=False)
    fig.update_yaxes(ticksuffix="%", secondary_y=True, tickfont=dict(size=8), showgrid=False)
    fig.update_xaxes(tickfont=dict(size=8), nticks=6)
    return fig


def _level_fig(dates, vals):
    import plotly.graph_objects as go
    fig = go.Figure(go.Scatter(x=dates, y=vals, mode="lines", line=dict(color=LEVEL_C, width=2),
                               fill="tozeroy", fillcolor="rgba(37,99,235,.07)"))
    fig.update_layout(height=180, template="plotly_white", showlegend=False,
                      margin=dict(l=4, r=4, t=6, b=4),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    fig.update_yaxes(tickfont=dict(size=8)); fig.update_xaxes(tickfont=dict(size=8), nticks=6)
    return fig


def _plot(fig, key):
    st.plotly_chart(fig, use_container_width=True, key=key, config={"displayModeBar": False})


# ═══════════════ 카드 ═══════════════
def _axis_badges_html(axes: dict) -> str:
    parts = []
    for key, label in AXIS_LABELS:
        v = (axes or {}).get(key)
        parts.append(
            f"<span style='background:{BADGE_BG};border-radius:6px;padding:3px 8px;"
            f"font-size:0.72rem;color:{MUT}'>{label} "
            f"<b style='color:{_color(v)}'>{_fmt(v, '{:+.1f}σ')}</b></span>")
    return " ".join(parts)


def render_trade_score_card(ticker6: str, name: str, secname: str) -> None:
    """수출·산업 모멘텀 스코어 카드. trade_scores.json 없거나 종목 미포함 → '—' 카드."""
    ts = get_trade_score(ticker6)
    as_of = load_trade_scores().get("as_of", "—")
    score = (ts or {}).get("company_score")
    rel = (ts or {}).get("reliability") or {}
    flags = (ts or {}).get("flags") or []
    axes = (get_industry_sector(secname) or {}).get("axes") or {}

    div_badge = (
        f"<span style='background:rgba(220,38,38,.1);color:{POS};border-radius:6px;"
        f"padding:3px 8px;font-size:0.72rem;font-weight:700'>⚠️ E/I 발산</span>"
        if "divergence" in flags else "")
    e_part, i_part = (ts or {}).get("export_part"), (ts or {}).get("industry_part")

    st.markdown(
        f"""
        <div style='background:{CARD_BG};border:1px solid {BORDER};border-radius:10px;
             padding:14px 16px;box-shadow:0 1px 3px rgba(0,0,0,.06)'>
          <div style='display:flex;gap:24px;align-items:center;flex-wrap:wrap'>
            <div style='min-width:150px'>
              <div style='font-size:0.72rem;color:{MUT}'>수출·산업 모멘텀 스코어 (기준 {as_of})</div>
              <div style='font-size:1.9rem;font-weight:800;color:{_color(score)};line-height:1.15'>
                {_fmt(score, '{:+.0f}')}</div>
              <div style='font-size:0.7rem;color:{MUT}'>−100~+100 · 신뢰도
                E {_fmt(rel.get('r_export'), '{:.2f}')} / I {_fmt(rel.get('r_industry'), '{:.2f}')}</div>
            </div>
            <div style='flex:1;min-width:260px'>
              <div style='margin-bottom:6px'>{_axis_badges_html(axes)}</div>
              <div style='font-size:0.78rem;color:{TXT}'>
                수출(E) <b style='color:{_color(e_part)}'>{_fmt(e_part, '{:+.0f}')}</b>
                &nbsp;·&nbsp; 산업(I) <b style='color:{_color(i_part)}'>{_fmt(i_part, '{:+.0f}')}</b>
                &nbsp; {div_badge}
              </div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("점수 산출 방식 · 근거 데이터 보기", key=f"ts_modal_{ticker6}"):
        _score_method_dialog(ticker6, name, secname, ts)


# ═══════════════ 모달 ═══════════════
def _sector_block(title: str, sec: dict) -> None:
    if not sec:
        st.markdown(f"**{title}** — 컨텍스트 없음(—)")
        return
    prof = sec.get("profile") or {}
    weights = sec.get("weights") or {}
    axes = sec.get("axes") or {}
    st.markdown(
        f"**{title}** · 섹터점수 <b style='color:{_color(sec.get('sector_score'))}'>"
        f"{_fmt(sec.get('sector_score'), '{:+.0f}')}</b> · 신뢰도 {_fmt(sec.get('confidence'), '{:.2f}')}",
        unsafe_allow_html=True)
    st.table([{"축": label, "z(자기이력)": _fmt(axes.get(key), "{:+.2f}"),
               "적용 가중": _fmt(weights.get(key), "{:.0%}", none="제외")}
              for key, label in AXIS_LABELS])
    st.caption(
        f"섹터 특성 자동가중: ρ(사이클성) {_fmt(prof.get('rho'), '{:.2f}')} · "
        f"π(단가주도) {_fmt(prof.get('pi'), '{:.2f}')} · σ(변동성) {_fmt(prof.get('sigma'), '{:.2f}')} — "
        "ρ↑→가속·사이클 강조, π↑→품질 강조, σ↑→모멘텀 신뢰 하향. 결측 축은 재정규화.")


def _render_industry_evidence(ticker6: str, secname: str) -> None:
    inds = _industry_evidence(secname)
    present = [x for x in inds if "dates" in x]
    missing = [x for x in inds if "dates" not in x]
    cc = _creditcard_evidence(ticker6)

    if not present and cc is None:
        st.caption("산업지표 스냅샷 없음 — 연동 예정/—")
    for i in range(0, len(present), 2):
        cols = st.columns(2)
        for j, x in enumerate(present[i:i + 2]):
            with cols[j]:
                axis = GROWTH_AXES if x["series_type"] == "growth" else LEVEL_AXES
                st.markdown(
                    f"<div style='font-size:0.74rem;font-weight:600;color:{TXT}'>{x['label']}</div>"
                    f"<div style='font-size:0.66rem;color:{MUT};margin-bottom:2px'>"
                    f"{x.get('unit','')} · 최신 {x['latest']} · 기여축 {axis}</div>",
                    unsafe_allow_html=True)
                fig = (_growth_fig(x["dates"], x["vals"], x.get("unit", ""))
                       if x["series_type"] == "growth" else _level_fig(x["dates"], x["vals"]))
                _plot(fig, key=f"ind_{ticker6}_{x['label']}")
    if cc is not None:
        st.markdown(
            f"<div style='font-size:0.74rem;font-weight:600;color:{TXT};margin-top:6px'>"
            f"카드 소비(직접) · 최신 {cc['latest']} · 기여축 {GROWTH_AXES}</div>",
            unsafe_allow_html=True)
        _plot(_growth_fig(cc["dates"], cc["vals"], "결제액"), key=f"cc_{ticker6}")
    if missing:
        st.caption("연동 예정/데이터 없음: " + ", ".join(x["label"] for x in missing))


@st.dialog("수출·산업 모멘텀 스코어 — 산출 방식 · 근거 데이터", width="large")
def _score_method_dialog(ticker6: str, name: str, secname: str, ts: dict) -> None:
    ts = ts or {}
    tab_method, tab_evidence = st.tabs(["산출 방식", "근거 데이터"])
    with tab_method:
        _render_method_tab(secname, ts)
    with tab_evidence:
        _render_evidence_tab(ticker6, name, secname, ts)
    if not ts:
        st.warning("이 종목의 점수 데이터가 없습니다 (trade_scores.json 미포함) — '—' 표시.")


def _render_method_tab(secname: str, ts: dict) -> None:
    """탭1 — 산출 흐름 + E/I 렌즈 축 z 표·자동가중 + 렌즈 종합·insight·flags."""
    rel = ts.get("reliability") or {}
    st.markdown(
        "**산출 흐름** ① 각 지표 4축 원신호(모멘텀·가속·품질·사이클) → "
        "② 자기 이력 robust z(±3 winsorize) → ③ 섹터 특성(ρ·π·σ) 자동 가중합 → "
        "④ 전 섹터 분포 percentile(−100~+100) → ⑤ 수출(E)·산업(I) 두 렌즈를 신뢰도 가중 종합.")
    st.divider()

    cat = SECNAME_TO_TRADE_CAT.get(secname)
    _sector_block(f"E렌즈 — 수출 실측 ({cat or '카테고리 매핑 없음'})",
                  get_export_sector(cat) if cat else None)
    st.divider()
    _sector_block(f"I렌즈 — 산업지표/카드소비 ({secname})", get_industry_sector(secname))
    st.divider()

    e, i = ts.get("export_part"), ts.get("industry_part")
    st.markdown(
        f"**렌즈 종합** — E <b style='color:{_color(e)}'>{_fmt(e, '{:+.1f}')}</b>"
        f"(r={_fmt(rel.get('r_export'), '{:.2f}')}) · "
        f"I <b style='color:{_color(i)}'>{_fmt(i, '{:+.1f}')}</b>"
        f"(r={_fmt(rel.get('r_industry'), '{:.2f}')}) · "
        f"노출도 {_fmt(ts.get('exposure'), '{:.2f}')} → 종합 "
        f"<b style='color:{_color(ts.get('company_score'))}'>"
        f"{_fmt(ts.get('company_score'), '{:+.1f}')}</b>",
        unsafe_allow_html=True)
    st.caption("score = (r_E·E + r_I·I)/(r_E+r_I) — 결측 렌즈 제외. "
               "r = 최신성·이력길이·직접성(직접 1.0/섹터폴백 exposure).")
    if ts.get("flags"):
        st.markdown("**플래그**: " + " · ".join(f"`{f}`" for f in ts["flags"]))
    if ts.get("insight"):
        st.info(ts["insight"])


def _render_evidence_tab(ticker6: str, name: str, secname: str, ts: dict) -> None:
    """탭2 — E 렌즈 수출 차트 + I 렌즈 산업지표·카드소비 미니차트."""
    st.markdown("#### 📊 E 렌즈 근거 — 수출 시계열")
    ev = _export_evidence(name, secname)
    if ev is None:
        st.caption("수출 시계열 없음 — 연동 예정/—")
    else:
        st.caption(f"출처: {ev['src']} · 최신 {ev['latest']} · 막대=수출액 / 라인=YoY%")
        _plot(_growth_fig(ev["dates"], ev["vals"], "수출액"), key=f"exp_{ticker6}")

    st.divider()
    st.markdown("#### 📊 I 렌즈 근거 — 산업지표 / 카드소비")
    _render_industry_evidence(ticker6, secname)
