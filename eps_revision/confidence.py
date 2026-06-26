"""신뢰도 게이트 — 최종 점수에 곱할 멀티플라이어 (0.5~1.0).

신뢰 낮은 리비전은 점수를 0(중립) 쪽으로 끌어당겨 노이즈 억제.
각 요소를 (0,1] 페널티로 만들어 곱하고 [0.5, 1.0]로 클립.
  - analyst_factor : analyst_n < 3 강한 캡(~0.55), 25개사+ → 1.0 (구간 선형)
  - age_factor     : avg_estimate_age_days 90일 초과 시 감점 (365일 → 0.7)
  - roll_factor    : fy_roll_flag True면 FY 롤오버 구간 → 0.85
  - dispersion_factor: CV(std/|mean|) 비정상적으로 크면 감점 (0.5+ → 0.7)

순수 함수. 결측은 '측정 불가 → 페널티 없음(1.0)' 또는 커버리지처럼 보수적 캡으로 처리.
"""

from __future__ import annotations

from typing import Optional

from .layer2 import dispersion_cv
from .schemas import EpsRevisionInput

# 경계 상수
MIN_MULT, MAX_MULT = 0.5, 1.0
N_LOW, N_FULL = 3, 25            # 애널 수: 미만 캡 / 이상 완전신뢰
N_CAP = 0.55                     # 저커버리지 강한 캡
AGE_OK, AGE_MAX = 90.0, 365.0    # 신선도: 이하 무감점 / 이상 바닥
AGE_FLOOR = 0.7
ROLL_DISCOUNT = 0.85
CV_OK, CV_HIGH = 0.15, 0.5       # 분산: 이하 무감점 / 이상 바닥
CV_FLOOR = 0.7


def analyst_factor(analyst_n: Optional[int]) -> float:
    """커버 애널 수 → 신뢰 페널티. <3(또는 결측) 강한 캡, >=25 완전신뢰, 사이 선형."""
    if analyst_n is None or analyst_n < N_LOW:
        return N_CAP
    if analyst_n >= N_FULL:
        return MAX_MULT
    return N_CAP + (analyst_n - N_LOW) / (N_FULL - N_LOW) * (MAX_MULT - N_CAP)


def age_factor(avg_estimate_age_days: Optional[float]) -> float:
    """추정치 평균 연령 → 페널티. 90일 이하 무감점, 365일 이상 0.7, 사이 선형. 결측은 무감점."""
    if avg_estimate_age_days is None:
        return MAX_MULT
    if avg_estimate_age_days <= AGE_OK:
        return MAX_MULT
    if avg_estimate_age_days >= AGE_MAX:
        return AGE_FLOOR
    return MAX_MULT - (avg_estimate_age_days - AGE_OK) / (AGE_MAX - AGE_OK) * (MAX_MULT - AGE_FLOOR)


def roll_factor(fy_roll_flag: Optional[bool]) -> float:
    """FY 롤오버 구간이면 디스카운트."""
    return ROLL_DISCOUNT if fy_roll_flag else MAX_MULT


def dispersion_factor(std: Optional[float], mean: Optional[float]) -> float:
    """추정치 변동계수(CV) → 페널티. 0.15 이하 무감점, 0.5 이상 0.7, 사이 선형. 결측은 무감점."""
    cv = dispersion_cv(std, mean)
    if cv is None:
        return MAX_MULT
    cv = abs(cv)
    if cv <= CV_OK:
        return MAX_MULT
    if cv >= CV_HIGH:
        return CV_FLOOR
    return MAX_MULT - (cv - CV_OK) / (CV_HIGH - CV_OK) * (MAX_MULT - CV_FLOOR)


def confidence_gate(data: EpsRevisionInput) -> float:
    """4개 페널티를 곱해 [0.5, 1.0] 신뢰도 멀티플라이어 산출 (최종 점수에 곱할 값)."""
    disp = data.get("dispersion") or {}
    fiscal = data.get("fiscal") or {}
    mult = (analyst_factor(disp.get("analyst_n"))
            * age_factor(disp.get("avg_estimate_age_days"))
            * roll_factor(fiscal.get("fy_roll_flag"))
            * dispersion_factor(disp.get("std"), disp.get("mean")))
    return max(MIN_MULT, min(MAX_MULT, mult))
