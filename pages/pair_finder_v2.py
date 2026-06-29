import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import plotly.graph_objects as go

from data.dashboard_data import SECTORS, CO, seed_rand, gen_spread
from data.scorer import score_all_stocks, get_stock_detail
from ui.sidebar import render_sidebar

# NOTE: st.navigation 앱에서는 페이지 설정을 app.py가 담당 → 여기선 set_page_config 호출 안 함.
render_sidebar()

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


# ── 숏 후보 계산: 같은 섹터, 다른 티커, eps_score 낮은 순 ─────────────────────
def _build_short_candidates(lt: str) -> list[dict]:
    """같은 섹터의 나머지 종목을 eps_score 낮은 순(숏 최선 우선)으로 반환."""
    long_sec = long_co.get("secId", "")

    same_sec_tickers: list[str] = []
    for sec in SECTORS:
        if sec["id"] == long_sec:
            same_sec_tickers = [c["t"] for c in sec["cos"] if c["t"] != lt]
            break

    candidates = []
    for pt in same_sec_tickers:
        pc = CO.get(pt)
        if not pc:
            continue

        short_eps   = None
        short_conf  = None
        short_flags = ""
        if _has_scores and _score_df is not None:
            _srow = _score_df[_score_df["ticker"] == pt]
            if not _srow.empty:
                short_eps   = float(_srow.iloc[0]["eps_score"])
                short_conf  = float(_srow.iloc[0]["confidence"])
                short_flags = str(_srow.iloc[0].get("flags", ""))

        pair_score = (
            round(_long_eps - short_eps, 1)
            if (_long_eps is not None and short_eps is not None) else None
        )

        sprd  = gen_spread(int(pt) % 500 + int(lt) % 500 + 3)
        r     = seed_rand(int(pt) % 1000 + int(lt) % 1000 + 7)
        cor   = round(62 + r() * 33)
        ind   = round(75 + r() * 25)
        prd   = round(55 + r() * 40)
        rev_s = round(48 + r() * 47)

        candidates.append({
            "t":           pt,
            "co":          pc,
            "short_eps":   short_eps,
            "short_conf":  short_conf,
            "short_flags": short_flags,
            "pair_score":  pair_score,
            "spread":      sprd,
            "cor":         cor,
            "ind":         ind,
            "prd":         prd,
            "rev_s":       rev_s,
        })

    # eps_score 낮은 순 정렬 (숏 최선 = 가장 부진한 종목)
    candidates.sort(
        key=lambda x: x["short_eps"] if x["short_eps"] is not None else 9999
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

            # 헤더
            _h = st.columns([0.4, 3.2, 1.8, 2, 1.6, 1.2])
            for col, lbl in zip(_h, ["#", "종목", "EPS점수", "페어차이", "신뢰도", ""]):
                with col:
                    st.markdown(
                        f"<div style='font-size:0.65rem;color:#546080'>{lbl}</div>",
                        unsafe_allow_html=True,
                    )
            st.markdown(
                "<hr style='margin:4px 0 6px;border:none;border-top:1px solid #1c2038'>",
                unsafe_allow_html=True,
            )

            def _render_pair_row(idx: int, pair: dict) -> None:
                pc     = pair["co"]
                is_sel = st.session_state.get(sel_key) == pair["t"]
                bg     = "rgba(255,64,96,.08)" if is_sel else "transparent"

                se     = pair["short_eps"]
                se_col = "#00c87a" if (se or 0) >= 20 else (
                         "#ff4060" if (se or 0) <= -20 else "#ffaa00")
                se_str = f"{se:+.0f}" if se is not None else "—"

                ps     = pair["pair_score"]
                ps_col = "#00c87a" if (ps or 0) > 10 else (
                         "#ff4060" if (ps or 0) < -10 else "#ffaa00")
                ps_str = (f"+{ps:.0f}" if (ps is not None and ps >= 0)
                          else (f"{ps:.0f}" if ps is not None else "—"))

                cf_str  = f"{pair['short_conf']:.2f}" if pair["short_conf"] is not None else "—"
                fl_icon = "⚠" if pair["short_flags"] else ""

                row = st.columns([0.4, 3.2, 1.8, 2, 1.6, 1.2])
                with row[0]:
                    st.markdown(
                        f"<div style='font-size:1rem;font-weight:800;"
                        f"color:#ff4060;padding-top:10px'>{idx+1}</div>",
                        unsafe_allow_html=True,
                    )
                with row[1]:
                    st.markdown(
                        f"<div style='background:{bg};border-radius:5px;padding:7px 6px'>"
                        f"<div style='font-size:0.88rem;font-weight:700'>{pc['n']}</div>"
                        f"<div style='font-size:0.68rem;color:#546080'>{pc['t']}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                with row[2]:
                    st.markdown(
                        f"<div style='padding-top:8px;font-size:1.05rem;"
                        f"font-weight:800;color:{se_col}'>{se_str}</div>",
                        unsafe_allow_html=True,
                    )
                with row[3]:
                    st.markdown(
                        f"<div style='padding-top:8px;font-size:1.05rem;"
                        f"font-weight:800;color:{ps_col}'>{ps_str}</div>",
                        unsafe_allow_html=True,
                    )
                with row[4]:
                    st.markdown(
                        f"<div style='padding-top:8px;font-size:0.85rem;"
                        f"color:#8899bb'>{cf_str} {fl_icon}</div>",
                        unsafe_allow_html=True,
                    )
                with row[5]:
                    if st.button(
                        "✓" if is_sel else "선택",
                        key=f"pick_{long_ticker}_{pair['t']}",
                        use_container_width=True,
                        type="primary" if is_sel else "secondary",
                    ):
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
    ps       = sel_pair["pair_score"]
    se_str   = f"{se:+.0f}" if se is not None else "—"
    ps_str   = (f"+{ps:.0f}" if (ps is not None and ps >= 0)
                else (f"{ps:.0f}" if ps is not None else "—"))
    ps_color = "#00c87a" if (ps or 0) > 10 else ("#ff4060" if (ps or 0) < -10 else "#ffaa00")
    long_eps_disp = f"{_long_eps:+.0f}" if _long_eps is not None else "—"

    # 배너
    st.markdown(
        f"<div style='background:#0f1220;border:1px solid #1c2038;border-radius:10px;"
        f"padding:14px 24px;display:flex;align-items:center;"
        f"justify-content:space-between;margin-bottom:16px'>"
        f"<div style='font-size:0.9rem;color:#8899bb'>"
        f"<b style='color:#dde3f8'>{long_co['n']}</b> "
        f"<span style='font-size:0.78rem'>(EPS {long_eps_disp})</span>"
        f" &nbsp;LONG / SHORT&nbsp; "
        f"<b style='color:#dde3f8'>{short_co['n']}</b> "
        f"<span style='font-size:0.78rem'>(EPS {se_str})</span></div>"
        f"<div style='font-size:1.5rem;font-weight:800;color:{ps_color}'>"
        f"페어 점수차 &nbsp; {ps_str}</div></div>",
        unsafe_allow_html=True,
    )

    dc1, dc2 = st.columns(2, gap="medium")

    with dc1:
        with st.container(border=True):
            st.markdown(
                "**페어 요인 분석**  "
                "<span style='font-size:0.72rem;color:#546080'>"
                "seed 기반 — 실제 데이터 연결 전 참고용</span>",
                unsafe_allow_html=True,
            )
            factors = [
                ("주가 상관관계", sel_pair["cor"],   "#4f8eff"),
                ("동일 업종",     sel_pair["ind"],   "#00c87a"),
                ("유사 제품군",   sel_pair["prd"],   "#ffaa00"),
                ("매출 역방향성", sel_pair["rev_s"], "#ff6b3d"),
            ]
            for label, val, fc in factors:
                pct = min(100, val)
                st.markdown(
                    f"<div style='margin-bottom:14px'>"
                    f"<div style='display:flex;justify-content:space-between;"
                    f"font-size:0.82rem;margin-bottom:6px'>"
                    f"<span style='color:#8899bb'>{label}</span>"
                    f"<span style='font-weight:700;color:{fc}'>{val}점</span></div>"
                    f"<div style='height:6px;background:#1c2038;border-radius:3px'>"
                    f"<div style='width:{pct}%;height:100%;background:{fc};"
                    f"border-radius:3px'></div></div></div>",
                    unsafe_allow_html=True,
                )

            br = short_co["br"]
            br_color  = "#ff4060" if br > 2.5 else "#dde3f8"
            warn_html = (" <span style='font-size:0.7rem;color:#ff4060'>⚠ 비용 높음</span>"
                         if br > 2.5 else "")
            st.markdown(
                "<div style='border-top:1px solid #1c2038;padding-top:10px'>"
                f"<div style='display:flex;justify-content:space-between;"
                f"align-items:center;padding:6px 0'>"
                f"<span style='font-size:0.82rem;color:#8899bb'>숏 차입 비용 (연)</span>"
                f"<span style='font-size:1rem;font-weight:700;color:{br_color}'>"
                f"{br}%{warn_html}</span></div></div>",
                unsafe_allow_html=True,
            )
            if br > 2.5:
                st.warning(f"⚠ 차입비용 {br}% — 페어 비용이 높아 수익성 잠식 가능")
            if sel_pair["short_flags"]:
                st.markdown(
                    f"<div style='margin-top:8px;font-size:0.75rem;color:#ffaa00;"
                    f"background:rgba(255,170,0,.08);padding:6px 10px;border-radius:6px'>"
                    f"⚠ {sel_pair['short_flags']}</div>",
                    unsafe_allow_html=True,
                )

    with dc2:
        with st.container(border=True):
            sprd       = sel_pair["spread"]
            last_sprd  = sprd[-1]["spread"] if sprd else 0
            sign_s     = "+" if last_sprd > 0 else ""
            sprd_color = "#00c87a" if last_sprd > 0 else "#ff4060"

            st.markdown(
                f"**페어 스프레드 추이 (누적 상대수익률 %)**<br>"
                f"<span style='font-size:0.75rem;color:#546080'>"
                f"양수 = {long_co['n']} 우위 &nbsp;·&nbsp; 음수 = {short_co['n']} 우위"
                f"</span>",
                unsafe_allow_html=True,
            )
            fig_s = go.Figure()
            fig_s.add_trace(go.Scatter(
                x=[d["m"] for d in sprd],
                y=[d["spread"] for d in sprd],
                mode="lines",
                line=dict(color="#4f8eff", width=2),
                fill="tozeroy",
                fillcolor="rgba(79,142,255,0.12)",
            ))
            fig_s.add_hline(y=0, line_dash="dash", line_color="#546080", line_width=1)
            fig_s.update_layout(
                height=210,
                margin=dict(l=40, r=20, t=10, b=36),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="#0a0d1a",
                font=dict(color="#dde3f8", size=10),
                showlegend=False,
                xaxis=dict(gridcolor="#1c2038", color="#546080", tickfont=dict(size=9)),
                yaxis=dict(gridcolor="#1c2038", color="#546080",
                           tickfont=dict(size=9), ticksuffix="%"),
            )
            st.plotly_chart(fig_s, use_container_width=True, config={"displayModeBar": False})
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;"
                f"font-size:0.82rem;margin-top:8px'>"
                f"<span style='color:#546080'>현재 스프레드</span>"
                f"<span style='font-weight:700;color:{sprd_color}'>"
                f"{sign_s}{last_sprd}%</span></div>",
                unsafe_allow_html=True,
            )

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
