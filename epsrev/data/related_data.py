"""epsrev/data/related_data.py — '관련 데이터' 통합 provider.

get_series(dataset_id, detail): 데이터셋 → {series:[{m,val,yoy}], meta, note}.
 - source=="bf_export": exports.py로 스냅샷(bf_export.json) 실데이터.
 - source=="industry": get_industry_data 스텁 → 빈 시리즈 + '연동 예정'.
compute_transform(series, kind): 라인이 보여줄 % 시리즈(YoY/MoM/YTD).
"""
from __future__ import annotations


from epsrev.data.related_config import DATASETS


def _key_for(d: dict, detail):
    key = d["key"]
    if detail and d.get("details"):
        for dt in d["details"]:
            if dt["label"] == detail:
                return dt["key"]
    return key


def get_series(dataset_id: str, detail=None) -> dict:
    d = DATASETS.get(dataset_id)
    if not d:
        return {"series": [], "meta": {}, "note": "미정의 데이터셋"}
    meta = {"frequency": d.get("frequency", "—"), "unit": d.get("unit", "—"),
            "source": d.get("source_name", "—"), "latest": "—"}

    if d["source"] == "bf_export":
        from epsrev.data.exports import get_export_series
        series = get_export_series(_key_for(d, detail))
        if series:
            meta["latest"] = series[-1]["m"]
        return {"series": series, "meta": meta,
                "note": None if series else "스냅샷에 데이터가 없습니다."}

    # industry(스텁) — 연동 예정
    try:
        from epsrev.data.industry import get_industry_data
        ind = get_industry_data(dataset_id) or {}
    except Exception:
        ind = {}
    series = ind.get("series") or []
    if series:
        meta["latest"] = series[-1].get("m", "—")
    return {"series": series, "meta": meta,
            "note": None if series else "산업 데이터 연동 예정"}


def compute_transform(series: list[dict], kind: str) -> list:
    """라인용 % 시리즈(series와 같은 길이). YoY(저장값)/MoM."""
    vals = [s.get("val") for s in series]
    n = len(series)
    if kind == "MoM":
        out = [None]
        for i in range(1, n):
            p = vals[i - 1]
            out.append(round((vals[i] - p) / p * 100, 1) if (p and vals[i] is not None) else None)
        return out
    # 기본 YoY(저장값)
    return [s.get("yoy") for s in series]
