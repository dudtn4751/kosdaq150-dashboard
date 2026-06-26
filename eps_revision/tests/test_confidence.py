"""신뢰도 게이트 단위테스트 — 풀신뢰 / 저커버리지 / 롤오버 (+ 하한 클립)."""

from __future__ import annotations

import pytest

from eps_revision.confidence import (
    age_factor,
    analyst_factor,
    confidence_gate,
    dispersion_factor,
    roll_factor,
)


def _base():
    return {
        "consensus": {"op_fy1": {"now": 110.0, "m1": 105.0, "m3": 100.0},
                      "op_fy2": {}, "eps_fy1": {}, "eps_fy2": {}},
        "diffusion": {"up_count": 8, "down_count": 2, "total": 12},
        "surprise": [],
        "dispersion": {"std": 5.0, "mean": 100.0, "analyst_n": 25, "avg_estimate_age_days": 20.0},
        "target_price": {"tp_now": None, "tp_3m_ago": None, "price": None},
        "actuals_ytd": {"ytd_cumulative_op": None, "fy_consensus_op": None, "quarters_elapsed": 0},
        "news_sentiment": 0.0,
        "fiscal": {"current_fy_tag": "2026", "fy_roll_flag": False},
        "sector": "정보기술",
    }


# ── 서브팩터 직접 ───────────────────────────────────────────
def test_subfactors():
    assert analyst_factor(25) == pytest.approx(1.0)
    assert analyst_factor(2) == pytest.approx(0.55)      # <3 강한 캡
    assert analyst_factor(None) == pytest.approx(0.55)
    assert analyst_factor(14) == pytest.approx(0.55 + 11 / 22 * 0.45)   # 0.775

    assert age_factor(20) == pytest.approx(1.0)
    assert age_factor(90) == pytest.approx(1.0)
    assert age_factor(365) == pytest.approx(0.7)
    assert age_factor(None) == pytest.approx(1.0)

    assert roll_factor(True) == pytest.approx(0.85)
    assert roll_factor(False) == pytest.approx(1.0)
    assert roll_factor(None) == pytest.approx(1.0)

    assert dispersion_factor(5.0, 100.0) == pytest.approx(1.0)    # cv 0.05
    assert dispersion_factor(50.0, 100.0) == pytest.approx(0.7)    # cv 0.5
    assert dispersion_factor(None, 100.0) == pytest.approx(1.0)    # 결측 무감점


# ── (1) 풀신뢰 ──────────────────────────────────────────────
def test_full_confidence():
    g = confidence_gate(_base())          # 25개사·20일·롤오버X·CV0.05
    assert g == pytest.approx(1.0)


# ── (2) 저커버리지 ─────────────────────────────────────────
def test_low_coverage():
    d = _base()
    d["dispersion"]["analyst_n"] = 2      # <3 → 0.55
    g = confidence_gate(d)
    assert g == pytest.approx(0.55)
    assert 0.5 <= g <= 1.0


# ── (3) 롤오버 ─────────────────────────────────────────────
def test_rollover():
    d = _base()
    d["fiscal"]["fy_roll_flag"] = True    # 0.85
    g = confidence_gate(d)
    assert g == pytest.approx(0.85)


# ── 하한 클립: 페널티 누적 시 0.5 바닥 ─────────────────────
def test_floor_clip():
    d = _base()
    d["dispersion"]["analyst_n"] = 2          # 0.55
    d["fiscal"]["fy_roll_flag"] = True         # 0.85 → 0.4675 (<0.5)
    d["dispersion"]["std"] = 60.0              # cv 0.6 → 0.7  (더 낮아짐)
    g = confidence_gate(d)
    assert g == pytest.approx(0.5)             # 0.5로 클립
