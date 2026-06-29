import sys, os

import streamlit as st
from epsrev.data.dashboard_data import SECTORS, CO
from epsrev.ui.sidebar import render_sidebar

render_sidebar()

# ── 섹터 특정 ─────────────────────────────────────────────────────────────────
sec_id = st.session_state.get("selected_sector_id", "")
sec    = next((s for s in SECTORS if s["id"] == sec_id), None)

if not sec:
    st.warning("섹터 그리드에서 섹터를 선택해 이동하세요.")
    if st.button("← 섹터 그리드로"):
        st.switch_page("epsrev/pages/1_sector_grid.py")
    st.stop()

# ── 상단 네비 ─────────────────────────────────────────────────────────────────
n1, n2 = st.columns([1, 8])
with n1:
    if st.button("← 전체"):
        st.switch_page("epsrev/pages/1_sector_grid.py")
with n2:
    st.markdown(
        f"<div style='font-size:1.35rem;font-weight:800;color:{sec['color']};margin-top:4px'>"
        f"{sec['name']}</div>",
        unsafe_allow_html=True,
    )

st.caption(f"총 {len(sec['cos'])}개 종목 · 우측 → 버튼으로 종목 상세 이동")
st.divider()

# ── 정렬된 종목 ───────────────────────────────────────────────────────────────
cos = sorted(
    [CO[c["t"]] for c in sec["cos"]],
    key=lambda x: x["total"] + x["bonus"],
    reverse=True,
)
color = sec["color"]


def fmt(n: float | int) -> str:
    return f"{int(n):,}" if n is not None else "—"


def _mini_bar(label: str, val: int, max_val: int) -> str:
    pct = min(100, round(val / max_val * 100))
    return (
        f"<div style='margin-bottom:7px'>"
        f"<div style='display:flex;justify-content:space-between;"
        f"font-size:0.68rem;color:#546080;margin-bottom:3px'>"
        f"<span>{label}</span>"
        f"<span style='color:#dde3f8'>{val}"
        f"<span style='color:#343d5a'>/{max_val}</span></span></div>"
        f"<div style='height:3px;background:#1c2038;border-radius:2px'>"
        f"<div style='width:{pct}%;height:100%;background:{color};"
        f"border-radius:2px'></div></div></div>"
    )


# ── 테이블 헤더 ───────────────────────────────────────────────────────────────
h = st.columns([0.5, 3, 4.5, 2.5, 2, 0.8])
labels = ["#", "종목", "점수 구성 (실적 / 데이터 / 수급)", "종합점수", "주가", ""]
for col, label in zip(h, labels):
    with col:
        st.caption(label)

st.markdown(
    "<hr style='margin:4px 0;border:none;border-top:1px solid #252945'>",
    unsafe_allow_html=True,
)

# ── 종목 행 ──────────────────────────────────────────────────────────────────
for i, c in enumerate(cos):
    row = st.columns([0.5, 3, 4.5, 2.5, 2, 0.8])

    with row[0]:
        st.markdown(
            f"<div style='font-size:1rem;font-weight:800;color:#343d5a;"
            f"padding-top:14px'>{i+1}</div>",
            unsafe_allow_html=True,
        )

    with row[1]:
        st.markdown(
            f"<div style='font-size:0.95rem;font-weight:700;margin-top:10px'>"
            f"{c['n']}</div>"
            f"<div style='font-size:0.72rem;color:#546080'>"
            f"{c['t']} · 시총 {fmt(c['mkt'])}억</div>",
            unsafe_allow_html=True,
        )

    with row[2]:
        bars = (
            _mini_bar("실적", c["sc"]["e"], 40)
            + _mini_bar("데이터", c["sc"]["d"], 35)
            + _mini_bar("수급", c["sc"]["s"], 25)
        )
        st.markdown(
            f"<div style='padding:10px 16px 10px 0'>{bars}</div>",
            unsafe_allow_html=True,
        )

    with row[3]:
        bon = c["bonus"]
        bonus_html = (
            f"<span style='font-size:0.72rem;font-weight:700;color:#ffaa00;"
            f"background:rgba(255,170,0,.15);padding:1px 7px;"
            f"border-radius:4px;margin-left:6px'>+{bon}</span>"
            if bon > 0 else ""
        )
        ev_html = "".join(
            f"<div style='font-size:0.65rem;color:#ffaa00;"
            f"background:rgba(255,170,0,.1);padding:2px 6px;"
            f"border-radius:3px;margin-top:4px;display:inline-block;"
            f"margin-right:3px'>+{e['pts']} "
            f"{e['txt'][:16]}{'…' if len(e['txt'])>16 else ''}</div>"
            for e in c["ev"]
        )
        st.markdown(
            f"<div style='padding-top:10px'>"
            f"<span style='font-size:1.3rem;font-weight:800'>{c['total']}</span>"
            f"{bonus_html}</div>"
            f"<div style='margin-top:3px'>{ev_html}</div>",
            unsafe_allow_html=True,
        )

    with row[4]:
        pc = c["pc"]
        pc_color = "#00c87a" if pc >= 0 else "#ff4060"
        pc_arrow = "▲" if pc >= 0 else "▼"
        st.markdown(
            f"<div style='font-size:0.95rem;font-weight:600;margin-top:10px'>"
            f"{fmt(c['p'])}원</div>"
            f"<div style='font-size:0.8rem;color:{pc_color};font-weight:600'>"
            f"{pc_arrow} {abs(pc)}%</div>",
            unsafe_allow_html=True,
        )

    with row[5]:
        st.write("")
        if st.button("→", key=f"co_{c['t']}", help=f"{c['n']} 상세"):
            st.session_state["selected_ticker"]    = c["t"]
            st.session_state["selected_sector_id"] = sec["id"]
            st.switch_page("epsrev/pages/3_company_detail.py")

    if i < len(cos) - 1:
        st.markdown(
            "<hr style='margin:2px 0;border:none;border-top:1px solid #1c2038'>",
            unsafe_allow_html=True,
        )
