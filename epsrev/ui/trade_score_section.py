"""종목 상세 — 수출·산업 모멘텀 스코어 카드 + '점수 산출 방식' 모달 (라이트 테마).

데이터: data/trade_scores.json (recompute 없음). 값 없으면 '—' graceful.
축(모멘텀·가속·품질·사이클) 배지는 I렌즈(앱 섹터 산업지표) 축 z 기준,
모달에서 E렌즈(수출 카테고리)·I렌즈 컨텍스트를 모두 보여준다.
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

AXIS_LABELS = [("mom", "모멘텀"), ("acc", "가속"), ("qual", "품질"), ("cyc", "사이클")]


def _fmt(v, pattern="{:+.1f}", none="—"):
    return none if v is None else pattern.format(v)


def _color(v):
    if v is None:
        return MUT
    return POS if v > 0 else NEG if v < 0 else MUT


def _axis_badges_html(axes: dict) -> str:
    parts = []
    for key, label in AXIS_LABELS:
        v = (axes or {}).get(key)
        parts.append(
            f"<span style='background:{BADGE_BG};border-radius:6px;padding:3px 8px;"
            f"font-size:0.72rem;color:{MUT}'>{label} "
            f"<b style='color:{_color(v)}'>{_fmt(v, '{:+.1f}σ')}</b></span>")
    return " ".join(parts)


def render_trade_score_card(ticker6: str, secname: str) -> None:
    """수출·산업 모멘텀 스코어 카드. trade_scores.json 없거나 종목 미포함 → 미표시 대신 '—' 카드."""
    ts = get_trade_score(ticker6)
    snap = load_trade_scores()
    as_of = snap.get("as_of", "—")

    score = (ts or {}).get("company_score")
    rel = (ts or {}).get("reliability") or {}
    flags = (ts or {}).get("flags") or []
    ind_sec = get_industry_sector(secname) or {}
    axes = ind_sec.get("axes") or {}

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
    if st.button("점수 산출 방식 보기", key=f"ts_modal_{ticker6}"):
        _score_method_dialog(ticker6, secname, ts)


def _sector_block(title: str, sec: dict) -> None:
    """모달 내 렌즈별 섹터 컨텍스트: 축 z + 자동가중(ρπσ) 표 + 점수."""
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
    rows = []
    for key, label in AXIS_LABELS:
        rows.append({
            "축": label,
            "z(자기이력)": _fmt(axes.get(key), "{:+.2f}"),
            "적용 가중": _fmt(weights.get(key), "{:.0%}", none="제외"),
        })
    st.table(rows)
    st.caption(
        f"섹터 특성 자동가중: ρ(사이클성) {_fmt(prof.get('rho'), '{:.2f}')} · "
        f"π(단가주도) {_fmt(prof.get('pi'), '{:.2f}')} · "
        f"σ(변동성) {_fmt(prof.get('sigma'), '{:.2f}')} — "
        "ρ↑→가속·사이클 강조, π↑→품질 강조, σ↑→모멘텀 신뢰 하향. "
        "결측 축은 가중 제외 후 재정규화(level형 품질축 등).")


@st.dialog("수출·산업 모멘텀 스코어 — 점수 산출 방식", width="large")
def _score_method_dialog(ticker6: str, secname: str, ts: dict) -> None:
    ts = ts or {}
    rel = ts.get("reliability") or {}
    st.markdown(
        "**산출 흐름** ① 각 지표 4축 원신호(모멘텀·가속·품질·사이클) → "
        "② 자기 이력 robust z(±3 winsorize) → ③ 섹터 특성(ρ·π·σ) 자동 가중합 → "
        "④ 전 섹터 분포 percentile(−100~+100) → ⑤ 수출(E)·산업(I) 두 렌즈를 "
        "신뢰도 가중으로 종합.")
    st.divider()

    cat = SECNAME_TO_TRADE_CAT.get(secname)
    _sector_block(f"E렌즈 — 수출 실측 ({cat or '카테고리 매핑 없음'})",
                  get_export_sector(cat) if cat else None)
    st.divider()
    _sector_block(f"I렌즈 — 산업지표/카드소비 ({secname})",
                  get_industry_sector(secname))
    st.divider()

    e, i = ts.get("export_part"), ts.get("industry_part")
    st.markdown(
        f"**렌즈 종합** — E <b style='color:{_color(e)}'>{_fmt(e, '{:+.1f}')}</b>"
        f"(r={_fmt(rel.get('r_export'), '{:.2f}')}) · "
        f"I <b style='color:{_color(i)}'>{_fmt(i, '{:+.1f}')}</b>"
        f"(r={_fmt(rel.get('r_industry'), '{:.2f}')}) · "
        f"노출도(exposure) {_fmt(ts.get('exposure'), '{:.2f}')} → "
        f"종합 <b style='color:{_color(ts.get('company_score'))}'>"
        f"{_fmt(ts.get('company_score'), '{:+.1f}')}</b>",
        unsafe_allow_html=True)
    st.caption("score = (r_E·E + r_I·I)/(r_E+r_I) — 결측 렌즈는 분모에서 제외. "
               "r = 최신성·이력길이·직접성(직접 1.0/섹터폴백 exposure).")

    if ts.get("flags"):
        st.markdown("**플래그**: " + " · ".join(f"`{f}`" for f in ts["flags"]))
    if ts.get("insight"):
        st.info(ts["insight"])
    if not ts:
        st.warning("이 종목의 점수 데이터가 없습니다 (trade_scores.json 미포함) — '—' 표시.")
