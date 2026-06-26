"""Layer 2 — 모멘텀 (리비전의 가속/감속).

무엇을 본다:
  - 1M 변화 vs 3M 변화 비교 → 리비전이 가속 중인지 감속 중인지 (2차 미분 성격)
  - 어닝 서프라이즈 추세 (최근 4Q actual vs consensus) → 추정 보수성/관성
핵심: 같은 +리비전이라도 '빨라지는' 종목과 '식어가는' 종목을 구분.

순수 함수. 계산 로직은 단계별 지시 시 작성. (현재 스캐폴딩)
"""

from __future__ import annotations

from .schemas import EpsRevisionInput, LayerResult


def revision_momentum(data: EpsRevisionInput) -> LayerResult:
    """리비전의 가속/감속을 점수화 → LayerResult.

    입력 사용: data['consensus'](1M vs 3M 변화 비교), data['surprise'](4Q).
    구현 대기.
    """
    raise NotImplementedError("Layer2(모멘텀) 구현 대기 — 단계별 지시 시 작성")
