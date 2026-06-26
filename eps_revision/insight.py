"""인사이트 — 점수·레이어·컴포넌트 분해를 한 줄 자연어로 요약.

가장 기여도 높은 레이어/컴포넌트를 골라 한 문장 생성. flags가 있으면 끝에 경고 덧붙임.
예: "3M 컨센 +78% 상향이 가속 중, YTD 런레이트가 연간 컨센 상회 → 추가 상향 여력
     → 강한 EPS 상향 모멘텀 | ⚠ 트로프 베이스효과 의심 — YoY 점수 미반영"
"""

from __future__ import annotations

from typing import Dict, List, Optional

_LAYER_KO = {"realized": "실현 리비전", "momentum": "리비전 모멘텀", "forward": "포워드 압력"}


def _verdict(score: float) -> str:
    if score >= 40:
        return "강한 EPS 상향 모멘텀"
    if score >= 15:
        return "EPS 상향 우위"
    if score <= -40:
        return "강한 EPS 하향 압력"
    if score <= -15:
        return "EPS 하향 우위"
    return "중립"


def generate_insight(score: float, layers: Dict[str, Optional[float]],
                     confidence: float, evidence: Dict[str, object],
                     flags: Optional[List[str]] = None) -> str:
    """한 줄 인사이트 생성."""
    flags = flags or []
    ev = evidence or {}
    parts: List[str] = []

    # 실현 리비전(+모멘텀 인라인)
    base = ev.get("rev_op_3m")
    if base is None:
        base = ev.get("rev_eps_3m")
    accel = ev.get("accel")
    if base is not None and abs(base) >= 0.01:
        d = "상향" if base > 0 else "하향"
        if accel is not None and abs(accel) >= 0.05:
            parts.append(f"3M 컨센 {base:+.0%} {d}이 " + ("가속 중" if accel > 0 else "둔화 중"))
        else:
            parts.append(f"3M 컨센 {base:+.0%} {d}")

    # 포워드 압력
    rr = ev.get("runrate_gap")
    if rr is not None and abs(rr) >= 0.02:
        parts.append("YTD 런레이트가 연간 컨센 " + ("상회 → 추가 상향 여력" if rr > 0 else "하회 → 하향 압력"))
    tpl = ev.get("tp_lead")
    if tpl is not None and tpl > 0.02:
        parts.append("TP 리비전이 EPS 선행")

    # 컴포넌트 신호가 약하면 우세 레이어로 폴백
    if not parts:
        avail = {k: v for k, v in (layers or {}).items() if v is not None}
        if avail:
            dom = max(avail, key=lambda k: abs(avail[k]))
            tone = "긍정" if avail[dom] > 0 else "부정"
            parts.append(f"{_LAYER_KO.get(dom, dom)} {tone} 신호 우위")
        else:
            parts.append("유효 리비전 신호 부족")

    sentence = ", ".join(parts) + f" → {_verdict(score)}"
    if confidence is not None and confidence < 0.7:
        sentence += f" (신뢰도 {confidence:.0%} — 커버리지/분산 주의)"
    if flags:
        sentence += " | ⚠ " + "; ".join(flags)
    return sentence
