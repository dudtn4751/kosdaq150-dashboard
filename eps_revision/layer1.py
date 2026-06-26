"""Layer 1 — 실현 리비전 (이미 일어난 컨센서스 변화).

이미 일어난 컨센 변화의 **방향·크기·폭**을 잰다. (재무 절대값·YoY 성장률 사용 금지)
  - rev_op_3m / rev_op_1m   : 영업이익 FY1 컨센서스 변화율 (now/past - 1)
  - rev_eps_3m / rev_eps_1m : EPS FY1 컨센서스 변화율
  - diffusion_idx           : (up - down) / total  추정 변경 애널 쏠림(폭)
  - sue                     : 최근 4Q 평균 (actual - consensus)/|consensus|  서프라이즈

원칙: 순수 함수, raw 값 반환(표준화는 나중 단계), 결측은 None(0으로 채우지 않음),
      분모 0/음수 가드. 컨센서스 변화율의 분모는 '과거 추정치'이며 0·음수면 None.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .schemas import DiffusionInput, EpsRevisionInput, LayerResult, TimePoint


def revision_ratio(now: Optional[float], past: Optional[float]) -> Optional[float]:
    """컨센서스 변화율 = now / past - 1. 분모(과거 추정치)가 0/음수거나 값 결측이면 None.

    음수 분모(적자 추정)는 변화율이 왜곡되므로 의도적으로 None 처리.
    """
    if now is None or past is None or past <= 0:
        return None
    return now / past - 1.0


def diffusion_index(diffusion: Optional[DiffusionInput]) -> Optional[float]:
    """리비전 확산 쏠림 = (up_count - down_count) / total. total 0/음수/결측이면 None."""
    if not diffusion:
        return None
    total = diffusion.get("total")
    up = diffusion.get("up_count")
    down = diffusion.get("down_count")
    if total is None or up is None or down is None or total <= 0:
        return None
    return (up - down) / total


def surprise_sue(surprise: Optional[List[Tuple[float, float]]]) -> Optional[float]:
    """최근 N분기 평균 SUE = mean[(actual - consensus) / |consensus|].

    consensus 0·결측 분기는 제외. 유효 분기가 없으면 None.
    """
    if not surprise:
        return None
    vals = []
    for pair in surprise:
        if pair is None or len(pair) != 2:
            continue
        actual, cons = pair
        if actual is None or cons is None or cons == 0:
            continue
        vals.append((actual - cons) / abs(cons))
    if not vals:
        return None
    return sum(vals) / len(vals)


def _tp(d: object) -> TimePoint:
    return d if isinstance(d, dict) else {}


def realized_revision(data: EpsRevisionInput) -> LayerResult:
    """이미 일어난 컨센서스 리비전의 6개 컴포넌트를 raw로 산출 → LayerResult.

    evidence에 각 컴포넌트 raw값(없으면 None) 보존. available = 컴포넌트 1개 이상 존재.
    raw = 가용 컴포넌트 평균(표준화 전 잠정 크기; 레이어 가중·섹터표준화는 이후 단계).
    """
    cons = data.get("consensus") or {}
    op1, eps1 = _tp(cons.get("op_fy1")), _tp(cons.get("eps_fy1"))

    comp = {
        "rev_op_3m": revision_ratio(op1.get("now"), op1.get("m3")),
        "rev_op_1m": revision_ratio(op1.get("now"), op1.get("m1")),
        "rev_eps_3m": revision_ratio(eps1.get("now"), eps1.get("m3")),
        "rev_eps_1m": revision_ratio(eps1.get("now"), eps1.get("m1")),
        "diffusion_idx": diffusion_index(data.get("diffusion")),
        "sue": surprise_sue(data.get("surprise")),
    }
    present = [v for v in comp.values() if v is not None]
    raw = (sum(present) / len(present)) if present else 0.0
    return LayerResult(raw=raw, evidence=dict(comp), available=bool(present))
