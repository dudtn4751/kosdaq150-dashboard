"""롱숏 알파 스코어 — 멀티팩터 L-S 점수 + 섹터 중립 페어 + 리스크 규칙.

1단계: EPS Revision(30) + 상대강도(15) + 이벤트(10) 통합. (대체데이터·퀄리티는 소스 확보 후)
데이터: data/alpha.json (scripts/update_alpha.py, 매일 05:00 KST).
"""

import json
import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from style import COLORS, now_kst  # noqa: E402

DATA = Path(__file__).parent.parent / "data"
UP, DOWN, MUT, ACC = COLORS["kr_up"], COLORS["kr_down"], COLORS["text_muted"], COLORS["accent"]


@st.cache_data(ttl=3600, show_spinner=False)
def load_alpha():
    p = DATA / "alpha.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def jo(eok):
    if not eok:
        return "—"
    return f"{eok/1e12:,.1f}조" if abs(eok) >= 1e12 else f"{eok/1e8:,.0f}억"


def sec_header(en, ko):
    st.markdown(
        f'<div style="margin:6px 0 12px;">'
        f'<div style="color:{ACC}; font-size:0.72rem; font-weight:700; letter-spacing:0.14em;">{en}</div>'
        f'<div style="color:#0B0F14; font-size:1.4rem; font-weight:800; letter-spacing:-0.02em;">{ko}</div></div>',
        unsafe_allow_html=True)


def score_color(v):
    return UP if v > 0 else (DOWN if v < 0 else MUT)


def factor_bar(label, v):
    """서브스코어 미니 바 (-100~+100), 중앙 기준 좌(파랑)/우(빨강)."""
    w = min(abs(v), 100) / 2  # 0~50% (반폭)
    side = "left:50%;" if v >= 0 else f"right:50%;"
    c = score_color(v)
    return (f'<div style="display:flex; align-items:center; gap:6px; margin:1px 0;">'
            f'<span style="width:34px; color:{MUT}; font-size:0.72rem; font-weight:700;">{label}</span>'
            f'<div style="flex:1; position:relative; height:8px; background:{COLORS["bg_card_hover"]}; border-radius:4px;">'
            f'<div style="position:absolute; {side} width:{w}%; height:100%; background:{c}; border-radius:4px;"></div>'
            f'<div style="position:absolute; left:50%; top:-1px; width:1px; height:10px; background:{COLORS["border"]};"></div></div>'
            f'<span style="width:34px; text-align:right; color:{c}; font-size:0.74rem; font-weight:800;">{v:+.0f}</span></div>')


sec_header("LONG-SHORT ALPHA", "롱숏 알파 스코어")
data = load_alpha()
if not data:
    st.warning("알파 데이터가 없습니다. `python3 scripts/update_alpha.py` 실행이 필요합니다.")
    st.stop()

cov = data.get("coverage_pct", 0)
st.markdown(
    f'<div style="color:{MUT}; font-size:0.88rem; font-weight:600; margin-bottom:4px;">'
    f'기준일 <b style="color:#16202E;">{data.get("date","-")}</b> · 유니버스 <b style="color:#16202E;">{data.get("universe",0)}</b>종목 · '
    f'커버리지 <b style="color:{ACC};">{cov}%</b></div>'
    f'<div style="color:{MUT}; font-size:0.8rem; margin-bottom:10px;">'
    f'활성 알파: EPS Revision(30) · 상대강도(15) · 이벤트(10) · '
    f'<span style="color:{MUT};">대기: 대체데이터(25)·퀄리티/저베타(20) — 소스 확보 후</span></div>',
    unsafe_allow_html=True)
if cov < 100:
    st.info(f"현재 가용 알파(EPS·상대강도·이벤트)만으로 산출, 비중 재정규화(커버리지 {cov}%). "
            "대체데이터(수출 등)·퀄리티 추가 시 점수가 정교해집니다.")

# ── 섹터 중립 페어 (메인 출력) ──
with st.container(border=True):
    sec_header("MARKET-NEUTRAL PAIRS", "섹터 중립 롱숏 페어")
    pairs = data.get("pairs") or []
    if not pairs:
        st.caption("유의미한 스프레드의 섹터 페어 없음")
    else:
        head = (f'<tr style="border-bottom:2px solid {COLORS["border"]}; color:{MUT}; font-size:0.82rem; font-weight:700;">'
                f'<th style="text-align:left; padding:8px 10px;">섹터</th>'
                f'<th style="text-align:left; color:{UP};">롱 (고점수)</th>'
                f'<th style="text-align:left; color:{DOWN};">숏 (저점수)</th>'
                f'<th style="text-align:right; padding-right:10px;">스프레드</th></tr>')
        trs = ""
        for p in pairs:
            trs += (f'<tr style="border-bottom:1px solid {COLORS["border"]}; font-size:0.92rem;">'
                    f'<td style="padding:8px 10px; color:{MUT}; font-weight:600;">{p["sector"]}</td>'
                    f'<td><b style="color:#16202E; font-weight:800;">{p["long"]["name"]}</b> '
                    f'<span style="color:{UP}; font-weight:700;">{p["long"]["score"]:+.0f}</span></td>'
                    f'<td><b style="color:#16202E; font-weight:800;">{p["short"]["name"]}</b> '
                    f'<span style="color:{DOWN}; font-weight:700;">{p["short"]["score"]:+.0f}</span></td>'
                    f'<td style="text-align:right; color:{ACC}; font-weight:800; padding-right:10px;">{p["spread"]:.0f}</td></tr>')
        st.markdown(f'<table style="width:100%; border-collapse:collapse; border:none;">{head}{trs}</table>',
                    unsafe_allow_html=True)
        st.caption("같은 섹터 내 최고점수(롱) ↔ 최저점수(숏) → 시장중립 페어. 스프레드가 클수록 알파 기대 ↑. "
                   "EPS 스프레드(메인 아이디어) + 상대강도 + 이벤트 종합.")

# ── 롱 / 숏 후보 (팩터 분해) ──
c1, c2 = st.columns(2)
for col, key, title, hc in [(c1, "longs", "롱 후보 (고점수)", UP), (c2, "shorts", "숏 후보 (저점수)", DOWN)]:
    with col:
        with st.container(border=True):
            st.markdown(f'<div style="color:{hc}; font-size:1.05rem; font-weight:800; margin-bottom:8px;">{title}</div>',
                        unsafe_allow_html=True)
            for s in (data.get(key) or [])[:12]:
                ev_tag = ""
                if s.get("index_event") == "add":
                    ev_tag = f' <span style="color:{UP}; font-size:0.7rem; font-weight:800;">편입</span>'
                elif s.get("index_event") == "remove":
                    ev_tag = f' <span style="color:{DOWN}; font-size:0.7rem; font-weight:800;">편출</span>'
                tp_tag = ""
                if s.get("tp") == "up":
                    tp_tag = f' <span style="color:{UP}; font-size:0.7rem;">TP↑</span>'
                elif s.get("tp") == "down":
                    tp_tag = f' <span style="color:{DOWN}; font-size:0.7rem;">TP↓</span>'
                st.markdown(
                    f'<div style="padding:7px 0; border-bottom:1px solid {COLORS["border"]};">'
                    f'<div style="display:flex; justify-content:space-between; align-items:baseline;">'
                    f'<span><b style="color:#16202E; font-size:0.96rem;">{s["name"]}</b>'
                    f'<span style="color:{MUT}; font-size:0.74rem;"> {s["sector"]}</span>{ev_tag}{tp_tag}</span>'
                    f'<b style="color:{score_color(s["score"])}; font-size:1.05rem;">{s["score"]:+.0f}</b></div>'
                    + factor_bar("EPS", s["eps"]) + factor_bar("RS", s["rs"]) + factor_bar("이벤트", s["event"])
                    + '</div>', unsafe_allow_html=True)

# ── 전체 랭킹 ──
with st.container(border=True):
    sec_header("FULL RANKING", "전체 종합 점수 랭킹")
    ranked = data.get("ranked") or []
    head = (f'<tr style="border-bottom:2px solid {COLORS["border"]}; color:{MUT}; font-size:0.8rem; font-weight:700;">'
            f'<th style="text-align:left; padding:6px 8px;">#</th><th style="text-align:left;">종목</th>'
            f'<th style="text-align:right;">종합</th><th style="text-align:right;">EPS</th>'
            f'<th style="text-align:right;">RS</th><th style="text-align:right;">이벤트</th>'
            f'<th style="text-align:right;">3M리비전</th><th style="text-align:right; padding-right:8px;">20일RS</th></tr>')
    trs = ""
    for i, s in enumerate(ranked[:60], 1):
        def cell(v, suf="", w=False):
            if v is None:
                return f'<td style="text-align:right; color:{MUT};">—</td>'
            return f'<td style="text-align:right; color:{score_color(v)}; font-weight:{"800" if w else "600"};">{v:+.0f}{suf}</td>'
        trs += (f'<tr style="border-bottom:1px solid {COLORS["border"]}; font-size:0.88rem;">'
                f'<td style="padding:6px 8px; color:{MUT};">{i}</td>'
                f'<td><b style="color:#16202E; font-weight:700;">{s["name"]}</b>'
                f'<span style="color:{MUT}; font-size:0.72rem;"> {s["sector"]}</span></td>'
                + cell(s["score"], w=True) + cell(s["eps"]) + cell(s["rs"]) + cell(s["event"])
                + cell(s.get("rev_3m"), "%") + cell(s.get("rs_20"), "%") + "</tr>")
    st.markdown(f'<table style="width:100%; border-collapse:collapse; border:none;">{head}{trs}</table>',
                unsafe_allow_html=True)

# ── 리스크 규칙 가이드 (A) ──
with st.expander("리스크 관리 규칙 (문서 기준 · 포지션 운용 가이드)"):
    st.markdown(f"""
**노출 한도** — Gross 초기 ~100%(E 60–80%)·안정화 ~150%(E 100–120%) / Net 평상 ~5%·국면 ~10% / 단일종목 ~5%(취득)·~8%(평가)

**MDD 관리 (목표 −3% 이내)**
- 2일 누적 −100bp(1/3 소진): Gross −20%, Net ≤5%
- 3일 누적 −150bp(1/2): Gross −30%, Net ≤3%
- 4일 누적 −200bp(2/3): Gross −50%, Net ~0%

**종목 Loss-cut** (숏 우선 — 스퀴즈 리스크)
- 숏 −10%/−15%/−20% → 20%/50%/70% 컷 (롱 페어 동반)
- 롱 −15%/−20%/−25% → 30%/50%/70% 컷 (숏 페어 동반)

**페어 P&L** — NAV −25bp/−35bp/−50bp → 30%/50%/청산
**Thesis Break** — 롱 EPS 리비전 하향 전환·숏 대형 수주 등 논리 훼손 시 손실률 무관 축소/청산
""")
    st.caption("현재는 신호·규칙 가이드(A) 단계. 라이브 포지션 북 연동(B) 시 자동 컷 신호로 확장 가능.")

st.caption(f"멀티팩터 알파(1단계) · 화면 로드 {now_kst()} (KST) · 매일 05:00 KST 자동 갱신")
