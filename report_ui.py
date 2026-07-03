"""공용 리포트 UI — 여러 페이지에서 재사용하는 '증권사 리포트 요약 모달' + 로더.

- load_reports_by_code(): data/research_reports.json → {종목코드: [리포트...]}
- render_report_dialog(rep): @st.dialog 요약 모달 (lazy Claude 요약 + graceful).

두 페이지(pages/longshort_alpha.py, epsrev/pages/3_company_detail.py)가 공통 사용.
리포트 레코드 키(한경 파이프라인): date, code, name, title, tp, opinion, broker, analyst,
    tp_prev, tp_change_pct, direction, report_id, pdf_url.
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

try:                                  # PDF 요약기(선택적 — 없어도 모달은 graceful 동작)
    from scripts.report_summarizer import get_report_summary
except Exception:
    get_report_summary = None

_DATA = Path(__file__).resolve().parent / "data"


@st.cache_data(ttl=3600, show_spinner=False)
def load_reports_by_code() -> dict:
    """data/research_reports.json → {code: [report, ...]} (최신순 유지)."""
    try:
        d = json.loads((_DATA / "research_reports.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    by: dict = {}
    for r in d.get("reports", []):
        by.setdefault(r.get("code"), []).append(r)
    return by


@st.dialog("📄 증권사 리포트 요약", width="large")
def render_report_dialog(rep: dict):
    """리포트 메타 + (lazy) Claude 요약 모달. report_id/pdf_url 없으면 graceful 안내."""
    title  = rep.get("title", "")
    broker = rep.get("broker") or rep.get("institution", "")
    meta = " · ".join(x for x in [
        broker, rep.get("analyst", ""), rep.get("date", ""),
        (f"목표가 {rep['tp']:,}원" if rep.get("tp") else ""), rep.get("opinion", ""),
    ] if x)
    st.markdown(f"**{title}**")
    if meta:
        st.caption(meta)
    st.divider()

    rid, url = rep.get("report_id"), rep.get("pdf_url")
    if not rid or not url:
        st.info("이 리포트는 원문 링크가 없어 요약을 제공할 수 없습니다. (과거 수집분)")
        return
    if get_report_summary is None:
        st.warning("요약 모듈을 불러오지 못했습니다.")
        st.link_button("원문 PDF 열기", url)
        return

    with st.spinner("리포트 원문 요약 중… (최초 1회만, 이후 캐시)"):
        summ = get_report_summary(rid, url)

    if summ is None:
        st.warning("요약 생성에 실패했습니다. 원문 PDF를 확인하세요.")
        st.link_button("원문 PDF 열기", url)
        return
    if summ.get("status") == "ocr_needed":
        st.warning("스캔 이미지 PDF로 본문 텍스트 추출이 불가합니다 (OCR 필요).")
        st.link_button("원문 PDF 열기", url)
        return

    if summ.get("tldr"):
        st.markdown(f"#### {summ['tldr']}")

    def _bullets(label, items):
        items = [x for x in (items or []) if x]
        if items:
            st.markdown(f"**{label}**")
            for it in items:
                st.markdown(f"- {it}")

    _bullets("투자포인트", summ.get("thesis"))
    _bullets("촉매", summ.get("catalysts"))
    _bullets("리스크", summ.get("risks"))
    if summ.get("tp_logic"):
        st.markdown(f"**목표주가 근거** — {summ['tp_logic']}")
    if summ.get("earnings"):
        st.markdown(f"**실적/추정 변화** — {summ['earnings']}")
    st.divider()
    st.link_button("원문 PDF 열기", url)
