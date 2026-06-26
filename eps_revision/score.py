"""메인 오케스트레이터 — 데이터 주입 → EPS Revision 서브스코어 dict 조립.

compute_eps_revision_score(data, sector_pool, ...) 한 종목의 최종 점수 산출.
파이프라인: Layer1/2/3 컴포넌트 → 신뢰도 게이트 → 섹터 표준화·집계 → 정합성 가드 → 인사이트.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

import pandas as pd

from .aggregate import aggregate_single
from .confidence import confidence_gate
from .guards import unit_consistency, yoy_consistency
from .insight import generate_insight
from .layer1 import realized_revision
from .layer2 import revision_momentum
from .layer3 import forward_pressure
from .schemas import EpsRevisionInput


def _num(x) -> Optional[float]:
    """numpy/NaN 안전 변환 → float 또는 None."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def extract_components(data: EpsRevisionInput,
                       sector_revision_autocorr: Optional[float] = None) -> Dict[str, Optional[float]]:
    """Layer1/2/3 evidence를 평탄한 컴포넌트 dict로 병합(disp_cv 등 보조 포함)."""
    comp: Dict[str, Optional[float]] = {}
    comp.update(realized_revision(data).evidence)
    comp.update(revision_momentum(data).evidence)
    comp.update(forward_pressure(data, sector_revision_autocorr).evidence)
    return comp


def compute_eps_revision_score(data: EpsRevisionInput,
                               sector_pool: pd.DataFrame,
                               sector_revision_autocorr: Optional[float] = None,
                               prev_year_actual_op: Optional[float] = None,
                               reported_yoy: Optional[float] = None,
                               code: str = "_target") -> Dict[str, object]:
    """한 종목의 EPS Revision 서브스코어 최종 dict 조립.

    sector_pool: 같은 섹터 종목들의 컴포넌트 DataFrame(섹터 표준화·랭크 기준).
    prev_year_actual_op·reported_yoy: YoY 정합성 가드용 외부 주입(선택).
    반환: {eps_score, layers, confidence, evidence, insight, flags}.
    """
    comp = extract_components(data, sector_revision_autocorr)
    conf = confidence_gate(data)
    agg = aggregate_single(comp, sector_pool, confidence=conf, code=code)

    layers = {k: _num(agg.get(k)) for k in ("realized", "momentum", "forward")}
    eps_score = _num(agg.get("score"))

    # 정합성 가드
    fy = (data.get("actuals_ytd") or {}).get("fy_consensus_op")
    flags: List[str] = yoy_consistency(fy, prev_year_actual_op, reported_yoy) + unit_consistency(data)

    # 화면 근거 패널용 원천값(컴포넌트 + 핵심 컨센 스냅샷)
    cons = data.get("consensus") or {}
    op1 = cons.get("op_fy1") if isinstance(cons.get("op_fy1"), dict) else {}
    eps1 = cons.get("eps_fy1") if isinstance(cons.get("eps_fy1"), dict) else {}
    tp = data.get("target_price") or {}
    ytd = data.get("actuals_ytd") or {}
    evidence = {
        **comp,
        "op_fy1_now": op1.get("now"), "fy_consensus_op": ytd.get("fy_consensus_op"),
        "eps_fy1_now": eps1.get("now"), "tp_now": tp.get("tp_now"),
        "combined_raw": _num(agg.get("combined_raw")), "confidence_mult": round(conf, 3),
        "sector": data.get("sector"),
    }
    insight = generate_insight(eps_score if eps_score is not None else 0.0,
                               layers, conf, comp, flags)
    return {
        "eps_score": eps_score,
        "layers": layers,
        "confidence": round(conf, 3),
        "evidence": evidence,
        "insight": insight,
        "flags": flags,
    }
