"""신뢰도 게이트 — 레이어 원점수를 얼마나 믿을지 (0~1 배수).

무엇을 본다:
  - dispersion.std/mean (추정치 분산↑ → 신뢰↓)
  - analyst_n (커버 애널리스트 수↓ → 신뢰↓)
  - avg_estimate_age_days (오래된 추정치 → 신뢰↓)
  - fiscal.fy_roll_flag (FY 전환기 왜곡 → 신뢰↓)
핵심: 신뢰 낮은 리비전은 점수를 0(중립) 쪽으로 끌어당겨 노이즈 억제.

순수 함수. 계산 로직은 단계별 지시 시 작성. (현재 스캐폴딩)
"""

from __future__ import annotations

from .schemas import EpsRevisionInput


def confidence_gate(data: EpsRevisionInput) -> float:
    """0~1 신뢰도 배수 산출 (1=완전신뢰, 0=무시).

    입력 사용: data['dispersion'], data['fiscal'].
    구현 대기.
    """
    raise NotImplementedError("신뢰도 게이트 구현 대기 — 단계별 지시 시 작성")
