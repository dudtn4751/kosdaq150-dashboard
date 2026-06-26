"""인사이트 — 점수·레이어 분해를 한 줄 자연어로 요약.

예: "컨센서스 3M +12% 상향이 가속 중이고 상향 애널 우위 → 강한 EPS 모멘텀"
어떤 레이어가 점수를 주도했는지 + 방향을 사람이 읽을 한 줄로.

순수 함수. 계산 로직은 단계별 지시 시 작성. (현재 스캐폴딩)
"""

from __future__ import annotations

from typing import Dict

from .schemas import LayerResult


def generate_insight(score: float, layers: Dict[str, LayerResult],
                     confidence: float, evidence: Dict[str, object]) -> str:
    """최종 점수·레이어 분해·근거로부터 한 줄 인사이트 생성. 구현 대기."""
    raise NotImplementedError("인사이트 생성 구현 대기 — 단계별 지시 시 작성")
