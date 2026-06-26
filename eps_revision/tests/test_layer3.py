"""Layer3 (포워드 압력) 단위테스트 — 런레이트 상회/하회 / TP선행 / 결측."""

from __future__ import annotations

import pytest

from eps_revision.layer3 import (
    forward_pressure,
    persistence,
    runrate_gap,
    tp_lead,
)


def _base():
    return {
        "consensus": {
            "op_fy1": {"now": 110.0, "m1": 105.0, "m3": 100.0},   # rev_op_3m=0.10
            "op_fy2": {"now": 130.0, "m1": 128.0, "m3": 120.0},
            "eps_fy1": {"now": 110.0, "m1": 105.0, "m3": 100.0},   # rev_eps_3m=0.10
            "eps_fy2": {"now": 6200.0, "m1": 6100.0, "m3": 5800.0},
        },
        "diffusion": {"up_count": 8, "down_count": 2, "total": 12},
        "surprise": [(110.0, 100.0)],
        "dispersion": {"std": 8.0, "mean": 100.0, "analyst_n": 12, "avg_estimate_age_days": 25.0},
        "target_price": {"tp_now": 130000.0, "tp_3m_ago": 100000.0, "price": 120000.0},  # tp_chg=0.30
        "actuals_ytd": {"ytd_cumulative_op": 60.0, "fy_consensus_op": 100.0, "quarters_elapsed": 2},
        "news_sentiment": 0.3,
        "fiscal": {"current_fy_tag": "2026", "fy_roll_flag": False},
        "sector": "정보기술",
    }


# ── 컴포넌트 직접 ───────────────────────────────────────────
def test_component_functions():
    # denom = 100*2/4 = 50, gap = 60/50-1 = 0.20
    assert runrate_gap(60.0, 100.0, 2) == pytest.approx(0.20)
    # tp_chg=0.30, rev_eps_3m=0.10 → 0.20
    assert tp_lead(130000.0, 100000.0, 0.10) == pytest.approx(0.20)
    assert persistence(0.8, 0.10) == pytest.approx(0.08)


# ── (1) 런레이트 상회 / 하회 ───────────────────────────────
def test_runrate_above_and_below():
    above = forward_pressure(_base(), sector_revision_autocorr=0.8)
    assert above.evidence["runrate_gap"] == pytest.approx(0.20)   # 상회
    assert above.evidence["runrate_gap"] > 0
    assert above.evidence["persistence"] == pytest.approx(0.08)    # 0.8 × 0.10
    assert above.available is True
    assert above.raw > 0

    d = _base()
    d["actuals_ytd"]["ytd_cumulative_op"] = 40.0     # denom 50 → gap -0.20
    below = forward_pressure(d, sector_revision_autocorr=0.8)
    assert below.evidence["runrate_gap"] == pytest.approx(-0.20)   # 하회
    assert below.evidence["runrate_gap"] < 0


# ── (2) TP 선행 ─────────────────────────────────────────────
def test_tp_lead():
    r = forward_pressure(_base())
    assert r.evidence["tp_lead"] == pytest.approx(0.20)   # 0.30 - 0.10 → TP가 EPS 선행
    assert r.evidence["tp_lead"] > 0
    # persistence는 autocorr 미주입 시 None
    assert r.evidence["persistence"] is None
    assert r.evidence["news_lead"] == pytest.approx(0.3)


# ── (3) 결측 ───────────────────────────────────────────────
def test_missing_and_guards():
    assert runrate_gap(60.0, 0.0, 2) is None        # 연간컨센 0
    assert runrate_gap(60.0, -100.0, 2) is None      # 연간컨센 음수
    assert runrate_gap(60.0, 100.0, 0) is None       # 진행분기 0
    assert runrate_gap(None, 100.0, 2) is None
    assert tp_lead(130000.0, 0.0, 0.1) is None       # tp 분모 0
    assert tp_lead(130000.0, 100000.0, None) is None  # rev_eps_3m 결측
    assert persistence(None, 0.1) is None             # autocorr 미주입
    assert persistence(0.8, None) is None

    d = _base()
    d["actuals_ytd"]["fy_consensus_op"] = 0.0        # runrate None
    d["target_price"]["tp_3m_ago"] = None             # tp_lead None
    d["consensus"]["op_fy1"]["now"] = None            # persistence(rev_op_3m) None
    r = forward_pressure(d, sector_revision_autocorr=0.8)
    assert r.evidence["runrate_gap"] is None
    assert r.evidence["tp_lead"] is None
    assert r.evidence["persistence"] is None
    assert r.available is False                       # 주요 신호 없음
    assert r.evidence["news_lead"] == pytest.approx(0.3)   # 보조는 남아있음


def test_all_primary_missing_available_false():
    d = _base()
    d["actuals_ytd"] = {"ytd_cumulative_op": None, "fy_consensus_op": None, "quarters_elapsed": None}
    d["target_price"] = {"tp_now": None, "tp_3m_ago": None, "price": None}
    d["consensus"]["op_fy1"] = {}
    d["news_sentiment"] = None
    r = forward_pressure(d)   # autocorr 미주입
    assert r.available is False
    assert all(v is None for v in r.evidence.values())
