"""STEP 5 pytest — 섹터 집계(가중합·재정규화·감쇄·percentile)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from epsrev.trade_score.schema import AxisSignals
from epsrev.trade_score.aggregate import (weighted_axis_sum, sector_raw,
                                          percentile_to_score, sector_score,
                                          sector_scores_batch, BASE_EFFECT_PENALTY)

W = {"mom": 0.30, "acc": 0.30, "qual": 0.20, "cyc": 0.20}


# ---------------- 가중합·재정규화 ----------------
def test_full_axes_weighted_sum():
    axes = AxisSignals(mom=1.0, acc=2.0, qual=-1.0, cyc=0.5)
    raw, eff = weighted_axis_sum(axes, W)
    assert raw == pytest.approx(0.3 * 1 + 0.3 * 2 + 0.2 * -1 + 0.2 * 0.5)
    assert sum(eff.values()) == pytest.approx(1.0)


def test_qual_none_renormalization_exact():
    # level 섹터: qual=None → mom/acc/cyc를 0.8로 재정규화
    axes = AxisSignals(mom=1.0, acc=2.0, qual=None, cyc=0.0)
    raw, eff = weighted_axis_sum(axes, W)
    assert eff == pytest.approx({"mom": 0.3 / 0.8, "acc": 0.3 / 0.8, "cyc": 0.2 / 0.8})
    assert raw == pytest.approx((0.3 * 1 + 0.3 * 2 + 0.2 * 0) / 0.8)


def test_all_axes_none_graceful():
    raw, eff = weighted_axis_sum(AxisSignals(), W)
    assert raw is None and eff == {}
    s = sector_score("빈섹터", AxisSignals(), W, conf=1.0, base_flag=False,
                     cross_sector_raws=[0.1, 0.2])
    assert s.sector_score is None and "no_data" in s.flags


# ---------------- 감쇄 ----------------
def test_base_effect_penalty_shrinks_magnitude():
    axes = AxisSignals(mom=2.0, acc=2.0, qual=2.0, cyc=2.0)
    plain, _ = sector_raw(axes, W, conf=1.0, base_flag=False)
    damped, _ = sector_raw(axes, W, conf=1.0, base_flag=True)
    assert damped == pytest.approx(plain * BASE_EFFECT_PENALTY)
    # 음수 raw도 크기만 줄고 방향 반전 없음
    neg = AxisSignals(mom=-2.0, acc=-2.0, qual=-2.0, cyc=-2.0)
    p, _ = sector_raw(neg, W, 1.0, False)
    d, _ = sector_raw(neg, W, 1.0, True)
    assert d == pytest.approx(p * BASE_EFFECT_PENALTY) and d < 0 and abs(d) < abs(p)


def test_confidence_scales_raw():
    axes = AxisSignals(mom=1.0, acc=1.0, qual=1.0, cyc=1.0)
    full, _ = sector_raw(axes, W, conf=1.0, base_flag=False)
    half, _ = sector_raw(axes, W, conf=0.5, base_flag=False)
    assert half == pytest.approx(full * 0.5)


# ---------------- percentile 매핑 ----------------
def test_percentile_mapping_range():
    pool = [-2.0, -1.0, 0.0, 1.0, 2.0]
    assert percentile_to_score(2.0, pool) == pytest.approx((0.9 * 2 - 1) * 100)   # 최상위
    assert percentile_to_score(-2.0, pool) == pytest.approx((0.1 * 2 - 1) * 100)  # 최하위
    assert percentile_to_score(0.0, pool) == pytest.approx(0.0)                   # 중앙


# ---------------- 배치 ----------------
def _entry(sector, mom, base_flag=False, conf=1.0, qual=None):
    axes = AxisSignals(mom=mom, acc=mom, qual=qual, cyc=mom)
    return {"sector": sector, "axes": axes, "weights": dict(W),
            "confidence": conf, "base_flag": base_flag}


def test_batch_percentile_ordering():
    entries = [_entry("강한섹터", 2.0, qual=2.0),
               _entry("중간섹터", 0.0, qual=0.0),
               _entry("약한섹터", -2.0, qual=-2.0)]
    out = sector_scores_batch(entries)
    scores = {s.sector: s.sector_score for s in out}
    assert scores["강한섹터"] > scores["중간섹터"] > scores["약한섹터"]
    assert scores["강한섹터"] > 0 > scores["약한섹터"]
    assert scores["중간섹터"] == pytest.approx(0.0)
    assert all(-100 <= s.sector_score <= 100 for s in out)


def test_batch_level_sector_mixed_with_growth():
    # level 섹터(qual=None)와 growth 섹터가 같은 배치에서 비교 가능
    entries = [_entry("금융(level)", 1.5, qual=None),
               _entry("반도체(growth)", 1.0, qual=1.0),
               _entry("약체", -1.0, qual=-1.0)]
    out = sector_scores_batch(entries)
    scores = {s.sector: s.sector_score for s in out}
    assert scores["금융(level)"] > scores["반도체(growth)"] > scores["약체"]
    fin = next(s for s in out if s.sector == "금융(level)")
    assert "qual" not in fin.weights                # 재정규화로 qual 제외 확인
    assert sum(fin.weights.values()) == pytest.approx(1.0)


def test_batch_base_effect_demotes_rank():
    # 동일 축이지만 base_effect 섹터는 감쇄로 순위 하락
    entries = [_entry("정상", 2.0, qual=2.0),
               _entry("기저효과", 2.0, base_flag=True, qual=2.0),
               _entry("바닥", -2.0, qual=-2.0)]
    out = sector_scores_batch(entries)
    scores = {s.sector: s.sector_score for s in out}
    assert scores["정상"] > scores["기저효과"] > scores["바닥"]
    assert "base_effect" in next(s for s in out if s.sector == "기저효과").flags


def test_batch_no_data_entry_graceful():
    entries = [_entry("정상", 1.0, qual=1.0),
               {"sector": "결측", "axes": AxisSignals(), "weights": dict(W),
                "confidence": 1.0, "base_flag": False}]
    out = sector_scores_batch(entries)
    missing = next(s for s in out if s.sector == "결측")
    assert missing.sector_score is None and "no_data" in missing.flags
    # 결측 섹터는 percentile 분포(pool)에서 빠져 정상 섹터가 단독 중앙(0)
    normal = next(s for s in out if s.sector == "정상")
    assert normal.sector_score == pytest.approx(0.0)
