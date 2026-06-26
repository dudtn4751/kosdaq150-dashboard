"""Layer 1 — 실현 리비전 (이미 일어난 컨센서스 리비전).

무엇을 본다:
  - OP/EPS FY1·FY2 컨센서스의 1M·3M 변화율 (이미 반영된 상향/하향)
  - 목표주가 3M 변화 (tp_now vs tp_3m_ago)
핵심: '절대 실적'이 아니라 '추정치가 이미 얼마나 움직였나'.

순수 함수. 계산 로직은 단계별 지시 시 작성. (현재 스캐폴딩)
"""

from __future__ import annotations

from .schemas import EpsRevisionInput, LayerResult


def realized_revision(data: EpsRevisionInput) -> LayerResult:
    """이미 일어난 컨센서스 리비전을 점수화 → LayerResult(raw, evidence, available).

    입력 사용: data['consensus'](op/eps FY1·FY2 now/m1/m3), data['target_price'].
    구현 대기.
    """
    raise NotImplementedError("Layer1(실현 리비전) 구현 대기 — 단계별 지시 시 작성")
