#!/usr/bin/env python3
"""월별(trade_history_long) 무결성 검사 — 커밋 전 게이트용.

배경 (2026-09-01 실측): HS 6자리 전환 이후 EPIC '품목 및 지역' 화면(월별 소스)이
서로 다른 품목에 같은 계열을 내려주는 상류 오류가 생겼다(레이저가공/다이싱·스트립/건식
세정·습식 식각 및 세정이 모두 349,940,647). 파일명은 품목별로 올바르게 오므로
스크래퍼 쪽 검증으로는 못 잡고, 신선도 게이트("기대 날짜 행이 있나")도 통과한다.
그 결과 오염 데이터가 커밋·브리핑까지 나갔다.

판정 기준 — 층위 교차 대조:
  정상일 때 월별 값은 같은 달 순별(decade) 월말 누계와 일치한다(2026-08-27 전 품목×
  최근 6개월 차이 0건 확인). '품목 커스텀 설정' 화면(순별 소스)은 같은 시기에도 정상이었다.
  → 최근 N개월에 대해 |월별 / 순별월말 − 1| > TOL 인 품목이 MAX_MISMATCH개를 넘으면 실패.
  추가로 최신월 커버리지가 MIN_COVERAGE 미만이면 실패(대량 타임아웃 = 화면 이상 신호).

CLI:  python3 check_trade_integrity.py [--months 3] [--monthly PATH] [--decade PATH]
      → stdout 요약, exit 0(정상) / 1(이상) / 2(입력 오류)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJ = Path(__file__).resolve().parent.parent
MONTHLY_CSV = PROJ / "data" / "trade_dashboard" / "trade_history_long.csv"
DECADE_CSV = PROJ / "data" / "trade_dashboard" / "trade_history_decade_long.csv"

TOL = 0.02            # 월별 vs 순별월말 허용 오차(잠정 정정 여지)
MAX_MISMATCH = 2      # 이 수를 넘는 품목이 어긋나면 실패
MIN_COVERAGE = 0.90   # 최신월에 값이 있는 품목 비율 하한


def _load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["기준일"] = pd.to_datetime(df["기준일"])
    df["ym"] = df["기준일"].dt.to_period("M")
    return df


def check(monthly: pd.DataFrame, decade: pd.DataFrame, months: int) -> tuple[bool, list[str]]:
    lines: list[str] = []
    # 순별 월말 = 각 (품목, 월)의 21일 이후 마지막 스냅샷
    dm = decade[decade["기준일"].dt.day > 20].sort_values("기준일")
    dec_end = dm.groupby(["품목명", "ym"])["수출금액"].last()

    common = sorted(set(monthly["ym"]) & set(dec_end.index.get_level_values("ym")))
    target = common[-months:]
    if not target:
        return False, ["비교 가능한 월이 없음(순별 월말 스냅샷 부재)"]

    bad: dict[str, list[str]] = {}
    for ym in target:
        mm = monthly[monthly["ym"] == ym].set_index("품목명")["수출금액"]
        for item, mv in mm.items():
            dv = dec_end.get((item, ym))
            if dv is None or pd.isna(dv) or not dv:
                continue
            r = float(mv) / float(dv)
            if abs(r - 1) > TOL:
                bad.setdefault(item, []).append(f"{ym} 월별 {float(mv):,.0f} vs 순별 {float(dv):,.0f} ({r:.2f}x)")

    all_items = set(monthly["품목명"])
    latest = monthly["ym"].max()
    have = set(monthly.loc[monthly["ym"] == latest, "품목명"])
    cov = len(have) / len(all_items) if all_items else 0.0

    ok_x = len(bad) <= MAX_MISMATCH
    ok_c = cov >= MIN_COVERAGE
    lines.append(f"교차대조 {', '.join(str(t) for t in target)}: 불일치 {len(bad)}품목 (허용 {MAX_MISMATCH})"
                 + ("" if ok_x else " ✗"))
    for item, v in list(bad.items())[:6]:
        lines.append(f"  · {item}: {v[-1]}")
    lines.append(f"최신월 {latest} 커버리지 {len(have)}/{len(all_items)} = {cov:.0%} (하한 {MIN_COVERAGE:.0%})"
                 + ("" if ok_c else " ✗"))
    return ok_x and ok_c, lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=3)
    ap.add_argument("--monthly", type=Path, default=MONTHLY_CSV)
    ap.add_argument("--decade", type=Path, default=DECADE_CSV)
    a = ap.parse_args()
    if not a.monthly.exists() or not a.decade.exists():
        print("INPUT_ERROR: CSV 없음")
        return 2
    ok, lines = check(_load(a.monthly), _load(a.decade), a.months)
    print(("OK" if ok else "CORRUPT") + ": " + lines[0])
    for ln in lines[1:]:
        print(ln)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
