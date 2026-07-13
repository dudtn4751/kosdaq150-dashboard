"""기업 종합 — 두 렌즈(E 수출 / I 산업) (핸드오프 4·6절 · STEP 6).

렌즈 배정은 지표 src로 결정(★이중계산 금지):
  src=="trade"    → E(수출) 렌즈
  src=="industry" → I(산업) 렌즈
같은 섹터에 두 src가 섞여 있어도 각자 올바른 렌즈로만 들어간다.

각 렌즈 값:
  E = 기업 직접수출 점수(있으면) · else 섹터수출 점수 × exposure
  I = 기업 직접(신용카드 companyId 등) 점수(있으면) · else 섹터산업 점수 × exposure
      (산업/CC 스냅샷 없으면 direct·sector 모두 None → r_I=0)

종합:
  score = (r_E·E + r_I·I) / (r_E + r_I),  결측 렌즈 drop.
  r = f_recency · f_length · f_direct   (f_direct=1.0 직접 / exposure 폴백)
  둘 다 결측이면 섹터 점수 상속(sector_inherit).
E·I가 크게 엇갈리면 divergence 플래그.
"""
from __future__ import annotations

import math
from typing import Optional

from epsrev.trade_score.schema import CompanyScore, Reliability

DIVERGENCE_GAP = 80.0    # |E − I| ≥ 이 값(−100~100 스케일) → 발산 플래그
DEFAULT_EXPOSURE = 1.0   # 노출 정보 없을 때 기본(폴백 시)


def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


# ---------- src 라우팅 ----------
def route_indicators_by_src(indicators: list):
    """SECTOR_INDUSTRY 지표 리스트 → (export_indicators, industry_indicators).
    src=="trade"→E, 그 외("industry" 기본)→I."""
    export, industry = [], []
    for it in indicators or []:
        (export if it.get("src") == "trade" else industry).append(it)
    return export, industry


# ---------- 노출도 ----------
def compute_exposure(hs_matched: Optional[float] = None,
                     export_share: Optional[float] = None) -> float:
    """exposure ∈ 0~1 = (HS_MAP/품목 매칭도) × (매출 내 수출비중).
    각 요소 없으면 1.0 취급 → 둘 다 없으면 DEFAULT_EXPOSURE."""
    m = 1.0 if _num(hs_matched) is None else max(0.0, min(1.0, float(hs_matched)))
    s = 1.0 if _num(export_share) is None else max(0.0, min(1.0, float(export_share)))
    return max(0.0, min(1.0, m * s))


# ---------- 렌즈 1개 → (value, reliability) ----------
def _lens(direct_score, sector_score, exposure: float,
          f_recency: float, f_length: float):
    """(lens_value, r). 직접점수 우선(f_direct=1.0), 없으면 섹터×exposure(f_direct=exposure).
    둘 다 없으면 (None, 0.0)."""
    direct = _num(direct_score)
    if direct is not None:
        r = _clip01(f_recency) * _clip01(f_length) * 1.0
        return direct, r
    sec = _num(sector_score)
    if sec is not None:
        exp = max(0.0, min(1.0, float(exposure)))
        r = _clip01(f_recency) * _clip01(f_length) * exp
        return sec * exp, r
    return None, 0.0


def _clip01(x) -> float:
    v = _num(x)
    return 0.0 if v is None else max(0.0, min(1.0, v))


# ---------- 종합 ----------
def company_score(ticker: str, *,
                  # E(수출) 렌즈 입력
                  export_direct: Optional[float] = None,
                  export_sector: Optional[float] = None,
                  export_recency: float = 1.0, export_length: float = 1.0,
                  # I(산업) 렌즈 입력
                  industry_direct: Optional[float] = None,
                  industry_sector: Optional[float] = None,
                  industry_recency: float = 1.0, industry_length: float = 1.0,
                  # 공통
                  exposure: float = DEFAULT_EXPOSURE,
                  sector_inherit: Optional[float] = None,
                  insight: str = "") -> CompanyScore:
    """두 렌즈 종합. r_I=0(산업 스냅샷 없음)이면 자연히 E 단독 점수가 된다."""
    E, r_E = _lens(export_direct, export_sector, exposure, export_recency, export_length)
    I, r_I = _lens(industry_direct, industry_sector, exposure, industry_recency, industry_length)

    flags = []
    # 발산: 두 렌즈 모두 유효할 때만
    if E is not None and I is not None and abs(E - I) >= DIVERGENCE_GAP:
        flags.append("divergence")

    denom = r_E + r_I
    if denom > 0 and (E is not None or I is not None):
        num = (r_E * (E or 0.0) if E is not None else 0.0) + \
              (r_I * (I or 0.0) if I is not None else 0.0)
        # 유효 렌즈만 분모에 (결측 렌즈 drop)
        eff_denom = (r_E if E is not None else 0.0) + (r_I if I is not None else 0.0)
        score = num / eff_denom if eff_denom > 0 else None
    else:
        score = None

    # 둘 다 결측 → 섹터 상속
    if score is None:
        inh = _num(sector_inherit)
        if inh is not None:
            score = inh
            flags.append("sector_inherit")

    return CompanyScore(
        ticker=ticker, company_score=score,
        export_part=E, industry_part=I, exposure=max(0.0, min(1.0, float(exposure))),
        reliability=Reliability(r_export=r_E, r_industry=r_I),
        flags=flags, insight=insight,
    )
