"""전처리 유틸 — STEP 0: 시그니처만 (구현은 STEP 1).

모든 시계열은 축 계산 전 월간 리샘플로 주기 통일(핸드오프 1절·STEP 1-0).
"""
from __future__ import annotations

import pandas as pd


def resample_monthly(series: pd.Series, how: str = "auto") -> pd.Series:
    """일/주/분기/반기 시계열 → 월간 통일. (STEP 1에서 구현)

    Args:
        series: DatetimeIndex(또는 YYYYMM) 인덱스 시계열.
        how: 리샘플 방식 —
             "last"   : 월말값 (level형 가격/지수 기본)
             "mean"   : 월평균 (level형 급변 지표 대안)
             "sum"    : 월합계 (growth/flow형 일·주 관측)
             "interp" : 분기/반기 → 월 보간(관측점만 유효 표시)
             "auto"   : config의 freq·series_type으로 자동 결정
                        (일/주+level→last, 일/주+growth→sum, 분기/반기→interp, 월→passthrough)

    Returns:
        월간 pd.Series (index=월말 Timestamp).
    """
    raise NotImplementedError("STEP 1에서 구현 — STEP 0은 시그니처만")
