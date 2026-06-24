"""ETF 수급 전략 — 신규 상장 / 패시브 리밸런싱 / 액티브 리밸런싱.

① 신규 상장: ETF AUM 추적 + TOP10 구성종목 클러스터링 매수압력 + 진입/청산 신호 (실데이터)
② 패시브 리밸런싱: 지수 정기 편입/편출 예측 + 동시호가 매매 (구조)
③ 액티브 리밸런싱: 사후 보유변화 추종 (구조)

데이터: data/etf_flow.json (scripts/update_etf_flow.py, 매일 05:00 KST).
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
def load_flow():
    p = DATA / "etf_flow.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def jo(eok):
    if eok is None:
        return "—"
    return f"{eok/1e4:,.1f}조" if abs(eok) >= 1e4 else f"{eok:,.0f}억"


def sec_header(en, ko):
    st.markdown(
        f'<div style="margin:6px 0 12px;">'
        f'<div style="color:{ACC}; font-size:0.72rem; font-weight:700; letter-spacing:0.14em;">{en}</div>'
        f'<div style="color:#0B0F14; font-size:1.4rem; font-weight:800; letter-spacing:-0.02em;">{ko}</div></div>',
        unsafe_allow_html=True)


def premise_box(html):
    st.markdown(
        f'<div style="background:rgba(21,101,192,0.05); border:1px solid {COLORS["border"]}; border-radius:10px; '
        f'padding:12px 15px; margin-bottom:14px; font-size:0.9rem; line-height:1.65; color:#16202E;">{html}</div>',
        unsafe_allow_html=True)


sec_header("ETF FLOW STRATEGY", "ETF 수급 전략")
data = load_flow()
if not data:
    st.warning("ETF 수급 데이터가 없습니다. `python3 scripts/update_etf_flow.py` 실행이 필요합니다.")
    st.stop()

st.markdown(
    f'<div style="color:{MUT}; font-size:0.88rem; font-weight:600; margin-bottom:6px;">'
    f'기준일 <b style="color:#16202E;">{data.get("date","-")}</b> · 국내 주식형 ETF '
    f'<b style="color:#16202E;">{data.get("count",0)}</b>개 · 구성종목 수집 {data.get("enriched",0)}개 · '
    f'매일 05:00 KST 자동 갱신</div>', unsafe_allow_html=True)

t1, t2, t3 = st.tabs(["① 신규 상장 수급압력", "② 패시브 리밸런싱", "③ 액티브 리밸런싱"])

# ════════════════ ① 신규 상장 수급압력 ════════════════
with t1:
    premise_box(
        "<b>전제</b> — 신규 ETF는 런칭 전 비중 확정·사전 매수 완료. "
        "이후 <b>AUM 증가에 따른 수급 확대</b>가 구성종목 주가 상승 트리거.<br>"
        "<b>전략</b> — ① AUM 급증 ETF의 구성종목 중 거래대금 대비 강한 매수압력 종목 필터 "
        "② 복수 ETF가 한 종목을 담는 <b>클러스터링</b>일수록 압력 ↑ "
        "③ <b>진입</b>: 상장 초기 AUM 증가·비중 확대 구간 / <b>청산</b>: AUM 유입 둔화 시 빠른 전환.")

    # 종목 매수 압력 (클러스터링)
    with st.container(border=True):
        sec_header("BUYING PRESSURE", "종목 매수 압력 (ETF 클러스터링)")
        pr = data.get("pressure") or []
        if not pr:
            st.caption("매수압력 데이터 없음")
        else:
            head = (f'<tr style="border-bottom:2px solid {COLORS["border"]}; color:{MUT}; font-size:0.82rem; font-weight:700;">'
                    f'<th style="text-align:left; padding:8px 10px;">#</th><th style="text-align:left;">종목</th>'
                    f'<th style="text-align:right;">ETF 매수압력</th><th style="text-align:center;">보유 ETF</th>'
                    f'<th style="text-align:center;">신규 ETF</th><th style="padding-right:10px;">주요 보유 ETF</th></tr>')
            trs = ""
            for i, p in enumerate(pr[:25], 1):
                etfs = " · ".join(f'{e["etf"]}({e["weight"]:.0f}%)' for e in p.get("top_etfs", [])[:3])
                newc = p.get("new_etf_count", 0)
                new_badge = (f'<span style="color:{UP}; font-weight:800;">{newc}</span>' if newc else
                             f'<span style="color:{MUT};">0</span>')
                trs += (
                    f'<tr style="border-bottom:1px solid {COLORS["border"]}; font-size:0.92rem;">'
                    f'<td style="text-align:left; padding:8px 10px; color:{MUT};">{i}</td>'
                    f'<td style="text-align:left;"><b style="color:#16202E; font-weight:800;">{p["name"]}</b>'
                    f'<span style="color:{MUT}; font-size:0.76rem;"> {p["code"]}</span></td>'
                    f'<td style="text-align:right; color:{UP}; font-weight:800;">{jo(p["pressure_eok"])}</td>'
                    f'<td style="text-align:center; color:#16202E; font-weight:700;">{p["etf_count"]}</td>'
                    f'<td style="text-align:center;">{new_badge}</td>'
                    f'<td style="color:{MUT}; padding-right:10px; font-size:0.82rem;">{etfs}</td></tr>')
            st.markdown(f'<table style="width:100%; border-collapse:collapse; border:none;">{head}{trs}</table>',
                        unsafe_allow_html=True)
            st.caption("매수압력 = Σ(ETF별 TOP10 비중 × 해당 ETF AUM). 보유 ETF 수가 많을수록(클러스터링) "
                       "수급 압력 집중. '신규 ETF'가 담을수록 신규 상장 수급 트리거 강함.")

    c1, c2 = st.columns(2)
    # 신규 상장 ETF
    with c1:
        with st.container(border=True):
            sec_header("NEW LISTINGS", "신규 상장 ETF")
            nl = data.get("new_listings") or []
            if nl:
                for e in nl[:12]:
                    st.markdown(
                        f'<div style="display:flex; justify-content:space-between; padding:5px 0; '
                        f'border-bottom:1px solid {COLORS["border"]}; font-size:0.9rem;">'
                        f'<b style="color:#16202E;">{e["name"]}</b>'
                        f'<span style="color:{MUT};">AUM {jo(e["aum"])}</span></div>', unsafe_allow_html=True)
            else:
                st.caption("최근 신규 상장 ETF 없음 (전일 유니버스 대비 신규 종목 자동 감지 — 매일 누적).")
    # AUM 급증 ETF
    with c2:
        with st.container(border=True):
            sec_header("AUM SURGE", "AUM 급증 ETF (전일 대비)")
            surge = [e for e in (data.get("aum_surge") or []) if e.get("aum_chg_pct")]
            if surge:
                for e in surge[:12]:
                    ch = e["aum_chg_pct"]
                    c = UP if ch > 0 else DOWN
                    st.markdown(
                        f'<div style="display:flex; justify-content:space-between; padding:5px 0; '
                        f'border-bottom:1px solid {COLORS["border"]}; font-size:0.9rem;">'
                        f'<b style="color:#16202E;">{e["name"]}</b>'
                        f'<span><span style="color:{MUT};">{jo(e["aum"])}</span> '
                        f'<span style="color:{c}; font-weight:800;">{ch:+.1f}%</span></span></div>',
                        unsafe_allow_html=True)
                st.caption("진입 후보: AUM 증가 가속 구간 / 청산 신호: 증가 둔화·감소 전환.")
            else:
                st.caption("AUM 변화는 전일 스냅샷 대비 계산 — 매일 누적되며 둘째 날부터 표시됩니다.")

    # 전체 국내 주식형 ETF AUM 랭킹
    with st.container(border=True):
        sec_header("UNIVERSE", "국내 주식형 ETF · AUM 순위")
        etfs = data.get("etfs") or []
        head = (f'<tr style="border-bottom:2px solid {COLORS["border"]}; color:{MUT}; font-size:0.82rem; font-weight:700;">'
                f'<th style="text-align:left; padding:7px 10px;">#</th><th style="text-align:left;">ETF</th>'
                f'<th style="text-align:right;">AUM</th><th style="text-align:right;">전일대비</th>'
                f'<th style="text-align:right; padding-right:10px;">거래대금</th></tr>')
        trs = ""
        for i, e in enumerate(etfs[:40], 1):
            ch = e.get("aum_chg_pct")
            ch_s = (f'<span style="color:{UP if ch>0 else DOWN if ch<0 else MUT}; font-weight:700;">{ch:+.1f}%</span>'
                    if ch is not None else f'<span style="color:{MUT};">—</span>')
            trs += (
                f'<tr style="border-bottom:1px solid {COLORS["border"]}; font-size:0.9rem;">'
                f'<td style="text-align:left; padding:7px 10px; color:{MUT};">{i}</td>'
                f'<td style="text-align:left;"><b style="color:#16202E; font-weight:700;">{e["name"]}</b></td>'
                f'<td style="text-align:right; color:#16202E; font-weight:800;">{jo(e["aum"])}</td>'
                f'<td style="text-align:right;">{ch_s}</td>'
                f'<td style="text-align:right; color:{MUT}; padding-right:10px;">{jo(e.get("amount",0)/100)}</td></tr>')
        st.markdown(f'<table style="width:100%; border-collapse:collapse; border:none;">{head}{trs}</table>',
                    unsafe_allow_html=True)
        st.caption("국내 주식형 ETF 전체. AUM 일별 추이는 매일 누적되어 진입·청산 타이밍 신호로 발전합니다.")

# ════════════════ ② 패시브 리밸런싱 ════════════════
with t2:
    premise_box(
        "<b>전제</b> — 지수 추종형(코스피/코스닥 등)은 <b>구성종목이 사전 공시</b>되고 편입 기준에 따라 "
        "사전 필터링이 일부 가능. 정기 변경 반영.<br>"
        "<b>전략</b> — 정기 편입/편출 종목을 <b>예측</b>하고 빠르게 팔로우업. "
        "원칙적으로 <b>반영일 직전 거래일 종가 동시호가</b>에 집중 매매, "
        "단 유동성 대비 매매 규모가 과도한 종목은 분할 매매.")
    with st.container(border=True):
        sec_header("STRUCTURE", "구성 (예정)")
        st.markdown(
            f'<ul style="font-size:0.92rem; line-height:1.8; color:#16202E;">'
            f'<li><b>편입/편출 예측</b> — 코스닥150 예측 엔진(이미 보유)을 ETF 추종지수로 확장 (사이드바 "코스닥 150 분석")</li>'
            f'<li><b>리밸런싱 일정</b> — 지수별 정기 변경일·반영일 캘린더</li>'
            f'<li><b>동시호가 매매 플랜</b> — 예측 종목별 필요 매매량 vs 유동성(거래대금) → 분할 여부 판단</li>'
            f'</ul>', unsafe_allow_html=True)
        st.info("이 탭은 전략 구조를 먼저 잡아둔 단계입니다. 코스닥150 예측 엔진 연계 + 지수 리밸 일정 데이터로 채울 예정.")

# ════════════════ ③ 액티브 리밸런싱 ════════════════
with t3:
    premise_box(
        "<b>전제</b> — 액티브 ETF는 주요 종목 비중 조정이 <b>사전 미공시</b>. "
        "리밸런싱 이후 KRX/네이버에서 확인 가능. 실제 매매는 운용사별로 상이하나 "
        "통상 <b>리밸런싱 일자 기준 2~3일 내</b> 완료.<br>"
        "<b>전략</b> — 편입비를 사전 파악하지 못하면 신규 편입/편출을 사전에 알 수 없음 → "
        "<b>보유 변화의 빠른 추종</b>이 핵심.")
    with st.container(border=True):
        sec_header("STRUCTURE", "구성 (예정)")
        st.markdown(
            f'<ul style="font-size:0.92rem; line-height:1.8; color:#16202E;">'
            f'<li><b>액티브 ETF TOP10 일별 변화 추적</b> — 신규 편입·비중 급증·편출 자동 감지(2~3일 내 추종)</li>'
            f'<li><b>변화 알림</b> — 전일 대비 신규 등장/비중 변화가 큰 종목 하이라이트</li>'
            f'<li><b>거래대금 대비 영향</b> — 액티브 매매 규모가 종목 유동성 대비 유의미한지 판단</li>'
            f'</ul>', unsafe_allow_html=True)
        st.info("이 탭은 전략 구조 단계입니다. 액티브 ETF 식별 + TOP10 일별 변화(diff) 추적으로 채울 예정.")

st.caption(f"네이버 ETF 데이터 기반 · 화면 로드 {now_kst()} (KST) · 매일 05:00 KST 자동 갱신")
