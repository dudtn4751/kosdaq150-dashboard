"""신선도 게이트 핵심 로직 테스트 — 새데이터(fresh)/옛데이터(stale) 판정, 갱신일별 기대일."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_trade_freshness import expected_dates, is_fresh, _prev_month_end


# ── 기대 스냅샷일 산출 ──
def test_expected_day11_current_month_10th():
    assert expected_dates(11, date(2026, 9, 11)) == {"decade": "2026-09-10"}


def test_expected_day21_current_month_20th():
    assert expected_dates(21, date(2026, 9, 21)) == {"decade": "2026-09-20"}


def test_expected_day1_prev_month_end_both_csvs():
    exp = expected_dates(1, date(2026, 9, 1))
    assert exp == {"decade": "2026-08-31", "monthly": "2026-08-31"}


def test_expected_day1_january_wraps_to_prev_december():
    exp = expected_dates(1, date(2026, 1, 1))
    assert exp == {"decade": "2025-12-31", "monthly": "2025-12-31"}


def test_prev_month_end_feb_leap_and_nonleap():
    assert _prev_month_end(date(2024, 3, 5)) == "2024-02-29"   # 윤년
    assert _prev_month_end(date(2026, 3, 5)) == "2026-02-28"


def test_non_update_day_returns_empty():
    assert expected_dates(15, date(2026, 9, 15)) == {}


# ── 새데이터 경로 (fresh) ──
def test_fresh_day11_when_10th_present():
    fresh, why = is_fresh(11, date(2026, 9, 11), {"2026-08-31", "2026-09-10"}, set())
    assert fresh is True and "2026-09-10" in why


def test_fresh_day1_requires_both_decade_and_monthly():
    dd = {"2026-08-31"}
    md = {"2026-08-31"}
    assert is_fresh(1, date(2026, 9, 1), dd, md)[0] is True


# ── 옛데이터 경로 (stale) ──
def test_stale_day11_when_10th_absent():
    fresh, why = is_fresh(11, date(2026, 9, 11), {"2026-08-31"}, set())
    assert fresh is False and "미도착" in why and "2026-09-10" in why


def test_stale_day1_when_monthly_missing_even_if_decade_present():
    # 순별엔 전월말 있으나 월별 CSV엔 아직 없음 → stale (월별 새 달 미도착)
    fresh, why = is_fresh(1, date(2026, 9, 1), {"2026-08-31"}, {"2026-07-31"})
    assert fresh is False and "월별" in why


def test_non_update_day_is_stale():
    assert is_fresh(15, date(2026, 9, 15), set(), set())[0] is False
