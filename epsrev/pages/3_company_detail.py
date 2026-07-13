import sys, os

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from epsrev.data.dashboard_data import SECTORS, CO, PAIR_MAP
from epsrev.data.scorer import get_stock_detail
from epsrev.data.related_config import get_related_panels   # 관련 데이터 패널 config
from epsrev.ui.related_panel import render_industry_panel   # 핵심/연관 산업지표 패널
from epsrev.data.value_chain import get_stock_value_chain   # 밸류체인 관련 기업
from epsrev.ui.trade_score_section import render_trade_score_card  # 수출·산업 모멘텀 스코어
from epsrev.ui.sidebar import render_sidebar
from report_ui import load_reports_by_code, render_report_dialog  # 공용 리포트 모달
from epsrev.ui.fin_section import render_fin_section  # FnGuide 스타일 실적 추이

render_sidebar()

KST = ZoneInfo("Asia/Seoul")

# ── 유틸 ─────────────────────────────────────────────────────────────────────
def fmt(n) -> str:
    return f"{int(n):,}" if n is not None else "—"


def _plot_bg() -> dict:
    return dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#0a0d1a",
        font=dict(color="#dde3f8", size=10),
        margin=dict(l=46, r=30, t=14, b=36),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#aab", size=9),
                    orientation="h", y=1.08),
        xaxis=dict(gridcolor="#1c2038", color="#546080", tickfont=dict(size=9)),
        yaxis=dict(gridcolor="#1c2038", color="#546080", tickfont=dict(size=9)),
    )


# ── 작업 1: 시총 캐시 함수 (pykrx, TTL=1일) ─────────────────────────────────
def _ref_date_kst() -> str:
    """당일 KST 날짜 반환. 장 종료(15:30) 전이면 전 영업일 선택."""
    now_kst = datetime.now(KST)
    d = now_kst.date()
    if now_kst.hour < 15 or (now_kst.hour == 15 and now_kst.minute < 30):
        d -= timedelta(days=1)
    # 토·일 → 금요일
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")


@st.cache_data(ttl=86400)
def _get_market_cap(ticker6: str, ref_date: str) -> tuple:
    """yfinance로 시총 조회 (KOSPI → .KS, KOSDAQ → .KQ 순 시도)."""
    try:
        import yfinance as yf
        for suffix in [".KS", ".KQ"]:
            info = yf.Ticker(ticker6 + suffix).info
            mcap = info.get("marketCap")
            if mcap:
                cap_eok = int(mcap) // 100_000_000  # 원 → 억
                return cap_eok, ref_date
        return None, ref_date
    except Exception:
        return None, ref_date


# ── 전체 종목 목록 ────────────────────────────────────────────────────────────
ALL_CO: list[dict] = [CO[c["t"]] for sec in SECTORS for c in sec["cos"]]
ticker_labels  = [f"{c['secName']} — {c['n']} ({c['t']})" for c in ALL_CO]
ticker_map     = {f"{c['secName']} — {c['n']} ({c['t']})": c["t"] for c in ALL_CO}

# 딥링크 수신: ?stock=<6자리> → 해당 종목 직행(소비 후 파라미터 제거)
_qs = st.query_params.get("stock")
if _qs:
    _qc = str(_qs).zfill(6)
    if _qc in CO:
        st.session_state["selected_ticker"] = _qc
    try:
        del st.query_params["stock"]
    except Exception:
        pass

preselect = st.session_state.get("selected_ticker")
default_idx = 0
if preselect:
    for i, c in enumerate(ALL_CO):
        if c["t"] == preselect:
            default_idx = i
            break

# key에 preselect 포함 → selected_ticker 변경(다른 페이지·밸류체인 이동) 시 selectbox 재초기화
sel_label = st.selectbox("종목 선택", ticker_labels, index=default_idx,
                         key=f"company_select_{preselect}", label_visibility="collapsed")
ticker  = ticker_map[sel_label]
st.session_state["selected_ticker"] = ticker
co      = CO[ticker]
ticker6 = str(ticker).zfill(6)

# ── EPS 리비전 상세 (scorer.py) ───────────────────────────────────────────────
_eps_detail  = None
_eps_score   = None
_eps_conf    = None
_eps_layers  = {}
_eps_ev      = {}
_eps_insight = None
_eps_flags   = []
try:
    _eps_detail  = get_stock_detail(ticker)
    _eps_score   = _eps_detail.get("eps_score")
    _eps_conf    = _eps_detail.get("confidence")
    _eps_layers  = _eps_detail.get("layers", {})
    _eps_ev      = _eps_detail.get("evidence", {})
    _eps_insight = _eps_detail.get("insight")
    _eps_flags   = _eps_detail.get("flags", [])
except Exception:
    pass

# EPS 점수 → 실적 버킷 (0~40)
if _eps_score is not None:
    _earnings_bucket = max(0, min(40, round((_eps_score + 100) / 200 * 40)))
else:
    _earnings_bucket = co["sc"]["e"]

_eps_score_str = f"{_eps_score:+.0f}" if _eps_score is not None else "—"
_eps_conf_str  = f"{_eps_conf:.2f}"   if _eps_conf  is not None else "—"

# ── 작업 1: 시총 조회 ─────────────────────────────────────────────────────────
_ref_date             = _ref_date_kst()
_mkt_cap, _mkt_d_raw = _get_market_cap(ticker6, _ref_date)
if _mkt_cap is not None:
    _mkt_d_fmt = f"{_mkt_d_raw[:4]}-{_mkt_d_raw[4:6]}-{_mkt_d_raw[6:]}"
    _mkt_html  = (
        f"시총 {_mkt_cap:,}억 "
        f"<span style='font-size:0.68rem;color:#546080'>({_mkt_d_fmt} 기준)</span>"
    )
else:
    _mkt_html = "시총 정보 없음"

# ═══════════════════════════════════════════════════════════════════════════════
# [1] 헤더 카드
# ═══════════════════════════════════════════════════════════════════════════════
with st.container(border=True):
    hc1, hc2, hc3 = st.columns([4, 2, 2])
    with hc1:
        st.markdown(
            f"<div style='font-size:1.5rem;font-weight:800;margin-bottom:4px'>"
            f"{co['n']}</div>"
            f"<div style='font-size:0.8rem;color:#546080'>"
            f"{co['t']} &nbsp;·&nbsp; "
            f"<span style='color:{co['secColor']}'>{co['secName']}</span>"
            f" &nbsp;·&nbsp; {_mkt_html}</div>",
            unsafe_allow_html=True,
        )
    with hc2:
        pc = co["pc"]
        pc_color = "#00c87a" if pc >= 0 else "#ff4060"
        pc_arrow = "▲" if pc >= 0 else "▼"
        st.markdown(
            f"<div style='font-size:1.3rem;font-weight:800;text-align:right'>"
            f"{fmt(co['p'])}원</div>"
            f"<div style='text-align:right;font-size:0.85rem;color:{pc_color};"
            f"font-weight:600'>{pc_arrow} {abs(pc)}%</div>",
            unsafe_allow_html=True,
        )
    with hc3:
        bon = co["bonus"]
        bonus_html = (
            f" <span style='font-size:0.85rem;font-weight:700;color:#ffaa00;"
            f"background:rgba(255,170,0,.15);padding:2px 9px;"
            f"border-radius:6px'>+{bon}</span>"
            if bon > 0 else ""
        )
        st.markdown(
            f"<div style='font-size:0.72rem;color:#546080;margin-bottom:6px'>"
            f"종합점수 (기준일)</div>"
            f"<div style='font-size:2rem;font-weight:800;line-height:1'>"
            f"{co['total']}{bonus_html}</div>"
            f"<div style='font-size:0.72rem;color:#546080;margin-top:6px'>"
            f"EPS리비전 {_eps_score_str} · 데이터{co['sc']['d']} · 수급{co['sc']['s']}</div>",
            unsafe_allow_html=True,
        )

st.write("")

# ═══════════════════════════════════════════════════════════════════════════════
# [2] 네비 버튼
# ═══════════════════════════════════════════════════════════════════════════════
nb1, nb2 = st.columns([1, 10])
with nb1:
    if st.button(f"← {co['secName']}"):
        st.session_state["selected_sector_id"] = co["secId"]
        st.switch_page("epsrev/pages/2_sector_detail.py")
with nb2:
    _, _r = st.columns([8, 2])
    with _r:
        if st.button("⚖️ 롱숏 페어 찾기 →", type="primary", use_container_width=True):
            st.session_state["long_ticker"] = ticker
            st.switch_page("epsrev/pages/4_pair_finder.py")

st.write("")

# ═══════════════════════════════════════════════════════════════════════════════
# [3] FnGuide Company Guide 스타일 실적 추이 (차트 + 표)
# ═══════════════════════════════════════════════════════════════════════════════
render_fin_section(ticker)

st.write("")

# ═══════════════════════════════════════════════════════════════════════════════
# EPS 상세 팝업(@st.dialog): 레이어 분해 + evidence + insight + flags + 두 차트
# ═══════════════════════════════════════════════════════════════════════════════
_EV_LABELS: dict[str, str] = {
    "rev_op_3m":     "3개월 OP 컨센 변화율",
    "rev_op_1m":     "1개월 OP 컨센 변화율",
    "rev_eps_3m":    "3개월 EPS 컨센 변화율",
    "rev_eps_1m":    "1개월 EPS 컨센 변화율",
    "diffusion_idx": "상향/하향 애널리스트 비율",
    "sue":           "최근 4Q 평균 어닝 서프라이즈",
    "accel":         "리비전 가속도",
    "disp_cv":       "추정치 분산 (낮을수록 수렴)",
    "runrate_gap":   "YTD 런레이트 vs 연간 컨센 갭",
    "tp_lead":       "목표주가 선행 신호",
    "persistence":   "리비전 관성",
    "news_lead":     "뉴스 감성 신호",
}


@st.dialog("EPS 리비전 상세", width="large")
def _eps_detail_dialog():
    # ── 레이어별 분해(실현/모멘텀/포워드) ──
    st.markdown("**레이어별 분해**  "
                "<span style='font-size:0.72rem;color:#546080'>실현(40%)·모멘텀(25%)·포워드(35%)</span>",
                unsafe_allow_html=True)
    _layer_items = [
        ("포워드압력 (35%)", "forward"),
        ("모멘텀 (25%)",    "momentum"),
        ("실현리비전 (40%)", "realized"),
    ]
    _lv = [_eps_layers.get(k) or 0.0 for _, k in _layer_items]
    _lc = ["#4F8BF9" if v >= 0 else "#ff7f3f" for v in _lv]
    _lt = [f"{v:+.3f}" for v in _lv]
    if any(abs(v) > 0 for v in _lv):
        fig_l = go.Figure(go.Bar(
            y=[label for label, _ in _layer_items], x=_lv, orientation="h",
            marker_color=_lc, text=_lt, textposition="outside",
            textfont=dict(size=11, color="#dde3f8"), cliponaxis=False,
        ))
        fig_l.add_vline(x=0, line_color="#546080", line_width=1)
        _bg = _plot_bg()
        _bg.update({"height": 150, "margin": dict(l=130, r=80, t=10, b=10),
                    "showlegend": False,
                    "xaxis": {**_bg.get("xaxis", {}), "zeroline": False},
                    "yaxis": {**_bg.get("yaxis", {}), "tickfont": dict(size=10)}})
        fig_l.update_layout(**_bg)
        st.plotly_chart(fig_l, use_container_width=True, config={"displayModeBar": False})
    else:
        st.caption("레이어 점수 데이터 없음")

    # ── 인사이트 / 플래그 ──
    if _eps_insight:
        st.info(_eps_insight, icon="💡")
    if _eps_flags:
        for _fl in _eps_flags:
            if _fl:
                st.warning(f"⚠️ {_fl}")

    # ── 근거 지표(Evidence) ──
    st.markdown("<div style='font-size:0.72rem;color:#546080;letter-spacing:2px;"
                "margin:12px 0 8px'>EPS REVISION EVIDENCE</div>", unsafe_allow_html=True)
    ev_items = list(_EV_LABELS.items())
    for row_start in range(0, len(ev_items), 3):
        cols = st.columns(3)
        for col, (key, label) in zip(cols, ev_items[row_start: row_start + 3]):
            val = _eps_ev.get(key) if _eps_ev else None
            if val is None:
                val_html = ("<span style='color:#343d5a'>— "
                            "<span style='font-size:0.6rem'>(연결 후 활성화)</span></span>")
            else:
                v_color = "#00c87a" if val > 0 else ("#ff4b4b" if val < 0 else "#dde3f8")
                sign    = "+" if val > 0 else ""
                val_html = f"<span style='color:{v_color};font-weight:700'>{sign}{val:.3f}</span>"
            with col:
                st.markdown(
                    f"<div style='background:#08090f;border-radius:8px;padding:10px 12px;"
                    f"margin-bottom:8px'><div style='font-size:0.65rem;color:#546080;"
                    f"margin-bottom:5px;line-height:1.4'>{label}</div>"
                    f"<div style='font-size:0.95rem'>{val_html}</div></div>",
                    unsafe_allow_html=True,
                )

    st.markdown("<hr style='margin:14px 0;border:none;border-top:1px solid #1c2038'>",
                unsafe_allow_html=True)

    # ── 컨센서스 추이 차트 (본문 [5우]에서 이동) ──
    st.markdown("**컨센서스 추이 — FY1/FY2 영업이익 추정 (억원)**")
    # TODO: FnSpace/빅파이낸스 연동 후 dummy_consensus를 실제 consensus_history로 교체
    dummy_consensus = [
        {"date": "25.02", "fy1": 11200, "fy2": 13800},
        {"date": "25.03", "fy1": 11150, "fy2": 13750},
        {"date": "25.04", "fy1": 11300, "fy2": 13900},
        {"date": "25.05", "fy1": 11450, "fy2": 14100},
        {"date": "25.06", "fy1": 11600, "fy2": 14250},
        {"date": "26.01", "fy1": 11580, "fy2": 14230},
    ]
    _cx  = [d["date"] for d in dummy_consensus]
    _cy1 = [d["fy1"]  for d in dummy_consensus]
    _cy2 = [d["fy2"]  for d in dummy_consensus]
    fig_cons = go.Figure()
    fig_cons.add_trace(go.Scatter(x=_cx, y=_cy1, name="FY1",
                                  line=dict(color="#3b82f6", width=2), mode="lines"))
    fig_cons.add_trace(go.Scatter(x=_cx, y=_cy2, name="FY2",
                                  line=dict(color="#fbbf24", width=2, dash="dot"), mode="lines"))
    fig_cons.add_annotation(x=_cx[-1], y=_cy1[-1], text=f"FY1 {_cy1[-1]:,}억",
                            showarrow=False, xanchor="left", xshift=8,
                            font=dict(size=9, color="#3b82f6"))
    fig_cons.add_annotation(x=_cx[-1], y=_cy2[-1], text=f"FY2 {_cy2[-1]:,}억",
                            showarrow=False, xanchor="left", xshift=8,
                            font=dict(size=9, color="#fbbf24"))
    _cl = _plot_bg()
    _cl["height"] = 240
    _cl["margin"] = dict(l=46, r=90, t=14, b=36)
    _cl["yaxis"]  = dict(gridcolor="#1c2038", color="#546080", tickfont=dict(size=9),
                         tickformat=",.0f",
                         title=dict(text="억원", font=dict(size=9, color="#546080")))
    fig_cons.update_layout(**_cl)
    st.plotly_chart(fig_cons, use_container_width=True, config={"displayModeBar": False})

    # ── 점수 1년 추이 (본문 [6좌]에서 이동) ──
    st.markdown("**점수 1년 추이**")
    hist = co["hist"]
    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(x=[d["m"] for d in hist], y=[d["score"] for d in hist],
                              name="점수", line=dict(color=co["secColor"], width=2.5),
                              mode="lines+markers", marker=dict(size=4, color=co["secColor"])))
    _l3 = _plot_bg()
    _l3["height"] = 200
    _l3["yaxis"]["range"] = [0, 100]
    fig3.update_layout(**_l3)
    st.plotly_chart(fig3, use_container_width=True, config={"displayModeBar": False})


# ═══════════════════════════════════════════════════════════════════════════════
# [4] 2열: 좌 — EPS Revision Score 카드(→팝업)  |  우 — 최신 리포트 컨센서스
# ═══════════════════════════════════════════════════════════════════════════════
r4_left, r4_right = st.columns(2, gap="medium")

# 두 박스(EPS 카드 / 리포트 컨센서스) 세로 높이 정렬 —
# st.columns는 flex row라 두 컬럼이 같은 높이로 stretch되므로, 각 bordered 컨테이너를
# height:100%로 채우면 짧아진 우측이 좌측 높이에 맞춰진다.
st.markdown(
    "<style>"
    # 컬럼(stColumn)은 flex로 이미 두 박스가 같은 높이로 stretch되지만, 그 안쪽
    # stLayoutWrapper가 콘텐츠 높이(짧은 쪽)로 멈춰 전파를 끊는다 → 래퍼+컨테이너를
    # height:100%로 채워 짧은 박스를 긴 박스 높이에 맞춘다.
    "div[data-testid='stLayoutWrapper']:has(> div[class*='st-key-eps_score_box']),"
    "div[data-testid='stLayoutWrapper']:has(> div[class*='st-key-report_consensus_box'])"
    "{height:100%;}"
    "div[class*='st-key-eps_score_box'], div[class*='st-key-report_consensus_box']"
    "{height:100%;}"
    "</style>",
    unsafe_allow_html=True,
)

# ─ 좌: EPS Revision Score 요약 카드(클릭 → 상세 팝업) ────────────────────────
with r4_left:
    with st.container(border=True, key="eps_score_box"):
        st.markdown(
            "<div style='font-size:0.72rem;color:#546080;letter-spacing:2px;"
            "margin-bottom:10px'>EPS REVISION SCORE</div>",
            unsafe_allow_html=True,
        )

        em1, em2, em3 = st.columns(3)

        def _eps_metric(col, label: str, value: str, sub: str = "", color: str = "#dde3f8") -> None:
            with col:
                st.markdown(
                    f"<div style='background:#08090f;border-radius:10px;"
                    f"padding:14px 18px;text-align:center'>"
                    f"<div style='font-size:0.68rem;color:#546080;margin-bottom:6px'>{label}</div>"
                    f"<div style='font-size:1.6rem;font-weight:800;color:{color}'>{value}</div>"
                    f"<div style='font-size:0.68rem;color:#546080;margin-top:4px'>{sub}</div></div>",
                    unsafe_allow_html=True,
                )

        if _eps_score is not None:
            _sc_color = "#00c87a" if _eps_score >= 20 else ("#ff4060" if _eps_score <= -20 else "#ffaa00")
        else:
            _sc_color = "#546080"
        _eps_metric(em1, "EPS 리비전 점수", _eps_score_str, "-100 ~ +100 범위", _sc_color)
        _eps_metric(em2, "실적 버킷 환산", f"{_earnings_bucket}", "0 ~ 40 범위")
        _eps_metric(em3, "신뢰도", _eps_conf_str, "컨피던스 게이트")

        # 인사이트 요약(있으면 한 줄) + 상세 보기 버튼
        st.write("")
        if _eps_insight:
            st.markdown(
                f"<div style='font-size:0.78rem;color:#8899bb;line-height:1.6;"
                f"margin-bottom:8px'>💡 {_eps_insight}</div>", unsafe_allow_html=True)
        if st.button("📐 EPS 상세 보기 (레이어·근거·추이 차트)", key=f"eps_detail_{ticker}",
                     use_container_width=True):
            _eps_detail_dialog()

# ─ 우: 최신 리포트 컨센서스 (현행 유지) ──────────────────────────────────────
with r4_right:
    with st.container(border=True, key="report_consensus_box"):
        st.markdown("**최신 리포트 컨센서스**")

        reports = load_reports_by_code().get(ticker, [])

        if not reports:
            st.markdown(
                "<div style='font-size:0.8rem;color:#546080;padding:6px 0'>"
                "최근 수집된 증권사 리포트가 없습니다.</div>",
                unsafe_allow_html=True,
            )
        else:
            _opinion_colors = {"BUY": "#00c87a", "매수": "#00c87a", "HOLD": "#ffaa00",
                               "중립": "#ffaa00", "SELL": "#ff4060", "매도": "#ff4060"}

            def _tp_change_html(tp, tp_prev) -> str:
                if not tp or not tp_prev:
                    return "<span style='color:#546080'>—</span>"
                if tp > tp_prev:
                    return f"<span style='color:#00c87a'>▲ +{tp - tp_prev:,}</span>"
                if tp < tp_prev:
                    return f"<span style='color:#ff4060'>▼ -{tp_prev - tp:,}</span>"
                return "<span style='color:#546080'>—</span>"

            def _num(v):
                return f"{v:,}" if isinstance(v, (int, float)) else "—"

            st.markdown(
                "<div style='font-size:0.72rem;color:#546080;margin-bottom:8px'>"
                "최근 3개 리포트 — TP·의견</div>",
                unsafe_allow_html=True,
            )
            _tbl = (
                "<div style='overflow-x:auto'>"
                "<table style='width:100%;border-collapse:collapse;font-size:0.75rem'>"
                "<thead><tr style='color:#546080;border-bottom:1px solid #1c2038'>"
                "<th style='text-align:left;padding:5px 6px'>기관</th>"
                "<th style='text-align:center;padding:5px 4px'>날짜</th>"
                "<th style='text-align:center;padding:5px 4px'>의견</th>"
                "<th style='text-align:right;padding:5px 4px'>TP(원)</th>"
                "<th style='text-align:right;padding:5px 4px'>TP변화</th>"
                "</tr></thead><tbody>"
            )
            for r in reports[:3]:
                op = r.get("opinion", "") or ""
                op_color = _opinion_colors.get(op, _opinion_colors.get(op.upper(), "#dde3f8"))
                _tbl += (
                    f"<tr style='border-bottom:1px solid #1c2038;color:#dde3f8'>"
                    f"<td style='padding:7px 6px;font-weight:600'>{r.get('broker','')}</td>"
                    f"<td style='padding:7px 4px;text-align:center;color:#546080;"
                    f"font-size:0.7rem'>{r.get('date','')}</td>"
                    f"<td style='padding:7px 4px;text-align:center'>"
                    f"<span style='color:{op_color};font-weight:700;font-size:0.7rem'>"
                    f"{op}</span></td>"
                    f"<td style='padding:7px 4px;text-align:right'>{_num(r.get('tp'))}</td>"
                    f"<td style='padding:7px 4px;text-align:right'>"
                    f"{_tp_change_html(r.get('tp'), r.get('tp_prev'))}</td>"
                    f"</tr>"
                )
            _tbl += "</tbody></table></div>"
            st.markdown(_tbl, unsafe_allow_html=True)

            # 🔎 증권사 버튼 = 유일한 요약 모달 진입점 (기존 '최근 리포트 목록' 블록 제거)
            _top = reports[:3]
            _cols = st.columns(len(_top))
            for i, r in enumerate(_top):
                with _cols[i]:
                    if st.button(f"🔎 {r.get('broker','')}", key=f"rptA_{ticker}_{i}",
                                 use_container_width=True):
                        render_report_dialog(r)

st.write("")

# ═══════════════════════════════════════════════════════════════════════════════
# [4.5] 수출·산업 모멘텀 스코어 (trade_scores.json — 카드 + 산출방식·근거 모달)
#       '수출 데이터(관련 데이터/산업지표)' 섹션 바로 위
# ═══════════════════════════════════════════════════════════════════════════════
render_trade_score_card(ticker6, co["n"], co["secName"])

st.write("")

# ═══════════════════════════════════════════════════════════════════════════════
# [5] 관련 데이터 — 핵심/연관 산업지표 2패널(레퍼런스 레이아웃, 라이트)
# ═══════════════════════════════════════════════════════════════════════════════
_panels = get_related_panels(ticker)
render_industry_panel(_panels["titles"]["핵심"], _panels["핵심"], ticker, slot="core")
if _panels["연관"]:                                            # 연관 데이터셋 있을 때만
    st.write("")
    render_industry_panel(_panels["titles"]["연관"], _panels["연관"], ticker, slot="rel")

st.write("")

# ═══════════════════════════════════════════════════════════════════════════════
# [6] 밸류체인 관련 기업 (공급사/고객사/동일 단계)
# ═══════════════════════════════════════════════════════════════════════════════
_vc = get_stock_value_chain(co["n"])
_vc_pos, _vc_sup, _vc_cus, _vc_peer = (_vc["positions"], _vc["suppliers"],
                                       _vc["customers"], _vc["peers"])


def _vc_tabdf(df, name_col, rel_col, is_edge):
    if df is None or df.empty:
        return pd.DataFrame()
    d = df.copy()
    d["_mc"] = pd.to_numeric(d["시가총액"], errors="coerce")
    if is_edge:
        d["_ord"] = d["신뢰도"].map(lambda x: 0 if str(x).strip() == "명시" else 1)
    else:
        d["_ord"] = 0
    d = d.sort_values(["_ord", "_mc"], ascending=[True, False], na_position="last")
    conf = (d["신뢰도"].map(lambda x: "🟢 명시" if str(x).strip() == "명시" else "⚪ 추정").values
            if is_edge else [""] * len(d))
    return pd.DataFrame({
        "종목명": d[name_col].values,
        "종목코드": [c if c else "" for c in d["종목코드"].values],
        "섹터": [s if s else "" for s in d["섹터"].values],
        "시총(억)": [f"{int(v):,}" if pd.notna(v) else "" for v in d["_mc"].values],
        "종합점수": [int(s) if pd.notna(pd.to_numeric(s, errors="coerce")) else "" for s in d["종합점수"].values],
        "관계": d[rel_col].values,
        "신뢰도": conf,
    })


with st.container(border=True):
    st.markdown("**🔗 밸류체인 관련 기업**")
    if all(x is None or x.empty for x in (_vc_pos, _vc_sup, _vc_cus, _vc_peer)):
        st.info("밸류체인 데이터에 등록되지 않은 종목입니다")
    else:
        # 포지션 태그(pill)
        if _vc_pos is not None and not _vc_pos.empty:
            _tags = []
            for _, r in _vc_pos.iterrows():
                parts = [str(r.get(k, "") or "").strip() for k in ("대분류", "서브섹터", "체인단계")]
                lab = " › ".join([p for p in parts if p])
                ch = str(r.get("제품체인", "") or "").strip()
                if ch:
                    lab += f"  ·  {ch}"
                if lab and lab not in _tags:
                    _tags.append(lab)
            st.markdown("".join(
                f"<span style='display:inline-block;background:#0f1220;border:1px solid #1c2038;"
                f"border-radius:14px;padding:4px 12px;margin:2px 6px 8px 0;font-size:0.75rem;"
                f"color:#9fb0d0'>{t}</span>" for t in _tags), unsafe_allow_html=True)

        _t_sup = _vc_tabdf(_vc_sup, "공급사", "설명", True)
        _t_cus = _vc_tabdf(_vc_cus, "고객사", "설명", True)
        _t_peer = _vc_tabdf(_vc_peer, "기업명", "체인단계", False)

        _tabs = st.tabs([f"공급사 ({len(_t_sup)})", f"고객사 ({len(_t_cus)})",
                         f"동일 단계 ({len(_t_peer)})"])
        for _tb, _tdf in zip(_tabs, [_t_sup, _t_cus, _t_peer]):
            with _tb:
                if _tdf.empty:
                    st.caption("해당 없음")
                else:
                    st.dataframe(_tdf, hide_index=True, use_container_width=True)
        st.caption("⚪ 추정은 서브섹터 기반 자동 매핑으로 실제 벤더 지위(1차/2차, 매출 비중)와 다를 수 있음. "
                   "🟢 명시는 제품체인·공시 기반.")

        # 관련 종목 상세 이동(유니버스 내 종목만)
        _opts = {}
        for _tdf in (_t_sup, _t_cus, _t_peer):
            for _, r in _tdf.iterrows():
                if r["종목코드"]:
                    _opts[f"{r['종목명']} ({r['종목코드']})"] = r["종목코드"]
        if _opts:
            _nc1, _nc2 = st.columns([3, 1])
            with _nc1:
                _pick = st.selectbox("관련 종목 상세 보기", list(_opts),
                                     key=f"vc_nav_{ticker}", label_visibility="collapsed")
            with _nc2:
                if st.button("상세 보기 →", key=f"vc_go_{ticker}", use_container_width=True):
                    st.session_state["selected_ticker"] = _opts[_pick]
                    st.rerun()

st.write("")

# ═══════════════════════════════════════════════════════════════════════════════
# [7] 공매도 잔고 추이 (밸류체인 바로 아래) — 실데이터(pykrx 공매도잔고) 우선, co["sb"] 폴백
#     ※ 기존 수출입 데이터·관련 뉴스 블록은 제거됨
# ═══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=3600, show_spinner=False)
def _load_short_balance(ticker6: str):
    """대차/공매도 잔고 시계열 → ([{m, bal(억), ratio(%)}...], source).
    pykrx get_shorting_balance_by_date(6자리) 우선 → 실패/빈값 시 None(호출부 폴백)."""
    try:
        import pandas as pd
        from pykrx import stock
        end = pd.Timestamp.today().normalize()
        start = end - pd.Timedelta(days=430)
        df = stock.get_shorting_balance_by_date(start.strftime("%Y%m%d"),
                                                end.strftime("%Y%m%d"), ticker6)
        if df is None or df.empty:
            return None
        bal_col = next((c for c in ("공매도잔고금액", "공매도금액", "잔고금액") if c in df.columns), None)
        ratio_col = next((c for c in ("비중", "공매도잔고비중") if c in df.columns), None)
        monthly = df.resample("ME").last() if hasattr(df, "resample") else df
        rows = []
        for idx, r in monthly.tail(12).iterrows():
            rows.append({
                "m": idx.strftime("%y.%m"),
                "bal": round(float(r[bal_col]) / 1e8) if bal_col else None,   # 원→억
                "ratio": round(float(r[ratio_col]), 2) if ratio_col else None,
            })
        return rows if rows else None
    except Exception:
        return None


_sb_rows = _load_short_balance(ticker6)
_sb_source = "pykrx 공매도잔고(실데이터)" if _sb_rows else "내장 스냅샷(co['sb'] 폴백)"
if not _sb_rows:
    _sb_rows = co["sb"]

with st.container(border=True):
    st.markdown("**📉 공매도 잔고 추이**")
    st.caption(f"데이터 소스: {_sb_source}")

    sb = _sb_rows
    sb_last = sb[-1]
    sb_m1 = sb[-2] if len(sb) >= 2 else sb[0]   # 1개월 전(월별 시계열)
    sb_chg = round((sb_last["bal"] - sb_m1["bal"]) / sb_m1["bal"] * 100, 1) if sb_m1.get("bal") else 0
    _ratio = sb_last.get("ratio")

    mc1, mc2, mc3 = st.columns(3)

    def _metric(col, label, val, warn=False):
        with col:
            color = "#DC2626" if warn else "#0F172A"
            st.markdown(
                f"<div style='background:#F3F4F6;border-radius:9px;padding:10px 12px;text-align:center'>"
                f"<div style='font-size:0.68rem;color:#64748B;margin-bottom:5px'>{label}</div>"
                f"<div style='font-size:0.95rem;font-weight:700;color:{color}'>{val}</div></div>",
                unsafe_allow_html=True)

    _metric(mc1, "잔고", f"{fmt(sb_last['bal'])}억" if sb_last.get("bal") is not None else "—")
    _metric(mc2, "1개월 증감율", f"{'+' if sb_chg > 0 else ''}{sb_chg}%", sb_chg > 10)
    _metric(mc3, "잔고/시총", f"{_ratio}%" if _ratio is not None else "—", (_ratio or 0) > 2)

    st.write("")
    # 이중축: 막대(잔고, 좌) + 라인(공매도 비율, 우) — 라이트 테마
    fig_sb = make_subplots(specs=[[{"secondary_y": True}]])
    fig_sb.add_trace(go.Bar(
        x=[d["m"] for d in sb], y=[d.get("bal") for d in sb],
        name="잔고(억)", marker_color="rgba(37,99,235,.35)", marker_line_width=0),
        secondary_y=False)
    if any(d.get("ratio") is not None for d in sb):
        fig_sb.add_trace(go.Scatter(
            x=[d["m"] for d in sb], y=[d.get("ratio") for d in sb],
            name="공매도 비율(%)", line=dict(color="#DC2626", width=2), mode="lines+markers"),
            secondary_y=True)
    fig_sb.update_layout(
        height=240, template="plotly_white", showlegend=True,
        margin=dict(l=46, r=40, t=10, b=32),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=1.12, font=dict(size=10)),
        font=dict(color="#0F172A", size=10))
    fig_sb.update_yaxes(title_text="잔고(억)", secondary_y=False, tickfont=dict(size=9),
                        gridcolor="#E5E7EB")
    fig_sb.update_yaxes(title_text="비율(%)", ticksuffix="%", secondary_y=True,
                        tickfont=dict(size=9), showgrid=False)
    fig_sb.update_xaxes(tickfont=dict(size=9))
    st.plotly_chart(fig_sb, use_container_width=True, config={"displayModeBar": False})

    if sb_chg > 15:
        st.warning(f"⚠ 공매도 잔고가 1개월 전 대비 {sb_chg}% 급증 — 숏 스퀴즈 리스크 주의", icon=None)
