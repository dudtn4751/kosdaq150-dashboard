"""STEP 6 pytest — 기업 종합(E/I 렌즈·src 라우팅·exposure·발산·상속)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from epsrev.trade_score.company import (route_indicators_by_src, compute_exposure,
                                        company_score, DIVERGENCE_GAP)


# ---------------- src 라우팅 ----------------
def test_src_routing_splits_lenses():
    inds = [
        {"code": 9, "sub": 3, "src": "trade"},      # → E
        {"code": 19, "sub": 70, "src": "industry"}, # → I
        {"code": 0, "sub": 84, "src": "industry"},  # → I
        {"code": 9, "sub": 8, "src": "trade"},      # → E
    ]
    exp, ind = route_indicators_by_src(inds)
    assert len(exp) == 2 and all(i["src"] == "trade" for i in exp)
    assert len(ind) == 2 and all(i["src"] == "industry" for i in ind)


def test_src_default_is_industry():
    exp, ind = route_indicators_by_src([{"code": 1, "sub": 1}])  # src 없음
    assert exp == [] and len(ind) == 1


# ---------------- exposure ----------------
def test_exposure_product_and_default():
    assert compute_exposure(0.8, 0.5) == pytest.approx(0.4)
    assert compute_exposure() == pytest.approx(1.0)        # 정보 없음 → 1.0
    assert compute_exposure(1.5, None) == pytest.approx(1.0)  # 클립
    assert compute_exposure(-0.2, 0.5) == pytest.approx(0.0)


# ---------------- 렌즈 우선순위(직접 vs 폴백) ----------------
def test_direct_export_beats_sector_fallback():
    # 직접 점수 있으면 f_direct=1.0, 섹터×exposure 무시
    cs = company_score("A", export_direct=60.0, export_sector=20.0, exposure=0.5)
    assert cs.export_part == pytest.approx(60.0)
    assert cs.reliability.r_export == pytest.approx(1.0)   # 직접 → f_direct 1.0
    assert cs.company_score == pytest.approx(60.0)         # r_I=0 → E 단독


def test_sector_fallback_scaled_by_exposure():
    cs = company_score("B", export_direct=None, export_sector=40.0, exposure=0.5)
    assert cs.export_part == pytest.approx(20.0)           # 40×0.5
    assert cs.reliability.r_export == pytest.approx(0.5)   # f_direct=exposure
    assert cs.company_score == pytest.approx(20.0)


def test_exposure_differentiation():
    hi = company_score("H", export_sector=50.0, exposure=1.0)
    lo = company_score("L", export_sector=50.0, exposure=0.2)
    assert hi.export_part > lo.export_part                 # 노출 큰 쪽 점수 큼
    assert hi.reliability.r_export > lo.reliability.r_export


# ---------------- 산업 결측(r_I=0) ----------------
def test_industry_missing_export_only():
    cs = company_score("C", export_direct=30.0)           # I 입력 없음
    assert cs.industry_part is None
    assert cs.reliability.r_industry == pytest.approx(0.0)
    assert cs.company_score == pytest.approx(30.0)         # E 단독


# ---------------- 두 렌즈 결합 ----------------
def test_two_lens_weighted_combine():
    cs = company_score("D", export_direct=60.0, industry_direct=20.0,
                       export_recency=1.0, export_length=1.0,
                       industry_recency=1.0, industry_length=1.0)
    # r_E=r_I=1 → 평균 40
    assert cs.company_score == pytest.approx(40.0)
    assert "divergence" not in cs.flags


def test_divergence_flag():
    # 경계 미만: |70-(-9)|=79 < 80 → 플래그 없음
    cs = company_score("E", export_direct=70.0, industry_direct=-9.0)
    assert "divergence" not in cs.flags
    # 경계 이상: |90-(-10)|=100 ≥ 80 → 플래그
    cs2 = company_score("E2", export_direct=90.0, industry_direct=-10.0)
    assert "divergence" in cs2.flags
    # 정확히 경계값 |80-0|=80 ≥ 80 → 플래그
    cs3 = company_score("E3", export_direct=80.0, industry_direct=0.0)
    assert "divergence" in cs3.flags


def test_reliability_weighting_shifts_toward_reliable_lens():
    # 산업 렌즈 신뢰도 낮으면 결합점수가 수출 쪽으로 당겨짐
    cs = company_score("F", export_direct=60.0, industry_direct=0.0,
                       industry_recency=0.2, industry_length=0.5)
    # r_E=1, r_I=0.1 → (1·60 + 0.1·0)/1.1 ≈ 54.5
    assert cs.company_score == pytest.approx(60.0 / 1.1, rel=1e-3)
    assert cs.company_score > 50.0                        # 수출 쪽 우세


# ---------------- 둘 다 결측 → 섹터 상속 ----------------
def test_both_missing_inherits_sector():
    cs = company_score("G", sector_inherit=15.0)
    assert cs.company_score == pytest.approx(15.0)
    assert "sector_inherit" in cs.flags
    assert cs.export_part is None and cs.industry_part is None


def test_both_missing_no_inherit_none():
    cs = company_score("H")
    assert cs.company_score is None
    assert cs.reliability.r_export == 0.0 and cs.reliability.r_industry == 0.0
