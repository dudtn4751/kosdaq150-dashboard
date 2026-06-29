import sys, os

import streamlit as st
from datetime import datetime
from epsrev.data.dashboard_data import SECTORS, CO
from epsrev.ui.sidebar import render_sidebar

render_sidebar()

# ── 헤더 ─────────────────────────────────────────────────────────────────────
h1, h2, h3 = st.columns([5, 4, 1])
with h1:
    st.markdown(
        "<div style='font-size:0.75rem;color:#546080;letter-spacing:2px;"
        "margin-bottom:4px'>EQUITY RESEARCH · 섹터 점수 랭킹</div>"
        "<div style='font-size:1.6rem;font-weight:800'>대시보드</div>",
        unsafe_allow_html=True,
    )
with h2:
    st.write("")
    st.caption(f"2026.06.26 기준 · 마지막 업데이트 {datetime.now().strftime('%H:%M')}")
with h3:
    st.write("")
    if st.button("🔄", help="새로고침", use_container_width=True):
        st.rerun()

st.divider()

# ── 유틸 ─────────────────────────────────────────────────────────────────────
def _score_color(sc: int) -> str:
    if sc >= 70: return "#00c87a"
    if sc >= 50: return "#ffaa00"
    return "#ff4060"


# ── 섹터 카드 렌더러 ──────────────────────────────────────────────────────────
def _render_card(sec: dict) -> None:
    cos = sorted(
        [CO[c["t"]] for c in sec["cos"]],
        key=lambda x: x["total"] + x["bonus"],
        reverse=True,
    )
    avg = round(sum(c["total"] for c in cos) / len(cos))
    color = sec["color"]

    with st.container(border=True):
        # 카드 상단: 섹터명 + 평균점수
        th, ts = st.columns([3, 2])
        with th:
            st.markdown(
                f"<div style='font-size:1.05rem;font-weight:800;color:{color};"
                f"margin-top:2px'>{sec['name']}</div>",
                unsafe_allow_html=True,
            )
        with ts:
            st.markdown(
                f"<div style='text-align:right;font-size:0.8rem;color:#546080;"
                f"background:#1c2038;padding:2px 10px;border-radius:20px;"
                f"display:inline-block;float:right;margin-top:4px'>"
                f"평균 {avg}점</div>",
                unsafe_allow_html=True,
            )

        st.divider()

        # 종목 리스트 (그리드에서는 상위 5개만 미리보기)
        cos_preview = cos[:5]
        for i, c in enumerate(cos_preview):
            sc  = c["total"]
            bon = c["bonus"]
            pc  = c["pc"]
            pc_color = "#00c87a" if pc >= 0 else "#ff4060"
            pc_arrow = "▲" if pc >= 0 else "▼"

            bonus_html = (
                f"<span style='font-size:0.7rem;font-weight:700;color:#ffaa00;"
                f"background:rgba(255,170,0,.15);padding:1px 7px;"
                f"border-radius:5px;margin-left:6px'>+{bon}</span>"
                if bon > 0 else ""
            )

            r_rank, r_info, r_score = st.columns([0.5, 3, 2.2])
            with r_rank:
                st.markdown(
                    f"<div style='color:#343d5a;font-weight:800;"
                    f"font-size:0.9rem;padding-top:8px'>{i+1}</div>",
                    unsafe_allow_html=True,
                )
            with r_info:
                st.markdown(
                    f"<div style='font-size:0.9rem;font-weight:600;"
                    f"white-space:nowrap;overflow:hidden;text-overflow:ellipsis'>"
                    f"{c['n']}</div>"
                    f"<div style='font-size:0.75rem;color:{pc_color};font-weight:600'>"
                    f"{pc_arrow} {abs(pc)}%</div>",
                    unsafe_allow_html=True,
                )
            with r_score:
                st.markdown(
                    f"<div style='text-align:right;font-size:1.15rem;"
                    f"font-weight:800;color:{_score_color(sc)}'>"
                    f"{sc}{bonus_html}</div>",
                    unsafe_allow_html=True,
                )

            if i < len(cos_preview) - 1:
                st.markdown(
                    "<hr style='margin:5px 0;border:none;border-top:1px solid #1c2038'>",
                    unsafe_allow_html=True,
                )

        st.write("")
        if st.button(
            "상세 보기 →",
            key=f"sec_{sec['id']}",
            use_container_width=True,
        ):
            st.session_state["selected_sector_id"] = sec["id"]
            st.switch_page("epsrev/pages/2_sector_detail.py")


# ── 4열 그리드 (4행 × 4열 = 13카드) ─────────────────────────────────────────
for row_start in range(0, len(SECTORS), 4):
    row_secs = SECTORS[row_start: row_start + 4]
    cols = st.columns(4, gap="medium")
    for col, sec in zip(cols, row_secs):
        with col:
            _render_card(sec)
    st.write("")