"""품목(item) 단위 엔진 스코어 — 수출입 대시보드 Signal Score를 엔진 방법론으로 통일.

기존 SIGNAL_SCORE_WEIGHTS(고정 가중 순위합)를 대체:
  품목별 4축 원신호 → 자기 이력 z → '품목이 속한 카테고리'의 자동 가중(ρπσ) →
  전 품목 raw 분포 percentile → 0~100 (기존 표시 스케일 유지).
엔진 산출 실패 품목은 호출부가 기존 점수로 폴백한다.
"""
from __future__ import annotations

import pandas as pd

from epsrev.trade_score.signals import growth_signals
from epsrev.trade_score.normalize import (axis_signal_histories, normalize_signals,
                                          indicator_stats, sector_profile_raw,
                                          finalize_profiles, W_BASE)
from epsrev.trade_score.aggregate import weighted_axis_sum, percentile_to_score


def _category_profiles(metrics_df: pd.DataFrame) -> dict:
    """카테고리(수출 섹터)별 자동 가중 — 섹터 컨텍스트와 동일 방법."""
    praws = {}
    for cat, g in metrics_df.groupby("category"):
        s = g.groupby("date")["export_amount"].sum().sort_index()
        vh = g.groupby("date")["volume_yoy"].median().sort_index()
        ph = g.groupby("date")["price_yoy"].median().sort_index()
        praws[cat] = sector_profile_raw([indicator_stats(
            values=s, series_type="growth", price_yoy_hist=ph, volume_yoy_hist=vh)])
    return finalize_profiles(praws)


def item_scores(metrics_df: pd.DataFrame) -> pd.DataFrame:
    """품목별 엔진 signal_score(0~100). 반환: [item_name, signal_score].

    metrics_df = compute_item_metrics 결과(품목×월 전 이력 —
    ma3_yoy/ma3_yoy_prev/volume_yoy/price_yoy/export_amount 필요).
    """
    if metrics_df is None or metrics_df.empty:
        return pd.DataFrame(columns=["item_name", "signal_score"])

    profiles = _category_profiles(metrics_df)

    rows = []
    for item, g in metrics_df.groupby("item_name"):
        g = g.sort_values("date")
        series = g.set_index("date")["export_amount"].astype(float)
        last = g.iloc[-1]
        raw_sig = growth_signals(
            series,
            ma3_yoy=last.get("ma3_yoy"), ma3_yoy_prev=last.get("ma3_yoy_prev"),
            volume_yoy=last.get("volume_yoy"), price_yoy=last.get("price_yoy"))
        hists = axis_signal_histories(
            series, "growth",
            ma3_yoy_hist=g.set_index("date")["ma3_yoy"],
            volume_yoy_hist=g.set_index("date")["volume_yoy"],
            price_yoy_hist=g.set_index("date")["price_yoy"])
        axes_z = normalize_signals(raw_sig, hists)
        cat = last.get("category")
        weights = profiles[cat].weights if cat in profiles else dict(W_BASE)
        raw, _ = weighted_axis_sum(axes_z, weights)
        rows.append({"item_name": item, "_raw": raw})

    pool = [r["_raw"] for r in rows if r["_raw"] is not None]
    for r in rows:
        if r["_raw"] is None or not pool:
            r["signal_score"] = None
        else:
            # −100~+100 percentile → 기존 표시 스케일 0~100
            r["signal_score"] = round((percentile_to_score(r["_raw"], pool) + 100.0) / 2.0, 1)
        r.pop("_raw")
    return pd.DataFrame(rows)
