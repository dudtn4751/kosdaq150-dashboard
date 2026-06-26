"""EPS Revision 서브스코어 패키지.

개별 종목의 EPS Revision 서브스코어(-100~+100, 섹터 상대)를 산출.
상위 종합스코어의 EPS 항목으로 투입: 종합 = EPS×35 + 상대강도×20 + 이벤트×12 + 퀄리티×10.

파이프라인 (단계별로 구현 예정):
  layer1.realized_revision   — 이미 일어난 컨센서스 리비전
  layer2.revision_momentum   — 변화의 가속/감속
  layer3.forward_pressure    — 미래 리비전 압력
  confidence.confidence_gate — 신뢰도 게이트(0~1)
  aggregate.combine_layers   — 레이어 결합 + 신뢰도 적용 → raw_score
  aggregate.standardize_*    — 섹터 표준화 → -100~+100 (단일/배치)
  insight.generate_insight   — 한 줄 인사이트

설계 원칙: 순수 함수, 외부 I/O 분리(데이터 주입), Python/pandas, 3.9 호환.
"""

from __future__ import annotations

from .schemas import (
    EpsRevisionInput,
    EpsRevisionResult,
    LayerResult,
    ConsensusInput,
    DiffusionInput,
    DispersionInput,
    TargetPriceInput,
    ActualsYTDInput,
    FiscalInput,
    TimePoint,
)

__all__ = [
    "EpsRevisionInput",
    "EpsRevisionResult",
    "LayerResult",
    "ConsensusInput",
    "DiffusionInput",
    "DispersionInput",
    "TargetPriceInput",
    "ActualsYTDInput",
    "FiscalInput",
    "TimePoint",
]
