"""STEP 7 pytest — 인사이트 문장 + 통합 파이프라인 종단."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from epsrev.trade_score.schema import (AxisSignals, SectorScore, CompanyScore,
                                       Reliability, SectorProfile)
from epsrev.trade_score.insight import (sector_insight, company_insight,
                                        sector_flags_extra, company_flags_extra)
from epsrev.trade_score.pipeline import compute_all, SECNAME_TO_TRADE_CAT


# ================= 인사이트 =================
def _sector(score=50.0, mom=1.0, acc=2.0, qual=0.5, cyc=0.3, conf=1.0, flags=None):
    return SectorScore(sector="테스트", sector_score=score,
                       axes=AxisSignals(mom=mom, acc=acc, qual=qual, cyc=cyc),
                       weights={"mom": .25, "acc": .35, "qual": .2, "cyc": .2},
                       profile=SectorProfile(), confidence=conf, flags=flags or [])


def test_sector_insight_names_dominant_axis():
    s = _sector(acc=2.5)                       # acc 기여 최대(0.35×2.5)
    txt = sector_insight(s)
    assert "가속" in txt and "+50" in txt


def test_sector_insight_peak_warning():
    s = _sector(score=10.0, mom=2.0, acc=-1.5)  # 모멘텀 양수 + 가속 급락
    assert "정점 통과" in sector_insight(s)


def test_sector_insight_base_effect_and_quality_warning():
    s = _sector(flags=["base_effect"], qual=-1.8)
    txt = sector_insight(s)
    assert "기저효과" in txt and "단가 주도" in txt


def test_sector_low_coverage_flag():
    s = _sector(conf=0.3)
    assert "low_coverage" in sector_flags_extra(s)
    s.flags += sector_flags_extra(s)
    assert "커버리지 낮음" in sector_insight(s)


def test_sector_insight_no_data():
    s = SectorScore(sector="빈섹터", sector_score=None)
    assert "데이터 부족" in sector_insight(s)


def _company(score=40.0, E=40.0, I=None, r_E=1.0, r_I=0.0, exposure=1.0, flags=None):
    return CompanyScore(ticker="000001", company_score=score, export_part=E,
                        industry_part=I, exposure=exposure,
                        reliability=Reliability(r_export=r_E, r_industry=r_I),
                        flags=flags or [])


def test_company_insight_fallback_mentions_exposure():
    txt = company_insight(_company(), direct_export=False)
    assert "섹터폴백" in txt and "산업렌즈 미연동" in txt


def test_company_insight_direct():
    txt = company_insight(_company(), direct_export=True)
    assert "직접수출" in txt


def test_company_insight_divergence_and_inherit():
    div = _company(I=-60.0, r_I=1.0, flags=["divergence"])
    assert "상충" in company_insight(div)
    inh = _company(E=None, flags=["sector_inherit"])
    assert "상속" in company_insight(inh)


def test_company_insight_none():
    c = CompanyScore(ticker="X", company_score=None)
    assert "커버리지 없음" in company_insight(c)


def test_company_low_coverage_flag():
    # 신뢰합 낮으면(폴백 노출 낮아 r 하락) low_coverage
    c = _company(r_E=0.2, r_I=0.0)      # r_sum=0.2 < 0.3
    assert "low_coverage" in company_flags_extra(c)
    # 신뢰합 충분하면(I-only여도) 오탐 없음
    ok = _company(E=None, I=-69.0, r_E=0.0, r_I=1.0, exposure=0.0)
    assert "low_coverage" not in company_flags_extra(ok)


# ================= 통합 파이프라인 종단 =================
def _synthetic_item_m():
    """2개 섹터 36개월: 강한(성장 가속) vs 약한(감소) — 합성 수출 데이터."""
    dates = pd.period_range("2023-01", periods=36, freq="M").to_timestamp(how="end")
    rows = []
    rng = np.random.default_rng(1)
    for i, d in enumerate(dates):
        rows.append({"category": "강한섹터", "item_name": "품목A", "date": d,
                     "export_amount": 100 * (1.03 ** i) * (1 + rng.normal(0, .01)),
                     "volume_yoy": 12.0, "price_yoy": 2.0})
        rows.append({"category": "약한섹터", "item_name": "품목B", "date": d,
                     "export_amount": 100 * (0.985 ** i) * (1 + rng.normal(0, .01)),
                     "volume_yoy": -6.0, "price_yoy": 3.0})
    return pd.DataFrame(rows)


def _synthetic_comp_m(dates):
    rows = [{"item_name": "품목A", "company_name": "직접기업", "date": d,
             "export_amount": 50 * (1.04 ** i), "volume_yoy": 15.0, "price_yoy": 1.0}
            for i, d in enumerate(dates)]
    return pd.DataFrame(rows)


def test_pipeline_end_to_end():
    item_m = _synthetic_item_m()
    comp_m = _synthetic_comp_m(sorted(item_m["date"].unique()))
    co_map = {"000001": {"n": "직접기업", "secName": "강한섹터"},
              "000002": {"n": "폴백기업", "secName": "약한섹터"},
              "000003": {"n": "미매핑기업", "secName": "금융·지주"}}
    # 테스트용: 합성 섹터명을 매핑에 임시 주입
    SECNAME_TO_TRADE_CAT["강한섹터"] = "강한섹터"
    SECNAME_TO_TRADE_CAT["약한섹터"] = "약한섹터"
    try:
        # I렌즈 비활성(빈 스냅샷 주입) — 이 테스트는 E렌즈 종단만 검증(헤르메틱)
        out = compute_all(item_m=item_m, comp_m=comp_m,
                          tickers=["000001", "000002", "000003"], co_map=co_map,
                          industry_snapshot={"series": {}}, creditcard_snapshot={"companies": {}})
    finally:
        SECNAME_TO_TRADE_CAT.pop("강한섹터"), SECNAME_TO_TRADE_CAT.pop("약한섹터")

    # 섹터: 강한 > 약한, insight 존재
    secs = out["sectors"]
    assert secs["강한섹터"].sector_score > secs["약한섹터"].sector_score
    assert all(s.insight for s in secs.values())

    # 직접기업: 직접수출 렌즈(r_E = recency·length·1.0), insight에 '직접수출'
    c1 = out["companies"]["000001"]
    assert c1.company_score is not None and "직접수출" in c1.insight
    assert c1.reliability.r_industry == 0.0            # 스냅샷 없음 → r_I=0

    # 폴백기업: 섹터폴백 문구 + 섹터점수×exposure
    c2 = out["companies"]["000002"]
    assert "섹터폴백" in c2.insight
    assert c2.export_part == pytest.approx(secs["약한섹터"].sector_score * 1.0)

    # 미매핑(금융): 수출 카테고리 없음 → 무점수 + 커버리지 없음 인사이트
    c3 = out["companies"]["000003"]
    assert c3.company_score is None and "커버리지 없음" in c3.insight
