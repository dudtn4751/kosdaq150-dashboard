"""STEP 4 pytest — 신뢰도(confidence) + 베이스효과 플래그."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from epsrev.trade_score.aggregate import (confidence, base_effect_flag,
                                          RECENCY_FLOOR)

AS_OF = "2026-07"   # 테스트 고정 기준월


# ---------------- f_recency ----------------
def test_recency_fresh_full():
    # 지연 0~2M → 1.0 (length·completeness 만점으로 고정해 recency만 분리)
    assert confidence("2026-07", 24, 0.0, as_of=AS_OF) == pytest.approx(1.0)
    assert confidence("2026-05", 24, 0.0, as_of=AS_OF) == pytest.approx(1.0)


def test_recency_linear_decay_to_half_at_12m():
    # 7M 지연 = 2~12M의 중간 → 0.75
    assert confidence("2025-12", 24, 0.0, as_of=AS_OF) == pytest.approx(0.75)
    assert confidence("2025-07", 24, 0.0, as_of=AS_OF) == pytest.approx(0.5)


def test_recency_floor_beyond_12m():
    assert confidence("2024-01", 24, 0.0, as_of=AS_OF) == pytest.approx(RECENCY_FLOOR)


def test_recency_yyyymm_int_input():
    assert confidence(202607, 24, 0.0, as_of=202607) == pytest.approx(1.0)


# ---------------- f_length ----------------
def test_length_short_series_scales():
    assert confidence(AS_OF, 12, 0.0, as_of=AS_OF) == pytest.approx(0.5)   # 12/24
    assert confidence(AS_OF, 6, 0.0, as_of=AS_OF) == pytest.approx(0.25)
    assert confidence(AS_OF, 48, 0.0, as_of=AS_OF) == pytest.approx(1.0)   # cap 1


# ---------------- f_completeness ----------------
def test_completeness_missing_ratio():
    assert confidence(AS_OF, 24, 0.2, as_of=AS_OF) == pytest.approx(0.8)
    assert confidence(AS_OF, 24, 1.0, as_of=AS_OF) == pytest.approx(0.0)


# ---------------- 곱·범위 ----------------
def test_confidence_product_and_bounds():
    # 7M 지연(0.75) × 12M 이력(0.5) × 결측 10%(0.9) = 0.3375
    c = confidence("2025-12", 12, 0.1, as_of=AS_OF)
    assert c == pytest.approx(0.75 * 0.5 * 0.9)
    for args in [("2026-07", 24, 0.0), ("2020-01", 3, 0.9), (None, None, None)]:
        v = confidence(*args, as_of=AS_OF)
        assert 0.0 <= v <= 1.0


def test_confidence_none_inputs_degrade():
    # latest_m 파싱불능→recency 하한, n_months None→length 0 → 0점
    assert confidence(None, None, None, as_of=AS_OF) == pytest.approx(0.0)


# ---------------- base_effect_flag ----------------
def test_base_effect_trough_surge_true():
    # 전년 -30% 트로프 기저 + 올해 +50% 급증 + ma3(10%)과 40%p 괴리 → True
    assert base_effect_flag(yoy=50.0, ma3_yoy=10.0, prior_yoy=-30.0) is True


def test_base_effect_normal_growth_false():
    # 정상 성장: 급증 아님/기저 정상/괴리 작음
    assert base_effect_flag(yoy=12.0, ma3_yoy=10.0, prior_yoy=8.0) is False
    # 급증이어도 전년 기저가 정상이면 False
    assert base_effect_flag(yoy=50.0, ma3_yoy=10.0, prior_yoy=5.0) is False
    # 급증+트로프여도 ma3와 괴리 작으면(추세 자체가 강함) False
    assert base_effect_flag(yoy=50.0, ma3_yoy=45.0, prior_yoy=-30.0) is False


def test_base_effect_level_always_false():
    # level형은 기저효과 개념 없음 — 극단값이어도 False
    assert base_effect_flag(yoy=500.0, ma3_yoy=0.0, prior_yoy=-90.0,
                            series_type="level") is False


def test_base_effect_missing_inputs_false():
    assert base_effect_flag(None, 10.0, -30.0) is False
    assert base_effect_flag(50.0, float("nan"), -30.0) is False
