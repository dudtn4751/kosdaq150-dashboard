"""Layer 3 — 포워드 압력 (앞으로 일어날 공식 컨센 변경을 선행하는 신호).

미래를 점치지 않는다. '공식 컨센 변경을 역사적으로 선행'하는 관측 가능한 신호만 모은다.
  - runrate_gap : YTD 실적 / (연간 컨센 × 진행분기/4) - 1.
                  양수 = YTD가 연간 컨센 내재 런레이트 상회 → 기계적 상향 압력(가장 깨끗).
  - tp_lead     : (목표주가 3M 변화) - (EPS 3M 리비전). 양수 = TP 리비전이 EPS를 선행.
  - persistence : 섹터 리비전 자기상관(외부 주입) × rev_op_3m. (자기상관 내부 추정 금지)
  - news_lead   : news_sentiment (보조 신호, 가중 낮게 사용 예정).

원칙: 순수 함수, raw 반환(표준화 나중), 결측 None(0으로 안 채움), 분모 0/음수 가드.
"""

from __future__ import annotations

from typing import Optional

from .layer1 import revision_ratio
from .schemas import EpsRevisionInput, LayerResult


def runrate_gap(ytd_cumulative_op: Optional[float],
                fy_consensus_op: Optional[float],
                quarters_elapsed: Optional[int]) -> Optional[float]:
    """YTD 실적 vs 연간 컨센 내재 런레이트 갭. 분모(연간컨센·진행분기) 0/음수·결측이면 None."""
    if ytd_cumulative_op is None or fy_consensus_op is None or quarters_elapsed is None:
        return None
    if fy_consensus_op <= 0 or quarters_elapsed <= 0:
        return None
    denom = fy_consensus_op * quarters_elapsed / 4.0
    if denom <= 0:
        return None
    return ytd_cumulative_op / denom - 1.0


def tp_lead(tp_now: Optional[float], tp_3m_ago: Optional[float],
            rev_eps_3m: Optional[float]) -> Optional[float]:
    """목표주가 3M 변화 - EPS 3M 리비전. TP·EPS 리비전 둘 중 하나라도 결측이면 None."""
    tp_chg = revision_ratio(tp_now, tp_3m_ago)   # 분모 0/음수·결측 가드 재사용
    if tp_chg is None or rev_eps_3m is None:
        return None
    return tp_chg - rev_eps_3m


def persistence(sector_revision_autocorr: Optional[float],
                rev_op_3m: Optional[float]) -> Optional[float]:
    """섹터 리비전 자기상관(외부 주입, 0~1) × rev_op_3m. 둘 중 하나라도 결측이면 None."""
    if sector_revision_autocorr is None or rev_op_3m is None:
        return None
    return sector_revision_autocorr * rev_op_3m


def forward_pressure(data: EpsRevisionInput,
                     sector_revision_autocorr: Optional[float] = None) -> LayerResult:
    """미래 리비전 압력 컴포넌트 raw 산출 → LayerResult.

    sector_revision_autocorr: 섹터별 리비전 자기상관계수(외부 주입). 없으면 persistence=None.
    evidence: runrate_gap, tp_lead, persistence, news_lead (결측 None).
    raw     : 주요 forward 신호(runrate_gap·tp_lead·persistence)의 가용 평균(잠정).
              news_lead는 보조(raw 제외 — 가중은 이후 결합 단계에서).
    available: 주요 forward 신호 1개 이상 존재.
    """
    cons = data.get("consensus") or {}
    op1 = cons.get("op_fy1") if isinstance(cons.get("op_fy1"), dict) else {}
    eps1 = cons.get("eps_fy1") if isinstance(cons.get("eps_fy1"), dict) else {}
    rev_op_3m = revision_ratio(op1.get("now"), op1.get("m3"))
    rev_eps_3m = revision_ratio(eps1.get("now"), eps1.get("m3"))

    ytd = data.get("actuals_ytd") or {}
    tp = data.get("target_price") or {}
    ns = data.get("news_sentiment")

    rr = runrate_gap(ytd.get("ytd_cumulative_op"), ytd.get("fy_consensus_op"),
                     ytd.get("quarters_elapsed"))
    tpl = tp_lead(tp.get("tp_now"), tp.get("tp_3m_ago"), rev_eps_3m)
    pers = persistence(sector_revision_autocorr, rev_op_3m)
    news = ns if isinstance(ns, (int, float)) else None

    evidence = {"runrate_gap": rr, "tp_lead": tpl, "persistence": pers, "news_lead": news}
    primary = [v for v in (rr, tpl, pers) if v is not None]
    raw = (sum(primary) / len(primary)) if primary else 0.0
    return LayerResult(raw=raw, evidence=evidence, available=bool(primary))
