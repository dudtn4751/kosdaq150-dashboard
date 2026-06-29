"""
eps_revision_score.py
=====================
EPS Revision 서브스코어 계산 모듈 (스캐폴드)

이 점수는 상위 종합스코어의 EPS 항목으로 들어간다:
    종합 = EPS×35 + 상대강도×20 + 이벤트×12 + 퀄리티×10

설계 철학 (핸드오프 문서 참고):
    재무 절대값이 아니라 "컨센서스가 변하는 방향·속도·앞으로 더 변할 압력"을 점수화한다.
    Layer1 실현리비전 / Layer2 모멘텀 / Layer3 포워드압력 → 신뢰도게이트 → 섹터표준화·집계.

작업 규칙:
    - 순수 함수. 외부 I/O 없음(데이터는 dataclass로 주입).
    - 결측은 None 반환. 집계 시 가중 0으로 빼고 재정규화(0으로 채우지 말 것).
    - 점수 입력은 컨센 추정치 변화율(now/3M전-1). YoY 성장률 사용 금지.

상태:
    [DONE]  스키마, Layer1/2/3 raw 함수(참조 구현)
    [TODO]  confidence_multiplier, sector_standardize, aggregate, integrity_guard,
            generate_insight, compute_eps_revision_score  ← STEP 4~6에서 Claude Code로 채움
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import math
import numpy as np


# =============================================================================
# 데이터 스키마  (실제 FnGuide/Bloomberg 필드명에 맞춰 STEP 0에서 조정)
# =============================================================================
@dataclass
class Consensus:
    op_fy1: float
    op_fy1_1m: float
    op_fy1_3m: float
    op_fy2: float
    eps_fy1: float
    eps_fy1_1m: float
    eps_fy1_3m: float
    eps_fy2: float


@dataclass
class Diffusion:
    up_count: int
    down_count: int
    total: int


@dataclass
class Dispersion:
    std: float
    mean: float
    analyst_n: int
    avg_estimate_age_days: float


@dataclass
class TargetPrice:
    tp_now: float
    tp_3m_ago: float
    price: float


@dataclass
class ActualsYTD:
    ytd_cumulative_op: float      # 회계연도 누적 영업이익(실적)
    fy_consensus_op: float        # 연간 영업이익 컨센서스
    quarters_elapsed: int         # 경과 분기(1~4)
    prior_fy_actual_op: float     # 직전연도 연간 실적(베이스효과 체크용)


@dataclass
class Fiscal:
    current_fy_tag: str
    fy_roll_flag: bool            # FY1->FY2 롤오버 구간 여부


@dataclass
class StockInput:
    ticker: str
    sector: str
    consensus: Consensus
    diffusion: Diffusion
    dispersion: Dispersion
    target_price: TargetPrice
    actuals_ytd: ActualsYTD
    fiscal: Fiscal
    surprise_4q: list[tuple[float, float]]   # [(actual_op, consensus_op), ...] 최근 4개 분기
    news_sentiment: float                    # KR-FinBERT, -1~+1
    # 외부 주입: 섹터별 리비전 자기상관계수(0~1). 모듈 내부에서 추정 금지.
    sector_revision_autocorr: float = 0.0


# =============================================================================
# 수급 스코어 데이터 스키마 + 계산 로직
# =============================================================================
@dataclass
class SupplyInput:
    """
    수급 서브스코어 입력값.

    단위 규칙:
    - net_buy, trading_value, adv20, market_cap, balance 값은 서로 같은 금액 단위여야 한다.
      예: 전부 원, 전부 백만원, 전부 억원 중 하나로 통일.
    - *_ratio, *_change 값은 소수로 입력한다. 예: 5% = 0.05, -12% = -0.12.
    - distance_to_20d_high는 현재가/20일고가 - 1. 예: 고가 대비 -3% = -0.03.

    설계:
    - 수급 점수 25점 = 외국인·기관 10 + 지속성 3 + 거래·가격반응 5 + 대차·공매도 4 + 신용·개인과열 3.
    - ETF·패시브 일반 수급은 기본 수급 점수에서 제외. 지수 편입/리밸런싱 등은 이벤트 보너스로 별도 처리.
    - 결측값은 중립점수(해당 배점의 50%)로 처리하고 flags에 남긴다.
    """
    ticker: str
    sector: str = ""

    # 기준 유동성/규모
    adv20: Optional[float] = None                         # 20일 평균 거래대금
    market_cap: Optional[float] = None                    # 시가총액

    # 외국인·기관 순매수
    foreign_net_buy_5d: Optional[float] = None
    institution_net_buy_5d: Optional[float] = None
    foreign_institution_net_buy_20d: Optional[float] = None
    foreign_institution_net_buy_5d: Optional[float] = None
    foreign_institution_net_buy_prev_5d: Optional[float] = None
    foreign_institution_buy_days_10: Optional[int] = None  # 최근 10거래일 중 외국인+기관 순매수 일수

    # 거래대금·가격 반응
    trading_value_today: Optional[float] = None
    return_5d: Optional[float] = None
    return_20d: Optional[float] = None
    distance_to_20d_high: Optional[float] = None           # 현재가/20일고가 - 1

    # 대차·공매도 부담
    loan_balance_mcap_ratio: Optional[float] = None        # 대차잔고/시총
    loan_balance_change_5d: Optional[float] = None
    loan_balance_change_20d: Optional[float] = None
    short_sell_value_ratio: Optional[float] = None         # 공매도 거래대금/전체 거래대금
    short_interest_ratio: Optional[float] = None           # 공매도 잔고/시총, 있으면 보조 사용

    # 신용·개인 과열
    credit_balance_mcap_ratio: Optional[float] = None      # 신용잔고/시총
    credit_balance_change_5d: Optional[float] = None
    credit_balance_change_20d: Optional[float] = None
    individual_net_buy_5d: Optional[float] = None


SUPPLY_WEIGHTS = {
    "foreign_institution_flow": 10.0,
    "flow_persistence": 3.0,
    "trading_price_reaction": 5.0,
    "borrow_short_pressure": 4.0,
    "credit_retail_overheat": 3.0,
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _score_between(
    value: Optional[float],
    *,
    bad: float,
    good: float,
    points: float,
    flags: Optional[list[str]] = None,
    label: str = "",
) -> float:
    """
    bad 값이면 0점, good 값이면 만점, 중간은 선형 보간.
    good < bad인 역방향 지표도 지원한다. None은 중립점수.
    """
    if value is None or not math.isfinite(value):
        if flags is not None and label:
            flags.append(f"{label} 결측 — 중립점수 적용")
        return points * 0.5
    if good == bad:
        return points * 0.5
    ratio = (value - bad) / (good - bad)
    return _clamp(ratio, 0.0, 1.0) * points


def _safe_divide(numer: Optional[float], denom: Optional[float]) -> Optional[float]:
    """numer/denom. 분모가 0/None/음수면 None."""
    if numer is None or denom is None:
        return None
    if denom <= 0:
        return None
    return numer / denom


def _avg_optional(values: list[Optional[float]]) -> Optional[float]:
    valid = [v for v in values if v is not None and math.isfinite(v)]
    return sum(valid) / len(valid) if valid else None


def compute_supply_score(s: SupplyInput) -> dict:
    """
    수급 서브스코어 0~25점 계산.

    반환 스키마:
    {
      "supply_score": float,       # 0~25
      "buckets": {...},           # 5개 버킷별 점수
      "evidence": {...},          # 화면 카드용 정규화 지표
      "insight": str,
      "flags": [...],
      "weights": SUPPLY_WEIGHTS,
    }
    """
    flags: list[str] = []

    # -------------------------------------------------------------------------
    # Evidence: 금액 → ADV20 대비 강도, ratio는 그대로 사용
    # -------------------------------------------------------------------------
    foreign_5d_adv = _safe_divide(s.foreign_net_buy_5d, s.adv20)
    institution_5d_adv = _safe_divide(s.institution_net_buy_5d, s.adv20)
    fi_20d_adv = _safe_divide(s.foreign_institution_net_buy_20d, s.adv20)
    fi_5d_adv = _safe_divide(s.foreign_institution_net_buy_5d, s.adv20)
    fi_prev_5d_adv = _safe_divide(s.foreign_institution_net_buy_prev_5d, s.adv20)
    fi_5d_accel = None if fi_5d_adv is None or fi_prev_5d_adv is None else fi_5d_adv - fi_prev_5d_adv

    trading_value_ratio = _safe_divide(s.trading_value_today, s.adv20)
    price_momentum = _avg_optional([s.return_5d, s.return_20d])
    loan_change = _avg_optional([s.loan_balance_change_5d, s.loan_balance_change_20d])
    credit_change = _avg_optional([s.credit_balance_change_5d, s.credit_balance_change_20d])
    individual_5d_adv = _safe_divide(s.individual_net_buy_5d, s.adv20)

    # 공매도는 거래대금 비중을 우선 사용하고, 없으면 잔고비율을 보조로 사용
    short_pressure = s.short_sell_value_ratio if s.short_sell_value_ratio is not None else s.short_interest_ratio

    evidence = {
        "foreign_5d_adv": foreign_5d_adv,
        "institution_5d_adv": institution_5d_adv,
        "foreign_institution_20d_adv": fi_20d_adv,
        "foreign_institution_5d_adv": fi_5d_adv,
        "foreign_institution_prev_5d_adv": fi_prev_5d_adv,
        "foreign_institution_5d_accel": fi_5d_accel,
        "foreign_institution_buy_days_10": s.foreign_institution_buy_days_10,
        "trading_value_ratio": trading_value_ratio,
        "return_5d": s.return_5d,
        "return_20d": s.return_20d,
        "price_momentum": price_momentum,
        "distance_to_20d_high": s.distance_to_20d_high,
        "loan_balance_mcap_ratio": s.loan_balance_mcap_ratio,
        "loan_balance_change": loan_change,
        "short_pressure": short_pressure,
        "credit_balance_mcap_ratio": s.credit_balance_mcap_ratio,
        "credit_balance_change": credit_change,
        "individual_5d_adv": individual_5d_adv,
    }

    # -------------------------------------------------------------------------
    # 1) 외국인·기관 순매수 강도 10점
    # -------------------------------------------------------------------------
    flow_score = 0.0
    flow_score += _score_between(foreign_5d_adv, bad=-0.30, good=0.50, points=3.0, flags=flags, label="외국인 5일 순매수/ADV20")
    flow_score += _score_between(institution_5d_adv, bad=-0.30, good=0.50, points=2.0, flags=flags, label="기관 5일 순매수/ADV20")
    flow_score += _score_between(fi_20d_adv, bad=-1.00, good=1.50, points=3.0, flags=flags, label="외국인+기관 20일 순매수/ADV20")

    # 동반 순매수: 둘 다 양수 2점, 하나만 양수 1점, 둘 다 음수 0점, 결측 중립 1점
    if foreign_5d_adv is None or institution_5d_adv is None:
        flags.append("외국인·기관 동반 순매수 여부 결측 — 중립점수 적용")
        flow_score += 1.0
    elif foreign_5d_adv > 0 and institution_5d_adv > 0:
        flow_score += 2.0
    elif foreign_5d_adv > 0 or institution_5d_adv > 0:
        flow_score += 1.0

    # -------------------------------------------------------------------------
    # 2) 수급 지속성·전환 3점
    # -------------------------------------------------------------------------
    if s.foreign_institution_buy_days_10 is None:
        flags.append("최근 10일 순매수일수 결측 — 중립점수 적용")
        buy_days_score = 0.75
    else:
        buy_days_score = _clamp(s.foreign_institution_buy_days_10, 0, 10) / 10.0 * 1.5

    accel_score = _score_between(fi_5d_accel, bad=-0.30, good=0.30, points=1.5, flags=flags, label="최근 5일 수급강도 개선")
    persistence_score = buy_days_score + accel_score

    # -------------------------------------------------------------------------
    # 3) 거래대금·가격 반응 5점
    # -------------------------------------------------------------------------
    trading_price_score = 0.0
    trading_price_score += _score_between(trading_value_ratio, bad=0.50, good=2.00, points=2.0, flags=flags, label="거래대금/ADV20")
    trading_price_score += _score_between(price_momentum, bad=-0.15, good=0.20, points=2.0, flags=flags, label="5일·20일 가격 모멘텀")
    trading_price_score += _score_between(s.distance_to_20d_high, bad=-0.20, good=0.00, points=1.0, flags=flags, label="20일 신고가 근접도")

    # -------------------------------------------------------------------------
    # 4) 대차·공매도 부담 4점 — 낮을수록 좋고, 감소하면 긍정
    # -------------------------------------------------------------------------
    borrow_short_score = 0.0
    borrow_short_score += _score_between(s.loan_balance_mcap_ratio, bad=0.05, good=0.005, points=1.5, flags=flags, label="대차잔고/시총")
    borrow_short_score += _score_between(loan_change, bad=0.20, good=-0.20, points=1.5, flags=flags, label="대차잔고 변화율")
    borrow_short_score += _score_between(short_pressure, bad=0.20, good=0.02, points=1.0, flags=flags, label="공매도 부담")

    # 높은 대차잔고가 감소하면서 주가가 오르는 경우는 숏커버 가능성으로 소폭 보정
    if (
        s.loan_balance_mcap_ratio is not None and s.loan_balance_mcap_ratio >= 0.03
        and loan_change is not None and loan_change < -0.05
        and price_momentum is not None and price_momentum > 0
    ):
        borrow_short_score = min(4.0, borrow_short_score + 0.3)
        flags.append("대차잔고 감소+주가 상승 — 숏커버 가능성 보정")

    # -------------------------------------------------------------------------
    # 5) 신용·개인 과열 3점 — 낮을수록 좋고, 개인 쏠림은 감점
    # -------------------------------------------------------------------------
    credit_retail_score = 0.0
    credit_retail_score += _score_between(s.credit_balance_mcap_ratio, bad=0.10, good=0.01, points=1.2, flags=flags, label="신용잔고/시총")
    credit_retail_score += _score_between(credit_change, bad=0.20, good=-0.10, points=1.2, flags=flags, label="신용잔고 변화율")
    credit_retail_score += _score_between(individual_5d_adv, bad=0.50, good=-0.30, points=0.6, flags=flags, label="개인 5일 순매수/ADV20")

    buckets = {
        "foreign_institution_flow": round(flow_score, 4),
        "flow_persistence": round(persistence_score, 4),
        "trading_price_reaction": round(trading_price_score, 4),
        "borrow_short_pressure": round(borrow_short_score, 4),
        "credit_retail_overheat": round(credit_retail_score, 4),
    }
    supply_score = round(sum(buckets.values()), 4)
    supply_score = _clamp(supply_score, 0.0, 25.0)

    insight = generate_supply_insight(supply_score, buckets, evidence)

    return {
        "supply_score": supply_score,
        "buckets": buckets,
        "evidence": evidence,
        "insight": insight,
        "flags": flags,
        "weights": SUPPLY_WEIGHTS,
    }


def generate_supply_insight(score: float, buckets: dict[str, float], evidence: dict) -> str:
    """수급 점수 요약 문장."""
    lead_bucket = max(buckets, key=lambda k: buckets[k]) if buckets else "foreign_institution_flow"
    weak_bucket = min(buckets, key=lambda k: buckets[k]) if buckets else "borrow_short_pressure"

    bucket_label = {
        "foreign_institution_flow": "외국인·기관 순매수",
        "flow_persistence": "수급 지속성",
        "trading_price_reaction": "거래대금·가격 반응",
        "borrow_short_pressure": "대차·공매도 부담",
        "credit_retail_overheat": "신용·개인 과열",
    }

    if score >= 19:
        tone = "수급 우수"
    elif score >= 15:
        tone = "수급 양호"
    elif score >= 11:
        tone = "수급 중립"
    elif score >= 7:
        tone = "수급 부담"
    else:
        tone = "수급 취약"

    fi20 = evidence.get("foreign_institution_20d_adv")
    loan = evidence.get("loan_balance_mcap_ratio")
    credit = evidence.get("credit_balance_mcap_ratio")

    details = []
    if fi20 is not None:
        details.append(f"외국인+기관 20일 순매수 {fi20:+.1%}/ADV20")
    if loan is not None:
        details.append(f"대차잔고/시총 {loan:.1%}")
    if credit is not None:
        details.append(f"신용잔고/시총 {credit:.1%}")

    detail_txt = ", ".join(details) if details else "핵심 수급 데이터 결측"
    return f"{tone}: {bucket_label[lead_bucket]} 기여가 크고, {bucket_label[weak_bucket]} 항목은 점검 필요. ({detail_txt})"


# =============================================================================
# 공통 가드 유틸
# =============================================================================
def _safe_ratio(numer: Optional[float], denom: Optional[float]) -> Optional[float]:
    """now/base - 1 형태의 변화율. 분모가 0/None/음수면 None."""
    if numer is None or denom is None:
        return None
    if denom <= 0:
        return None
    return numer / denom - 1.0


# =============================================================================
# Layer 1 — 실현 리비전  [참조 구현 완료]
# =============================================================================
def layer1_realized(s: StockInput) -> dict[str, Optional[float]]:
    c = s.consensus
    d = s.diffusion

    rev_op_1m = _safe_ratio(c.op_fy1, c.op_fy1_1m)
    rev_op_3m = _safe_ratio(c.op_fy1, c.op_fy1_3m)
    rev_eps_1m = _safe_ratio(c.eps_fy1, c.eps_fy1_1m)
    rev_eps_3m = _safe_ratio(c.eps_fy1, c.eps_fy1_3m)

    diffusion_idx = (d.up_count - d.down_count) / d.total if d.total else None

    # SUE: 최근 4Q 평균 (actual - consensus)/|consensus|
    sue_terms = [
        (a - cons) / abs(cons)
        for a, cons in s.surprise_4q
        if cons not in (0, None)
    ]
    sue = sum(sue_terms) / len(sue_terms) if sue_terms else None

    return {
        "rev_op_1m": rev_op_1m,
        "rev_op_3m": rev_op_3m,
        "rev_eps_1m": rev_eps_1m,
        "rev_eps_3m": rev_eps_3m,
        "diffusion_idx": diffusion_idx,
        "sue": sue,
    }


# =============================================================================
# Layer 2 — 리비전 모멘텀 (가속/감속)  [참조 구현 완료]
# =============================================================================
def layer2_momentum(s: StockInput, l1: dict) -> dict[str, Optional[float]]:
    rev_op_1m = l1.get("rev_op_1m")
    rev_op_3m = l1.get("rev_op_3m")

    # 단순 연율화: 1M 속도 = ×12, 3M 속도 = ×4. 양수면 상향 가속.
    if rev_op_1m is None or rev_op_3m is None:
        accel = None
    else:
        accel = (rev_op_1m * 12) - (rev_op_3m * 4)

    disp = s.dispersion
    disp_cv = disp.std / abs(disp.mean) if disp.mean not in (0, None) else None

    # diffusion_trend: 이전 분기 diffusion 데이터가 생기면 채움(현재는 None)
    diffusion_trend = None

    return {
        "accel": accel,
        "disp_cv": disp_cv,
        "diffusion_trend": diffusion_trend,
    }


# =============================================================================
# Layer 3 — 포워드 압력 (★핵심)  [참조 구현 완료]
# =============================================================================
def layer3_forward(s: StockInput, l1: dict) -> dict[str, Optional[float]]:
    a = s.actuals_ytd
    tp = s.target_price

    # runrate_gap: YTD 실적이 연간 컨센 내재 런레이트를 상회하면 양수 -> 상향 압력
    if a.fy_consensus_op and a.quarters_elapsed:
        implied = a.fy_consensus_op * a.quarters_elapsed / 4.0
        runrate_gap = (a.ytd_cumulative_op / implied - 1.0) if implied > 0 else None
    else:
        runrate_gap = None

    # tp_lead: 목표주가 리비전이 EPS 리비전을 선행하면 양수
    tp_chg = _safe_ratio(tp.tp_now, tp.tp_3m_ago)
    rev_eps_3m = l1.get("rev_eps_3m")
    tp_lead = (tp_chg - rev_eps_3m) if (tp_chg is not None and rev_eps_3m is not None) else None

    # persistence: 섹터 자기상관계수(외부 주입) × 최근 3M 리비전
    rev_op_3m = l1.get("rev_op_3m")
    persistence = (s.sector_revision_autocorr * rev_op_3m) if rev_op_3m is not None else None

    news_lead = s.news_sentiment  # 보조 신호(가중 낮게)

    return {
        "runrate_gap": runrate_gap,
        "tp_lead": tp_lead,
        "persistence": persistence,
        "news_lead": news_lead,
    }


# =============================================================================
# STEP 4 — 신뢰도 게이트  [TODO: Claude Code]
# =============================================================================
def confidence_multiplier(s: StockInput) -> float:
    """
    0.5~1.0 멀티플라이어. 최종 점수에 곱한다.
    - analyst_n < 3 -> 강한 캡(0.5~0.6), 25개사 이상 -> 1.0 수렴
    - avg_estimate_age_days 길수록 디스카운트(90일 초과 감점)
    - fiscal.fy_roll_flag True -> 디스카운트
    - dispersion CV 비정상 과대 -> 디스카운트
    각 요소 0~1 페널티를 곱하고 0.5~1.0로 클립.
    """
    disp = s.dispersion

    # (1) 커버리지 페널티
    n = disp.analyst_n
    if n < 3:
        coverage_p = 0.50
    elif n < 10:
        coverage_p = 0.50 + (n - 3) / (10 - 3) * (0.80 - 0.50)
    elif n < 25:
        coverage_p = 0.80 + (n - 10) / (25 - 10) * (1.00 - 0.80)
    else:
        coverage_p = 1.00

    # (2) 신선도 페널티
    age = disp.avg_estimate_age_days
    if age <= 30:
        freshness_p = 1.00
    elif age <= 90:
        freshness_p = 1.00 + (age - 30) / (90 - 30) * (0.85 - 1.00)
    elif age <= 180:
        freshness_p = 0.85 + (age - 90) / (180 - 90) * (0.70 - 0.85)
    else:
        freshness_p = 0.65

    # (3) 롤오버 페널티
    rollover_p = 0.85 if s.fiscal.fy_roll_flag else 1.00

    # (4) 분산 페널티
    if disp.mean == 0:
        dispersion_p = 1.00
    else:
        cv = disp.std / abs(disp.mean)
        if cv < 0.10:
            dispersion_p = 1.00
        elif cv < 0.30:
            dispersion_p = 1.00 + (cv - 0.10) / (0.30 - 0.10) * (0.85 - 1.00)
        else:
            dispersion_p = 0.75

    raw = coverage_p * freshness_p * rollover_p * dispersion_p
    return max(0.5, min(1.0, raw))


# =============================================================================
# STEP 5 — 섹터 표준화 + 집계  [TODO: Claude Code]
# =============================================================================
def sector_standardize(values: list[float]) -> list[float]:
    """섹터 내 robust z-score(winsorize ±3σ 선적용). 단일종목/배치 둘 다."""
    non_none = [v for v in values if v is not None]
    if len(non_none) <= 1:
        return [0.0 if v is not None else None for v in values]

    arr = np.array(non_none, dtype=float)
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med)))

    lower = med - 3.0 * mad
    upper = med + 3.0 * mad
    scale = 1.4826 * mad

    result = []
    for v in values:
        if v is None:
            result.append(None)
            continue
        v_w = float(np.clip(v, lower, upper))
        result.append(0.0 if scale == 0.0 else (v_w - med) / scale)
    return result


# 레이어 가중치 (forward 강조)
LAYER_WEIGHTS = {"realized": 0.40, "momentum": 0.25, "forward": 0.35}


_L1_KEYS = ["rev_op_1m", "rev_op_3m", "rev_eps_1m", "rev_eps_3m", "diffusion_idx", "sue"]
_L2_KEYS = ["accel", "disp_cv", "diffusion_trend"]
_L3_KEYS = ["runrate_gap", "tp_lead", "persistence", "news_lead"]


def aggregate(
    stocks: list[StockInput],
    layers_batch: list[dict],
) -> list[dict]:
    """
    1) 각 컴포넌트를 섹터 내 robust z-score로 표준화
    2) 레이어 내부 균등가중 평균 (결측은 가중 0으로 재정규화)
    3) 레이어 가중합(realized .40 / momentum .25 / forward .35), 결측 레이어 재정규화
    4) × confidence_multiplier
    5) 섹터 percentile → -100~+100 선형 매핑
    """
    N = len(stocks)
    all_l1 = [lb["l1"] for lb in layers_batch]
    all_l2 = [lb["l2"] for lb in layers_batch]
    all_l3 = [lb["l3"] for lb in layers_batch]

    # Step 1: 컴포넌트별 섹터 표준화
    def _std_layer(layer_dicts, keys):
        return {k: sector_standardize([d.get(k) for d in layer_dicts]) for k in keys}

    std_l1 = _std_layer(all_l1, _L1_KEYS)
    std_l2 = _std_layer(all_l2, _L2_KEYS)
    std_l3 = _std_layer(all_l3, _L3_KEYS)

    def _mean_nonnull(vals):
        valid = [v for v in vals if v is not None]
        return sum(valid) / len(valid) if valid else None

    raw_scores = []
    results = []

    for i, s in enumerate(stocks):
        # Step 2: 레이어 내부 균등가중 평균
        l1_s = _mean_nonnull([std_l1[k][i] for k in _L1_KEYS])
        l2_s = _mean_nonnull([std_l2[k][i] for k in _L2_KEYS])
        l3_s = _mean_nonnull([std_l3[k][i] for k in _L3_KEYS])

        # Step 3: 레이어 가중합, 결측 레이어 재정규화
        layers = [("realized", l1_s, 0.40), ("momentum", l2_s, 0.25), ("forward", l3_s, 0.35)]
        total_w = sum(w for _, v, w in layers if v is not None)
        if total_w == 0.0:
            raw = 0.0
        else:
            raw = sum(w / total_w * v for _, v, w in layers if v is not None)

        # Step 4: 신뢰도 게이트
        raw *= confidence_multiplier(s)
        raw_scores.append(raw)
        results.append({
            "layer_scores": {"realized": l1_s, "momentum": l2_s, "forward": l3_s},
        })

    # Step 5: 섹터 percentile → -100~+100
    if N == 1:
        final_scores = [0.0]
    else:
        final_scores = []
        for v in raw_scores:
            below = sum(1 for x in raw_scores if x < v)
            equal = sum(1 for x in raw_scores if x == v)
            pct = (below + (equal - 1) / 2) / (N - 1) * 100.0
            final_scores.append(pct * 2 - 100.0)

    for res, fs in zip(results, final_scores):
        res["raw_score"] = fs

    return results


# =============================================================================
# STEP 6 — 정합성 가드 + 인사이트  [TODO: Claude Code]
# =============================================================================
def integrity_guard(s: StockInput) -> list[str]:
    """
    YoY 정합성 체크: |fy_consensus_op / prior_fy_actual_op - 1| 을 계산해,
    표기 YoY와 크게 불일치하거나 베이스(prior_fy_actual_op)가 비정상적으로 작으면
    '트로프 베이스효과 의심 — YoY 점수 미반영' 플래그를 추가.
    단위·통화 일관성 assert도 여기서.
    """
    flags: list[str] = []
    a = s.actuals_ytd
    c = s.consensus

    # 체크 1: 트로프 베이스효과 (YoY 내재 성장률 > 200%)
    if a.prior_fy_actual_op > 0:
        yoy_implied = a.fy_consensus_op / a.prior_fy_actual_op - 1.0
        if yoy_implied > 2.0:
            flags.append("트로프 베이스효과 의심 — YoY 점수 미반영")

    # 체크 2: 직전연도 실적이 비정상적으로 작음
    if a.prior_fy_actual_op > 0 and a.prior_fy_actual_op < a.fy_consensus_op * 0.3:
        flags.append("직전연도 실적이 현재 컨센의 30% 미만 — 베이스 정상 여부 확인 필요")

    # 체크 3: EPS / OP 단위 불일치
    if c.op_fy1 > 0 and c.eps_fy1 is not None:
        ratio = c.eps_fy1 / c.op_fy1
        if ratio < 0.1 or ratio > 10:
            flags.append("EPS/OP 단위 불일치 의심 — 스키마 확인 필요")

    return flags


_LAYER_COMP_MAP: dict[str, list[str]] = {
    "realized": ["rev_op_3m", "rev_eps_3m", "diffusion_idx", "sue"],
    "momentum": ["accel", "disp_cv"],
    "forward":  ["runrate_gap", "tp_lead", "persistence", "news_lead"],
}

_LAYER_LABEL: dict[str, str] = {
    "realized": "실현 리비전",
    "momentum": "리비전 모멘텀",
    "forward":  "포워드 압력",
}

_COMP_LABEL: dict[str, str] = {
    "rev_op_3m":    "3M 영업이익 컨센 상향",
    "rev_eps_3m":   "3M EPS 컨센 상향",
    "diffusion_idx":"애널리스트 확산지수",
    "sue":          "어닝 서프라이즈",
    "accel":        "리비전 가속",
    "disp_cv":      "추정치 분산",
    "runrate_gap":  "YTD 런레이트 초과",
    "tp_lead":      "목표주가 선행 상향",
    "persistence":  "섹터 리비전 지속성",
    "news_lead":    "뉴스 센티먼트",
}


def generate_insight(layers: dict, flags: list[str], evidence: dict) -> str:
    """
    기여도 최상위 레이어/컴포넌트를 골라 자연어 한 문장.
    예: "3M 컨센 +78% 상향이 가속 중, YTD 런레이트가 연간 컨센 상회 → 추가 상향 여력.
         단 YoY는 트로프 베이스효과로 미반영."
    flags 있으면 끝에 경고 덧붙임.
    """
    # 주도 레이어: 유효(non-None) 중 최댓값, 전부 None이면 realized 기본
    valid_layers = {k: v for k, v in layers.items() if v is not None}
    if valid_layers:
        lead_layer = max(valid_layers, key=lambda k: valid_layers[k])
        lead_val: float = valid_layers[lead_layer]
    else:
        lead_layer, lead_val = "realized", 0.0

    # 주도 컴포넌트: 해당 레이어 내 절댓값 최대
    comp_vals = {
        k: evidence[k]
        for k in _LAYER_COMP_MAP[lead_layer]
        if evidence.get(k) is not None
    }
    if comp_vals:
        lead_comp = max(comp_vals, key=lambda k: abs(comp_vals[k]))
        val = comp_vals[lead_comp]
        # 비율값(≤5)은 %, 그 외 소수점 2자리
        val_str = f"{val:+.1%}" if abs(val) <= 5.0 else f"{val:+.2f}"
        comp_desc = f"{_COMP_LABEL[lead_comp]}({val_str})"
    else:
        comp_desc = _LAYER_LABEL[lead_layer]

    direction = "상향 압력 유효" if lead_val >= 0 else "하향 압력 우세"
    sentence = f"{comp_desc} 주도, {_LAYER_LABEL[lead_layer]} 우위 → {direction}."

    # 단일종목 모드 플래그는 인사이트 문장에서 제외 (별도 필드에 표시)
    warn_flags = [f for f in flags if "단일종목" not in f]
    if warn_flags:
        sentence += " 단, " + " / ".join(warn_flags) + "."

    return sentence


# =============================================================================
# 메인 진입점  [TODO: STEP 6에서 조립]
# =============================================================================
def compute_eps_revision_score(
    s: StockInput,
    sector_dist: Optional[list[StockInput]] = None,
) -> dict:
    """
    반환 스키마:
    {
      "eps_score": float,                                  # -100~+100
      "layers": {"realized": .., "momentum": .., "forward": ..},
      "confidence": float,                                 # 0.5~1.0
      "evidence": {...},                                   # 화면 '근거자료' 패널용 원천값
      "insight": str,
      "flags": [...]
    }
    sector_dist=None: 단일종목 모드 — 섹터 상대화 불가, eps_score=0.0.
    """
    # Layer 원천값 계산
    l1 = layer1_realized(s)
    l2 = layer2_momentum(s, l1)
    l3 = layer3_forward(s, l1)

    # 근거자료 패널용 원천값 (None 포함)
    evidence: dict = {
        "rev_op_3m":    l1.get("rev_op_3m"),
        "rev_eps_3m":   l1.get("rev_eps_3m"),
        "diffusion_idx":l1.get("diffusion_idx"),
        "sue":          l1.get("sue"),
        "accel":        l2.get("accel"),
        "disp_cv":      l2.get("disp_cv"),
        "runrate_gap":  l3.get("runrate_gap"),
        "tp_lead":      l3.get("tp_lead"),
        "persistence":  l3.get("persistence"),
        "news_lead":    l3.get("news_lead"),
    }

    flags = integrity_guard(s)
    conf = confidence_multiplier(s)

    if sector_dist is None:
        # 단일종목 모드: 표준화 불가
        flags.append("단일종목 모드 — 섹터 상대화 불가")
        layer_scores: dict = {"realized": None, "momentum": None, "forward": None}
        eps_score = 0.0
    else:
        # 배치 모드: s를 인덱스 0으로 고정해 aggregate 호출
        all_stocks = [s] + list(sector_dist)
        all_layers_data = [{"l1": l1, "l2": l2, "l3": l3}]
        for sx in sector_dist:
            lx1 = layer1_realized(sx)
            lx2 = layer2_momentum(sx, lx1)
            lx3 = layer3_forward(sx, lx1)
            all_layers_data.append({"l1": lx1, "l2": lx2, "l3": lx3})

        agg_results = aggregate(all_stocks, all_layers_data)
        res_s = agg_results[0]           # s는 인덱스 0
        eps_score = res_s["raw_score"]
        layer_scores = res_s["layer_scores"]

    insight = generate_insight(layer_scores, flags, evidence)

    return {
        "eps_score":  eps_score,
        "layers":     layer_scores,
        "confidence": conf,
        "evidence":   evidence,
        "insight":    insight,
        "flags":      flags,
    }


# =============================================================================
# 단위테스트 골격  (pytest)   ── 각 STEP에서 채워 통과시킬 것
# =============================================================================
def _sample_stock(**overrides) -> StockInput:
    """테스트용 기본 종목. overrides로 케이스별 변형."""
    base = StockInput(
        ticker="005930",
        sector="IT",
        consensus=Consensus(
            op_fy1=85.5, op_fy1_1m=70.0, op_fy1_3m=47.9,
            op_fy2=95.0,
            eps_fy1=44459, eps_fy1_1m=40000, eps_fy1_3m=30000,
            eps_fy2=50000,
        ),
        diffusion=Diffusion(up_count=20, down_count=3, total=25),
        dispersion=Dispersion(std=4.0, mean=85.5, analyst_n=25, avg_estimate_age_days=20),
        target_price=TargetPrice(tp_now=455000, tp_3m_ago=380000, price=325500),
        actuals_ytd=ActualsYTD(
            ytd_cumulative_op=24.0, fy_consensus_op=85.5,
            quarters_elapsed=1, prior_fy_actual_op=43.6,
        ),
        fiscal=Fiscal(current_fy_tag="FY26", fy_roll_flag=False),
        surprise_4q=[(12.0, 10.0), (11.0, 10.5), (9.0, 9.5), (10.0, 8.0)],
        news_sentiment=0.28,
        sector_revision_autocorr=0.45,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_layer1_normal():
    l1 = layer1_realized(_sample_stock())
    assert l1["rev_op_3m"] is not None and l1["rev_op_3m"] > 0      # 상향
    assert l1["diffusion_idx"] == (20 - 3) / 25
    assert l1["sue"] is not None


def test_layer1_zero_denominator():
    s = _sample_stock()
    s.consensus.op_fy1_3m = 0.0
    l1 = layer1_realized(s)
    assert l1["rev_op_3m"] is None                                  # 분모 0 -> None


def test_layer3_runrate_gap():
    l1 = layer1_realized(_sample_stock())
    l3 = layer3_forward(_sample_stock(), l1)
    # YTD 24.0 vs 런레이트 85.5*1/4=21.375 -> 상회 -> 양수
    assert l3["runrate_gap"] is not None and l3["runrate_gap"] > 0


def test_confidence_full():
    s = _sample_stock()
    # analyst_n=25, age=20, roll=False, cv=4.0/85.5≈0.047 < 0.10
    assert confidence_multiplier(s) == 1.0


def test_confidence_low_coverage():
    s = _sample_stock()
    s.dispersion = Dispersion(std=4.0, mean=85.5, analyst_n=2, avg_estimate_age_days=20)
    # coverage_p=0.5 → 어떤 조건이어도 clip 하한에 걸림
    assert confidence_multiplier(s) == 0.5


def test_confidence_rollover():
    s = _sample_stock()
    s.fiscal = Fiscal(current_fy_tag="FY26", fy_roll_flag=True)
    # coverage_p=1.0, freshness_p=1.0, rollover_p=0.85, dispersion_p=1.0 → 0.85
    result = confidence_multiplier(s)
    assert abs(result - 0.85) < 1e-9


def _make_batch(n=5):
    stocks = [_sample_stock() for _ in range(n)]
    l1s = [layer1_realized(s) for s in stocks]
    l2s = [layer2_momentum(s, l1) for s, l1 in zip(stocks, l1s)]
    l3s = [layer3_forward(s, l1) for s, l1 in zip(stocks, l1s)]
    layers_batch = [{"l1": l1, "l2": l2, "l3": l3} for l1, l2, l3 in zip(l1s, l2s, l3s)]
    return stocks, layers_batch


def test_aggregate_batch():
    stocks, layers_batch = _make_batch(5)
    results = aggregate(stocks, layers_batch)
    assert len(results) == 5
    for r in results:
        assert -100 <= r["raw_score"] <= 100


def test_aggregate_single():
    stocks, layers_batch = _make_batch(1)
    results = aggregate(stocks, layers_batch)
    assert len(results) == 1
    assert results[0]["raw_score"] == 0.0


def test_aggregate_missing():
    stocks, layers_batch = _make_batch(3)
    # stock[0]의 Layer3 전체를 None으로 대체
    null_l3 = {k: None for k in _L3_KEYS}
    layers_batch[0]["l3"] = null_l3
    results = aggregate(stocks, layers_batch)
    assert len(results) == 3
    assert results[0]["layer_scores"]["forward"] is None   # forward 없음
    assert -100 <= results[0]["raw_score"] <= 100          # 재정규화 후 정상 범위


def test_compute_normal():
    s = _sample_stock()
    sector = [_sample_stock() for _ in range(5)]
    result = compute_eps_revision_score(s, sector_dist=sector)
    assert -100 <= result["eps_score"] <= 100
    assert isinstance(result["insight"], str) and result["insight"]
    # 트로프 베이스 플래그 없음 (prior=43.6, yoy_implied≈96% < 200%)
    assert not any("트로프 베이스" in f for f in result["flags"])
    # 섹터 배치 모드 → 단일종목 플래그 없음
    assert not any("단일종목" in f for f in result["flags"])


def test_compute_trough_base():
    s = _sample_stock()
    s.actuals_ytd = ActualsYTD(
        ytd_cumulative_op=24.0, fy_consensus_op=85.5,
        quarters_elapsed=1, prior_fy_actual_op=6.6,   # yoy_implied≈11.95 > 2.0
    )
    result = compute_eps_revision_score(s)             # 단일종목 모드로 플래그 확인
    assert any("트로프 베이스효과" in f for f in result["flags"])


def test_compute_low_coverage():
    s = _sample_stock()
    s.dispersion = Dispersion(std=4.0, mean=85.5, analyst_n=2, avg_estimate_age_days=20)
    result = compute_eps_revision_score(s)             # 단일종목 모드
    # analyst_n=2 → coverage_p=0.5 → confidence clipped to 0.5
    assert result["confidence"] <= 0.55


if __name__ == "__main__":
    import pprint
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    s = _sample_stock()
    sector_dist = [_sample_stock() for _ in range(5)]
    result = compute_eps_revision_score(s, sector_dist=sector_dist)
    pprint.pprint(result)
