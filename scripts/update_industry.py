"""산업지표 스냅샷 생성 (PHASE B) — Mac 로컬 전용, 클라우드/CI/Cowork 금지(정지 리스크).

industry_config의 src=="industry" 지표만 조회(선택된 것만 — 전체 9,131 금지).
엔드포인트: /api/industry/excel/codes/{code}/subCodes/{sub} (파라미터 없이 전체 시계열,
dataCode별 datas 반환) + /api/industry/header/... (unit·frequency·yoyFlag).
level형은 원값 그대로 저장(YoY는 엔진 몫). 실패는 graceful(해당 지표 skip).

출력: data/bf_industry.json — loaders.load_industry_snapshot() 기대 스키마:
  {generated_at, series: {"{code}/{sub}": {label, unit, freq, series_type, data:[{m, val}]}}}

실행: python3 scripts/update_industry.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bigfinance_session import login, api_get  # noqa: E402
from epsrev.data.industry_config import SECTOR_INDUSTRY  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_PATH = BASE_DIR / "data" / "bf_industry.json"
DELAY = 0.6
TIMEOUT = 45


def _selected_industry_indicators() -> dict:
    """src=="industry"인 (code, sub) → 지표 메타. 중복 제거."""
    picked = {}
    for items in SECTOR_INDUSTRY.values():
        for it in items:
            if it.get("src", "industry") != "industry":
                continue
            picked[(it["code"], it["sub"])] = it
    return picked


def _fetch_series(session, code: int, sub: int):
    """(data_points, header). data_points=[{m, val}] — 지표 대표 시계열(첫 dataCode
    또는 '총계/계' 우선). 원값 그대로(level형 YoY 계산은 엔진). 실패 → (None, None)."""
    try:
        excel = api_get(session, f"/api/industry/excel/codes/{code}/subCodes/{sub}",
                        timeout=TIMEOUT)
    except Exception:
        return None, None
    dcs = excel.get("industryDataCodes") if isinstance(excel, dict) else None
    if not dcs:
        return None, None
    # 대표 dataCode: 이름에 '계/총계/Total' 포함 우선, 없으면 첫 번째
    rep = next((d for d in dcs if any(k in str(d.get("dataName", ""))
               for k in ("총계", "계", "Total", "total"))), dcs[0])
    points = [{"m": str(r.get("date")), "val": r.get("value")}
              for r in (rep.get("datas") or []) if r.get("value") is not None]

    header = None
    try:
        header = api_get(session, f"/api/industry/header/codes/{code}/subCodes/{sub}",
                         timeout=TIMEOUT)
    except Exception:
        pass
    return points, header


def main():
    picked = _selected_industry_indicators()
    print(f"[산업지표] 대상 {len(picked)}개 (src=industry) — 전체 9,131 아님")
    session = login(timeout=TIMEOUT)
    print("      로그인 OK")

    series = {}
    ok = fail = 0
    for i, ((code, sub), meta) in enumerate(picked.items(), 1):
        time.sleep(DELAY)
        points, header = _fetch_series(session, code, sub)
        key = f"{code}/{sub}"
        if not points:
            fail += 1
            print(f"  [{i:>2}/{len(picked)}] skip {key} «{meta['label']}» (데이터 없음)")
            continue
        unit = (header or {}).get("unit")
        freq = (header or {}).get("frequency") or meta.get("freq")
        series[key] = {
            "label": meta["label"], "unit": unit, "freq": freq,
            "series_type": meta["series_type"], "data": points,
        }
        ok += 1
        print(f"  [{i:>2}/{len(picked)}] ok   {key} «{meta['label']}» "
              f"{len(points)}pt {points[0]['m']}~{points[-1]['m']} [{unit}]")

    # generated_at은 시계열 최신월(파일 mtime·실행시각 아님 — 데이터 기준)
    latest = max((p["m"] for s in series.values() for p in s["data"]), default=None)
    snap = {"generated_at": latest, "series": series}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT_PATH.relative_to(BASE_DIR)} — {ok}개 성공 / {fail}개 skip · 최신 {latest}")


if __name__ == "__main__":
    main()
