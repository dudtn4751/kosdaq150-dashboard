"""집계 — 컴포넌트 섹터 내 표준화 + 레이어 결합 + 섹터 percentile → -100~+100.

흐름 (단일종목/배치 공통):
  1) 각 컴포넌트를 섹터 내 robust z-score로 표준화 (winsorize ±3σ 먼저)
  2) 레이어 내부 컴포넌트 균등가중 평균(결측은 빼고 재정규화 — 0으로 안 채움)
  3) 레이어 가중합: realized 0.40 · momentum 0.25 · forward 0.35 (결측 레이어 빼고 재정규화)
  4) × 신뢰도 멀티플라이어
  5) 섹터 내 percentile → -100~+100 매핑

방향: 모든 채택 컴포넌트는 '높을수록 강세(롱)'. disp_cv는 방향 반대+신뢰도게이트에서 사용 →
      점수 컴포넌트에서 제외. news_lead는 보조(현재 균등, 추후 하향 튜닝 예정).
순수 함수, pandas. 결측 컴포넌트는 가중 0으로 빼고 재정규화.
"""

from __future__ import annotations

from typing import Dict, Mapping, Optional, Union

import numpy as np
import pandas as pd

# 레이어별 채택 컴포넌트(모두 높을수록 강세) + 레이어 가중
LAYER_COMPONENTS: Dict[str, list] = {
    "realized": ["rev_op_3m", "rev_op_1m", "rev_eps_3m", "rev_eps_1m", "diffusion_idx", "sue"],
    "momentum": ["accel", "diffusion_trend"],            # disp_cv 제외(방향반대·신뢰도게이트서 사용)
    "forward": ["runrate_gap", "tp_lead", "persistence", "news_lead"],
}
LAYER_WEIGHTS: Dict[str, float] = {"realized": 0.40, "momentum": 0.25, "forward": 0.35}
ALL_COMPONENTS = [c for comps in LAYER_COMPONENTS.values() for c in comps]
WINSOR_SIGMA = 3.0
MAD_C = 1.4826   # MAD → 표준편차 일치 상수(정규분포)


def robust_zscore(series: pd.Series) -> pd.Series:
    """winsorize ±3σ 후 robust z-score = (x - median) / (1.4826·MAD).

    NaN은 보존(표준화서 제외). MAD 0이면 std로 폴백, 그것도 0이면 0.
    """
    s = pd.to_numeric(series, errors="coerce")
    if s.notna().sum() == 0:
        return s
    mu, sd = s.mean(), s.std()
    s_w = s.clip(mu - WINSOR_SIGMA * sd, mu + WINSOR_SIGMA * sd) if (sd and sd > 0) else s
    med = s_w.median()
    mad = (s_w - med).abs().median()
    if mad and mad > 0:
        return (s_w - med) / (MAD_C * mad)
    sd2 = s_w.std()
    if sd2 and sd2 > 0:
        return (s_w - med) / sd2
    return s_w.where(s_w.isna(), 0.0)   # 분산 0 → 모두 동일 → 0 (NaN 보존)


def standardize_components(df: pd.DataFrame) -> pd.DataFrame:
    """컴포넌트별(열) 섹터 내 robust z. 없는 컴포넌트 열은 건너뜀."""
    out = pd.DataFrame(index=df.index)
    for col in ALL_COMPONENTS:
        if col in df.columns:
            out[col] = robust_zscore(df[col])
    return out


def combine_layers(zdf: pd.DataFrame) -> pd.DataFrame:
    """표준화된 컴포넌트 → 레이어 점수(균등평균) + combined_raw(레이어 가중합, 결측 재정규화)."""
    out = pd.DataFrame(index=zdf.index)
    for layer, comps in LAYER_COMPONENTS.items():
        cols = [c for c in comps if c in zdf.columns]
        # 균등가중 = 가용 컴포넌트 평균(결측 자동 제외·재정규화). 전부 결측이면 NaN
        out[layer] = zdf[cols].mean(axis=1, skipna=True) if cols else np.nan
    num = pd.Series(0.0, index=zdf.index)
    den = pd.Series(0.0, index=zdf.index)
    for layer, w in LAYER_WEIGHTS.items():
        ls = out[layer]
        mask = ls.notna()
        num = num.add((ls * w).where(mask, 0.0), fill_value=0.0)
        den = den.add(pd.Series(w, index=zdf.index).where(mask, 0.0), fill_value=0.0)
    out["combined_raw"] = num / den.replace(0.0, np.nan)   # 가용 레이어 없으면 NaN
    return out


def _to_series(val: Optional[Union[Mapping, pd.Series, float]], index: pd.Index,
               default: float = 1.0) -> pd.Series:
    if val is None:
        return pd.Series(default, index=index, dtype=float)
    if isinstance(val, pd.Series):
        return val.reindex(index).fillna(default).astype(float)
    if isinstance(val, Mapping):
        return pd.Series({k: val.get(k, default) for k in index}, dtype=float)
    return pd.Series(float(val), index=index, dtype=float)   # 스칼라


def _percentile_score(combined_adj: pd.Series) -> pd.Series:
    """섹터 내 percentile → -100~+100. 유효 표본 2개 미만이면 중립 0."""
    valid = combined_adj.notna()
    score = pd.Series(np.nan, index=combined_adj.index)
    if valid.sum() >= 2:
        pct = combined_adj[valid].rank(pct=True)        # (0,1]
        score.loc[valid] = ((pct - 0.5) * 200).round(1)  # -100~+100
    elif valid.sum() == 1:
        score.loc[valid] = 0.0                            # 단일 표본 → 랭크 불가 → 중립
    return score


def aggregate_batch(components_df: pd.DataFrame,
                    confidence: Optional[Union[Mapping, pd.Series]] = None,
                    sector: Optional[Union[str, Mapping, pd.Series]] = None) -> pd.DataFrame:
    """배치 집계. components_df(index=code, 열=컴포넌트) → 점수 DataFrame.

    confidence: code→0.5~1.0 (없으면 1.0). sector: 단일 str/None=한 풀, 또는 code→sector(그룹별 표준화).
    반환 열: realized, momentum, forward, combined_raw, confidence, combined_adj, score(-100~+100).
    """
    df = components_df.copy()
    conf = _to_series(confidence, df.index, 1.0)
    sec = (None if sector is None or isinstance(sector, str)
           else _to_series_str(sector, df.index))

    parts = []
    if sec is None:
        groups = [df.index]
    else:
        groups = [df.index[sec.loc[df.index] == s] for s in sec.loc[df.index].dropna().unique()]
    for idx in groups:
        z = standardize_components(df.loc[idx])
        cl = combine_layers(z)
        cl["confidence"] = conf.loc[idx]
        cl["combined_adj"] = cl["combined_raw"] * cl["confidence"]
        cl["score"] = _percentile_score(cl["combined_adj"])
        parts.append(cl)
    res = pd.concat(parts).reindex(df.index)
    return res[["realized", "momentum", "forward", "combined_raw", "confidence", "combined_adj", "score"]]


def _to_series_str(val: Union[Mapping, pd.Series], index: pd.Index) -> pd.Series:
    if isinstance(val, pd.Series):
        return val.reindex(index)
    return pd.Series({k: val.get(k) for k in index})


def aggregate_single(stock_components: Mapping[str, Optional[float]],
                     sector_pool: pd.DataFrame,
                     confidence: float = 1.0,
                     code: str = "_target") -> Dict[str, object]:
    """단일종목 모드 — 종목 컴포넌트 1건 + 같은 섹터 분포(sector_pool)로 표준화·랭크.

    sector_pool: 같은 섹터 종목들의 컴포넌트 DataFrame(타깃 포함/미포함 무관).
    반환: 타깃의 점수 dict(score·layers·combined_raw·confidence).
    """
    row = pd.DataFrame([dict(stock_components)], index=[code])
    cols = sorted(set(sector_pool.columns) | set(row.columns) | set(ALL_COMPONENTS))
    pool = sector_pool.reindex(columns=cols)
    pool = pool.loc[[c for c in pool.index if c != code]]    # 타깃 중복 제거
    combined = pd.concat([pool, row.reindex(columns=cols)])
    conf = pd.Series(1.0, index=combined.index, dtype=float)
    conf.loc[code] = confidence                               # 풀 신뢰도 미상 → 1.0 가정
    res = aggregate_batch(combined, confidence=conf, sector=None)
    return res.loc[code].to_dict()
