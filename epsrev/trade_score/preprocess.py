"""전처리 유틸 — 월간 리샘플 (핸드오프 1절·STEP 1-0).

모든 시계열은 축 계산 전 월간으로 주기 통일. 주기 혼재 상태로 YoY/차분을 내면 왜곡.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

# freq 라벨 → 유형 (config의 freq 필드 값)
_SUB_MONTHLY = {"일", "주", "D", "W", "daily", "weekly"}
_SUPRA_MONTHLY = {"분기", "반기", "Q", "H", "quarterly", "semiannual"}
_MONTHLY = {"월", "M", "monthly", None}


def _to_month_end_index(series: pd.Series) -> pd.Series:
    """인덱스를 월말 Timestamp로 정규화. 허용: DatetimeIndex·PeriodIndex·
    YYYYMM(int/str)·'YYYY-MM'. 파싱 불능이면 ValueError."""
    if series.empty:
        return series
    idx = series.index
    if isinstance(idx, pd.PeriodIndex):
        ts = idx.to_timestamp(how="end").normalize()
    elif isinstance(idx, pd.DatetimeIndex):
        ts = idx
    else:
        def _parse(v):
            s = str(v)
            if s.isdigit() and len(s) == 6:          # 202301
                return pd.Timestamp(int(s[:4]), int(s[4:6]), 1)
            return pd.Timestamp(s)                    # '2023-01', '2023-01-15' 등
        ts = pd.DatetimeIndex([_parse(v) for v in idx])
    out = series.copy()
    out.index = ts
    return out.sort_index()


def _resolve_auto(freq: Optional[str], series_type: Optional[str]) -> str:
    """auto 규칙: 일/주+growth→sum(유량 합산), 일/주+level→mean(월평균, 노이즈 완화),
    분기/반기→interp, 월간→passthrough."""
    if freq in _SUB_MONTHLY:
        return "sum" if series_type == "growth" else "mean"
    if freq in _SUPRA_MONTHLY:
        return "interp"
    return "passthrough"


def resample_monthly(series: pd.Series, how: str = "auto",
                     freq: Optional[str] = None,
                     series_type: Optional[str] = None) -> pd.Series:
    """일/주/분기/반기 시계열 → 월간 통일. 반환 index=월말 Timestamp.

    how: "last"(월말값) | "mean"(월평균) | "sum"(월합계) |
         "interp"(분기/반기→월 선형보간, 관측 구간 안쪽만) |
         "auto"(freq·series_type로 자동: 일/주+growth→sum, 일/주+level→mean,
                분기/반기→interp, 월→그대로)
    """
    if series is None or len(series) == 0:
        return pd.Series(dtype=float)
    s = _to_month_end_index(series.astype(float))

    if how == "auto":
        how = _resolve_auto(freq, series_type)

    if how == "passthrough":
        # 이미 월간 — 월말 인덱스로만 정규화(중복 월은 마지막 관측)
        return s.groupby(s.index.to_period("M")).last().rename(None).pipe(_period_to_ts)
    if how in ("last", "mean", "sum"):
        grouped = s.groupby(s.index.to_period("M"))
        agg = {"last": grouped.last, "mean": grouped.mean, "sum": grouped.sum}[how]()
        return _period_to_ts(agg)
    if how == "interp":
        # 분기/반기 관측 → 월간 업샘플. 관측 구간 안쪽(limit_area="inside")만 선형보간.
        monthly = s.groupby(s.index.to_period("M")).last()
        full = pd.period_range(monthly.index.min(), monthly.index.max(), freq="M")
        up = monthly.reindex(full).interpolate(method="linear", limit_area="inside")
        return _period_to_ts(up)
    raise ValueError(f"unknown how={how!r}")


def _period_to_ts(s: pd.Series) -> pd.Series:
    out = s.copy()
    out.index = s.index.to_timestamp(how="end").normalize()
    return out
