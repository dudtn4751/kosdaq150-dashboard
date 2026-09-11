#!/usr/bin/env python3
"""수출입 스냅샷 신선도 게이트 — 갱신일에 '기대한' 새 스냅샷이 실제로 들어왔는지 판정.

갱신일별 기대 데이터(EPIC 상류 갱신 여부를 이걸로 판단):
  - 1일  : 순별(decade) '전월 말일' + 월별(monthly) '전월(말일)' 둘 다 새로 존재.
  - 11일 : 순별 '당월 10일' 스냅샷 존재.
  - 21일 : 순별 '당월 20일' 스냅샷 존재.

CLI:  python3 check_trade_freshness.py <day> [--as-of YYYY-MM-DD]
      → stdout에 FRESH/STALE 한 줄, exit 0(fresh) / 1(stale) / 2(입력오류).
importable: expected_dates(day, as_of) / is_fresh(day, as_of, decade_dates, monthly_dates)
"""
from __future__ import annotations

import argparse
import calendar
import sys
from datetime import date
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
DECADE_CSV = PROJ / "data" / "trade_dashboard" / "trade_history_decade_long.csv"
MONTHLY_CSV = PROJ / "data" / "trade_dashboard" / "trade_history_long.csv"
UPDATE_DAYS = (1, 11, 21)


def _prev_month_end(d: date) -> str:
    py, pm = (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)
    last = calendar.monthrange(py, pm)[1]
    return f"{py}-{pm:02d}-{last:02d}"


def expected_dates(day: int, as_of: date) -> dict:
    """day별 기대 기준일. 반환 {'decade': 'YYYY-MM-DD', 'monthly'?: 'YYYY-MM-DD'}.
    갱신일이 아니면 {} (게이트 비적용)."""
    if day == 1:
        pme = _prev_month_end(as_of)
        return {"decade": pme, "monthly": pme}
    if day == 11:
        return {"decade": f"{as_of.year}-{as_of.month:02d}-10"}
    if day == 21:
        return {"decade": f"{as_of.year}-{as_of.month:02d}-20"}
    return {}


def is_fresh(day: int, as_of: date, decade_dates: set, monthly_dates: set) -> tuple[bool, str]:
    """(fresh?, 사유). decade_dates/monthly_dates는 CSV '기준일' 문자열 집합."""
    exp = expected_dates(day, as_of)
    if not exp:
        return False, f"day {day}는 갱신일(1/11/21) 아님"
    ok_decade = exp["decade"] in decade_dates
    ok_monthly = ("monthly" not in exp) or (exp["monthly"] in monthly_dates)
    if ok_decade and ok_monthly:
        return True, f"기대 스냅샷 확인: {exp['decade']}" + (f" (+월별 {exp['monthly']})" if "monthly" in exp else "")
    miss = []
    if not ok_decade:
        miss.append(f"순별 {exp['decade']}")
    if not ok_monthly:
        miss.append(f"월별 {exp['monthly']}")
    return False, "미도착: " + ", ".join(miss)


def _load_dates(path: Path) -> set:
    if not path.exists():
        return set()
    import pandas as pd
    try:
        df = pd.read_csv(path, usecols=["기준일"])
    except Exception:
        df = pd.read_csv(path)
    col = "기준일" if "기준일" in df.columns else df.columns[0]
    return set(df[col].astype(str).str.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("day", type=int)
    ap.add_argument("--as-of", default=None, help="기준일 오버라이드 YYYY-MM-DD (테스트용)")
    a = ap.parse_args()
    as_of = date.fromisoformat(a.as_of) if a.as_of else date.today()

    dd = _load_dates(DECADE_CSV)
    md = _load_dates(MONTHLY_CSV)
    fresh, why = is_fresh(a.day, as_of, dd, md)
    latest = sorted(dd)[-1] if dd else "(없음)"
    print(f"{'FRESH' if fresh else 'STALE'}: {why} · 순별 최신={latest}")
    return 0 if fresh else 1


if __name__ == "__main__":
    sys.exit(main())
