"""통합 테스트 — compute_eps_revision_score: 정상 / 트로프베이스 / 저커버리지."""

from __future__ import annotations

import pandas as pd
import pytest

from eps_revision.aggregate import ALL_COMPONENTS
from eps_revision.score import compute_eps_revision_score, extract_components


def _input(op_now=110.0, eps_now=5500.0, analyst_n=25, age=20.0,
           ytd=60.0, fy=100.0, q=2, tp_now=130000.0, tp_3m=100000.0,
           news=0.3, roll=False):
    """양호한 상향 케이스 기본 입력. 인자로 케이스별 변형."""
    return {
        "consensus": {
            "op_fy1": {"now": op_now, "m1": 105.0, "m3": 100.0},
            "op_fy2": {"now": 130.0, "m1": 128.0, "m3": 120.0},
            "eps_fy1": {"now": eps_now, "m1": 5200.0, "m3": 5000.0},
            "eps_fy2": {"now": 6200.0, "m1": 6100.0, "m3": 5800.0},
        },
        "diffusion": {"up_count": 8, "down_count": 2, "total": 12},
        "surprise": [(110.0, 100.0), (120.0, 105.0)],
        "dispersion": {"std": 6.0, "mean": 100.0, "analyst_n": analyst_n, "avg_estimate_age_days": age},
        "target_price": {"tp_now": tp_now, "tp_3m_ago": tp_3m, "price": 120000.0},
        "actuals_ytd": {"ytd_cumulative_op": ytd, "fy_consensus_op": fy, "quarters_elapsed": q},
        "news_sentiment": news,
        "fiscal": {"current_fy_tag": "2026", "fy_roll_flag": roll},
        "sector": "정보기술",
    }


def _pool():
    """섹터 풀(컴포넌트 DataFrame) — 타깃(상향)보다 약한 4종목으로 랭크 기준 제공."""
    rows = {}
    for i, k in enumerate([-0.10, -0.04, 0.0, 0.03]):
        rows[f"P{i}"] = {c: k for c in ALL_COMPONENTS}
    return pd.DataFrame.from_dict(rows, orient="index")[ALL_COMPONENTS]


def _schema_ok(out):
    assert set(out) == {"eps_score", "layers", "confidence", "evidence", "insight", "flags"}
    assert set(out["layers"]) == {"realized", "momentum", "forward"}
    assert isinstance(out["insight"], str) and out["insight"]
    assert isinstance(out["flags"], list)
    if out["eps_score"] is not None:
        assert -100.0 <= out["eps_score"] <= 100.0


# ── (1) 정상 케이스 ─────────────────────────────────────────
def test_normal_case():
    out = compute_eps_revision_score(
        _input(), _pool(), sector_revision_autocorr=0.6,
        prev_year_actual_op=80.0, reported_yoy=0.25)   # 100/80-1=0.25, 표기와 일치
    _schema_ok(out)
    assert out["flags"] == []                          # 정합성 문제 없음
    assert out["eps_score"] > 0                         # 강한 상향 → 풀 대비 상위
    assert out["confidence"] == pytest.approx(1.0)      # 25개사·신선·롤오버X
    assert "→" in out["insight"]
    assert out["evidence"]["rev_op_3m"] == pytest.approx(0.10)


# ── (2) 트로프 베이스 케이스 ───────────────────────────────
def test_trough_base_case():
    out = compute_eps_revision_score(
        _input(), _pool(), sector_revision_autocorr=0.6,
        prev_year_actual_op=5.0, reported_yoy=0.25)    # 베이스 5 << 컨센 100 → 트로프
    _schema_ok(out)
    assert any("트로프" in f for f in out["flags"])
    assert "트로프" in out["insight"]                   # 인사이트 끝에 경고
    # YoY는 점수에 미반영 — 점수는 여전히 산출(리비전 기반)
    assert out["eps_score"] is not None


# ── (3) 저커버리지 케이스 ──────────────────────────────────
def test_low_coverage_case():
    out = compute_eps_revision_score(
        _input(analyst_n=2), _pool(), sector_revision_autocorr=0.6,
        prev_year_actual_op=80.0)
    _schema_ok(out)
    assert out["confidence"] == pytest.approx(0.55)     # analyst_n<3 강한 캡
    assert "신뢰도" in out["insight"]                    # 저신뢰 경고 문구


# ── 단위 불일치 가드 ───────────────────────────────────────
def test_unit_inconsistency_flag():
    out = compute_eps_revision_score(
        _input(op_now=11000.0), _pool(),                # op_fy1 11000 vs fy 100 → 110배
        prev_year_actual_op=80.0)
    assert any("단위" in f for f in out["flags"])
