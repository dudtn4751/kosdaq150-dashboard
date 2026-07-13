"""수출·산업 모멘텀 스코어 — dataclass 스키마 (핸드오프 6·7절. STEP 0: 계산 없음).

값 규약:
  - 각 축 원신호/z값은 결측 시 None (0 채우기 금지 — 가중제외 재정규화는 STEP 5).
  - level형(series_type="level") 시리즈는 qual이 항상 None.
  - 점수 스케일: sector_score/company_score = cross-sector percentile 매핑 −100~+100.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AxisSignals:
    """4축 신호(원신호 또는 자기이력 z). 결측 축은 None."""
    mom: Optional[float] = None   # 모멘텀: growth=ma3_yoy · level=Δ레벨
    acc: Optional[float] = None   # 가속: growth=Δma3_yoy+저점반등 · level=2차차분
    qual: Optional[float] = None  # 품질: 물량 vs 단가 (level형은 항상 None → 가중제외)
    cyc: Optional[float] = None   # 사이클: runrate_gap(최근/24M평균 − 1)


@dataclass
class SectorProfile:
    """섹터 특성 통계(핸드오프 2절②) + 자동 가중."""
    rho: Optional[float] = None    # autocorr(ma3_yoy, lag=3) clip 0~1 — 지속성/사이클성
    pi: Optional[float] = None     # Var(price)/(Var(price)+Var(volume)) — 단가 주도성
    sigma: Optional[float] = None  # MAD(ma3_yoy) 전섹터 min-max 0~1 — 변동성
    weights: dict = field(default_factory=dict)  # {"mom","acc","qual","cyc"} Σ=1


@dataclass
class SectorScore:
    """섹터 출력(핸드오프 6절): score + 축·가중·프로파일·신뢰도·플래그·인사이트."""
    sector: str = ""
    sector_score: Optional[float] = None          # −100 ~ +100
    axes: AxisSignals = field(default_factory=AxisSignals)          # z화된 축
    weights: dict = field(default_factory=dict)   # 실제 적용 가중(결측 재정규화 후)
    profile: SectorProfile = field(default_factory=SectorProfile)
    confidence: Optional[float] = None            # 0~1 (최신성·이력·결측)
    flags: list = field(default_factory=list)     # ["base_effect", ...]
    insight: str = ""


@dataclass
class Reliability:
    """기업 렌즈 신뢰도 r = f_recency · f_length · f_direct (핸드오프 4절)."""
    r_export: Optional[float] = None   # E(수출) 렌즈
    r_industry: Optional[float] = None # I(산업) 렌즈 (스텁이면 0)


@dataclass
class CompanyScore:
    """기업 출력(핸드오프 6절): 두 렌즈(E 수출 / I 산업) 종합."""
    ticker: str = ""
    company_score: Optional[float] = None          # −100 ~ +100
    export_part: Optional[float] = None            # E 렌즈 점수(직접 or 섹터×exposure)
    industry_part: Optional[float] = None          # I 렌즈 점수(없으면 None → drop)
    exposure: Optional[float] = None               # 0~1, HS_MAP×수출비중
    reliability: Reliability = field(default_factory=Reliability)
    flags: list = field(default_factory=list)      # ["divergence", "base_effect", ...]
    insight: str = ""
