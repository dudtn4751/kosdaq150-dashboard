"""
목업 픽스처 기반 FnSpace 번들(assemble_extra) + builder 연결 테스트. 라이브 호출 없음.
실행: python -m pytest epsrev/tests/test_fnspace_bundle.py
"""
from datetime import date

from epsrev.adapters import fnspace as fns
from epsrev.adapters import fnspace_client as client
from epsrev.adapters.fnspace_parser import load_fixture, parse_all
from epsrev.adapters.builder import build_stock_input

ASOF = date(2026, 6, 29)   # 목업 최신일 — 결정적 테스트


def _normalized_from_mocks():
    return parse_all(
        "A005930",
        raw_forward=load_fixture("mock_forward.json"),
        raw_estimate_daily=load_fixture("mock_estimate_daily.json"),
        raw_estimate_fiscal=load_fixture("mock_estimate_fiscal.json"),
        raw_opinion_tp=load_fixture("mock_opinion_tp.json"),
        raw_financial=load_fixture("mock_financial.json"),
    )


def _bundle():
    return fns.assemble_extra(_normalized_from_mocks(), asof=ASOF)


# ── assemble_extra: 매핑 정확성 ────────────────────────────────────────────────
def test_bundle_eps_from_forward():
    b = _bundle()
    assert b["eps_fy1"] == 5600.0
    assert b["eps_fy1_1m"] == 5300.0
    assert b["eps_fy1_3m"] == 5000.0
    assert b["eps_fy2"] == 6800.0          # fiscal FY2 EPS


def test_bundle_op_from_daily_and_fiscal():
    b = _bundle()
    assert b["op_fy1"] == 358000.0
    assert b["op_fy1_1m"] == 345000.0
    assert b["op_fy1_3m"] == 330000.0
    assert b["op_fy2"] == 420000.0         # fiscal FY2 OP
    assert b["fy_consensus_op"] == 358000.0  # fiscal FY1 OP


def test_bundle_tp_and_analyst():
    b = _bundle()
    assert b["tp_now"] == 92000.0
    assert b["tp_3m_ago"] == 78000.0
    assert b["analyst_n"] == 26


def test_bundle_diffusion_proxy():
    b = _bundle()
    # 목표주가 1M 상향/하향/전체 = 12/2/26
    assert b["diffusion"] == {"up_count": 12, "down_count": 2, "total": 26}


def test_bundle_dispersion_none():
    b = _bundle()
    d = b["dispersion"]
    assert d["std"] is None and d["mean"] is None and d["avg_estimate_age_days"] is None
    assert d["analyst_n"] == 26            # analyst_n만 opinion_tp에서


def test_bundle_surprise_4q():
    b = _bundle()
    sq = b["surprise_4q"]
    assert len(sq) == 4
    assert sq[-1] == (96000.0, 92000.0)    # 26Q2 (actual, consensus)


def test_bundle_schema_matches_builder():
    """번들 키가 builder fnspace_extra 소비 키의 부분집합인지(스키마 정합)."""
    b = _bundle()
    allowed = {
        "eps_fy1", "eps_fy1_1m", "eps_fy1_3m", "eps_fy2",
        "op_fy1", "op_fy1_1m", "op_fy1_3m", "op_fy2",
        "fy_consensus_op", "tp_now", "tp_3m_ago", "analyst_n",
        "diffusion", "dispersion", "surprise_4q",
    }
    assert set(b).issubset(allowed), f"예상치 못한 키: {set(b) - allowed}"


# ── get_fnspace_bundle: 키 없으면 None ──────────────────────────────────────────
def test_get_bundle_disabled_returns_none():
    assert client.FNSPACE_ENABLED is False     # 테스트 환경엔 키 없음
    assert fns.get_fnspace_bundle("005930") is None


# ── builder 연결: 번들 주입 시 실제값 반영 ───────────────────────────────────────
def test_builder_consumes_bundle():
    b = _bundle()
    fin = [{"q": "26Q1", "rev": 100000, "op": 91000, "opm": 20},
           {"q": "26Q2", "rev": 110000, "op": 96000, "opm": 21}]
    cons = [{"m": "26.05", "fy1": 999, "fy2": 888},
            {"m": "26.06", "fy1": 999, "fy2": 888}]   # 더미 — 번들이 덮어써야 함
    si = build_stock_input(
        ticker="005930", sector="반도체·IT하드웨어",
        fin=fin, cons=cons, rpt={"tp": 111}, news=[],
        price_data={"price": 62000}, fnspace_extra=b,
    )
    assert si is not None
    # op_fy1 은 cons(999)가 아니라 번들(358000)
    assert si.consensus.op_fy1 == 358000.0
    assert si.consensus.eps_fy1 == 5600.0
    # tp_now 는 rpt(111)가 아니라 번들(92000)
    assert si.target_price.tp_now == 92000.0
    assert si.target_price.tp_3m_ago == 78000.0
    assert si.diffusion.up_count == 12 and si.diffusion.total == 26
    assert si.dispersion.std is None and si.dispersion.analyst_n == 26
    assert si.actuals_ytd.fy_consensus_op == 358000.0
    assert si.surprise_4q[-1] == (96000.0, 92000.0)


def test_builder_dummy_fallback_when_no_bundle():
    """번들 None(키 없음 환경) → 기존 더미/cons 폴백 유지."""
    fin = [{"q": "26Q1", "rev": 100000, "op": 9000, "opm": 20}]
    cons = [{"m": "26.05", "fy1": 14000, "fy2": 17000},
            {"m": "26.06", "fy1": 14200, "fy2": 17100}]
    si = build_stock_input(
        ticker="005930", sector="반도체·IT하드웨어",
        fin=fin, cons=cons, rpt={"tp": 260000}, news=[],
        price_data={"price": 62000},   # fnspace_extra 미지정 → 자동 시도(키없음→None)
    )
    assert si is not None
    assert si.consensus.op_fy1 == 14200.0      # cons 폴백
    assert si.target_price.tp_now == 260000.0  # rpt 폴백
