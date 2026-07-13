"""통합 파이프라인 (STEP 7) — STEP 1~6을 엮는 진입점.

compute_all()        : 수출 실측 → 전 섹터 SectorScore + (요청 티커) CompanyScore, insight 포함.
get_trade_score(tk)  : 티커 1개의 CompanyScore (섹터 컨텍스트는 프로세스 캐시).

⚠️ 기존 sc.d(calc_data_score)·대시보드 signal_score 교체/UI 연결은 하지 않는다 —
   산업 스냅샷(PHASE B) 전에는 무수출 기업이 무점수로 회귀하므로 연동은 그 후.
산업(I) 렌즈: 스냅샷(data/bf_industry.json·bf_creditcard.json) 부재 시 r_I=0 (현행 정상).
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from epsrev.trade_score.schema import SectorScore, CompanyScore
from epsrev.trade_score.signals import growth_signals
from epsrev.trade_score.normalize import (axis_signal_histories, normalize_signals,
                                          indicator_stats, sector_profile_raw,
                                          finalize_profiles)
from epsrev.trade_score.aggregate import (confidence, base_effect_flag, sector_raw,
                                          percentile_to_score, recency_factor,
                                          length_factor)
from epsrev.trade_score.company import company_score, compute_exposure
from epsrev.trade_score.insight import (sector_insight, company_insight,
                                        sector_flags_extra, company_flags_extra)

# 앱 섹터(secName) → 수출 카테고리 (v1 근사 — 정확 일치 + 명시 매핑만, 나머지 None)
SECNAME_TO_TRADE_CAT = {
    "반도체": "반도체",
    "전기전자": "전기전자",
    "2차전지·배터리소재": "2차전지·배터리소재",
    "철강·비철금속": "철강·비철금속",
    "건설·운송·상사": "건설·운송·상사",
    "전력기기·전력인프라·원전": "전력기기·전력인프라·원전",
    "바이오·의료기기": "바이오/의료기기",
    "K소비재·유통": "화장품",   # 대표 근사(화장품 비중) — 세분은 PHASE B에서
    # 자동차·모빌리티 / 금융·지주 / 정유·화학·석유화학 / 조선·방산·우주항공 /
    # 인터넷·소프트웨어·게임·콘텐츠 → 수출 카테고리 없음(None) → I렌즈(산업) 몫
}

DIRECT_MIN_MONTHS = 15   # 기업 직접수출 시리즈 최소 개월(YoY 파생 가능선)


# ---------- 섹터 컨텍스트 ----------
def _sector_series(g: pd.DataFrame):
    s = g.groupby("date")["export_amount"].sum().sort_index()
    vh = g.groupby("date")["volume_yoy"].median().sort_index()
    ph = g.groupby("date")["price_yoy"].median().sort_index()
    return s, vh, ph


def build_sector_context(item_m: pd.DataFrame, as_of=None) -> dict:
    """전 섹터: 원신호→z→프로파일→raw→percentile. {"as_of","scores","raw_pool","profiles"}."""
    as_of = as_of or item_m["date"].max()
    praws, per_sec = {}, {}
    for sec, g in item_m.groupby("category"):
        s, vh, ph = _sector_series(g)
        raw_sig = growth_signals(
            s,
            volume_yoy=float(vh.iloc[-1]) if vh.notna().any() else None,
            price_yoy=float(ph.iloc[-1]) if ph.notna().any() else None)
        axes_z = normalize_signals(raw_sig, axis_signal_histories(
            s, "growth", volume_yoy_hist=vh, price_yoy_hist=ph))
        praws[sec] = sector_profile_raw([indicator_stats(
            values=s, series_type="growth", price_yoy_hist=ph, volume_yoy_hist=vh)])
        months = s.dropna()
        span = (months.index.max().to_period("M") - months.index.min().to_period("M")).n + 1
        conf = confidence(months.index.max(), len(months),
                          max(0.0, 1 - len(months) / span), as_of=as_of)
        yoy_s = (s.pct_change(12) * 100).dropna()
        ma3_s = yoy_s.rolling(3).mean()
        bflag = base_effect_flag(
            yoy=float(yoy_s.iloc[-1]) if len(yoy_s) else None,
            ma3_yoy=float(ma3_s.dropna().iloc[-1]) if ma3_s.notna().any() else None,
            prior_yoy=float(yoy_s.iloc[-13]) if len(yoy_s) >= 13 else None)
        per_sec[sec] = {"axes": axes_z, "conf": conf, "bflag": bflag}

    profiles = finalize_profiles(praws)
    raws = {}
    for sec, m in per_sec.items():
        r, eff = sector_raw(m["axes"], profiles[sec].weights, m["conf"], m["bflag"])
        raws[sec] = (r, eff)
    pool = [r for r, _ in raws.values() if r is not None]

    scores = {}
    for sec, m in per_sec.items():
        r, eff = raws[sec]
        flags = (["base_effect"] if m["bflag"] else [])
        if r is None:
            sc = SectorScore(sector=sec, sector_score=None, axes=m["axes"], weights=eff,
                             profile=profiles[sec], confidence=m["conf"],
                             flags=flags + ["no_data"])
        else:
            sc = SectorScore(sector=sec, sector_score=percentile_to_score(r, pool),
                             axes=m["axes"], weights=eff, profile=profiles[sec],
                             confidence=m["conf"], flags=flags)
        sc.flags += sector_flags_extra(sc)
        sc.insight = sector_insight(sc)
        scores[sec] = sc
    return {"as_of": as_of, "scores": scores, "raw_pool": pool, "profiles": profiles}


# ---------- 기업 ----------
def _direct_export_score(name: str, cat: Optional[str], ctx: dict,
                         comp_m: Optional[pd.DataFrame]):
    """기업 직접수출 점수: 실측 매칭 시 (score, f_recency, f_length), 아니면 (None,1,1).
    점수 스케일 통일: 기업 raw를 '섹터 raw 분포' percentile에 태워 −100~100."""
    if comp_m is None or comp_m.empty or not name:
        return None, 1.0, 1.0
    rows = comp_m[comp_m["company_name"].astype(str).str.contains(name, na=False, regex=False)]
    if rows.empty:
        return None, 1.0, 1.0
    s = rows.groupby("date")["export_amount"].sum().sort_index()
    if len(s.dropna()) < DIRECT_MIN_MONTHS:
        return None, 1.0, 1.0
    vh = rows.groupby("date")["volume_yoy"].median().sort_index()
    ph = rows.groupby("date")["price_yoy"].median().sort_index()
    raw_sig = growth_signals(
        s, volume_yoy=float(vh.iloc[-1]) if vh.notna().any() else None,
        price_yoy=float(ph.iloc[-1]) if ph.notna().any() else None)
    axes_z = normalize_signals(raw_sig, axis_signal_histories(
        s, "growth", volume_yoy_hist=vh, price_yoy_hist=ph))
    weights = (ctx["profiles"][cat].weights if cat and cat in ctx["profiles"]
               else {"mom": .3, "acc": .3, "qual": .2, "cyc": .2})
    f_rec = recency_factor(s.index.max(), as_of=ctx["as_of"])
    f_len = length_factor(len(s.dropna()))
    r, _ = sector_raw(axes_z, weights, conf=1.0, base_flag=False)
    if r is None:
        return None, f_rec, f_len
    return percentile_to_score(r, ctx["raw_pool"]), f_rec, f_len


def score_company(ticker: str, name: str, secname: str, ctx: dict,
                  comp_m: Optional[pd.DataFrame] = None,
                  industry_snapshot: Optional[dict] = None,
                  creditcard_snapshot: Optional[dict] = None) -> CompanyScore:
    """기업 1개 종합. 산업/CC 스냅샷 비어 있으면 I렌즈 입력 None → r_I=0 (정상)."""
    cat = SECNAME_TO_TRADE_CAT.get(secname)
    sec_score = ctx["scores"][cat].sector_score if cat and cat in ctx["scores"] else None
    exposure = compute_exposure(hs_matched=1.0 if cat else 0.0)

    direct, f_rec, f_len = _direct_export_score(name, cat, ctx, comp_m)

    # 산업(I) 렌즈 — PHASE B에서 스냅샷 연결(현재 빈 스키마 → None → r_I=0)
    ind_series = (industry_snapshot or {}).get("series") or {}
    cc_companies = (creditcard_snapshot or {}).get("companies") or {}
    industry_direct = None   # cc_companies.get(ticker) 시계열 → 점수화는 PHASE B
    industry_sector = None   # SECTOR_INDUSTRY 지표 시계열 → 점수화는 PHASE B
    _ = (ind_series, cc_companies)  # seam 명시

    cs = company_score(
        ticker,
        export_direct=direct, export_sector=sec_score,
        export_recency=f_rec, export_length=f_len,
        industry_direct=industry_direct, industry_sector=industry_sector,
        exposure=exposure, sector_inherit=None)
    cs.flags += company_flags_extra(cs)
    cs.insight = company_insight(cs, direct_export=direct is not None)
    return cs


# ---------- 진입점 ----------
def compute_all(item_m: Optional[pd.DataFrame] = None,
                comp_m: Optional[pd.DataFrame] = None,
                tickers: Optional[list] = None,
                co_map: Optional[dict] = None,
                as_of=None) -> dict:
    """{"as_of", "sectors": {카테고리: SectorScore}, "companies": {ticker: CompanyScore}}.

    item_m/comp_m 미지정 시 실데이터 로드. co_map: {ticker: {"n": 이름, "secName": 섹터}}
    (미지정 시 epsrev CO 사용). tickers 미지정 시 기업 점수는 생략(섹터만).
    """
    if item_m is None or comp_m is None:
        from epsrev.trade_score.loaders import load_export_metrics
        loaded_item, loaded_comp = load_export_metrics()
        item_m = item_m if item_m is not None else loaded_item
        comp_m = comp_m if comp_m is not None else loaded_comp

    ctx = build_sector_context(item_m, as_of=as_of)

    companies = {}
    if tickers:
        if co_map is None:
            from epsrev.data.dashboard_data import CO
            co_map = {t: {"n": v["n"], "secName": v.get("secName", "")}
                      for t, v in CO.items()}
        from epsrev.trade_score.loaders import (load_industry_snapshot,
                                                load_creditcard_snapshot)
        ind_snap, cc_snap = load_industry_snapshot(), load_creditcard_snapshot()
        for tk in tickers:
            info = co_map.get(str(tk).zfill(6), {})
            companies[tk] = score_company(
                str(tk).zfill(6), info.get("n", ""), info.get("secName", ""),
                ctx, comp_m, ind_snap, cc_snap)

    return {"as_of": ctx["as_of"], "sectors": ctx["scores"], "companies": companies}


_CTX = {"key": None, "result": None}   # 프로세스 캐시(수출 데이터 기준)


def get_trade_score(ticker: str) -> CompanyScore:
    """티커 1개 CompanyScore. 섹터 컨텍스트·데이터는 최초 1회만 로드(프로세스 캐시)."""
    from epsrev.trade_score.loaders import load_export_metrics
    if _CTX["result"] is None:
        item_m, comp_m = load_export_metrics()
        _CTX["result"] = (build_sector_context(item_m), comp_m)
    ctx, comp_m = _CTX["result"]
    from epsrev.data.dashboard_data import CO
    info = CO.get(str(ticker).zfill(6), {})
    from epsrev.trade_score.loaders import (load_industry_snapshot,
                                            load_creditcard_snapshot)
    return score_company(str(ticker).zfill(6), info.get("n", ""),
                         info.get("secName", ""), ctx, comp_m,
                         load_industry_snapshot(), load_creditcard_snapshot())
