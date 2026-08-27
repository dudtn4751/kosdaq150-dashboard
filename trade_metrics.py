"""수출입 지표 계산 — Streamlit 페이지와 Flask API가 공유하는 순수 계산 모듈.

UI 프레임워크에 의존하지 않는다(streamlit import 금지). 캐싱은 호출측 책임:
  - Streamlit: @st.cache_data 로 감싸서 사용
  - Flask: 파일 mtime 기준 캐시로 감싸서 사용

decade CSV는 **월누계(MTD)** 다: 10일=1~10일 누계, 20일=1~20일 누계, 월말=그 달 전체.
구간 증분(inc1/2/3)은 여기서 파생하며, 음수(통계 정정치)는 클립하지 않는다.

★ 잠정/확정과 3층위 구조 (기업별 지연을 '버그'로 오인하지 말 것)
  - **잠정치(매월 1일 발표)**: 품목 단위만. **국내 지역 정보가 없어 기업을 특정할 수 없다.**
    → 순별(10/20/월말) CSV·월간 CSV가 여기서 나온다.
  - **확정치(매월 15일 발표)**: 지역 정보가 포함돼 **비로소 기업 특정이 가능**해진다.
    → company_trade_history_long.csv(기업별)는 확정치에만 존재한다.
  - 따라서 **매월 1일~15일 구간에는 기업별이 월간보다 한 달 뒤처져 보인다**(발표 주기 차이,
    데이터 누락 아님). 15일 이후에는 월간과 기업별의 최신월이 같아진다.
  - 완료월에서 순별 월말값과 월간 CSV 값은 동일하다(2026-08 전 품목 검증). 월간 계열의
    정본은 trade_history_long.csv이며, 진행월(부분 누계)은 월간 계열에서 제외한다.
"""

from functools import lru_cache

import numpy as np
import pandas as pd

BUCKETS = ("상순", "중순", "월말")


@lru_cache(maxsize=1)
def kr_holidays(y0: int = 2015, y1: int = 2028) -> tuple:
    import holidays as _hol

    return tuple(sorted(_hol.KR(years=range(y0, y1))))


def bizdays(start, end) -> int:
    """[start, end] 양끝 포함 영업일수 — 월~금 + 한국 공휴일 제외."""
    s = start.date() if hasattr(start, "date") else start
    e = (end + pd.Timedelta(days=1)).date() if hasattr(end, "date") else end
    return int(np.busday_count(s, e, holidays=list(kr_holidays())))


def decade_bucket(day: int) -> str:
    """일(day) → 순. 스크래퍼 스냅샷 day는 10(상순)/20(중순)/28~31(월말)."""
    if day <= 10:
        return "상순"
    if day <= 20:
        return "중순"
    return "월말"


def prepare_decade(df: pd.DataFrame) -> pd.DataFrame:
    """순별 원본에 y/m/decade 파생 컬럼 추가(월간 롤업 없이 그대로)."""
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    d["y"] = d["date"].dt.year
    d["m"] = d["date"].dt.month
    d["decade"] = d["date"].dt.day.map(decade_bucket)
    return d


def decade_monthly(dec: pd.DataFrame, item_name: str) -> pd.DataFrame:
    """월×구간 증분 파생: inc1=10일누계 / inc2=20일−10일 / inc3=월말−20일.
    진행월은 존재 구간까지만. 반환 1행=1개월(ym, inc1/2/3, cum, last_date, last_bkt,
    price, d1/d2/d3, biz1/2/3)."""
    d = dec[dec["item_name"] == item_name].sort_values("date")
    rows = []
    for (yy, mm), g in d.groupby(["y", "m"]):
        by = {r["decade"]: r for _, r in g.iterrows()}
        c10 = by.get("상순", {}).get("export_amount")
        c20 = by.get("중순", {}).get("export_amount")
        c30 = by.get("월말", {}).get("export_amount")
        last = g.iloc[-1]
        mstart = pd.Timestamp(int(yy), int(mm), 1)
        d1, d2, d3 = (by.get(b, {}).get("date") for b in BUCKETS)
        rows.append({
            "ym": pd.Period(year=int(yy), month=int(mm), freq="M"),
            "y": int(yy), "m": int(mm),
            "inc1": c10,
            "inc2": (c20 - c10) if (c20 is not None and c10 is not None) else None,
            "inc3": (c30 - c20) if (c30 is not None and c20 is not None) else None,
            "cum": last["export_amount"], "last_date": last["date"], "last_bkt": last["decade"],
            "price": last["unit_price"],
            "d1": d1, "d2": d2, "d3": d3,
            "biz1": bizdays(mstart, d1) if d1 is not None else None,
            "biz2": bizdays(mstart + pd.Timedelta(days=10), d2) if d2 is not None else None,
            "biz3": bizdays(mstart + pd.Timedelta(days=20), d3) if d3 is not None else None,
        })
    return pd.DataFrame(rows).sort_values("ym").reset_index(drop=True)


def decade_same_bucket_yoy(dec: pd.DataFrame, item_name: str) -> pd.DataFrame:
    """★동순 비교: 각 스냅샷을 전년 '같은 순'과 비교한 YoY(%) 컬럼을 붙여 반환."""
    d = dec[dec["item_name"] == item_name].sort_values("date").copy()
    lookup = dec.set_index(["item_name", "y", "m", "decade"])["export_amount"].to_dict()
    yoys = []
    for _, r in d.iterrows():
        prev = lookup.get((item_name, int(r["y"]) - 1, int(r["m"]), r["decade"]))
        yoys.append((r["export_amount"] / prev - 1.0) * 100.0 if prev else None)
    d["same_bucket_yoy"] = yoys
    return d


def month_series(metrics: pd.DataFrame, item_name: str) -> pd.DataFrame:
    """월별 시계열 + 영업일수/일평균. metrics는 compute_item_metrics 결과."""
    d = metrics[metrics["item_name"] == item_name].sort_values("date").copy()
    if d.empty:
        return d
    d["ym"] = d["date"].dt.to_period("M")
    starts = [pd.Timestamp(p.year, p.month, 1) for p in d["ym"]]
    d["biz"] = [bizdays(s, s + pd.offsets.MonthEnd(0)) for s in starts]
    d["day_avg"] = d["export_amount"] / d["biz"]
    return d
