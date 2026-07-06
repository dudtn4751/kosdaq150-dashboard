import sys, os

import streamlit as st
import plotly.graph_objects as go

from epsrev.data.dashboard_data import SECTORS, CO
from epsrev.data.scorer import score_all_stocks, get_stock_detail, get_price_df
from epsrev.pair_stats import compute_pair_stats, rank_pair_score
from epsrev.pair_signal import pair_signal, hedge_sizing
from epsrev.pair_backtest import backtest_spread, rebase100
from epsrev.ui.sidebar import render_sidebar

render_sidebar()


@st.cache_data(ttl=3600, show_spinner=False)
def _pair_stats_cached(long_t: str, short_t: str) -> dict | None:
    """(롱,숏) 실측 통계 — 가격 캐시 + 통계 캐시. 실패 시 None."""
    dl, ds = get_price_df(long_t), get_price_df(short_t)
    if dl is None or ds is None:
        return None
    return compute_pair_stats(dl, ds, lookback=60)


def _sig_badge(sig: dict) -> str:
    """신호 상태 → 색 배지 HTML. sig 없으면 빈 문자열."""
    if not sig:
        return ""
    s = sig.get("state", "대기")
    col = {"진입가능": "#00c87a", "청산": "#4f8eff", "손절": "#ff4060"}.get(s, "#8899bb")
    return (f"<span style='font-size:0.68rem;font-weight:800;color:{col};"
            f"background:{col}22;padding:2px 7px;border-radius:5px'>{s}</span>")

st.markdown(
    "<div style='font-size:1.5rem;font-weight:800;margin-bottom:2px'>⚖️ 롱숏 페어 파인더</div>"
    "<div style='font-size:0.8rem;color:#546080;margin-bottom:8px'>"
    "섹터 내 EPS 리비전 점수 기반 롱숏 조합 탐색 · 스프레드 추이 분석</div>",
    unsafe_allow_html=True,
)
st.divider()

# ── TODO: 유니버스 동적 로드 함수 자리 ──────────────────────────────────────
# def load_universe(path: str) -> pd.DataFrame:
#     """CSV 유니버스 파일에서 종목 목록을 로드한다.
#     컬럼 필수: ticker, name, sector
#     TODO: 유니버스 파일(CSV) 수신 후 여기서 로드하여 DUMMY_STOCKS 대체
#     """
#     import pandas as pd
#     return pd.read_csv(path)
# ─────────────────────────────────────────────────────────────────────────────

# ── EPS 스코어 전체 데이터 로드 ───────────────────────────────────────────────
@st.cache_data(ttl=600)
def _load_scores():
    return score_all_stocks()

try:
    _score_df = _load_scores()
    _has_scores = True
except Exception as _e:
    _score_df = None
    _has_scores = False
    st.warning(f"scorer 로드 실패: {_e}")

# ── 전체 종목 목록 (대시보드 기준) ───────────────────────────────────────────
ALL_CO: list[dict] = [CO[c["t"]] for sec in SECTORS for c in sec["cos"]]

def fmt(n) -> str:
    return f"{int(n):,}" if n is not None else "—"


# ── LONG 포지션 선택 ──────────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("**롱 포지션 선택**")
    preselect_long = st.session_state.get("long_ticker", ALL_CO[0]["t"])

    ticker_labels = [f"[{c['secName']}] {c['n']}" for c in ALL_CO]
    ticker_map    = {f"[{c['secName']}] {c['n']}": c["t"] for c in ALL_CO}
    rev_map       = {v: k for k, v in ticker_map.items()}

    default_idx = 0
    if preselect_long in rev_map:
        lbl = rev_map[preselect_long]
        if lbl in ticker_labels:
            default_idx = ticker_labels.index(lbl)

    long_label  = st.selectbox("롱 종목", ticker_labels, index=default_idx,
                                label_visibility="collapsed")
    long_ticker = ticker_map[long_label]
    long_co     = CO[long_ticker]

st.write("")

# ── 롱 종목 EPS 점수 조회 ─────────────────────────────────────────────────────
_long_eps   = None
_long_conf  = None
_long_flags = ""
if _has_scores and _score_df is not None:
    _lrow = _score_df[_score_df["ticker"] == long_ticker]
    if not _lrow.empty:
        _long_eps   = float(_lrow.iloc[0]["eps_score"])
        _long_conf  = float(_lrow.iloc[0]["confidence"])
        _long_flags = str(_lrow.iloc[0].get("flags", ""))


STAT_TOP_N = 8  # EPS 스프레드 상위 N개만 통계 계산(비용 제한)


# ── 숏 후보 계산: 같은 섹터 → EPS 스프레드 상위 N개만 실측 통계·복합점수 ──────────
def _build_short_candidates(lt: str) -> list[dict]:
    """같은 섹터 종목을 EPS 스프레드(롱−숏) 큰 순으로 상위 N개만 실측 통계 계산 후 복합점수로 정렬."""
    long_sec = long_co.get("secId", "")
    same_sec_tickers = []
    for sec in SECTORS:
        if sec["id"] == long_sec:
            same_sec_tickers = [c["t"] for c in sec["cos"] if c["t"] != lt]
            break

    candidates = []
    for pt in same_sec_tickers:
        pc = CO.get(pt)
        if not pc:
            continue
        short_eps = short_conf = None
        short_flags = ""
        if _has_scores and _score_df is not None:
            _srow = _score_df[_score_df["ticker"] == pt]
            if not _srow.empty:
                short_eps  = float(_srow.iloc[0]["eps_score"])
                short_conf = float(_srow.iloc[0]["confidence"])
                short_flags = str(_srow.iloc[0].get("flags", ""))
        eps_spread = (round(_long_eps - short_eps, 1)
                      if (_long_eps is not None and short_eps is not None) else None)
        candidates.append({
            "t": pt, "co": pc, "short_eps": short_eps, "short_conf": short_conf,
            "short_flags": short_flags, "eps_spread": eps_spread,
            "stats": {}, "comp_score": None, "signal": None,
        })

    # EPS 스프레드 큰 순(숏 최선) → 상위 N개만 실측 통계
    candidates.sort(key=lambda x: (x["eps_spread"] if x["eps_spread"] is not None else -9999),
                    reverse=True)
    for i, c in enumerate(candidates):
        if i < STAT_TOP_N:
            stats = _pair_stats_cached(lt, c["t"])
            if stats:
                c["stats"] = stats
                c["comp_score"] = rank_pair_score(stats, c["eps_spread"])
                c["signal"] = pair_signal(stats)

    # 복합점수 있으면 그 순, 없으면 EPS 스프레드 순
    candidates.sort(
        key=lambda x: (1, x["comp_score"]) if x["comp_score"] is not None
        else (0, (x["eps_spread"] if x["eps_spread"] is not None else -9999)),
        reverse=True,
    )
    return candidates


pairs = _build_short_candidates(long_ticker)

# ── 2열: LONG 요약 | 숏 후보 목록 ───────────────────────────────────────────
lc1, lc2 = st.columns(2, gap="medium")

with lc1:
    with st.container(border=True):
        eps_str  = f"{_long_eps:+.0f}" if _long_eps  is not None else "—"
        eps_col  = "#00c87a" if (_long_eps or 0) >= 20 else (
                   "#ff4060" if (_long_eps or 0) <= -20 else "#ffaa00")

        st.markdown(
            f"<div style='font-size:0.72rem;color:{long_co['secColor']};"
            f"letter-spacing:2px;margin-bottom:6px'>LONG</div>"
            f"<div style='font-size:1.3rem;font-weight:800;margin-bottom:4px'>"
            f"{long_co['n']}</div>"
            f"<div style='font-size:0.8rem;color:#546080;margin-bottom:16px'>"
            f"{long_co['secName']} · {long_co['t']}</div>",
            unsafe_allow_html=True,
        )
        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            st.markdown(
                "<div style='font-size:0.68rem;color:#546080;margin-bottom:4px'>현재가</div>"
                f"<div style='font-size:0.9rem;font-weight:600'>{fmt(long_co['p'])}원</div>",
                unsafe_allow_html=True,
            )
        with mc2:
            st.markdown(
                "<div style='font-size:0.68rem;color:#546080;margin-bottom:4px'>EPS 리비전</div>"
                f"<div style='font-size:0.9rem;font-weight:800;color:{eps_col}'>{eps_str}</div>",
                unsafe_allow_html=True,
            )
        with mc3:
            br_color = "#00c87a" if long_co["br"] < 1 else "#dde3f8"
            st.markdown(
                "<div style='font-size:0.68rem;color:#546080;margin-bottom:4px'>차입비용(연)</div>"
                f"<div style='font-size:0.9rem;font-weight:600;color:{br_color}'>"
                f"{long_co['br']}%</div>",
                unsafe_allow_html=True,
            )

        if long_co["ev"]:
            st.markdown(
                "<div style='margin-top:12px;border-top:1px solid #1c2038;padding-top:10px'>",
                unsafe_allow_html=True,
            )
            for ev in long_co["ev"]:
                st.markdown(
                    f"<div style='font-size:0.75rem;color:#ffaa00;"
                    f"background:rgba(255,170,0,.1);padding:4px 9px;"
                    f"border-radius:5px;margin-bottom:4px'>"
                    f"+{ev['pts']} {ev['txt']}</div>",
                    unsafe_allow_html=True,
                )
            st.markdown("</div>", unsafe_allow_html=True)

        if _long_flags:
            st.markdown(
                f"<div style='margin-top:10px;font-size:0.72rem;color:#ffaa00'>"
                f"⚠ {_long_flags}</div>",
                unsafe_allow_html=True,
            )

with lc2:
    with st.container(border=True):
        st.markdown(
            f"**숏 후보 — {long_co['secName']} 섹터 내 "
            f"({len(pairs)}종목 · 상위 5개 표시)**"
        )

        # ── 숏 후보 선정 기준 설명 ───────────────────────────────────────
        with st.expander("📌 숏 후보 선정 기준", expanded=False):
            st.markdown(
                """
<div style='font-size:0.82rem;line-height:1.8;color:#8899bb'>

**1. 동일 섹터 내 종목만 대상**
&nbsp;&nbsp;롱 종목과 같은 섹터의 종목만 비교합니다. 섹터 공통 매크로 리스크를 헤지하고 순수한 종목 간 상대적 우열을 포착하기 위함입니다.

**2. EPS 리비전 점수 낮은 순 정렬**
&nbsp;&nbsp;애널리스트 컨센서스 EPS 추정치가 지속적으로 하향 조정되는 종목일수록 숏 우선순위가 높습니다. 점수가 낮을수록(음수일수록) 실적 기대감이 무너지고 있는 신호입니다.

**3. 페어 점수차 (EPS 롱 − EPS 숏)**
&nbsp;&nbsp;롱 종목의 EPS 점수에서 숏 후보의 EPS 점수를 뺀 값입니다. 값이 클수록 두 종목의 실적 방향성 차이가 크고 페어 수익 가능성이 높습니다.

**4. 차입 비용 (br)**
&nbsp;&nbsp;숏 포지션 유지에 드는 연 차입비용입니다. 2.5% 초과 시 수익성을 잠식할 수 있어 경고 표시됩니다.

**5. 신뢰도 (Confidence)**
&nbsp;&nbsp;EPS 리비전 계산에 사용된 데이터의 충분성·일관성 지표입니다. 낮을수록 신호의 노이즈가 큽니다.

</div>
""",
                unsafe_allow_html=True,
            )

        if not pairs:
            st.caption("같은 섹터에 다른 종목이 없습니다.")
            sel_pair = None
        else:
            sel_key = f"sel_pair_{long_ticker}"
            if sel_key not in st.session_state:
                st.session_state[sel_key] = pairs[0]["t"]

            # 헤더 (실측 통계)
            _WID = [0.4, 2.6, 1.3, 1.2, 1.4, 1.1, 1.1]
            _h = st.columns(_WID)
            for col, lbl in zip(_h, ["#", "종목", "복합점수", "상관", "반감기", "z", ""]):
                with col:
                    st.markdown(f"<div style='font-size:0.65rem;color:#546080'>{lbl}</div>",
                                unsafe_allow_html=True)
            st.markdown("<hr style='margin:4px 0 6px;border:none;border-top:1px solid #1c2038'>",
                        unsafe_allow_html=True)

            def _render_pair_row(idx: int, pair: dict) -> None:
                pc     = pair["co"]
                is_sel = st.session_state.get(sel_key) == pair["t"]
                bg     = "rgba(255,64,96,.08)" if is_sel else "transparent"
                stt    = pair.get("stats") or {}

                comp = pair.get("comp_score")
                comp_str = f"{comp:.0f}" if comp is not None else "—"
                comp_col = ("#00c87a" if (comp or 0) >= 60 else
                            "#ffaa00" if (comp or 0) >= 40 else "#8899bb")
                corr = stt.get("corr"); corr_str = f"{corr:.2f}" if corr is not None else "—"
                hl = stt.get("half_life"); hl_str = f"{hl:.0f}일" if hl is not None else "—"
                z = stt.get("zscore"); z_str = f"{z:+.1f}" if z is not None else "—"
                z_col = "#ff4060" if (isinstance(z, (int, float)) and abs(z) >= 2) else "#dde3f8"
                badge = _sig_badge(pair.get("signal"))

                row = st.columns(_WID)
                with row[0]:
                    st.markdown(f"<div style='font-size:1rem;font-weight:800;color:#ff4060;"
                                f"padding-top:12px'>{idx+1}</div>", unsafe_allow_html=True)
                with row[1]:
                    st.markdown(
                        f"<div style='background:{bg};border-radius:5px;padding:7px 6px'>"
                        f"<div style='font-size:0.86rem;font-weight:700'>{pc['n']} "
                        f"{badge}</div>"
                        f"<div style='font-size:0.68rem;color:#546080'>{pc['t']}</div></div>",
                        unsafe_allow_html=True)
                with row[2]:
                    st.markdown(f"<div style='padding-top:10px;font-size:1.05rem;"
                                f"font-weight:800;color:{comp_col}'>{comp_str}</div>",
                                unsafe_allow_html=True)
                with row[3]:
                    st.markdown(f"<div style='padding-top:12px;font-size:0.85rem;"
                                f"color:#8899bb'>{corr_str}</div>", unsafe_allow_html=True)
                with row[4]:
                    st.markdown(f"<div style='padding-top:12px;font-size:0.85rem;"
                                f"color:#8899bb'>{hl_str}</div>", unsafe_allow_html=True)
                with row[5]:
                    st.markdown(f"<div style='padding-top:12px;font-size:0.9rem;"
                                f"font-weight:700;color:{z_col}'>{z_str}</div>",
                                unsafe_allow_html=True)
                with row[6]:
                    if st.button("✓" if is_sel else "선택",
                                 key=f"pick_{long_ticker}_{pair['t']}",
                                 use_container_width=True,
                                 type="primary" if is_sel else "secondary"):
                        st.session_state[sel_key] = pair["t"]
                        st.rerun()

                st.markdown(
                    "<hr style='margin:2px 0;border:none;border-top:1px solid #1c2038'>",
                    unsafe_allow_html=True,
                )

            # 상위 5개 항상 표시
            TOP_N = 5
            for idx, pair in enumerate(pairs[:TOP_N]):
                _render_pair_row(idx, pair)

            # 나머지는 펼치기
            if len(pairs) > TOP_N:
                with st.expander(f"나머지 {len(pairs) - TOP_N}개 후보 더 보기"):
                    for idx, pair in enumerate(pairs[TOP_N:], start=TOP_N):
                        _render_pair_row(idx, pair)

            sel_pair = next(
                (p for p in pairs if p["t"] == st.session_state.get(sel_key)),
                pairs[0] if pairs else None,
            )

# ── 페어 상세 분석 ────────────────────────────────────────────────────────────
if pairs and sel_pair:
    st.write("")
    short_co = sel_pair["co"]
    se       = sel_pair["short_eps"]
    se_str   = f"{se:+.0f}" if se is not None else "—"
    long_eps_disp = f"{_long_eps:+.0f}" if _long_eps is not None else "—"
    stt  = sel_pair.get("stats") or {}
    sig  = sel_pair.get("signal")
    comp = sel_pair.get("comp_score")
    comp_str = f"{comp:.0f}" if comp is not None else "—"
    comp_col = ("#00c87a" if (comp or 0) >= 60 else
                "#ffaa00" if (comp or 0) >= 40 else "#8899bb")
    sig_state = sig.get("state") if sig else "—"
    sig_col = {"진입가능": "#00c87a", "청산": "#4f8eff", "손절": "#ff4060"}.get(sig_state, "#8899bb")

    # 배너: 복합점수 + 신호 상태
    st.markdown(
        f"<div style='background:#0f1220;border:1px solid #1c2038;border-radius:10px;"
        f"padding:14px 24px;display:flex;align-items:center;justify-content:space-between;"
        f"margin-bottom:14px'>"
        f"<div style='font-size:0.9rem;color:#8899bb'>"
        f"<b style='color:#dde3f8'>{long_co['n']}</b> <span style='font-size:0.78rem'>(EPS {long_eps_disp})</span>"
        f" &nbsp;LONG / SHORT&nbsp; "
        f"<b style='color:#dde3f8'>{short_co['n']}</b> <span style='font-size:0.78rem'>(EPS {se_str})</span></div>"
        f"<div style='display:flex;align-items:center;gap:18px'>"
        f"<div style='text-align:right'><div style='font-size:0.62rem;color:#546080'>복합점수</div>"
        f"<div style='font-size:1.4rem;font-weight:800;color:{comp_col}'>{comp_str}</div></div>"
        f"<div style='font-size:1rem;font-weight:800;color:{sig_col};background:{sig_col}22;"
        f"padding:6px 14px;border-radius:8px'>{sig_state}</div></div></div>",
        unsafe_allow_html=True,
    )

    # 투입 자본(헤지 사이징용)
    _cap_c1, _cap_c2 = st.columns([3, 1])
    with _cap_c2:
        capital = st.number_input("투입 자본(원)", min_value=0, value=10_000_000,
                                  step=1_000_000, key=f"cap_{long_ticker}_{sel_pair['t']}")

    dc1, dc2 = st.columns(2, gap="medium")

    with dc1:
        with st.container(border=True):
            st.markdown("**실측 페어 통계 · 신호 · 헤지**")
            _stat_rows = [
                ("상관 (로그수익률)", stt.get("corr"), 2, ""),
                ("코인테그 p-value", stt.get("coint_p"), 3, ""),
                ("스프레드 ADF p", stt.get("adf_p"), 3, ""),
                ("반감기", stt.get("half_life"), 0, "일"),
                ("현재 z-score", stt.get("zscore"), 2, ""),
                ("헤지 베타", stt.get("beta"), 2, ""),
            ]
            _body = ""
            for lbl, val, nd, suf in _stat_rows:
                vs = f"{val:.{nd}f}{suf}" if isinstance(val, (int, float)) else "—"
                _body += (f"<div style='display:flex;justify-content:space-between;font-size:0.82rem;"
                          f"padding:5px 0;border-bottom:1px solid #14182c'>"
                          f"<span style='color:#8899bb'>{lbl}</span>"
                          f"<span style='color:#dde3f8;font-weight:700'>{vs}</span></div>")
            st.markdown(_body, unsafe_allow_html=True)

            if sig:
                st.markdown(
                    f"<div style='margin-top:10px;font-size:0.8rem'>{_sig_badge(sig)} "
                    f"<span style='color:#8899bb'>{sig.get('reason', '')}</span></div>",
                    unsafe_allow_html=True)

            hz = hedge_sizing(stt.get("beta"), capital)
            st.markdown(
                "<div style='border-top:1px solid #1c2038;margin-top:10px;padding-top:8px'>"
                "<div style='font-size:0.72rem;color:#546080;margin-bottom:4px'>헤지 비율·제안 (달러/베타 중립)</div>"
                f"<div style='display:flex;justify-content:space-between;font-size:0.82rem;padding:3px 0'>"
                f"<span style='color:#00c87a'>롱 {long_co['n']} × {hz['long_w']}</span>"
                f"<span style='color:#dde3f8;font-weight:700'>{hz['long_amt']:,}원</span></div>"
                f"<div style='display:flex;justify-content:space-between;font-size:0.82rem;padding:3px 0'>"
                f"<span style='color:#ff4060'>숏 {short_co['n']} × {hz['short_w']}</span>"
                f"<span style='color:#dde3f8;font-weight:700'>{hz['short_amt']:,}원</span></div></div>",
                unsafe_allow_html=True)

            br = short_co["br"]
            if br > 2.5:
                st.warning(f"⚠ 숏 차입비용 {br}% — 페어 비용이 높아 수익성 잠식 가능")
            if sel_pair.get("short_flags"):
                st.caption(f"⚠ {sel_pair['short_flags']}")

    with dc2:
        with st.container(border=True):
            st.markdown("**리베이스 오버레이**  <span style='font-size:0.72rem;color:#546080'>"
                        "시작점 100 정규화 — 상대 성과</span>", unsafe_allow_html=True)
            _rl = rebase100(get_price_df(long_ticker))
            _rs = rebase100(get_price_df(sel_pair["t"]))
            if _rl and _rs:
                fig_rb = go.Figure()
                fig_rb.add_trace(go.Scatter(x=[d["date"] for d in _rl], y=[d["val"] for d in _rl],
                                            name=long_co["n"], line=dict(color="#00c87a", width=2)))
                fig_rb.add_trace(go.Scatter(x=[d["date"] for d in _rs], y=[d["val"] for d in _rs],
                                            name=short_co["n"], line=dict(color="#ff4060", width=2)))
                fig_rb.add_hline(y=100, line_dash="dash", line_color="#546080", line_width=1)
                fig_rb.update_layout(height=210, margin=dict(l=40, r=20, t=10, b=30),
                                     paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#0a0d1a",
                                     font=dict(color="#dde3f8", size=10),
                                     legend=dict(orientation="h", y=1.14, font=dict(size=9)),
                                     xaxis=dict(gridcolor="#1c2038", color="#546080", tickfont=dict(size=9)),
                                     yaxis=dict(gridcolor="#1c2038", color="#546080", tickfont=dict(size=9)))
                st.plotly_chart(fig_rb, use_container_width=True, config={"displayModeBar": False})
            else:
                st.caption("⚠ 일봉 데이터가 없어 리베이스 차트를 그릴 수 없습니다.")

        # 숏 종목 EPS 리비전 요약
        st.write("")
        with st.container(border=True):
            st.markdown(f"**{short_co['n']} EPS 리비전 상세**")
            try:
                _sd   = get_stock_detail(sel_pair["t"])
                _sep  = _sd.get("eps_score")
                _sep_str  = f"{_sep:+.0f}" if _sep is not None else "—"
                _sep_col  = "#00c87a" if (_sep or 0) >= 20 else (
                            "#ff4060" if (_sep or 0) <= -20 else "#ffaa00")
                _sconf    = _sd.get("confidence")
                _sconf_str = f"{_sconf:.2f}" if _sconf is not None else "—"
                _s_earn   = max(0, min(40, round(((_sep or 0) + 100) / 200 * 40)))
                _si       = _sd.get("insight", "")
                _sf       = _sd.get("flags", [])

                sc1, sc2, sc3 = st.columns(3)
                for col, lbl, val, col_c in [
                    (sc1, "EPS 리비전 점수", _sep_str,       _sep_col),
                    (sc2, "실적 버킷 환산",  str(_s_earn),   "#dde3f8"),
                    (sc3, "신뢰도",          _sconf_str,     "#dde3f8"),
                ]:
                    with col:
                        st.markdown(
                            f"<div style='background:#08090f;border-radius:8px;"
                            f"padding:10px;text-align:center'>"
                            f"<div style='font-size:0.65rem;color:#546080;margin-bottom:4px'>{lbl}</div>"
                            f"<div style='font-size:1.2rem;font-weight:800;color:{col_c}'>{val}</div>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                if _si:
                    st.info(_si, icon="💡")
                for _fl in _sf:
                    if _fl:
                        st.warning(f"⚠️ {_fl}")
            except Exception:
                st.caption("EPS 리비전 상세 없음 (유니버스 미포함 종목)")
"""렌더 스니펫 (참고) — 페어 파인더 페이지의 '페어 상세 분석' 아래에 붙여 넣는 패널 블록.

이 블록은 두 순수 함수(pair_ratio_panel·leg_technical_panel)가 반환한 dict만 소비해 차트/메트릭을 그립니다.
의존 모듈이 없으면 크래시 없이 '비활성 캡션'만 표시(방어 import).

필요 전역(페어 파인더 페이지에 이미 있는 것):
  st, go(plotly.graph_objects), pairs, sel_pair, long_ticker, long_co, short_co
필요 파일(같은 repo):
  pair_panel.py, pair_tech_panel.py (루트),  data/scorer.py 에 get_price_df(ticker)
"""

# ── 아래를 페어 파인더 페이지 끝(페어 상세 분석 블록 다음)에 그대로 붙여넣기 ──

if pairs and sel_pair:                                   # noqa: F821
    # 의존(get_price_df·pair_panel·pair_tech_panel)이 없는 환경에서도 안 깨지게 방어
    try:
        from epsrev.pair_panel import pair_ratio_panel
        from epsrev.pair_tech_panel import leg_technical_panel
        from epsrev.data.scorer import get_price_df
    except Exception:
        pair_ratio_panel = leg_technical_panel = get_price_df = None

    _dfl = get_price_df(long_ticker) if get_price_df else None        # noqa: F821
    _dfs = get_price_df(sel_pair["t"]) if get_price_df else None      # noqa: F821

    st.write("")                                          # noqa: F821
    if pair_ratio_panel is None or get_price_df is None:
        st.info("비율선·레그별 기술 패널: 일봉 소스(get_price_df)와 pair_panel·pair_tech_panel "  # noqa: F821
                "모듈을 repo에 추가하면 활성화됩니다.", icon="📐")
    elif _dfl is None or _dfs is None:
        st.caption("⚠ 선택 페어의 일봉 데이터가 없어 패널을 그릴 수 없습니다.")    # noqa: F821
    else:
        rp = pair_ratio_panel(_dfl, _dfs, lookback=40)
        tp = leg_technical_panel(_dfl, _dfs)

        def _v(x, suf="", nd=2):
            return f"{x:.{nd}f}{suf}" if isinstance(x, (int, float)) else "—"

        # ── 비율선 패널 ──
        with st.container(border=True):                  # noqa: F821
            st.markdown("**📐 비율선 패널**  <span style='font-size:0.72rem;color:#546080'>"  # noqa: F821
                        "진입 타이밍 · 헤지 건전성</span>", unsafe_allow_html=True)
            s, cur, fl = rp["series"], rp["current"], rp["flags"]
            fig_r = go.Figure()                          # noqa: F821
            fig_r.add_trace(go.Scatter(x=s["date"], y=s["log_ratio"], name="log비율",  # noqa: F821
                                       line=dict(color="#4f8eff", width=2)))
            fig_r.add_trace(go.Scatter(x=s["date"], y=s["ma20"], name="MA20",          # noqa: F821
                                       line=dict(color="#00c87a", width=1, dash="dot")))
            fig_r.add_trace(go.Scatter(x=s["date"], y=s["ma60"], name="MA60",          # noqa: F821
                                       line=dict(color="#ffaa00", width=1, dash="dot")))
            fig_r.update_layout(height=230, margin=dict(l=40, r=20, t=8, b=30),
                                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#0a0d1a",
                                font=dict(color="#dde3f8", size=10),
                                legend=dict(orientation="h", y=1.12, font=dict(size=9)),
                                xaxis=dict(gridcolor="#1c2038", color="#546080", tickfont=dict(size=9)),
                                yaxis=dict(gridcolor="#1c2038", color="#546080", tickfont=dict(size=9)))
            st.plotly_chart(fig_r, use_container_width=True, config={"displayModeBar": False})  # noqa: F821

            z = cur["zscore"]
            z_col = "#ff4060" if (isinstance(z, (int, float)) and z >= 2) else (
                    "#00c87a" if (isinstance(z, (int, float)) and z <= -2) else "#dde3f8")
            m = st.columns(5)                            # noqa: F821
            for col, lbl, val, c in [
                (m[0], "z-score", _v(z), z_col),
                (m[1], "롤링상관", _v(cur["roll_corr"]), "#00c87a" if fl["corr_ok"] else "#ff4060"),
                (m[2], "추세기울기", _v(cur["slope60"], nd=4), "#dde3f8"),
                (m[3], "반감기(일)", _v(cur["half_life"], nd=1), "#dde3f8"),
                (m[4], "헤지베타", _v(cur["roll_beta"]), "#dde3f8"),
            ]:
                with col:
                    st.markdown(f"<div style='text-align:center'><div style='font-size:0.62rem;"  # noqa: F821
                                f"color:#546080'>{lbl}</div><div style='font-size:1rem;font-weight:800;"
                                f"color:{c}'>{val}</div></div>", unsafe_allow_html=True)
            corr_txt = "상관 양호" if fl["corr_ok"] else "⚠ 상관 약화(페어 논리 주의)"
            corr_c = "#00c87a" if fl["corr_ok"] else "#ff4060"
            st.markdown(f"<div style='margin-top:8px;font-size:0.78rem'>"   # noqa: F821
                        f"<span style='color:{corr_c}'>{corr_txt}</span> &nbsp;·&nbsp; "
                        f"<span style='color:#8899bb'>{fl['z_state']}</span> &nbsp;·&nbsp; "
                        f"<span style='color:#8899bb'>{fl['trend_state']}</span></div>",
                        unsafe_allow_html=True)

        st.write("")                                     # noqa: F821
        # ── 레그별 기술 확인(발산) 패널 ──
        with st.container(border=True):                  # noqa: F821
            ds, flag = tp["divergence_score"], tp["flag"]
            ds_col = ("#00c87a" if (isinstance(ds, (int, float)) and ds >= 40) else
                      "#ff4060" if (isinstance(ds, (int, float)) and ds <= -40) else "#ffaa00")
            flag_col = ("#00c87a" if flag == "이상적 발산" else
                        "#ffaa00" if flag.startswith("페어 약함") else "#8899bb")
            st.markdown(f"<div style='display:flex;align-items:center;justify-content:space-between'>"  # noqa: F821
                        f"<span style='font-weight:700'>🔬 레그별 기술 확인</span>"
                        f"<span style='font-size:0.95rem'>발산 점수 "
                        f"<b style='color:{ds_col};font-size:1.25rem'>{_v(ds, nd=0)}</b> &nbsp;"
                        f"<b style='color:{flag_col}'>{flag}</b></span></div>", unsafe_allow_html=True)

            def _leg_card(col, title, leg, tcolor):
                with col:
                    st.markdown(f"<div style='font-size:0.72rem;color:{tcolor};letter-spacing:1px;"  # noqa: F821
                                f"margin-bottom:6px'>{title}</div>", unsafe_allow_html=True)
                    rows = [("이격도(20일)", _v(leg["disparity20"], nd=1)), ("이동평균 배열", leg["ma_stack"]),
                            ("MACD", leg["macd_state"]), ("RSI(14)", _v(leg["rsi14"], nd=1)),
                            ("거래대금추세", _v(leg["vol_trend"]))]
                    body = "".join(
                        f"<div style='display:flex;justify-content:space-between;font-size:0.8rem;"
                        f"padding:3px 0;border-bottom:1px solid #14182c'><span style='color:#546080'>{k}</span>"
                        f"<span style='color:#dde3f8;font-weight:600'>{v}</span></div>" for k, v in rows)
                    st.markdown(body, unsafe_allow_html=True)   # noqa: F821

            t1, t2 = st.columns(2, gap="medium")          # noqa: F821
            _leg_card(t1, f"LONG · {long_co['n']}", tp["long"], "#00c87a")    # noqa: F821
            _leg_card(t2, f"SHORT · {short_co['n']}", tp["short"], "#ff4060")  # noqa: F821
            st.caption("좋은 페어 = 롱 강(정배열·골든·유입) / 숏 약(역배열·데드·무거래). "  # noqa: F821
                       "둘 다 같은 방향이면 발산 0 근처 → 페어 약함. (일봉 120일이면 정/역배열 산출)")

        st.write("")                                     # noqa: F821
        # ── 스프레드 룰(±2σ 진입/0.5σ 청산) 백테스트 요약 ──
        with st.container(border=True):                  # noqa: F821
            st.markdown("**🧪 스프레드 룰 백테스트**  <span style='font-size:0.72rem;color:#546080'>"  # noqa: F821
                        "±2σ 진입 · |z|≤0.5 청산 · lookback 60일 (log 스프레드 기준)</span>",
                        unsafe_allow_html=True)
            bt = backtest_spread(_dfl, _dfs, entry=2.0, exit=0.5, lookback=60)  # noqa: F821
            if bt["trades"] == 0:
                st.caption("청산까지 완료된 회귀 트레이드가 없습니다(발산 지속 또는 데이터 부족).")  # noqa: F821
            else:
                wr = bt["win_rate"]
                wr_col = "#00c87a" if (wr or 0) >= 55 else ("#ff4060" if (wr or 0) < 45 else "#ffaa00")
                bcols = st.columns(5)                    # noqa: F821
                for col, lbl, val, c in [
                    (bcols[0], "트레이드",   f"{bt['trades']}회", "#dde3f8"),
                    (bcols[1], "승률",       f"{wr:.0f}%", wr_col),
                    (bcols[2], "평균보유",   f"{bt['avg_hold']:.0f}일", "#dde3f8"),
                    (bcols[3], "평균손익",   f"{bt['avg_pnl']:+.3f}", "#00c87a" if bt['avg_pnl'] > 0 else "#ff4060"),
                    (bcols[4], "MDD(log)",   f"{bt['mdd']:.3f}", "#ff4060"),
                ]:
                    with col:
                        st.markdown(f"<div style='text-align:center'><div style='font-size:0.62rem;"  # noqa: F821
                                    f"color:#546080'>{lbl}</div><div style='font-size:1.05rem;"
                                    f"font-weight:800;color:{c}'>{val}</div></div>", unsafe_allow_html=True)
                st.caption("과거 회귀 성향의 통계적 참고치일 뿐, 미래 수익을 보장하지 않습니다. "  # noqa: F821
                           "손익·MDD는 log 스프레드 단위(수수료·차입비용 제외).")
