"""집계 — 신뢰도·베이스효과 (핸드오프 4·5절 · STEP 4).

STEP 5(섹터 집계·cross-sector percentile)는 이 모듈에 추가 예정.
"""
from __future__ import annotations

import math
from typing import Optional

import pandas as pd

# ---- 신뢰도 감쇄 상수 (핸드오프 4절) ----
RECENCY_FULL_MONTHS = 2     # 지연 ≤2M → f_recency=1.0
RECENCY_DECAY_MONTHS = 12   # 12M 지연 → 0.5 (2→12M 선형감쇄)
RECENCY_FLOOR = 0.5         # 그 이상 하한 유지
LENGTH_FULL_MONTHS = 24     # 이력 24M 이상 → f_length=1.0

# ---- 베이스효과 판정 상수 (핸드오프 5절, growth형 전용) ----
BASE_YOY_SURGE = 30.0       # |yoy| 급증 기준(%)
BASE_PRIOR_TROUGH = -10.0   # 전년동월 yoy 트로프 기준(%)
BASE_MA3_GAP = 15.0         # yoy ↔ ma3_yoy 괴리 기준(%p)


def _to_month(ts) -> Optional[pd.Period]:
    """latest_m 유연 파싱: Timestamp/Period/'YYYY-MM'/YYYYMM(int) → 월 Period."""
    if ts is None:
        return None
    try:
        if isinstance(ts, pd.Period):
            return ts.asfreq("M")
        s = str(ts)
        if s.isdigit() and len(s) == 6:
            return pd.Period(year=int(s[:4]), month=int(s[4:6]), freq="M")
        return pd.Timestamp(s).to_period("M")
    except Exception:
        return None


def confidence(latest_m, n_months: Optional[int], missing_ratio: Optional[float],
               as_of=None) -> float:
    """0~1 신뢰도 = f_recency · f_length · f_completeness.

    f_recency      : 지연 ≤2M → 1.0, 12M → 0.5 선형감쇄, 이후 0.5 하한 유지.
    f_length       : min(1, n_months/24).
    f_completeness : 1 − missing_ratio (0~1 클립).
    파싱 불능/결측 입력은 해당 요소를 최악값으로(감쇄 방향) 처리한다.
    """
    # f_recency
    latest = _to_month(latest_m)
    now = _to_month(as_of) or pd.Timestamp.today().to_period("M")
    if latest is None:
        f_recency = RECENCY_FLOOR
    else:
        lag = max(0, (now - latest).n)
        if lag <= RECENCY_FULL_MONTHS:
            f_recency = 1.0
        elif lag >= RECENCY_DECAY_MONTHS:
            f_recency = RECENCY_FLOOR
        else:
            span = RECENCY_DECAY_MONTHS - RECENCY_FULL_MONTHS
            f_recency = 1.0 - (1.0 - RECENCY_FLOOR) * (lag - RECENCY_FULL_MONTHS) / span

    # f_length
    n = 0 if n_months is None else max(0, int(n_months))
    f_length = min(1.0, n / LENGTH_FULL_MONTHS)

    # f_completeness
    m = 1.0 if missing_ratio is None else float(missing_ratio)
    if math.isnan(m) or math.isinf(m):
        m = 1.0
    f_completeness = min(1.0, max(0.0, 1.0 - m))

    return f_recency * f_length * f_completeness


def base_effect_flag(yoy, ma3_yoy, prior_yoy, series_type: str = "growth") -> bool:
    """베이스효과 의심 플래그(참이면 점수 감쇄용).

    growth형 전용: ① |yoy| 급증(≥BASE_YOY_SURGE) ② 전년동월 yoy가 트로프
    (≤BASE_PRIOR_TROUGH — 낮은 기저) ③ yoy와 ma3_yoy 괴리 큼(≥BASE_MA3_GAP)
    세 조건 동시 충족 시 True.
    ★ level형은 항상 False — 레벨엔 '전년 기저' 개념이 없음(YoY 로직 자체 금지).
    입력 결측(None/NaN)은 판정 불가 → False.
    """
    if series_type == "level":
        return False

    vals = []
    for v in (yoy, ma3_yoy, prior_yoy):
        if v is None:
            return False
        try:
            f = float(v)
        except (TypeError, ValueError):
            return False
        if math.isnan(f) or math.isinf(f):
            return False
        vals.append(f)
    y, ma3, prior = vals

    surged = abs(y) >= BASE_YOY_SURGE
    prior_trough = prior <= BASE_PRIOR_TROUGH
    ma3_gap = abs(y - ma3) >= BASE_MA3_GAP
    return surged and prior_trough and ma3_gap
