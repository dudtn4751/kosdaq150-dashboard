"""정합성 가드 — 점수화 전/후 데이터 신뢰성 플래그.

- yoy_consistency : 내재 YoY(연간컨센/직전연도실적-1) vs 외부표기 YoY 불일치, 또는
                    베이스 과소(트로프 베이스효과) → 플래그. (YoY는 점수에 미반영이 기본)
- unit_consistency: 같은 단위/통화여야 할 값들의 스케일 점검(단위·통화 일관성).

순수 함수, 플래그 리스트 반환(파이프라인 안전성 위해 raise 대신 플래그).
"""

from __future__ import annotations

from typing import List, Optional

from .schemas import EpsRevisionInput

TROUGH_RATIO = 0.2     # 직전연도 베이스가 연간컨센의 20% 미만 → 트로프 의심
YOY_MISMATCH_TOL = 0.5  # 내재 YoY vs 표기 YoY 50%p 초과 차이 → 불일치
UNIT_RATIO = 50.0       # 같은 단위 추정치 스케일 50배 이상 차이 → 단위 불일치 의심


def yoy_consistency(fy_consensus_op: Optional[float],
                    prev_year_actual_op: Optional[float],
                    reported_yoy: Optional[float] = None) -> List[str]:
    """YoY 정합성·트로프 베이스 플래그. (둘 다 외부 주입; 없으면 검사 생략)."""
    flags: List[str] = []
    if fy_consensus_op is None or prev_year_actual_op is None:
        return flags
    # 트로프 베이스효과: 직전연도 적자/0 또는 비정상적으로 작은 베이스
    if prev_year_actual_op <= 0:
        flags.append("트로프 베이스효과 의심(직전연도 적자/0) — YoY 점수 미반영")
        return flags
    if abs(prev_year_actual_op) < TROUGH_RATIO * abs(fy_consensus_op):
        flags.append("트로프 베이스효과 의심(베이스 과소) — YoY 점수 미반영")
    # 내재 YoY vs 외부표기 YoY 불일치
    implied = fy_consensus_op / prev_year_actual_op - 1.0
    if reported_yoy is not None and abs(implied - reported_yoy) > YOY_MISMATCH_TOL:
        flags.append(f"YoY 정합성 불일치(내재 {implied:+.0%} vs 표기 {reported_yoy:+.0%})")
    return flags


def unit_consistency(data: EpsRevisionInput) -> List[str]:
    """단위·통화 일관성 점검. 같은 연간 영업이익 추정(op_fy1.now vs fy_consensus_op)이
    50배 이상 차이거나 진행분기가 0~4 밖이면 플래그."""
    flags: List[str] = []
    cons = data.get("consensus") or {}
    op1 = cons.get("op_fy1") if isinstance(cons.get("op_fy1"), dict) else {}
    ytd = data.get("actuals_ytd") or {}
    op_now, fy = op1.get("now"), ytd.get("fy_consensus_op")
    if op_now not in (None, 0) and fy not in (None, 0):
        ratio = abs(op_now / fy)
        if ratio > UNIT_RATIO or ratio < 1.0 / UNIT_RATIO:
            flags.append("단위·통화 불일치 의심(op_fy1·fy_consensus 스케일 상이)")
    q = ytd.get("quarters_elapsed")
    if q is not None and not (0 <= q <= 4):
        flags.append(f"진행분기 비정상({q}) — 런레이트 신뢰 불가")
    return flags
