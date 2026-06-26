"""Layer 3 — 포워드 압력 (앞으로 일어날 리비전 압력).

무엇을 본다:
  - 리비전 확산도 diffusion (up/down/total 애널리스트 수) → 변경의 폭·방향 쏠림
  - YTD 진행률 vs 연간 컨센서스 (actuals_ytd) → 잠재 beat/miss → 추정 상/하향 압력
  - 뉴스 심리(KR-FinBERT) → 아직 추정치에 안 반영된 심리 선행
핵심: '아직 컨센서스에 반영 안 된' 향후 리비전 방향을 선반영.

순수 함수. 계산 로직은 단계별 지시 시 작성. (현재 스캐폴딩)
"""

from __future__ import annotations

from .schemas import EpsRevisionInput, LayerResult


def forward_pressure(data: EpsRevisionInput) -> LayerResult:
    """미래 리비전 압력을 점수화 → LayerResult.

    입력 사용: data['diffusion'], data['actuals_ytd'], data['news_sentiment'].
    구현 대기.
    """
    raise NotImplementedError("Layer3(포워드 압력) 구현 대기 — 단계별 지시 시 작성")
