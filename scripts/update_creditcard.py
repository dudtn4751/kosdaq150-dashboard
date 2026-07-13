"""신용카드 소비 스냅샷 생성 (PHASE B) — Mac 로컬 전용, 클라우드/CI/Cowork 금지.

- COMPANY_CREDITCARD의 companyId → /launch-data/credit-card/companies/{id}/trends
- SECTOR_CREDITCARD의 lCode/mCode → /launch-data/credit-card/sectors/{lCode}/{mCode}/trends
trends 응답: [{date, value, valueYoY, count, ...}] — value(결제금액)를 대표 시계열로.
YoY는 엔진(growth형)이 계산하므로 value 원값만 저장. 실패는 graceful.

출력: data/bf_creditcard.json — loaders.load_creditcard_snapshot() 스키마:
  {generated_at, companies: {ticker: {companyId, data:[{m,val}]}},
   sectors: {"{lCode}/{mCode}": {label, data:[{m,val}]}}}

실행: python3 scripts/update_creditcard.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bigfinance_session import login, api_get  # noqa: E402
from epsrev.data.industry_config import (SECTOR_CREDITCARD, build_company_creditcard)  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_PATH = BASE_DIR / "data" / "bf_creditcard.json"
DELAY = 0.6
TIMEOUT = 45


def _trend_points(rows) -> list:
    """trends 응답 → [{m, val}] (value=결제금액 원값). m은 YYYY-MM."""
    out = []
    for r in rows or []:
        if not isinstance(r, dict) or r.get("value") is None:
            continue
        d = str(r.get("date", ""))[:7]   # 2018-01-01 → 2018-01
        out.append({"m": d, "val": r["value"]})
    return out


def _full_company_map():
    """전체 61종목 {ticker: companyId} — searchable-companies ∩ 유니버스."""
    catalog = json.loads((BASE_DIR / "data" / "bf_creditcard_catalog.json").read_text(encoding="utf-8"))
    from epsrev.data.dashboard_data import CO
    return build_company_creditcard(catalog.get("searchable_companies") or [], set(CO.keys()))


def main():
    session = login(timeout=TIMEOUT)
    print("로그인 OK")

    # ---- 기업 ----
    comp_map = _full_company_map()
    print(f"[기업 카드소비] 대상 {len(comp_map)}종목")
    companies, cok, cfail = {}, 0, 0
    for i, (tk, cid) in enumerate(sorted(comp_map.items()), 1):
        time.sleep(DELAY)
        try:
            rows = api_get(session, f"/api/launch-data/credit-card/companies/{cid}/trends",
                           timeout=TIMEOUT)
            pts = _trend_points(rows)
        except Exception:
            pts = []
        if pts:
            companies[tk] = {"companyId": cid, "data": pts}
            cok += 1
        else:
            cfail += 1
        if i % 15 == 0 or i == len(comp_map):
            print(f"  …{i}/{len(comp_map)} (ok {cok}/skip {cfail})")

    # ---- 섹터 ----
    sec_targets = {}
    for items in SECTOR_CREDITCARD.values():
        for it in items:
            sec_targets[(it["lCode"], it["mCode"])] = it["label"]
    print(f"[섹터 카드소비] 대상 {len(sec_targets)}개")
    sectors, sok, sfail = {}, 0, 0
    for (lc, mc), label in sec_targets.items():
        time.sleep(DELAY)
        try:
            rows = api_get(session, f"/api/launch-data/credit-card/sectors/{lc}/{mc}/trends",
                           timeout=TIMEOUT)
            pts = _trend_points(rows)
        except Exception:
            pts = []
        if pts:
            sectors[f"{lc}/{mc}"] = {"label": label, "data": pts}
            sok += 1
            print(f"  ok   {lc}/{mc} «{label}» {len(pts)}pt {pts[0]['m']}~{pts[-1]['m']}")
        else:
            sfail += 1
            print(f"  skip {lc}/{mc} «{label}»")

    latest = max((p["m"] for grp in (companies.values(), sectors.values())
                  for e in grp for p in e["data"]), default=None)
    snap = {"generated_at": latest, "companies": companies, "sectors": sectors}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT_PATH.relative_to(BASE_DIR)} — 기업 {cok}·섹터 {sok} 성공 · 최신 {latest}")


if __name__ == "__main__":
    main()
