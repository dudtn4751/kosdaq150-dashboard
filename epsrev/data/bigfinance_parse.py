"""빅파이낸스 /api/fsCore/{code} 응답 → get_fin_timeseries 스키마 순수 변환.

네트워크 없음(클라우드 안전). raw JSON(dict)만 받아 {quarterly, annual} 반환.
단위: 빅파이낸스 원 → 백만원(/1e6). 분기값은 이미 개별(누적 아님).
"""
from __future__ import annotations

# 내 스키마 키 ← 빅파이낸스 키 (금액: 원→백만원)
_AMT = {
    "rev": "revenue",
    "op": "operatingProfit",
    "ni": "netProfit",
    "ni_ctrl": "netProfitExcludingMinorityInterest",
    "assets": "totalAssets",
    "liab": "totalLiabilities",
    "equity": "totalShareholdersEquity",
    "cf_op": "operatingActivities",
    "cf_inv": "investingActivities",
    "cf_fin": "financingActivities",
}


def _num(v):
    try:
        if v is None or v == "":
            return None
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _mn(v):
    n = _num(v)
    return None if n is None else round(n / 1e6, 1)


def _period(label: str) -> str:
    """'1Q 2013' → '2013 1Q', '2013' → '2013'. 실패 시 원문."""
    if not label:
        return ""
    s = str(label).strip()
    if "Q" in s:
        parts = s.split()
        if len(parts) == 2:
            q, y = parts
            if q.endswith("Q"):
                return f"{y} {q}"          # '1Q 2013' → '2013 1Q'
            return f"{q} {y}"              # 이미 'YYYY nQ'
    return s


def _at(arr, i):
    return arr[i] if isinstance(arr, list) and i < len(arr) else None


def _rows(block: dict) -> list[dict]:
    if not isinstance(block, dict):
        return []
    labels = block.get("displayAccountingDate") or []
    n = len(labels)
    out = []
    for i in range(n):
        period = _period(labels[i])
        if not period:
            continue
        row = {"period": period}
        for my_k, bf_k in _AMT.items():
            row[my_k] = _mn(_at(block.get(bf_k), i))
        # 마진(비율 0~1 → %)
        opm = _num(_at(block.get("operatingProfitOPM"), i))
        row["opm"] = None if opm is None else round(opm * 100, 1)
        # PER/PBR(비율 그대로)
        row["per"] = _num(_at(block.get("per"), i))
        row["pbr"] = _num(_at(block.get("pbr"), i))
        out.append(row)
    return out


def parse_fscore(raw: dict) -> dict:
    """빅파이낸스 fsCore JSON → {quarterly:[...], annual:[...]}. 실패 시 빈 리스트."""
    if not isinstance(raw, dict):
        return {"quarterly": [], "annual": []}
    return {
        "quarterly": _rows(raw.get("quarterly") or {}),
        "annual": _rows(raw.get("yearly") or {}),
    }
