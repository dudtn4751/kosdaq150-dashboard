"""집계 — 레이어 결합 + 섹터 표준화.

순서:
  1) combine_layers: Layer1/2/3 raw를 가중 결합 + 신뢰도 게이트 적용 → raw_score
  2) standardize_sector_relative: 섹터 내 분포로 z표준화 → -100~+100

섹터 상대화는 단일종목/배치 둘 다 지원(아래 두 진입점).
순수 함수. 계산 로직은 단계별 지시 시 작성. (현재 스캐폴딩)
"""

from __future__ import annotations

from typing import Dict, Mapping, Sequence

from .schemas import LayerResult


def combine_layers(layers: Mapping[str, LayerResult], confidence: float) -> float:
    """레이어 raw 가중 결합 → 신뢰도 게이트 곱 → 표준화 전 raw_score.

    layers: {"realized","momentum","forward"} → LayerResult. 구현 대기.
    """
    raise NotImplementedError("combine_layers 구현 대기 — 단계별 지시 시 작성")


def standardize_sector_relative(raw_score: float, sector_pool: Sequence[float]) -> float:
    """[단일종목] 한 종목 raw_score를 같은 섹터 raw 분포(sector_pool) 대비 z표준화 → -100~+100.

    구현 대기.
    """
    raise NotImplementedError("섹터 표준화(단일) 구현 대기 — 단계별 지시 시 작성")


def standardize_sector_batch(raw_by_code: Mapping[str, float],
                             sector_by_code: Mapping[str, str]) -> Dict[str, float]:
    """[배치] {code: raw} + {code: sector} → 섹터별 z표준화 → {code: -100~+100}.

    구현 대기.
    """
    raise NotImplementedError("섹터 표준화(배치) 구현 대기 — 단계별 지시 시 작성")
