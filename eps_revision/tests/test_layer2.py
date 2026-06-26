"""Layer2 (리비전 모멘텀) 단위테스트 — 가속 / 감속 / 결측."""

from __future__ import annotations

import pytest

from eps_revision.layer2 import (
    dispersion_cv,
    diffusion_trend,
    revision_accel,
    revision_momentum,
)


def _base():
    return {
        "consensus": {
            "op_fy1": {"now": 108.0, "m1": 100.0, "m3": 100.0},   # 1M에 +8% 전부 → 가속
            "op_fy2": {"now": 130.0, "m1": 128.0, "m3": 120.0},
            "eps_fy1": {"now": 5500.0, "m1": 5300.0, "m3": 5000.0},
            "eps_fy2": {"now": 6200.0, "m1": 6100.0, "m3": 5800.0},
        },
        "diffusion": {"up_count": 8, "down_count": 2, "total": 12},
        "surprise": [(110.0, 100.0)],
        "dispersion": {"std": 8.0, "mean": 100.0, "analyst_n": 12, "avg_estimate_age_days": 25.0},
        "target_price": {"tp_now": 150000.0, "tp_3m_ago": 130000.0, "price": 120000.0},
        "actuals_ytd": {"ytd_cumulative_op": 60.0, "fy_consensus_op": 100.0, "quarters_elapsed": 2},
        "news_sentiment": 0.3,
        "fiscal": {"current_fy_tag": "2026", "fy_roll_flag": False},
        "sector": "정보기술",
    }


# ── 컴포넌트 직접 ───────────────────────────────────────────
def test_component_functions():
    # rev_1m=0.08, rev_3m=0.08 → 0.08*12 - 0.08*4 = 0.64
    assert revision_accel(0.08, 0.08) == pytest.approx(0.64)
    assert diffusion_trend(0.5, 0.0) == pytest.approx(0.5)
    assert dispersion_cv(8.0, 100.0) == pytest.approx(0.08)


# ── (1) 가속 케이스 ─────────────────────────────────────────
def test_acceleration():
    r = revision_momentum(_base())          # 1M에 +8% 전부 일어남
    assert r.available is True
    assert r.evidence["accel"] == pytest.approx(0.64)
    assert r.evidence["accel"] > 0           # 가속
    assert r.evidence["disp_cv"] == pytest.approx(0.08)
    assert r.evidence["diffusion_trend"] is None   # 직전 확산도 미제공
    assert r.raw > 0

    # 직전 확산도 제공 시 추세 계산
    d = _base()
    d["diffusion_prev"] = {"up_count": 5, "down_count": 5, "total": 12}   # 직전 idx 0
    r2 = revision_momentum(d)
    assert r2.evidence["diffusion_trend"] == pytest.approx(0.5)   # 0.5 - 0


# ── (2) 감속 케이스 ─────────────────────────────────────────
def test_deceleration():
    d = _base()
    d["consensus"]["op_fy1"] = {"now": 110.0, "m1": 110.0, "m3": 100.0}   # 최근 1M 변화 0, 3M +10%
    r = revision_momentum(d)
    # accel = 0*12 - 0.10*4 = -0.40
    assert r.evidence["accel"] == pytest.approx(-0.40)
    assert r.evidence["accel"] < 0           # 감속
    assert r.raw < 0


# ── (3) 결측 케이스 ─────────────────────────────────────────
def test_missing():
    assert revision_accel(None, 0.1) is None
    assert revision_accel(0.1, None) is None
    assert diffusion_trend(0.5, None) is None
    assert dispersion_cv(8.0, 0.0) is None       # mean 0
    assert dispersion_cv(None, 100.0) is None
    assert dispersion_cv(8.0, None) is None

    d = _base()
    d["consensus"]["op_fy1"]["now"] = None       # accel 불가
    d["dispersion"]["mean"] = 0.0                 # disp_cv None
    r = revision_momentum(d)
    assert r.evidence["accel"] is None
    assert r.evidence["disp_cv"] is None
    assert r.evidence["diffusion_trend"] is None
    assert r.available is False                   # 방향성 신호 없음
    # 결측을 0으로 채우지 않음
    assert all(v is None for v in r.evidence.values())
