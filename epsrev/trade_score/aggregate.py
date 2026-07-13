"""집계 — 신뢰도·베이스효과(STEP 4) + 섹터 집계·cross-sector percentile(STEP 5).

섹터 점수 파이프라인(핸드오프 3절):
  raw = Σ w·C (결측 축 가중제외 재정규화) → base_effect 감쇄 → ×confidence
  → 전 섹터 raw 분포 percentile → −100~+100.
"""
from __future__ import annotations

import math
from typing import Optional

import pandas as pd

from epsrev.trade_score.schema import AxisSignals, SectorProfile, SectorScore

# ---- 신뢰도 감쇄 상수 (핸드오프 4절) ----
RECENCY_FULL_MONTHS = 2     # 지연 ≤2M → f_recency=1.0
RECENCY_DECAY_MONTHS = 12   # 12M 지연 → 0.5 (2→12M 선형감쇄)
RECENCY_FLOOR = 0.5         # 그 이상 하한 유지
LENGTH_FULL_MONTHS = 24     # 이력 24M 이상 → f_length=1.0

# ---- 베이스효과 판정 상수 (핸드오프 5절, growth형 전용) ----
BASE_YOY_SURGE = 30.0       # |yoy| 급증 기준(%)
BASE_PRIOR_TROUGH = -10.0   # 전년동월 yoy 트로프 기준(%)
BASE_MA3_GAP = 15.0         # yoy ↔ ma3_yoy 괴리 기준(%p)


def _to_month(ts) -> Optional[pd.Period]:
    """latest_m 유연 파싱: Timestamp/Period/'YYYY-MM'/YYYYMM(int) → 월 Period."""
    if ts is None:
        return None
    try:
        if isinstance(ts, pd.Period):
            return ts.asfreq("M")
        s = str(ts)
        if s.isdigit() and len(s) == 6:
            return pd.Period(year=int(s[:4]), month=int(s[4:6]), freq="M")
        return pd.Timestamp(s).to_period("M")
    except Exception:
        return None


def confidence(latest_m, n_months: Optional[int], missing_ratio: Optional[float],
               as_of=None) -> float:
    """0~1 신뢰도 = f_recency · f_length · f_completeness.

    f_recency      : 지연 ≤2M → 1.0, 12M → 0.5 선형감쇄, 이후 0.5 하한 유지.
    f_length       : min(1, n_months/24).
    f_completeness : 1 − missing_ratio (0~1 클립).
    파싱 불능/결측 입력은 해당 요소를 최악값으로(감쇄 방향) 처리한다.
    """
    # f_recency
    latest = _to_month(latest_m)
    now = _to_month(as_of) or pd.Timestamp.today().to_period("M")
    if latest is None:
        f_recency = RECENCY_FLOOR
    else:
        lag = max(0, (now - latest).n)
        if lag <= RECENCY_FULL_MONTHS:
            f_recency = 1.0
        elif lag >= RECENCY_DECAY_MONTHS:
            f_recency = RECENCY_FLOOR
        else:
            span = RECENCY_DECAY_MONTHS - RECENCY_FULL_MONTHS
            f_recency = 1.0 - (1.0 - RECENCY_FLOOR) * (lag - RECENCY_FULL_MONTHS) / span

    # f_length
    n = 0 if n_months is None else max(0, int(n_months))
    f_length = min(1.0, n / LENGTH_FULL_MONTHS)

    # f_completeness
    m = 1.0 if missing_ratio is None else float(missing_ratio)
    if math.isnan(m) or math.isinf(m):
        m = 1.0
    f_completeness = min(1.0, max(0.0, 1.0 - m))

    return f_recency * f_length * f_completeness


def base_effect_flag(yoy, ma3_yoy, prior_yoy, series_type: str = "growth") -> bool:
    """베이스효과 의심 플래그(참이면 점수 감쇄용).

    growth형 전용: ① |yoy| 급증(≥BASE_YOY_SURGE) ② 전년동월 yoy가 트로프
    (≤BASE_PRIOR_TROUGH — 낮은 기저) ③ yoy와 ma3_yoy 괴리 큼(≥BASE_MA3_GAP)
    세 조건 동시 충족 시 True.
    ★ level형은 항상 False — 레벨엔 '전년 기저' 개념이 없음(YoY 로직 자체 금지).
    입력 결측(None/NaN)은 판정 불가 → False.
    """
    if series_type == "level":
        return False

    vals = []
    for v in (yoy, ma3_yoy, prior_yoy):
        if v is None:
            return False
        try:
            f = float(v)
        except (TypeError, ValueError):
            return False
        if math.isnan(f) or math.isinf(f):
            return False
        vals.append(f)
    y, ma3, prior = vals

    surged = abs(y) >= BASE_YOY_SURGE
    prior_trough = prior <= BASE_PRIOR_TROUGH
    ma3_gap = abs(y - ma3) >= BASE_MA3_GAP
    return surged and prior_trough and ma3_gap


# ======================================================================
# 섹터 집계 (핸드오프 3절 · STEP 5)
# ======================================================================
BASE_EFFECT_PENALTY = 0.5   # base_effect_flag True → raw 크기 감쇄 배수
AXES = ("mom", "acc", "qual", "cyc")


def weighted_axis_sum(axes_z: AxisSignals, weights: dict):
    """raw = Σ w·C. C=None 축은 가중 제외 후 나머지 Σ=1 재정규화.

    반환 (raw, effective_weights). 유효 축이 없으면 (None, {}).
    level 섹터의 qual=None은 여기서 자연 제외된다.
    """
    valid = {}
    for ax in AXES:
        c = getattr(axes_z, ax, None)
        w = weights.get(ax)
        if c is None or w is None or w <= 0:
            continue
        if isinstance(c, float) and (math.isnan(c) or math.isinf(c)):
            continue
        valid[ax] = (float(w), float(c))
    total_w = sum(w for w, _ in valid.values())
    if total_w <= 0:
        return None, {}
    eff = {ax: w / total_w for ax, (w, _) in valid.items()}
    raw = sum(eff[ax] * c for ax, (_, c) in valid.items())
    return raw, eff


def sector_raw(axes_z: AxisSignals, weights: dict, conf: float, base_flag: bool):
    """percentile 매핑 전의 섹터 raw. (raw, effective_weights)."""
    raw, eff = weighted_axis_sum(axes_z, weights)
    if raw is None:
        return None, eff
    if base_flag:
        raw *= BASE_EFFECT_PENALTY      # 크기 감쇄(0 방향) — 방향 반전 없음
    c = 0.0 if conf is None else min(1.0, max(0.0, float(conf)))
    return raw * c, eff


def percentile_to_score(raw: float, cross_raws) -> float:
    """전 섹터 raw 분포 내 percentile(0~1, 동값 0.5 처리) → −100~+100."""
    pool = [r for r in cross_raws if r is not None
            and not (isinstance(r, float) and (math.isnan(r) or math.isinf(r)))]
    if not pool:
        return 0.0
    below = sum(1 for r in pool if r < raw)
    equal = sum(1 for r in pool if r == raw)
    pct = (below + 0.5 * equal) / len(pool)
    return (pct * 2.0 - 1.0) * 100.0


def sector_score(sector: str, axes_z: AxisSignals, weights: dict,
                 conf: float, base_flag: bool, cross_sector_raws,
                 profile: Optional[SectorProfile] = None) -> SectorScore:
    """단일 섹터 점수. cross_sector_raws = 전 섹터 raw 리스트(자기 자신 포함 권장)."""
    raw, eff = sector_raw(axes_z, weights, conf, base_flag)
    flags = ["base_effect"] if base_flag else []
    if raw is None:
        return SectorScore(sector=sector, sector_score=None, axes=axes_z,
                           weights=eff, profile=profile or SectorProfile(),
                           confidence=conf, flags=flags + ["no_data"], insight="")
    return SectorScore(
        sector=sector,
        sector_score=percentile_to_score(raw, cross_sector_raws),
        axes=axes_z, weights=eff,
        profile=profile or SectorProfile(),
        confidence=conf, flags=flags, insight="",
    )


def sector_scores_batch(entries: list) -> list:
    """배치(전 섹터 동시) — percentile 분포를 배치 raw로 구성.

    entry: {"sector", "axes"(z화 AxisSignals), "weights", "confidence",
            "base_flag"(bool), "profile"(옵션)}
    """
    raws = []
    for e in entries:
        raw, eff = sector_raw(e["axes"], e["weights"], e.get("confidence", 1.0),
                              bool(e.get("base_flag", False)))
        raws.append((raw, eff))
    pool = [r for r, _ in raws if r is not None]

    out = []
    for e, (raw, eff) in zip(entries, raws):
        base_flag = bool(e.get("base_flag", False))
        flags = ["base_effect"] if base_flag else []
        if raw is None:
            out.append(SectorScore(sector=e["sector"], sector_score=None,
                                   axes=e["axes"], weights=eff,
                                   profile=e.get("profile") or SectorProfile(),
                                   confidence=e.get("confidence"),
                                   flags=flags + ["no_data"], insight=""))
            continue
        out.append(SectorScore(sector=e["sector"],
                               sector_score=percentile_to_score(raw, pool),
                               axes=e["axes"], weights=eff,
                               profile=e.get("profile") or SectorProfile(),
                               confidence=e.get("confidence"),
                               flags=flags, insight=""))
    return out
