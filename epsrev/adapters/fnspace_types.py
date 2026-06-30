"""
epsrev/adapters/fnspace_types.py
================================
FnSpace 5개 엔드포인트의 **정규화된 중간표현(normalized intermediate representation)**.

위치: 원시 JSON(fixtures / 실제 응답)  →  [이 중간표현]  →  StockInput / fnspace_extra

목적:
    - 원시 필드명(`DATE`/`VAL`/`OP_EST` 등)과 **분리**한다.
      실제 FnSpace 필드명이 무엇이든, 파서(fnspace.py, 다음 STEP)가 이 타입으로 정규화하면
      하위 로직(빌더·스코어)은 필드명 변화에 영향받지 않는다.
    - "우리가 실제로 쓰는 값"만 담는다(원시 응답의 잡다한 필드는 버림).

상태:
    [DONE] 타입 정의 (이 파일)
    [TODO] 원시 JSON → 이 타입으로의 파싱  ← 다음 STEP (fnspace.py)
    [TODO] 이 타입 → fnspace_extra 변환     ← 다음 STEP

단위 주의: op/eps/tp 의 절대 단위는 엔드포인트에 따라 다를 수 있으나(억원/원 등),
    스코어는 변화율(now/3M전-1)을 쓰므로 **시계열 내 단위 일관성**만 지키면 된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── 공통 ──────────────────────────────────────────────────────────────────────
@dataclass
class DatedValue:
    """일별 시계열 한 점. date='YYYY-MM-DD'."""
    date: str
    value: float


# ── 1) forward: 12M Forward EPS 일별 시계열 ─────────────────────────────────────
@dataclass
class ForwardEPSSeries:
    code: str
    points: list[DatedValue] = field(default_factory=list)   # 12M Fwd EPS 일별 (오름차순 권장)
    # 소비처: eps_fy1(오늘) / eps_fy1_1m(≈20거래일 전) / eps_fy1_3m(≈60거래일 전)


# ── 2) estimate_daily: 영업이익(·당기순이익) 추정 일별 시계열 ─────────────────────
@dataclass
class EstimateDailySeries:
    code: str
    op: list[DatedValue] = field(default_factory=list)       # 영업이익 추정 일별
    np: list[DatedValue] = field(default_factory=list)       # 당기순이익 추정 일별 (보조, 선택)
    # 소비처: op_fy1(오늘) / op_fy1_1m / op_fy1_3m


# ── 3) estimate_fiscal: FY1/FY2 영업이익·EPS 추정 ───────────────────────────────
@dataclass
class FiscalEstimate:
    code: str
    fy1_tag: str = ""                 # 결산년월 e.g. "2026.12"
    fy1_op: Optional[float] = None    # FY1 영업이익 추정  → fy_consensus_op
    fy1_eps: Optional[float] = None   # FY1 EPS 추정
    fy2_tag: str = ""                 # e.g. "2027.12"
    fy2_op: Optional[float] = None    # FY2 영업이익 추정  → op_fy2
    fy2_eps: Optional[float] = None   # FY2 EPS 추정       → eps_fy2


# ── 4) opinion_tp: 목표주가 / 참여 증권사 / 목표주가 리비전 카운트 ────────────────
@dataclass
class TPRevisionCounts:
    """목표주가 상향/하향/전체 (특정 기간)."""
    up: int = 0
    down: int = 0
    total: int = 0


@dataclass
class OpinionTargetPrice:
    code: str
    tp_points: list[DatedValue] = field(default_factory=list)  # 목표주가(Adj.) 일별
    analyst_n: Optional[int] = None                            # 참여 증권사 수 → analyst_n
    rev_1w: Optional[TPRevisionCounts] = None                  # 1주
    rev_1m: Optional[TPRevisionCounts] = None                  # 1개월 → diffusion(proxy)
    rev_3m: Optional[TPRevisionCounts] = None                  # 3개월 → diffusion trend(1M vs 3M)
    # 소비처: tp_now(오늘) / tp_3m_ago(≈60거래일 전), analyst_n, diffusion proxy


# ── 5) financial: 최근 4분기 실제 영업이익 + 어닝 서프라이즈 ─────────────────────
@dataclass
class QuarterActual:
    quarter: str                          # "25Q3"
    actual_op: Optional[float] = None     # 실제 영업이익
    consensus_op: Optional[float] = None  # 직전 컨센서스 영업이익 (서프라이즈 기준)
    surprise_pct: Optional[float] = None  # 어닝 서프라이즈 % (있으면 그대로, 없으면 다음 STEP에서 산출)


@dataclass
class FinancialActuals:
    code: str
    quarters: list[QuarterActual] = field(default_factory=list)  # 최근 4Q(오름차순 권장)
    # 소비처: surprise_4q = [(actual_op, consensus_op), ...] 최근 4Q


# ── 5개 묶음 (한 종목의 정규화 결과 일체) ───────────────────────────────────────
@dataclass
class FnSpaceNormalized:
    """한 종목에 대한 5개 엔드포인트 정규화 결과 묶음. 결측 엔드포인트는 None."""
    code: str
    forward: Optional[ForwardEPSSeries] = None
    estimate_daily: Optional[EstimateDailySeries] = None
    fiscal: Optional[FiscalEstimate] = None
    opinion_tp: Optional[OpinionTargetPrice] = None
    financial: Optional[FinancialActuals] = None
