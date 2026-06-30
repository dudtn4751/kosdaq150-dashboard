"""
목업 픽스처 기반 FnSpace 파서 테스트 (라이브 호출 없음).
실행: python -m pytest epsrev/tests/test_fnspace_parser.py
"""
from datetime import date

from epsrev.adapters.fnspace_parser import (
    load_fixture,
    parse_estimate_daily,
    parse_estimate_fiscal,
    parse_financial,
    parse_forward,
    parse_opinion_tp,
    pick_timepoints,
)


# ── forward ────────────────────────────────────────────────────────────────
def test_parse_forward():
    fw = parse_forward(load_fixture("mock_forward.json"))
    assert fw is not None
    assert fw.code == "005930"                 # 'A005930' → 정규화
    assert len(fw.points) == 7
    assert fw.points[0].date == "2026-03-30"   # 오름차순 정렬
    assert fw.points[-1].value == 5600.0


def test_forward_timepoints():
    fw = parse_forward(load_fixture("mock_forward.json"))
    tp = pick_timepoints(fw.points, asof=date(2026, 6, 29))
    assert tp.now == 5600.0                     # 2026-06-29
    assert tp.m1 == 5300.0                       # ≈1M전(2026-05-29)
    assert tp.m3 == 5000.0                       # ≈3M전(2026-03-30)


# ── estimate_daily ───────────────────────────────────────────────────────────
def test_parse_estimate_daily():
    ed = parse_estimate_daily(load_fixture("mock_estimate_daily.json"))
    assert ed is not None
    assert len(ed.op) == 7 and len(ed.np) == 7
    tp = pick_timepoints(ed.op, asof=date(2026, 6, 29))
    assert tp.now == 358000.0
    assert tp.m1 == 345000.0
    assert tp.m3 == 330000.0


# ── estimate_fiscal ──────────────────────────────────────────────────────────
def test_parse_estimate_fiscal():
    fc = parse_estimate_fiscal(load_fixture("mock_estimate_fiscal.json"))
    assert fc is not None
    assert fc.fy1_tag == "2026.12" and fc.fy1_op == 358000.0 and fc.fy1_eps == 5600.0
    assert fc.fy2_tag == "2027.12" and fc.fy2_op == 420000.0 and fc.fy2_eps == 6800.0


# ── opinion_tp ───────────────────────────────────────────────────────────────
def test_parse_opinion_tp():
    op = parse_opinion_tp(load_fixture("mock_opinion_tp.json"))
    assert op is not None
    assert op.analyst_n == 26
    assert len(op.tp_points) == 5
    tp = pick_timepoints(op.tp_points, asof=date(2026, 6, 29))
    assert tp.now == 92000.0
    assert tp.m3 == 78000.0                      # ≈3M전(2026-03-30)
    assert op.rev_1m.up == 12 and op.rev_1m.down == 2 and op.rev_1m.total == 26
    assert op.rev_3m.up == 18 and op.rev_3m.total == 28


# ── financial ────────────────────────────────────────────────────────────────
def test_parse_financial():
    fin = parse_financial(load_fixture("mock_financial.json"))
    assert fin is not None
    assert len(fin.quarters) == 4
    last = fin.quarters[-1]                       # 정렬 후 26Q2
    assert last.quarter == "26Q2"
    assert last.actual_op == 96000.0 and last.consensus_op == 92000.0
    assert last.surprise_pct == 4.35


# ── 견고성: None/빈 입력 ───────────────────────────────────────────────────────
def test_parse_none_inputs():
    assert parse_forward(None) is None
    assert parse_estimate_daily({}) is None       # 봉투 없음
    assert parse_opinion_tp({"dataset": []}) is None


def test_pick_timepoints_empty_and_missing():
    # 빈 시계열 → 전부 None
    empty = pick_timepoints([], asof=date(2026, 6, 29))
    assert empty.now is None and empty.m1 is None and empty.m3 is None
    # 허용오차 초과 → 결측. asof를 시계열보다 한참 미래로
    fw = parse_forward(load_fixture("mock_forward.json"))
    far = pick_timepoints(fw.points, asof=date(2027, 1, 1), tol_days=20)
    assert far.now is None                        # 최신점(2026-06-29)과 186일 차 → 초과
