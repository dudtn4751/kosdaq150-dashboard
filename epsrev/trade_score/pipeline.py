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

import pandas as pd

from epsrev.trade_score.schema import SectorScore, CompanyScore, AxisSignals
from epsrev.trade_score.signals import growth_signals, level_signals
from epsrev.trade_score.preprocess import resample_monthly
from epsrev.trade_score.normalize import (axis_signal_histories, normalize_signals,
                                          indicator_stats, sector_profile_raw,
                                          finalize_profiles)
from epsrev.trade_score.aggregate import (confidence, base_effect_flag, sector_raw,
                                          percentile_to_score, recency_factor,
                                          length_factor)
from epsrev.trade_score.company import company_score, compute_exposure
from epsrev.trade_score.insight import (sector_insight, company_insight,
                                        sector_flags_extra, company_flags_extra)
from epsrev.data.industry_config import SECTOR_INDUSTRY, COMPANY_CREDITCARD

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


# ---------- 산업(I) 렌즈 — bf_industry.json / bf_creditcard.json ----------
def _snapshot_series(entry: dict):
    """스냅샷 시계열 entry {data:[{m,val}]} → pd.Series (index=원 날짜문자열)."""
    idx, vals = [], []
    for p in (entry or {}).get("data", []) or []:
        if p.get("m") is None or p.get("val") is None:
            continue
        idx.append(p["m"]); vals.append(p["val"])
    return pd.Series(vals, index=idx, dtype=float) if idx else None


def _indicator_axes_z(series: pd.Series, series_type: str, freq):
    """단일 지표 시계열 → 월간 리샘플 → 원신호 → 자기이력 z (AxisSignals)."""
    monthly = resample_monthly(series, how="auto", freq=freq, series_type=series_type)
    if monthly is None or monthly.dropna().empty:
        return None, None
    raw = level_signals(monthly) if series_type == "level" else growth_signals(monthly)
    z = normalize_signals(raw, axis_signal_histories(monthly, series_type))
    return z, monthly


def _avg_axes(axes_list) -> AxisSignals:
    """지표별 z된 축을 평균(각 축은 이미 단위정규화됨 · None 무시)."""
    out = {}
    for ax in ("mom", "acc", "qual", "cyc"):
        vals = [getattr(a, ax) for a in axes_list if a and getattr(a, ax) is not None]
        out[ax] = sum(vals) / len(vals) if vals else None
    return AxisSignals(**out)


def build_industry_sector_context(industry_snapshot: dict, as_of=None) -> dict:
    """앱 섹터(SECTOR_INDUSTRY)별 산업 점수. src=="industry" 지표만(스냅샷 대상).
    {"scores": {secName: SectorScore}, "raw_pool": [...]}"""
    series_map = (industry_snapshot or {}).get("series") or {}
    per_sec, praws = {}, {}
    for secname, items in SECTOR_INDUSTRY.items():
        axes_list, stats_list, confs, latest_months = [], [], [], []
        for it in items:
            if it.get("src", "industry") != "industry":
                continue
            entry = series_map.get(f"{it['code']}/{it['sub']}")
            s = _snapshot_series(entry)
            if s is None:
                continue
            freq = (entry or {}).get("freq") or it.get("freq")
            z, monthly = _indicator_axes_z(s, it["series_type"], freq)
            if z is None:
                continue
            axes_list.append(z)
            stats_list.append(indicator_stats(values=monthly, series_type=it["series_type"]))
            mm = monthly.dropna()
            confs.append(confidence(mm.index.max(), len(mm), 0.0, as_of=as_of))
            latest_months.append(mm.index.max())
        if not axes_list:
            per_sec[secname] = None
            continue
        per_sec[secname] = {
            "axes": _avg_axes(axes_list),
            "conf": sum(confs) / len(confs) if confs else 0.0,
        }
        praws[secname] = sector_profile_raw(stats_list)

    profiles = finalize_profiles(praws)
    raws = {}
    for sec, m in per_sec.items():
        if m is None:
            raws[sec] = (None, {})
            continue
        raws[sec] = sector_raw(m["axes"], profiles[sec].weights, m["conf"], base_flag=False)
    pool = [r for r, _ in raws.values() if r is not None]

    scores = {}
    for sec, m in per_sec.items():
        r, eff = raws[sec]
        if m is None or r is None:
            scores[sec] = SectorScore(sector=sec, sector_score=None, flags=["no_data"])
        else:
            scores[sec] = SectorScore(
                sector=sec, sector_score=percentile_to_score(r, pool),
                axes=m["axes"], weights=eff, profile=profiles[sec], confidence=m["conf"])
    return {"scores": scores, "raw_pool": pool}


def _industry_company_direct(ticker: str, cc_snapshot: dict, ind_ctx: dict, as_of=None):
    """신용카드 기업 직접 소비 시계열 → 산업 렌즈 직접 점수(있으면).
    반환 (score|None, f_recency, f_length). ind_ctx.raw_pool로 스케일 통일."""
    comp = (cc_snapshot or {}).get("companies") or {}
    entry = comp.get(ticker)
    s = _snapshot_series(entry)
    if s is None or len(s.dropna()) < DIRECT_MIN_MONTHS:
        return None, 1.0, 1.0
    z, monthly = _indicator_axes_z(s, "growth", "월")
    if z is None:
        return None, 1.0, 1.0
    raw, _ = sector_raw(z, {"mom": .3, "acc": .3, "qual": .2, "cyc": .2}, conf=1.0, base_flag=False)
    if raw is None:
        return None, 1.0, 1.0
    pool = ind_ctx["raw_pool"] or [raw]
    mm = monthly.dropna()
    return (percentile_to_score(raw, pool),
            recency_factor(mm.index.max(), as_of=as_of), length_factor(len(mm)))


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
                  ind_ctx: Optional[dict] = None,
                  creditcard_snapshot: Optional[dict] = None,
                  as_of=None) -> CompanyScore:
    """기업 1개 종합. E=수출 렌즈, I=산업 렌즈(bf_industry/bf_creditcard 스냅샷).
    스냅샷 비어 있으면 I렌즈 입력 None → r_I=0 (현행 정상)."""
    cat = SECNAME_TO_TRADE_CAT.get(secname)
    sec_score = ctx["scores"][cat].sector_score if cat and cat in ctx["scores"] else None
    export_exposure = compute_exposure(hs_matched=1.0 if cat else 0.0)
    direct, f_rec, f_len = _direct_export_score(name, cat, ctx, comp_m)

    # 산업(I) 렌즈
    industry_sector = None
    industry_exposure = 0.0
    if ind_ctx and secname in ind_ctx["scores"]:
        industry_sector = ind_ctx["scores"][secname].sector_score
        industry_exposure = 1.0 if industry_sector is not None else 0.0
    industry_direct, i_rec, i_len = (None, 1.0, 1.0)
    if ind_ctx:
        industry_direct, i_rec, i_len = _industry_company_direct(
            ticker, creditcard_snapshot, ind_ctx, as_of=as_of)

    cs = company_score(
        ticker,
        export_direct=direct, export_sector=sec_score,
        export_recency=f_rec, export_length=f_len,
        industry_direct=industry_direct, industry_sector=industry_sector,
        industry_recency=i_rec, industry_length=i_len,
        export_exposure=export_exposure, industry_exposure=industry_exposure,
        exposure=export_exposure, sector_inherit=None)
    cs.flags += company_flags_extra(cs)
    cs.insight = company_insight(cs, direct_export=direct is not None)
    return cs


# ---------- 진입점 ----------
def compute_all(item_m: Optional[pd.DataFrame] = None,
                comp_m: Optional[pd.DataFrame] = None,
                tickers: Optional[list] = None,
                co_map: Optional[dict] = None,
                industry_snapshot: Optional[dict] = None,
                creditcard_snapshot: Optional[dict] = None,
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
        ind_snap = industry_snapshot if industry_snapshot is not None else load_industry_snapshot()
        cc_snap = creditcard_snapshot if creditcard_snapshot is not None else load_creditcard_snapshot()
        ind_ctx = build_industry_sector_context(ind_snap, as_of=ctx["as_of"])
        for tk in tickers:
            info = co_map.get(str(tk).zfill(6), {})
            companies[tk] = score_company(
                str(tk).zfill(6), info.get("n", ""), info.get("secName", ""),
                ctx, comp_m, ind_ctx, cc_snap, as_of=ctx["as_of"])

    return {"as_of": ctx["as_of"], "sectors": ctx["scores"], "companies": companies}


_CTX = {"key": None, "result": None}   # 프로세스 캐시(수출 데이터 기준)


def get_trade_score(ticker: str) -> CompanyScore:
    """티커 1개 CompanyScore. 섹터 컨텍스트·데이터는 최초 1회만 로드(프로세스 캐시)."""
    from epsrev.trade_score.loaders import (load_export_metrics, load_industry_snapshot,
                                            load_creditcard_snapshot)
    if _CTX["result"] is None:
        item_m, comp_m = load_export_metrics()
        ctx = build_sector_context(item_m)
        ind_ctx = build_industry_sector_context(load_industry_snapshot(), as_of=ctx["as_of"])
        _CTX["result"] = (ctx, comp_m, ind_ctx, load_creditcard_snapshot())
    ctx, comp_m, ind_ctx, cc_snap = _CTX["result"]
    from epsrev.data.dashboard_data import CO
    info = CO.get(str(ticker).zfill(6), {})
    return score_company(str(ticker).zfill(6), info.get("n", ""),
                         info.get("secName", ""), ctx, comp_m, ind_ctx, cc_snap,
                         as_of=ctx["as_of"])
