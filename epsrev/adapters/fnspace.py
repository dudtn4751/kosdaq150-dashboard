"""
epsrev/adapters/fnspace.py
==========================
정규화 중간표현(fnspace_types) → builder.py의 fnspace_extra dict 변환 + 번들 수집.

파이프라인 최종 단:
    fnspace_client(fetch raw) → fnspace_parser(정규화) → [이 파일] → fnspace_extra → StockInput

핵심 함수:
    get_fnspace_bundle(ticker) -> dict | None
        - 5개 엔드포인트를 모아 builder.fnspace_extra 스키마와 정확히 일치하는 dict 생성.
        - FNSPACE_ENABLED=False(키 없음/미설정)면 None → builder는 기존 더미 폴백 유지.
    assemble_extra(normalized, asof) -> dict
        - 순수 변환(정규화 묶음 → extra). 목업 테스트가 이 함수를 직접 검증.

매핑(요청 사양):
    eps_fy1/_1m/_3m   ← forward 12M Fwd EPS 시점값(오늘/1M전/3M전)
    eps_fy2           ← estimate_fiscal FY2 EPS
    op_fy1/_1m/_3m    ← estimate_daily 영업이익 추정 시점값
    op_fy2            ← estimate_fiscal FY2 OP
    fy_consensus_op   ← estimate_fiscal FY1 OP
    tp_now/tp_3m_ago  ← opinion_tp 목표주가(Adj.) 시점값
    analyst_n         ← opinion_tp 참여 증권사 수
    diffusion         ← 목표주가 상향/하향/전체(1M) proxy로 up/down/total 재구성
    dispersion        ← std/mean/avg_estimate_age_days = None (개별 추정치 분포 미제공),
                        analyst_n만 opinion_tp에서
    surprise_4q       ← financial 최근 4분기 (actual_op, consensus_op)
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from epsrev.adapters import fnspace_client as client
from epsrev.adapters import fnspace_parser as parser
from epsrev.adapters.fnspace_parser import TimePoints, pick_timepoints
from epsrev.adapters.fnspace_types import FnSpaceNormalized, OpinionTargetPrice


# ── 부분 변환 헬퍼 ──────────────────────────────────────────────────────────────
def _diffusion_from_tp(opinion: Optional[OpinionTargetPrice]) -> dict:
    """목표주가 1M 상향/하향/전체 → diffusion proxy {up_count, down_count, total}."""
    r = opinion.rev_1m if opinion else None
    if r is None:
        return {"up_count": 0, "down_count": 0, "total": 1}   # 중립(0으로 나눔 방지)
    total = r.total if r.total > 0 else max(r.up + r.down, 1)
    return {"up_count": r.up, "down_count": r.down, "total": total}


def _surprise_from_financial(fin) -> list[tuple[float, float]]:
    """financial 최근 4분기 → [(actual_op, consensus_op), ...]. consensus 없으면 surprise%로 역산."""
    if not fin or not fin.quarters:
        return []
    out: list[tuple[float, float]] = []
    for q in fin.quarters[-4:]:
        if q.actual_op is None:
            continue
        cons = q.consensus_op
        if cons is None and q.surprise_pct is not None and q.surprise_pct != -100:
            cons = q.actual_op / (1.0 + q.surprise_pct / 100.0)   # actual=cons*(1+s/100)
        if cons is None:
            continue
        out.append((float(q.actual_op), float(cons)))
    return out


# ── 정규화 묶음 → fnspace_extra (순수 변환) ─────────────────────────────────────
def assemble_extra(nrm: FnSpaceNormalized, asof: Optional[date] = None) -> dict:
    """
    builder.fnspace_extra 스키마와 정확히 일치하는 dict.
    값이 없는 float 레벨키(op_fy1/op_fy2/fy_consensus_op/tp_now)는 '생략' → builder가 더미 폴백.
    """
    extra: dict = {}

    # EPS: forward 시점값
    fwd = pick_timepoints(nrm.forward.points, asof) if nrm.forward else TimePoints()
    extra["eps_fy1"]    = fwd.now
    extra["eps_fy1_1m"] = fwd.m1
    extra["eps_fy1_3m"] = fwd.m3
    extra["eps_fy2"]    = nrm.fiscal.fy2_eps if nrm.fiscal else None

    # OP: estimate_daily 시점값
    op = pick_timepoints(nrm.estimate_daily.op, asof) if nrm.estimate_daily else TimePoints()
    if op.now is not None:
        extra["op_fy1"] = op.now
    extra["op_fy1_1m"] = op.m1
    extra["op_fy1_3m"] = op.m3

    # FY2 OP / FY1 컨센 OP: fiscal
    if nrm.fiscal:
        if nrm.fiscal.fy2_op is not None:
            extra["op_fy2"] = nrm.fiscal.fy2_op
        if nrm.fiscal.fy1_op is not None:
            extra["fy_consensus_op"] = nrm.fiscal.fy1_op

    # 목표주가: opinion_tp 시점값
    tp = pick_timepoints(nrm.opinion_tp.tp_points, asof) if nrm.opinion_tp else TimePoints()
    if tp.now is not None:
        extra["tp_now"] = tp.now
    extra["tp_3m_ago"] = tp.m3

    analyst_n = nrm.opinion_tp.analyst_n if nrm.opinion_tp else None
    extra["analyst_n"] = analyst_n

    # diffusion proxy + dispersion(미제공 → None)
    extra["diffusion"]  = _diffusion_from_tp(nrm.opinion_tp)
    extra["dispersion"] = {
        "std": None, "mean": None,
        "analyst_n": analyst_n, "avg_estimate_age_days": None,
    }

    # surprise_4q: financial
    sq = _surprise_from_financial(nrm.financial)
    if sq:
        extra["surprise_4q"] = sq

    return extra


# ── 번들 수집(라이브) ───────────────────────────────────────────────────────────
def get_fnspace_bundle(ticker: str, asof: Optional[date] = None) -> Optional[dict]:
    """
    5개 엔드포인트 호출 → 정규화 → fnspace_extra dict.
    키 없음/미설정(FNSPACE_ENABLED=False)면 None (builder 더미 폴백 유지).
    """
    if not client.FNSPACE_ENABLED:
        return None

    nrm = parser.parse_all(
        ticker,
        raw_forward=client.forward(ticker),
        raw_estimate_daily=client.estimate_daily(ticker),
        raw_estimate_fiscal=client.estimate_fiscal(ticker),
        raw_opinion_tp=client.opinion_tp(ticker),
        raw_financial=client.financial(ticker),
    )
    return assemble_extra(nrm, asof)
