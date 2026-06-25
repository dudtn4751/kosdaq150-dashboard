"""롱숏 알파 스코어 — 종목 검색 → 스코어 + 근거 자료.

종목을 검색하면 종합 L-S 점수 + 판정, 그 아래에 팩터별 근거(EPS 리비전·상대강도·이벤트)와
원천 데이터(컨센서스·증권사 리포트·ETF 매수압력)를 제시. 하단에 페어·전체 랭킹 참고.
데이터: data/alpha.json (+ consensus·research·etf_flow), scripts/update_alpha.py, 매일 05:00 KST.
"""

import json
import os
import sys
from pathlib import Path

import streamlit as st
import plotly.graph_objects as go

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from style import COLORS, now_kst  # noqa: E402


def spark_fig(values, color, area=False, bars=False):
    """미니 차트 (가격=라인, 거래대금=막대)."""
    fig = go.Figure()
    x = list(range(len(values)))
    if bars:
        fig.add_trace(go.Bar(x=x, y=values, marker_color=color, marker_line_width=0))
    else:
        fig.add_trace(go.Scatter(x=x, y=values, mode="lines", line=dict(color=color, width=2),
                                 fill="tozeroy" if area else None,
                                 fillcolor="rgba(224,53,43,0.07)" if area else None))
    fig.update_layout(height=110, margin=dict(l=4, r=4, t=4, b=4),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis=dict(visible=False), showlegend=False, hovermode=False,
                      yaxis=dict(showgrid=True, gridcolor="rgba(0,0,0,0.06)", showticklabels=False, zeroline=False))
    return fig

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


def sec_header(en, ko):
    st.markdown(
        f'<div style="margin:6px 0 10px;">'
        f'<div style="color:{ACC}; font-size:0.72rem; font-weight:700; letter-spacing:0.14em;">{en}</div>'
        f'<div style="color:#0B0F14; font-size:1.4rem; font-weight:800; letter-spacing:-0.02em;">{ko}</div></div>',
        unsafe_allow_html=True)


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


sec_header("LONG-SHORT ALPHA", "롱숏 알파 스코어")
alpha = _load("alpha.json")
if not alpha or not alpha.get("ranked"):
    st.warning("알파 데이터가 없습니다. `python3 scripts/update_alpha.py` 실행이 필요합니다.")
    st.stop()

ranked = alpha["ranked"]
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

st.markdown(
    f'<div style="color:{MUT}; font-size:0.86rem; font-weight:600; margin-bottom:10px;">'
    f'기준일 <b style="color:#16202E;">{alpha.get("date","-")}</b> · 유니버스 {N}종목 · 커버리지 '
    f'<b style="color:{ACC};">{cov}%</b> (활성: EPS Revision·상대강도·이벤트 / 대기: 대체데이터·퀄리티)</div>',
    unsafe_allow_html=True)

# ── 종목 검색 ──
sel_name = st.selectbox("종목 검색 (이름 입력)", [""] + [s["name"] for s in ranked],
                        index=0, placeholder="종목명을 입력하세요 (예: 삼성전자)")
if not sel_name:
    st.info("종목을 검색하면 종합 점수와 근거 자료가 표시됩니다. (아래 페어·랭킹은 참고용)")
else:
    s = by_name[sel_name]
    score = s["score"]
    verdict, vcolor = ("롱 후보", UP) if score >= 20 else (("숏 후보", DOWN) if score <= -20 else ("중립", MUT))

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
            st.markdown('<div style="padding-top:8px;">'
                        + factor_bar("EPS", s["eps"]) + factor_bar("상대강도", s["rs"]) + factor_bar("이벤트", s["event"])
                        + f'<div style="color:{MUT}; font-size:0.76rem; margin-top:6px;">종합 = '
                        f'EPS×30 + 상대강도×15 + 이벤트×10 (가용 비중 재정규화)</div></div>',
                        unsafe_allow_html=True)

    # ── 차트 · 수급 시각화 ──
    spark, amt = s.get("spark") or [], s.get("amt_spark") or []
    if spark or amt:
        ch1, ch2 = st.columns(2)
        with ch1:
            with st.container(border=True):
                pc = UP if (len(spark) > 1 and spark[-1] >= spark[0]) else DOWN
                st.markdown(f'<div style="font-weight:700; color:#16202E; font-size:0.92rem;">가격 추이 (60일)</div>',
                            unsafe_allow_html=True)
                if spark:
                    st.plotly_chart(spark_fig(spark, pc, area=True), use_container_width=True,
                                    config={"displayModeBar": False}, key="px")
        with ch2:
            with st.container(border=True):
                st.markdown(f'<div style="font-weight:700; color:#16202E; font-size:0.92rem;">거래대금 추이 (60일, 억)</div>',
                            unsafe_allow_html=True)
                if amt:
                    st.plotly_chart(spark_fig(amt, ACC, bars=True), use_container_width=True,
                                    config={"displayModeBar": False}, key="amt")
                else:
                    st.caption("거래대금 데이터 없음")

    # ── 근거 자료 ──
    sec_header("EVIDENCE", "근거 자료")

    # 1) EPS Revision 근거
    with st.container(border=True):
        c = consensus.get(s["code"], {})
        rev, yoy, op = s.get("rev_3m"), s.get("yoy"), c.get("op_est")
        st.markdown(f'<div style="font-weight:800; color:#16202E; font-size:1.02rem;">① EPS Revision '
                    f'<span style="color:{sc(s["eps"])}; font-size:0.9rem;">{s["eps"]:+.0f}점</span></div>',
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
        st.caption("EPS/영업이익 컨센서스 상향·리포트 목표주가 상향 = 롱 근거 (메인 아이디어).")

    # 2) 상대강도 근거
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
        st.caption("RS = 종목 20일 수익률 − 업종 평균. 업종 대비 우위(+) = 시장이 인정하는 방향 → 롱, 열위(−) → 숏.")

    # 3) 이벤트 근거
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

    # 추천 페어 (상관 기반 헤지 — 상관 × 점수 스프레드)
    cp = s.get("pair")
    with st.container(border=True):
        sec_header("PAIR", "추천 페어 (상관 헤지)")
        if not cp:
            st.caption("적합한 상관 페어 없음 (헤지 가능 상관 0.3↑ + 반대 점수 필요).")
        else:
            my_side = "롱" if score >= 0 else "숏"
            cp_side = "숏" if score >= 0 else "롱"
            ms, cs = (s["name"], cp["name"]) if score >= 0 else (cp["name"], s["name"])
            msc, csc = (score, cp["score"]) if score >= 0 else (cp["score"], score)
            st.markdown(
                f'<div style="font-size:1.0rem; color:#16202E; line-height:1.7;">'
                f'<span style="color:{UP}; font-weight:800;">롱 {ms}</span> '
                f'<span style="color:{sc(msc)};">({msc:+.0f})</span> ↔ '
                f'<span style="color:{DOWN}; font-weight:800;">숏 {cs}</span> '
                f'<span style="color:{sc(csc)};">({csc:+.0f})</span></div>'
                f'<div style="display:flex; gap:20px; margin-top:6px; font-size:0.9rem; color:#16202E;">'
                f'<span>상관(헤지) <b style="color:{ACC};">{cp["corr"]:.2f}</b></span>'
                f'<span>점수 스프레드 <b style="color:{ACC};">{cp["spread"]:.0f}</b></span>'
                f'<span>{"동일 섹터" if cp.get("same_sector") else "교차 섹터"}</span></div>',
                unsafe_allow_html=True)
            st.caption("상관이 높을수록 시장/섹터 베타가 상쇄(헤지)되고, 점수 스프레드가 클수록 알파 기대 ↑. "
                       f"{s['name']}을(를) {my_side}, {cp['name']}을(를) {cp_side}으로.")

st.divider()
# ── 참고: 페어·랭킹 ──
with st.expander("참고 — 섹터 중립 페어 / 롱·숏 후보 랭킹", expanded=not sel_name):
    pairs = alpha.get("pairs") or []
    if pairs:
        st.markdown("**상관 헤지 페어 (품질 = 상관 × 스프레드 순)**")
        for p in pairs[:12]:
            st.markdown(f'<div style="font-size:0.88rem; padding:2px 0;">'
                        f'L <b>{p["long"]["name"]}</b>({p["long"]["score"]:+.0f}) ↔ '
                        f'S <b>{p["short"]["name"]}</b>({p["short"]["score"]:+.0f}) · '
                        f'상관 {p["corr"]:.2f} · 스프레드 {p["spread"]:.0f} '
                        f'<span style="color:{MUT};">{"동일섹터" if p.get("same_sector") else "교차"}</span></div>',
                        unsafe_allow_html=True)
    cc1, cc2 = st.columns(2)
    cc1.markdown("**롱 후보** " + " · ".join(f'{x["name"]}({x["score"]:+.0f})' for x in alpha.get("longs", [])[:10]))
    cc2.markdown("**숏 후보** " + " · ".join(f'{x["name"]}({x["score"]:+.0f})' for x in alpha.get("shorts", [])[:10]))

with st.expander("리스크 관리 규칙 (문서 기준 가이드)"):
    st.markdown("""
**노출**: Gross 100→150% / Net ±5~10% / 단일종목 8%
**MDD(-3% 목표)**: 2일 −100bp→Gross−20% / 3일 −150bp→−30% / 4일 −200bp→−50%
**Loss-cut**: 숏 −10/−15/−20%→20/50/70% · 롱 −15/−20/−25%→30/50/70% (페어 동반)
**Thesis Break**: 롱 EPS 하향전환·숏 대형수주 등 논리 훼손 시 손실률 무관 청산
""")

st.caption(f"멀티팩터 알파(1단계) · 화면 로드 {now_kst()} (KST) · 매일 05:00 KST 자동 갱신")
