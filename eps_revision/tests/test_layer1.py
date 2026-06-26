"""Layer1 (실현 리비전) 단위테스트.

(1) 정상 상향  (2) 분모 0/음수  (3) 결측치
실행: pytest eps_revision/tests/test_layer1.py  (또는 python -m pytest)
"""

from __future__ import annotations

import pytest

from eps_revision.layer1 import (
    diffusion_index,
    realized_revision,
    revision_ratio,
    surprise_sue,
)


def _base():
    """기본(정상 상향) 입력. 케이스별로 일부만 덮어쓴다."""
    return {
        "consensus": {
            "op_fy1": {"now": 110.0, "m1": 105.0, "m3": 100.0},
            "op_fy2": {"now": 130.0, "m1": 128.0, "m3": 120.0},
            "eps_fy1": {"now": 5500.0, "m1": 5000.0, "m3": 5000.0},
            "eps_fy2": {"now": 6200.0, "m1": 6100.0, "m3": 5800.0},
        },
        "diffusion": {"up_count": 8, "down_count": 2, "total": 12},
        "surprise": [(110.0, 100.0), (120.0, 100.0)],
        "dispersion": {"std": 8.0, "mean": 100.0, "analyst_n": 12, "avg_estimate_age_days": 25.0},
        "target_price": {"tp_now": 150000.0, "tp_3m_ago": 130000.0, "price": 120000.0},
        "actuals_ytd": {"ytd_cumulative_op": 60.0, "fy_consensus_op": 100.0, "quarters_elapsed": 2},
        "news_sentiment": 0.3,
        "fiscal": {"current_fy_tag": "2026", "fy_roll_flag": False},
        "sector": "정보기술",
    }


# ── (1) 정상 상향 ───────────────────────────────────────────
def test_normal_upward():
    r = realized_revision(_base())
    e = r.evidence
    assert r.available is True
    assert e["rev_op_3m"] == pytest.approx(0.10)          # 110/100-1
    assert e["rev_op_1m"] == pytest.approx(110 / 105 - 1)  # ≈0.04762
    assert e["rev_eps_3m"] == pytest.approx(0.10)          # 5500/5000-1
    assert e["rev_eps_1m"] == pytest.approx(0.10)
    assert e["diffusion_idx"] == pytest.approx(0.5)        # (8-2)/12
    assert e["sue"] == pytest.approx(0.15)                 # (0.10+0.20)/2
    assert r.raw > 0                                        # 상향 → 양(+)


def test_component_functions_direct():
    assert revision_ratio(110.0, 100.0) == pytest.approx(0.10)
    assert diffusion_index({"up_count": 8, "down_count": 2, "total": 12}) == pytest.approx(0.5)
    assert surprise_sue([(110.0, 100.0), (120.0, 100.0)]) == pytest.approx(0.15)


# ── (2) 분모 0 / 음수 ───────────────────────────────────────
def test_zero_and_negative_denominator():
    assert revision_ratio(110.0, 0.0) is None       # 분모 0
    assert revision_ratio(110.0, -50.0) is None      # 분모 음수(적자 추정) → 가드
    assert diffusion_index({"up_count": 5, "down_count": 1, "total": 0}) is None  # total 0
    # SUE: consensus 0 분기는 제외, 나머지로 평균
    assert surprise_sue([(50.0, 0.0), (60.0, 50.0)]) == pytest.approx(0.20)
    assert surprise_sue([(50.0, 0.0)]) is None       # 유효 분기 없음

    d = _base()
    d["consensus"]["op_fy1"]["m3"] = 0.0             # rev_op_3m 분모 0
    d["diffusion"]["total"] = 0                      # diffusion None
    r = realized_revision(d)
    assert r.evidence["rev_op_3m"] is None
    assert r.evidence["diffusion_idx"] is None
    assert r.evidence["rev_op_1m"] is not None        # 나머지는 정상
    assert r.available is True                         # 일부라도 있으면 True


# ── (3) 결측치 ──────────────────────────────────────────────
def test_missing_values_return_none_not_zero():
    assert revision_ratio(None, 100.0) is None
    assert revision_ratio(110.0, None) is None
    assert diffusion_index(None) is None
    assert surprise_sue(None) is None
    assert surprise_sue([]) is None

    d = _base()
    d["consensus"]["op_fy1"]["now"] = None           # op 변화율 둘 다 None
    d["consensus"]["eps_fy1"]["m1"] = None            # rev_eps_1m None
    r = realized_revision(d)
    assert r.evidence["rev_op_3m"] is None
    assert r.evidence["rev_op_1m"] is None
    assert r.evidence["rev_eps_1m"] is None
    assert r.evidence["rev_eps_3m"] is not None        # eps m3 정상
    # 결측을 0으로 채우지 않았는지: None 그대로
    assert any(v is None for v in r.evidence.values())


def test_all_missing_available_false():
    d = _base()
    d["consensus"] = {"op_fy1": {}, "op_fy2": {}, "eps_fy1": {}, "eps_fy2": {}}
    d["diffusion"] = {"up_count": None, "down_count": None, "total": None}
    d["surprise"] = []
    r = realized_revision(d)
    assert r.available is False
    assert all(v is None for v in r.evidence.values())
