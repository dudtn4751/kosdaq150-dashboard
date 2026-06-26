"""aggregate 단위테스트 — 배치 5종목 / 단일종목 / 일부 결측 / 신뢰도 / 표준화 수학."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eps_revision.aggregate import (
    ALL_COMPONENTS,
    LAYER_COMPONENTS,
    aggregate_batch,
    aggregate_single,
    combine_layers,
    robust_zscore,
)


def _df(strengths):
    """{code: k} → 모든 컴포넌트를 k로 채운 DataFrame(섹터 풀)."""
    rows = {code: {c: float(k) for c in ALL_COMPONENTS} for code, k in strengths.items()}
    return pd.DataFrame.from_dict(rows, orient="index")[ALL_COMPONENTS]


# ── robust z-score ─────────────────────────────────────────
def test_robust_zscore():
    assert (robust_zscore(pd.Series([5.0, 5.0, 5.0, 5.0])) == 0).all()    # 상수 → 0
    s = robust_zscore(pd.Series([1.0, 2.0, 3.0, np.nan]))
    assert pd.isna(s.iloc[3]) and pd.notna(s.iloc[0])                      # NaN 보존
    z = robust_zscore(pd.Series([1.0, 2.0, 3.0, 4.0, 100.0]))
    assert z.iloc[2] == pytest.approx(0.0)                                # 중앙값 원소 → 0
    assert z.is_monotonic_increasing


# ── combine_layers: 레이어 가중 + 결측 재정규화 ────────────
def test_combine_layers_renormalize():
    z = pd.DataFrame(index=["X", "Y"])
    for c in LAYER_COMPONENTS["realized"]:
        z[c] = [1.0, 1.0]
    for c in LAYER_COMPONENTS["forward"]:
        z[c] = [2.0, 1.0]
    for c in LAYER_COMPONENTS["momentum"]:
        z[c] = [np.nan, 1.0]          # X는 모멘텀 결측
    cl = combine_layers(z)
    assert pd.isna(cl.loc["X", "momentum"])
    assert cl.loc["X", "realized"] == pytest.approx(1.0)
    assert cl.loc["X", "forward"] == pytest.approx(2.0)
    # X: 모멘텀 빠지고 (0.40·1 + 0.35·2)/(0.40+0.35) = 1.4667  (0으로 안 채움)
    assert cl.loc["X", "combined_raw"] == pytest.approx((0.40 * 1 + 0.35 * 2) / 0.75)
    # Y: 전 레이어 존재 → 0.40+0.25+0.35 = 1.0
    assert cl.loc["Y", "combined_raw"] == pytest.approx(1.0)


# ── (1) 배치 5종목 ─────────────────────────────────────────
def test_batch_five():
    res = aggregate_batch(_df({"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}))
    assert res["score"].between(-100, 100).all()
    assert res["combined_raw"].is_monotonic_increasing       # 강도 순
    assert res["score"].is_monotonic_increasing
    assert res.loc["E", "score"] == pytest.approx(100.0)     # 최강 → 상위 percentile
    assert res.loc["C", "score"] == pytest.approx(20.0)      # 중앙(percentile 0.6)


# ── (2) 단일종목 ───────────────────────────────────────────
def test_single_stock():
    pool = _df({"P1": 1, "P2": 2, "P3": 3, "P4": 4})
    strong = {c: 6.0 for c in ALL_COMPONENTS}
    out = aggregate_single(strong, pool, confidence=1.0, code="T")
    assert out["score"] == pytest.approx(100.0)              # 풀 대비 최강 → +100
    weak = {c: 0.0 for c in ALL_COMPONENTS}
    out2 = aggregate_single(weak, pool, confidence=1.0, code="T")
    assert out2["score"] < 0                                  # 풀 대비 최약 → 음수


# ── (3) 일부 결측 ──────────────────────────────────────────
def test_partial_missing_renormalized():
    df = _df({"A": 1, "B": 2, "C": 3, "D": 4, "E": 5})
    df.loc["C", ["accel", "diffusion_trend"]] = np.nan        # C 모멘텀 전체 결측
    res = aggregate_batch(df)
    assert pd.isna(res.loc["C", "momentum"])                  # 모멘텀 NaN
    assert pd.notna(res.loc["C", "combined_raw"])             # 나머지 레이어로 결합
    assert pd.notna(res.loc["C", "score"])                    # 점수 산출됨(0으로 안 채움)


# ── 신뢰도 멀티플라이어 효과 ───────────────────────────────
def test_confidence_effect():
    # A·B 동일 강세(비중앙), C·D 약세 → A,B의 combined_raw>0 이라야 신뢰도 효과가 보임
    df = _df({"A": 5, "B": 5, "C": 1, "D": 1})
    res = aggregate_batch(df, confidence={"A": 1.0, "B": 0.5, "C": 1.0, "D": 1.0})
    assert res.loc["A", "combined_raw"] > 0
    assert res.loc["A", "combined_adj"] > res.loc["B", "combined_adj"]   # 신뢰도가 B 축소
    assert res.loc["A", "score"] >= res.loc["B", "score"]


# ── 멀티 섹터 그룹 표준화 ─────────────────────────────────
def test_multi_sector_grouping():
    df = _df({"A": 1, "B": 5, "X": 1, "Y": 5})
    sector = {"A": "S1", "B": "S1", "X": "S2", "Y": "S2"}
    res = aggregate_batch(df, sector=sector)
    # 섹터별로 독립 표준화 → 각 섹터 강자(B, Y)가 자기 섹터서 +100, 약자는 더 낮음
    assert res.loc["B", "score"] == pytest.approx(100.0)
    assert res.loc["Y", "score"] == pytest.approx(100.0)
    assert res.loc["A", "score"] < res.loc["B", "score"]
    assert res.loc["X", "score"] < res.loc["Y", "score"]
