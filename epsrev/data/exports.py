"""epsrev/data/exports.py — 빅파이낸스 수출(무역) 데이터 provider.

seam: get_export_data(ticker) 하나가 '관련 수출 데이터'를 책임진다.
소스: 빅파이낸스 launch-data/trade (로그인 필요) → 스냅샷 data/bf_export.json → 여기서 읽기.
클라우드에서는 스냅샷만 소비(로그인 코드 없음).

매핑: 대시보드 섹터(secId) → 빅파이낸스 (산업코드, 제품코드). 대표 품목 1개.
수출과 무관한 섹터(finance, power)는 미매핑 → 빈 결과(플레이스홀더).
"""
from __future__ import annotations

import json
import os

# 섹터 → (industryCode, productCode, 라벨). 대표 수출 품목.
SECTOR_EXPORT: dict[str, tuple] = {
    "semi":      (1, 3, "반도체 총계"),
    "elec":      (1, 1, "휴대전화 완성품"),
    "shipdef":   (13, 1, "선박"),
    "auto":      (2, 1, "자동차 총계"),
    "bat":       (9, 3, "리튬이온 배터리"),
    "bio":       (11, 1, "의약품"),
    "consumer":  (5, 1, "화장품 총계"),
    "internet":  (15, 1, "K-콘텐츠(음반·DVD)"),
    "steel":     (3, 1, "철강제품 총계"),
    "petrochem": (8, 1, "화학 총계"),
    "construct": (10, 3, "건설기계(굴삭기)"),
    # power(전력), finance(금융): 수출 대표품목 없음 → 미매핑
}

_SNAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                     "data", "bf_export.json")


def parse_export_chart(raw, keep: int = 24) -> list[dict]:
    """빅파이낸스 export/chart 응답 [[YYYYMM, USD, yoy], ...] → [{m, val, yoy}] 최근 keep개.
    val: 백만달러(USD/1e6), yoy: %(소수*100). 순수 함수."""
    out = []
    if not isinstance(raw, list):
        return out
    for row in raw:
        try:
            ym, usd, yoy = row[0], row[1], row[2]
            ys = str(int(ym))
            m = f"{ys[2:4]}.{ys[4:6]}"                       # 202601 → '26.01'
            val = round(usd / 1e6) if isinstance(usd, (int, float)) else None
            yv = round(yoy * 100, 1) if isinstance(yoy, (int, float)) else None
            if val is not None:
                out.append({"m": m, "val": val, "yoy": yv})
        except Exception:
            continue
    return out[-keep:]


def _load_snapshot():
    try:
        with open(_SNAP, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def get_export_data(ticker: str) -> dict:
    """종목의 '관련 수출 데이터'. {series:[{m,val,yoy}], label, note}.
    ticker의 섹터 → 매핑 → 스냅샷의 해당 시계열. 미매핑/미연동 → 빈 series + note."""
    try:
        from epsrev.data.dashboard_data import CO
        sec = (CO.get(str(ticker).zfill(6)) or {}).get("secId")
    except Exception:
        sec = None
    m = SECTOR_EXPORT.get(sec)
    if not m:
        return {"series": [], "label": None, "note": "이 섹터는 대표 수출 품목이 없습니다."}
    ic, pc, label = m
    snap = _load_snapshot()
    if not snap:
        return {"series": [], "label": label,
                "note": "수출 스냅샷(data/bf_export.json)이 없습니다 — 빅파이낸스 업데이트 필요."}
    entry = (snap.get("series") or {}).get(f"{ic}-{pc}")
    series = (entry or {}).get("data") or []
    return {"series": series, "label": (entry or {}).get("label", label),
            "note": None if series else "스냅샷에 해당 품목 데이터가 없습니다."}
