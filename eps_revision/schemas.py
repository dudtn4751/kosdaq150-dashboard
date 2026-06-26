"""EPS Revision 서브스코어 — 입출력 스키마.

설계 철학: 재무지표 절대값이 아니라
  (1) 이미 일어난 컨센서스 리비전 (Layer1 실현)
  (2) 그 변화의 가속/감속        (Layer2 모멘텀)
  (3) 미래 리비전 압력            (Layer3 포워드)
3개 레이어로 분해 → 신뢰도 게이트 → 섹터 표준화·집계 → 인사이트.

모든 계산은 순수 함수. 외부 I/O(스크레이프·DB)는 이 패키지 밖에서 수행하고,
아래 스키마 형태로 데이터를 '주입'한다. (Python 3.9 호환)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, TypedDict


# ── 입력 스키마 (data injection) ─────────────────────────────
class TimePoint(TypedDict):
    """한 추정치의 시점별 값. None 허용(미커버/결측)."""
    now: Optional[float]   # 현재 컨센서스
    m1: Optional[float]    # 1개월 전
    m3: Optional[float]    # 3개월 전


class ConsensusInput(TypedDict):
    """영업이익·EPS의 당해(FY1)·차기(FY2) 컨센서스, 각각 now/1M전/3M전."""
    op_fy1: TimePoint
    op_fy2: TimePoint
    eps_fy1: TimePoint
    eps_fy2: TimePoint


class DiffusionInput(TypedDict):
    """trailing 3M 추정 변경 애널리스트 수 (리비전 확산도)."""
    up_count: int
    down_count: int
    total: int


class DispersionInput(TypedDict):
    """추정치 분산·신선도 (신뢰도 게이트 입력)."""
    std: float
    mean: float
    analyst_n: int
    avg_estimate_age_days: float


class TargetPriceInput(TypedDict):
    """목표주가 현재·3M전 + 현재가."""
    tp_now: Optional[float]
    tp_3m_ago: Optional[float]
    price: Optional[float]


class ActualsYTDInput(TypedDict):
    """연초누계 실적 vs 연간 컨센서스 (포워드 압력: 진행률 기반 beat/miss)."""
    ytd_cumulative_op: Optional[float]
    fy_consensus_op: Optional[float]
    quarters_elapsed: int


class FiscalInput(TypedDict):
    """회계연도 태그·롤오버 플래그 (FY 전환 왜곡 보정)."""
    current_fy_tag: str
    fy_roll_flag: bool


class EpsRevisionInput(TypedDict):
    """개별 종목 1개의 EPS Revision 입력 묶음."""
    consensus: ConsensusInput
    diffusion: DiffusionInput
    surprise: List[Tuple[float, float]]   # 최근 4Q [(actual_op, consensus_op), ...]
    dispersion: DispersionInput
    target_price: TargetPriceInput
    actuals_ytd: ActualsYTDInput
    news_sentiment: float                 # -1~+1 (KR-FinBERT)
    fiscal: FiscalInput
    sector: str


# ── 중간/출력 스키마 ─────────────────────────────────────────
@dataclass
class LayerResult:
    """레이어 1개의 산출 — 표준화 전 원점수 + 근거 + 가용여부."""
    raw: float                              # 표준화 전 레이어 원점수
    evidence: Dict[str, object] = field(default_factory=dict)
    available: bool = True                  # 입력 결측 시 False(집계서 가중 제외)


@dataclass
class EpsRevisionResult:
    """개별 종목 최종 EPS Revision 서브스코어.

    score: 섹터 상대 -100~+100 (상위 종합스코어의 EPS 항목으로 투입).
    """
    score: float                            # 섹터 표준화 후 최종 -100~+100
    raw_score: float                        # 표준화 전 결합 원점수
    layers: Dict[str, LayerResult]          # {"realized","momentum","forward"}
    confidence: float                       # 0~1 신뢰도 게이트
    evidence: Dict[str, object]             # 통합 근거 dict
    insight: str                            # 한 줄 인사이트
    sector: str
