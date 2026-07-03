import sys, os

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from epsrev.data.dashboard_data import SECTORS, CO, PAIR_MAP
from epsrev.data.scorer import get_stock_detail
from epsrev.ui.sidebar import render_sidebar
from report_ui import load_reports_by_code, render_report_dialog  # 공용 리포트 모달

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

preselect = st.session_state.get("selected_ticker")
default_idx = 0
if preselect:
    for i, c in enumerate(ALL_CO):
        if c["t"] == preselect:
            default_idx = i
            break

sel_label = st.selectbox("종목 선택", ticker_labels, index=default_idx,
                         label_visibility="collapsed")
ticker  = ticker_map[sel_label]
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
# [3] 작업 2: 분기 실적 추이 — 풀너비
# ═══════════════════════════════════════════════════════════════════════════════

# TODO: FnSpace API 발행 후 dummy_quarterly를 quarterly_earnings 엔드포인트 실제 호출로 교체
dummy_quarterly = [
    {"quarter": "23Q3", "revenue":  9067, "op_income":  176, "opm":  1.9},
    {"quarter": "23Q4", "revenue": 11305, "op_income":  347, "opm":  3.1},
    {"quarter": "24Q1", "revenue": 12430, "op_income": 2886, "opm": 23.2},
    {"quarter": "24Q2", "revenue": 16423, "op_income": 5470, "opm": 33.3},
    {"quarter": "24Q3", "revenue": 17573, "op_income": 7028, "opm": 40.0},
    {"quarter": "24Q4", "revenue": 19767, "op_income": 8083, "opm": 40.9},
    {"quarter": "25Q1", "revenue": 17643, "op_income": 6959, "opm": 39.4},
    {"quarter": "25Q2", "revenue": 14820, "op_income": 4650, "opm": 31.4},
]

with st.container(border=True):
    st.markdown("**분기 실적 추이 (억원)**")

    _qx   = [d["quarter"]  for d in dummy_quarterly]
    _qrev = [d["revenue"]   for d in dummy_quarterly]
    _qop  = [d["op_income"] for d in dummy_quarterly]
    _qopm = [d["opm"]       for d in dummy_quarterly]

    _qfig = make_subplots(specs=[[{"secondary_y": True}]])

    _qfig.add_trace(
        go.Bar(
            x=_qx, y=_qrev,
            name="매출(억원)",
            marker_color="#1e2d4d",
            marker_line_width=0,
            hovertemplate="<b>%{x}</b><br>매출: %{y:,}억원<extra></extra>",
        ),
        secondary_y=False,
    )
    _qfig.add_trace(
        go.Bar(
            x=_qx, y=_qop,
            name="영업이익(억원)",
            marker_color="#3b82f6",
            marker_line_width=0,
            hovertemplate="<b>%{x}</b><br>영업이익: %{y:,}억원<extra></extra>",
        ),
        secondary_y=False,
    )
    _qfig.add_trace(
        go.Scatter(
            x=_qx, y=_qopm,
            name="OPM(%)",
            line=dict(color="#f97316", width=2),
            mode="lines",
            customdata=list(zip(_qrev, _qop, _qopm)),
            hovertemplate=(
                "<b>%{x}</b><br>"
                "매출: %{customdata[0]:,}억원<br>"
                "영업이익: %{customdata[1]:,}억원<br>"
                "OPM: %{customdata[2]:.1f}%<extra></extra>"
            ),
        ),
        secondary_y=True,
    )

    _qlayout = _plot_bg()
    _qlayout["height"]          = 280
    _qlayout["barmode"]         = "group"
    _qlayout["hovermode"]       = "x unified"
    _qlayout["paper_bgcolor"]   = "rgba(0,0,0,0)"
    _qlayout["plot_bgcolor"]    = "rgba(0,0,0,0)"
    _qlayout["legend"]          = dict(
        bgcolor="rgba(0,0,0,0)", font=dict(color="#aab", size=9),
        orientation="h", x=1.0, xanchor="right", y=1.12,
    )
    _qlayout["xaxis"]  = dict(gridcolor="#2a2a2a", color="#546080", tickfont=dict(size=9))
    _qlayout["yaxis"]  = dict(gridcolor="#2a2a2a", color="#546080", tickfont=dict(size=9))
    _qlayout["yaxis2"] = dict(
        overlaying="y", side="right",
        gridcolor="rgba(0,0,0,0)", color="#546080",
        tickfont=dict(size=9), ticksuffix="%",
    )
    _qfig.update_layout(**_qlayout)
    st.plotly_chart(_qfig, use_container_width=True, config={"displayModeBar": False})

st.write("")

# ═══════════════════════════════════════════════════════════════════════════════
# [4] 2열: 좌 — EPS Revision Score + 방법론 expander  |  우 — 최신 리포트 컨센서스
# ═══════════════════════════════════════════════════════════════════════════════
r4_left, r4_right = st.columns(2, gap="medium")

# ─ 좌: EPS Revision Score 요약 카드 + 작업 3 방법론 expander ─────────────────
with r4_left:
    with st.container(border=True):
        st.markdown(
            "<div style='font-size:0.72rem;color:#546080;letter-spacing:2px;"
            "margin-bottom:10px'>EPS REVISION SCORE</div>",
            unsafe_allow_html=True,
        )

        em1, em2, em3 = st.columns(3)

        def _eps_metric(col, label: str, value: str, sub: str = "") -> None:
            with col:
                st.markdown(
                    f"<div style='background:#08090f;border-radius:10px;"
                    f"padding:14px 18px;text-align:center'>"
                    f"<div style='font-size:0.68rem;color:#546080;margin-bottom:6px'>"
                    f"{label}</div>"
                    f"<div style='font-size:1.6rem;font-weight:800;color:#dde3f8'>"
                    f"{value}</div>"
                    f"<div style='font-size:0.68rem;color:#546080;margin-top:4px'>"
                    f"{sub}</div></div>",
                    unsafe_allow_html=True,
                )

        if _eps_score is not None:
            _sc_color = "#00c87a" if _eps_score >= 20 else ("#ff4060" if _eps_score <= -20 else "#ffaa00")
            _sc_disp  = f"{_eps_score:+.0f}"
        else:
            _sc_color = "#546080"
            _sc_disp  = "—"

        with em1:
            st.markdown(
                f"<div style='background:#08090f;border-radius:10px;"
                f"padding:14px 18px;text-align:center'>"
                f"<div style='font-size:0.68rem;color:#546080;margin-bottom:6px'>"
                f"EPS 리비전 점수</div>"
                f"<div style='font-size:1.6rem;font-weight:800;color:{_sc_color}'>"
                f"{_sc_disp}</div>"
                f"<div style='font-size:0.68rem;color:#546080;margin-top:4px'>"
                f"-100 ~ +100 범위</div></div>",
                unsafe_allow_html=True,
            )
        _eps_metric(em2, "실적 버킷 환산", f"{_earnings_bucket}", "0 ~ 40 범위")
        _eps_metric(em3, "신뢰도", _eps_conf_str, "컨피던스 게이트")

        # 레이어 점수 가로 막대 차트
        st.write("")
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
                y=[label for label, _ in _layer_items],
                x=_lv,
                orientation="h",
                marker_color=_lc,
                text=_lt,
                textposition="outside",
                textfont=dict(size=11, color="#dde3f8"),
                cliponaxis=False,
            ))
            fig_l.add_vline(x=0, line_color="#546080", line_width=1)
            _bg = _plot_bg()
            _bg.update({
                "height": 130,
                "margin": dict(l=130, r=80, t=10, b=10),
                "showlegend": False,
                "xaxis": {**_bg.get("xaxis", {}), "zeroline": False},
                "yaxis": {**_bg.get("yaxis", {}), "tickfont": dict(size=10)},
            })
            fig_l.update_layout(**_bg)
            st.plotly_chart(fig_l, use_container_width=True, config={"displayModeBar": False})
        else:
            st.caption("레이어 점수 데이터 없음")

        # 인사이트
        if _eps_insight:
            st.info(_eps_insight, icon="💡")
        elif _eps_detail is None:
            total = co["total"]
            if total >= 75:
                fb = f"실적·데이터·수급 모두 우수 ({total}점). 상향 모멘텀 기대."
            elif total >= 55:
                fb = f"양호한 점수 ({total}점). 일부 약점 보완 시 추가 상승 여력."
            else:
                fb = f"점수 부진 ({total}점). 하향 리스크 관리 필요."
            st.info(fb, icon="💡")

        if _eps_flags:
            for _fl in _eps_flags:
                if _fl:
                    st.warning(f"⚠️ {_fl}")

        # ── 작업 3: EPS Revision Score 방법론 expander ──────────────────────
        st.write("")
        with st.expander("📐 스코어 산출 방식", expanded=False):
            st.markdown(
                """
**EPS 리비전 스코어 (-100 ~ +100)** 는 3개 레이어의 가중 합산입니다.

| 레이어 | 가중치 | 구성 지표 |
|--------|--------|----------|
| 실현 리비전 | 40% | 3M/1M OP·EPS 컨센서스 변화율, 애널리스트 상향/하향 비율 (Diffusion Index), 최근 4Q 평균 어닝 서프라이즈 |
| 모멘텀 | 25% | 리비전 가속도 (최근 변화율 − 3M 전), 추정치 분산 (낮을수록 신뢰도 ↑) |
| 포워드 압력 | 35% | YTD 런레이트 갭, TP 선행성 (TP 변화 vs EPS 변화 차이), 리비전 지속성 (연속 방향성) |

**실적 버킷 환산 (0 ~ 40점)**: 리비전 스코어를 선형 변환.
-100→0점, +100→40점 (중립 0점 = 20점)

**신뢰도 게이트**: 커버리지 애널리스트 3인 미만 시 0.5 적용,
1인 이하 시 0.0 적용.
"""
            )

# ─ 우: 작업 5 — 최신 리포트 컨센서스 [블록A + 블록B] ─────────────────────────
with r4_right:
    with st.container(border=True):
        st.markdown("**최신 리포트 컨센서스**")

        # data/research_reports.json에서 현재 종목코드로 필터한 실제 리포트
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

            # ── 블록 A: 최근 3개 리포트 TP 테이블 (EPS는 리포트 데이터 없음 → —) ──
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

            # 테이블 상위 3개 → 클릭 요약 버튼
            _top = reports[:3]
            _cols = st.columns(len(_top))
            for i, r in enumerate(_top):
                with _cols[i]:
                    if st.button(f"🔎 {r.get('broker','')}", key=f"rptA_{ticker}_{i}",
                                 use_container_width=True):
                        render_report_dialog(r)

            # ── 블록 B: 최근 리포트 목록 (클릭 시 요약) ──────────────────────────
            st.markdown(
                "<div style='border-top:1px solid #1c2038;margin:14px 0 10px'></div>"
                "<div style='font-size:0.72rem;color:#546080;margin-bottom:10px'>"
                "최근 리포트 목록 (클릭 시 요약)</div>",
                unsafe_allow_html=True,
            )
            for idx, r in enumerate(reports):
                title = (r.get("title", "") or "")[:46]
                label = f"{title}  ·  {r.get('broker','')} {r.get('date','')}"
                key = f"rptB_{ticker}_{idx}_{r.get('report_id') or 'x'}"
                if st.button(label, key=key, use_container_width=True):
                    render_report_dialog(r)

st.write("")

# ═══════════════════════════════════════════════════════════════════════════════
# [5] 2열: 좌 — 투자 포인트 (LLM, 기존 로직 유지)  |  우 — 컨센서스 추이 차트
# ═══════════════════════════════════════════════════════════════════════════════
r5_left, r5_right = st.columns(2, gap="medium")

# ─ 좌: LLM 투자포인트 ────────────────────────────────────────────────────────
with r5_left:
    with st.container(border=True):
        ip_key = f"ip_{ticker}"

        th, tb = st.columns([3, 2])
        with th:
            st.markdown("**투자 포인트**")
        with tb:
            btn_label = (
                "⏳ 생성 중…" if st.session_state.get(f"ip_loading_{ticker}")
                else ("🔄 재생성" if ip_key in st.session_state else "✨ LLM 생성")
            )
            gen_btn = st.button(
                btn_label,
                key=f"gen_{ticker}",
                disabled=bool(st.session_state.get(f"ip_loading_{ticker}")),
                use_container_width=True,
            )

        if gen_btn:
            st.session_state[f"ip_loading_{ticker}"] = True
            with st.spinner("Claude API 호출 중…"):
                try:
                    api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
                    if not api_key:
                        raise ValueError("st.secrets에 ANTHROPIC_API_KEY가 없습니다.")
                    import anthropic
                    client = anthropic.Anthropic(api_key=api_key)

                    fin2 = co["fin"][-2:]
                    cons = co["cons"]
                    c1   = cons[-1]
                    c4   = cons[-4] if len(cons) >= 4 else cons[0]
                    direction = "상향 조정 중" if c1["fy1"] > c4["fy1"] else "하향 조정 중"
                    ctx = (
                        f"기업명: {co['n']} ({ticker})\n"
                        f"섹터: {co['secName']}\n"
                        f"시가총액: {co['mkt']:,}억원\n\n"
                        "[최근 2분기 실적]\n"
                        + "\n".join(
                            f"{f['q']}: 매출 {f['rev']:,}억 / "
                            f"영업이익 {f['op']:,}억 (OPM {f['opm']}%)"
                            for f in fin2
                        )
                        + f"\n\n[컨센서스]\nFY1 영업이익 추정 {direction}\n"
                        f"3개월 전: {c4['fy1']:,}억 → 현재: {c1['fy1']:,}억\n\n"
                        "[이벤트]\n"
                        + ("\n".join(f"- {e['txt']}" for e in co["ev"]) if co["ev"] else "없음")
                        + f"\n\n[EPS 리비전 점수]\n"
                        f"EPS리비전 {_eps_score_str} | 데이터 {co['sc']['d']}/35"
                        f" | 수급 {co['sc']['s']}/25"
                    )
                    msg = client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=800,
                        messages=[{
                            "role": "user",
                            "content": (
                                "당신은 한국 주식 리서치 애널리스트입니다. "
                                "아래 데이터만 근거로 투자 포인트 3가지를 JSON으로만 출력하세요. "
                                "데이터 외 내용 금지. "
                                '형식(마크다운 없이 순수 JSON): '
                                '{"points":[{"title":"...","body":"..."},'
                                '{"title":"...","body":"..."},'
                                '{"title":"...","body":"..."}]}\n\n' + ctx
                            ),
                        }],
                    )
                    text  = msg.content[0].text
                    clean = text.replace("```json", "").replace("```", "").strip()
                    data  = json.loads(clean)
                    st.session_state[ip_key] = data.get("points", [])
                except Exception as e:
                    st.session_state[ip_key] = [
                        {"title": "생성 오류", "body": str(e)}
                    ]
            st.session_state[f"ip_loading_{ticker}"] = False
            st.rerun()

        ip = st.session_state.get(ip_key)
        if not ip:
            st.markdown(
                "<div style='color:#546080;font-size:0.85rem;text-align:center;"
                "padding:30px 0;line-height:1.8'>LLM 생성 버튼을 클릭하면<br>"
                "실적·컨센서스·이벤트 데이터를 기반으로<br>투자 포인트를 자동 생성합니다</div>",
                unsafe_allow_html=True,
            )
        else:
            for j, pt in enumerate(ip):
                if j > 0:
                    st.markdown(
                        "<hr style='margin:10px 0;border:none;border-top:1px solid #1c2038'>",
                        unsafe_allow_html=True,
                    )
                st.markdown(
                    f"<div style='font-size:0.85rem;font-weight:700;"
                    f"color:{co['secColor']};margin-bottom:5px'>"
                    f"{j+1}. {pt.get('title','')}</div>"
                    f"<div style='font-size:0.8rem;color:#8899bb;line-height:1.7'>"
                    f"{pt.get('body', pt.get('content',''))}</div>",
                    unsafe_allow_html=True,
                )

# ─ 우: 작업 4 — 컨센서스 추이 차트 ──────────────────────────────────────────
with r5_right:
    with st.container(border=True):
        st.markdown("**컨센서스 추이 — FY1/FY2 영업이익 추정 (억원)**")

        # TODO: FnSpace API 발행 후 dummy_consensus를 consensus_history 엔드포인트 실제 호출로 교체
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
        fig_cons.add_trace(go.Scatter(
            x=_cx, y=_cy1,
            name="FY1",
            line=dict(color="#3b82f6", width=2),
            mode="lines",
        ))
        fig_cons.add_trace(go.Scatter(
            x=_cx, y=_cy2,
            name="FY2",
            line=dict(color="#fbbf24", width=2, dash="dot"),
            mode="lines",
        ))

        # 끝단 최신값 annotation
        fig_cons.add_annotation(
            x=_cx[-1], y=_cy1[-1],
            text=f"FY1 {_cy1[-1]:,}억",
            showarrow=False, xanchor="left", xshift=8,
            font=dict(size=9, color="#3b82f6"),
        )
        fig_cons.add_annotation(
            x=_cx[-1], y=_cy2[-1],
            text=f"FY2 {_cy2[-1]:,}억",
            showarrow=False, xanchor="left", xshift=8,
            font=dict(size=9, color="#fbbf24"),
        )

        _cons_layout = _plot_bg()
        _cons_layout["height"]  = 240
        _cons_layout["margin"]  = dict(l=46, r=90, t=14, b=36)   # 우측 annotation 공간
        _cons_layout["yaxis"]   = dict(
            gridcolor="#1c2038", color="#546080", tickfont=dict(size=9),
            tickformat=",.0f", title=dict(text="억원", font=dict(size=9, color="#546080")),
        )
        fig_cons.update_layout(**_cons_layout)
        st.plotly_chart(fig_cons, use_container_width=True, config={"displayModeBar": False})

st.write("")

# ═══════════════════════════════════════════════════════════════════════════════
# [6] 2열: 좌 — 점수 1년 추이  |  우 — 관련 수출 데이터  (기존 로직 유지)
# ═══════════════════════════════════════════════════════════════════════════════
r6c1, r6c2 = st.columns(2, gap="medium")

with r6c1:
    with st.container(border=True):
        st.markdown("**점수 1년 추이**")
        hist = co["hist"]
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(
            x=[d["m"] for d in hist], y=[d["score"] for d in hist],
            name="점수", line=dict(color=co["secColor"], width=2.5),
            mode="lines+markers",
            marker=dict(size=4, color=co["secColor"]),
        ))
        layout3 = _plot_bg()
        layout3["height"] = 200
        layout3["yaxis"]["range"] = [0, 100]
        fig3.update_layout(**layout3)
        st.plotly_chart(fig3, use_container_width=True, config={"displayModeBar": False})

with r6c2:
    with st.container(border=True):
        st.markdown("**관련 수출 데이터 (백만달러 · YoY%)**")
        exp = co["exp"]
        fig4 = make_subplots(specs=[[{"secondary_y": True}]])
        fig4.add_trace(
            go.Bar(x=[d["m"] for d in exp], y=[d["val"] for d in exp],
                   name="수출액($M)",
                   marker_color="rgba({},{},{},0.33)".format(
                       *[int(co["secColor"].lstrip("#")[i:i+2], 16) for i in (0, 2, 4)]),
                   marker_line_width=0),
            secondary_y=False,
        )
        fig4.add_trace(
            go.Scatter(x=[d["m"] for d in exp], y=[d["yoy"] for d in exp],
                       name="YoY%", line=dict(color=co["secColor"], width=2),
                       mode="lines"),
            secondary_y=True,
        )
        layout4 = _plot_bg()
        layout4["height"] = 200
        layout4["yaxis2"] = dict(
            overlaying="y", side="right",
            gridcolor="rgba(0,0,0,0)", color="#546080",
            tickfont=dict(size=9), ticksuffix="%",
        )
        fig4.update_layout(**layout4)
        st.plotly_chart(fig4, use_container_width=True, config={"displayModeBar": False})

st.write("")

# ═══════════════════════════════════════════════════════════════════════════════
# EPS 리비전 근거자료 카드 (기존 유지)
# ═══════════════════════════════════════════════════════════════════════════════
with st.container(border=True):
    st.markdown(
        "<div style='font-size:0.72rem;color:#546080;letter-spacing:2px;"
        "margin-bottom:10px'>EPS REVISION EVIDENCE</div>",
        unsafe_allow_html=True,
    )

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

    ev_items = list(_EV_LABELS.items())
    for row_start in range(0, len(ev_items), 4):
        row_items = ev_items[row_start: row_start + 4]
        cols = st.columns(4)
        for col, (key, label) in zip(cols, row_items):
            val = _eps_ev.get(key) if _eps_ev else None
            if val is None:
                val_html = (
                    "<span style='color:#343d5a'>— "
                    "<span style='font-size:0.6rem'>(FnSpace 연결 후 활성화)</span></span>"
                )
            else:
                v_color = "#00c87a" if val > 0 else ("#ff4b4b" if val < 0 else "#dde3f8")
                sign    = "+" if val > 0 else ""
                val_html = f"<span style='color:{v_color};font-weight:700'>{sign}{val:.3f}</span>"

            with col:
                st.markdown(
                    f"<div style='background:#08090f;border-radius:8px;"
                    f"padding:10px 12px;margin-bottom:8px'>"
                    f"<div style='font-size:0.65rem;color:#546080;margin-bottom:5px;"
                    f"line-height:1.4'>{label}</div>"
                    f"<div style='font-size:0.95rem'>{val_html}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        if row_start + 4 < len(ev_items):
            st.write("")

st.write("")

# ═══════════════════════════════════════════════════════════════════════════════
# 대차잔고 + 관련 뉴스 (기존 유지)
# ═══════════════════════════════════════════════════════════════════════════════
r_sb1, r_sb2 = st.columns(2, gap="medium")

with r_sb1:
    with st.container(border=True):
        st.markdown("**대차잔고**")
        sb      = co["sb"]
        sb_last = sb[-1]
        sb_m1   = sb[-5] if len(sb) >= 5 else sb[0]
        sb_chg  = round((sb_last["bal"] - sb_m1["bal"]) / sb_m1["bal"] * 100, 1) if sb_m1["bal"] else 0

        mc1, mc2, mc3 = st.columns(3)

        def _metric(col, label, val, warn=False):
            with col:
                color = "#ff4060" if warn else "#dde3f8"
                st.markdown(
                    f"<div style='background:#08090f;border-radius:9px;"
                    f"padding:10px 12px;text-align:center'>"
                    f"<div style='font-size:0.68rem;color:#546080;margin-bottom:5px'>{label}</div>"
                    f"<div style='font-size:0.95rem;font-weight:700;color:{color}'>{val}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        _metric(mc1, "잔고",        f"{fmt(sb_last['bal'])}억")
        _metric(mc2, "1개월 증감율", f"{'+' if sb_chg > 0 else ''}{sb_chg}%", sb_chg > 10)
        _metric(mc3, "잔고/시총",   f"{sb_last['ratio']}%", sb_last["ratio"] > 2)

        st.write("")
        fig5 = make_subplots(specs=[[{"secondary_y": False}]])
        fig5.add_trace(go.Bar(
            x=[d["m"] for d in sb], y=[d["bal"] for d in sb],
            name="대차잔고(억)", marker_color="rgba(255,64,96,.25)",
            marker_line_width=0,
        ))
        fig5.add_trace(go.Scatter(
            x=[d["m"] for d in sb], y=[d["bal"] for d in sb],
            name=" ", line=dict(color="#ff4060", width=2), mode="lines",
        ))
        layout5 = _plot_bg()
        layout5["height"]     = 140
        layout5["showlegend"] = False
        fig5.update_layout(**layout5)
        st.plotly_chart(fig5, use_container_width=True, config={"displayModeBar": False})

        if sb_chg > 15:
            st.warning(
                f"⚠ 대차잔고가 1개월 전 대비 {sb_chg}% 급증 — 숏 스퀴즈 리스크 주의",
                icon=None,
            )

with r_sb2:
    with st.container(border=True):
        st.markdown("**관련 뉴스**")
        news = co.get("news", [])
        if news:
            for idx, item in enumerate(news):
                st.markdown(
                    f"<div style='display:flex;gap:12px;padding:10px 0;"
                    f"{'border-bottom:1px solid #1c2038;' if idx < len(news)-1 else ''}'>"
                    f"<div style='font-size:0.75rem;color:#546080;white-space:nowrap;"
                    f"margin-top:2px'>{item['d']}</div>"
                    f"<div style='font-size:0.82rem;color:#dde3f8;line-height:1.55'>"
                    f"{item['t']}</div></div>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("뉴스 없음")
