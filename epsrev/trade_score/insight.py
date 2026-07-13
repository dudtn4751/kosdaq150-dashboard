"""인사이트/플래그 문장 (핸드오프 §7 · STEP 7) — 축·렌즈 기여 기반 한 줄 요약.

결정적(deterministic) 템플릿 — 같은 입력이면 같은 문장. LLM 미사용.
"""
from __future__ import annotations

from typing import Optional

from epsrev.trade_score.schema import SectorScore, CompanyScore

AXIS_LABEL = {"mom": "모멘텀", "acc": "가속", "qual": "품질(물량)", "cyc": "추세위치"}
LOW_CONFIDENCE = 0.5      # 섹터 저커버리지 기준
LOW_EXPOSURE = 0.5        # 기업 저커버리지 기준(폴백 노출)
LOW_RELIABILITY = 0.3     # 기업 저커버리지 기준(렌즈 신뢰 합)


def _state_label(score: Optional[float]) -> str:
    if score is None:
        return "무점수"
    if score >= 60:
        return "강세 상단"
    if score >= 20:
        return "개선 국면"
    if score > -20:
        return "중립"
    if score > -60:
        return "둔화 국면"
    return "약세 하단"


# ---------- 섹터 ----------
def sector_flags_extra(s: SectorScore) -> list:
    """섹터 추가 플래그: 신뢰도 낮음 → low_coverage."""
    extra = []
    if s.confidence is not None and s.confidence < LOW_CONFIDENCE:
        extra.append("low_coverage")
    return extra


def sector_insight(s: SectorScore) -> str:
    """축 기여(실효가중×z) 기반 한 줄: 상태 + 주도축 + 경고."""
    if s.sector_score is None:
        return f"{s.sector}: 데이터 부족 — 점수 산출 불가"

    contrib = {ax: s.weights.get(ax, 0.0) * z
               for ax, z in (("mom", s.axes.mom), ("acc", s.axes.acc),
                             ("qual", s.axes.qual), ("cyc", s.axes.cyc))
               if z is not None and s.weights.get(ax)}
    parts = [f"{s.sector}: {_state_label(s.sector_score)}({s.sector_score:+.0f})"]
    if contrib:
        top_ax = max(contrib, key=lambda a: abs(contrib[a]))
        z_top = getattr(s.axes, top_ax)
        parts.append(f"주도축 {AXIS_LABEL[top_ax]}({z_top:+.1f}σ)")
        # 모멘텀 양수인데 가속 음수 → 정점 통과 경고
        if (s.axes.mom is not None and s.axes.mom > 0
                and s.axes.acc is not None and s.axes.acc < -0.5):
            parts.append("가속 둔화 — 모멘텀 정점 통과 주의")
        # 품질 열위(단가 주도) 경고
        if s.axes.qual is not None and s.axes.qual < -1.0:
            parts.append("단가 주도 성장(물량 열위) 주의")
    if "base_effect" in s.flags:
        parts.append("기저효과 의심(감쇄 적용)")
    if "low_coverage" in s.flags:
        parts.append("커버리지 낮음(신뢰 하향)")
    return " · ".join(parts)


# ---------- 기업 ----------
def company_flags_extra(c: CompanyScore) -> list:
    """기업 추가 플래그: 활성 렌즈 신뢰 합이 낮으면 low_coverage.
    (exposure는 이미 r=recency·length·direct에 반영되므로 신뢰합만으로 판정 —
     I-only 기업이 export exposure=0 때문에 오탐되지 않게.)"""
    extra = []
    r_sum = (c.reliability.r_export or 0.0) + (c.reliability.r_industry or 0.0)
    if c.company_score is not None and r_sum < LOW_RELIABILITY:
        extra.append("low_coverage")
    return extra


def company_insight(c: CompanyScore, direct_export: bool = False) -> str:
    """렌즈 기여 기반 한 줄: 어떤 렌즈가 점수를 만들었고 무엇이 비었는지."""
    if c.company_score is None:
        return f"{c.ticker}: 수출·산업 렌즈 커버리지 없음 — 점수 없음"

    r_E = c.reliability.r_export or 0.0
    r_I = c.reliability.r_industry or 0.0
    parts = [f"{c.ticker}: {_state_label(c.company_score)}({c.company_score:+.0f})"]

    if "sector_inherit" in c.flags:
        parts.append("섹터 점수 상속(기업 렌즈 없음)")
    else:
        if c.export_part is not None:
            src = "직접수출" if direct_export else f"섹터폴백(exposure {c.exposure:.1f})"
            parts.append(f"수출렌즈 {c.export_part:+.0f}·{src}")
        if c.industry_part is not None:
            parts.append(f"산업렌즈 {c.industry_part:+.0f}")
        elif r_I == 0.0:
            parts.append("산업렌즈 미연동(r_I=0)")

    if "divergence" in c.flags:
        parts.append("⚠️ 수출·산업 신호 상충")
    if "base_effect" in c.flags:
        parts.append("기저효과 의심")
    if "low_coverage" in c.flags:
        parts.append("커버리지 낮음")
    return " · ".join(parts)
