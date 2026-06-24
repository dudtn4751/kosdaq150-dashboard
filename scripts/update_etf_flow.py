"""ETF 수급 전략 — 데이터 수집 (프로젝트: ETF 매매 전략 ① 신규 상장 수급압력).

국내 주식형 ETF(네이버 etfTabCode 1·2·3)의 일별 AUM·거래대금을 수집하고,
상위 ETF의 TOP10 구성종목(네이버 etfAnalysis)으로 '종목별 ETF 매수 압력(클러스터링)'을 산출.
일별 스냅샷을 누적해 AUM 증가/둔화(진입·청산 신호)와 신규 상장 ETF를 추적.

출력: data/etf_flow.json
"""

import json
import sys
import time
import urllib.request
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

warnings.filterwarnings("ignore")

KST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_PATH = PROJECT_ROOT / "data" / "etf_flow.json"
KR_EQUITY_TABS = {1, 2, 3}   # 1 국내시장지수 · 2 국내업종/테마 · 3 국내파생/전략
ENRICH_TOP = 80              # AUM 상위 N개 ETF만 TOP10 구성종목 수집(부하 관리)
HISTORY_KEEP = 30


def _get(url, dec="utf-8", ref="https://finance.naver.com/"):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": ref})
    return urllib.request.urlopen(req, timeout=12).read().decode(dec, "ignore")


def fetch_universe():
    """네이버 ETF 목록 → 국내 주식형 ETF (AUM·거래대금)."""
    # etfItemList.nhn 은 euc-kr 인코딩 (utf-8로 읽으면 한글 ETF명이 깨짐)
    j = json.loads(_get("https://finance.naver.com/api/sise/etfItemList.nhn", dec="euc-kr"))
    rows = j.get("result", {}).get("etfItemList", [])
    out = []
    for r in rows:
        if r.get("etfTabCode") not in KR_EQUITY_TABS:
            continue
        out.append({
            "code": str(r["itemcode"]), "name": r["itemname"], "tab": r.get("etfTabCode"),
            "aum": float(r.get("marketSum") or 0),       # 억원
            "price": float(r.get("nowVal") or 0),
            "volume": int(r.get("quant") or 0),
            "amount": float(r.get("amonut") or 0),        # 거래대금(백만원 단위로 추정)
        })
    return out


def fetch_holdings(code):
    """etfAnalysis → 상장일 + TOP10 구성종목(코드·비중%)."""
    try:
        j = json.loads(_get(f"https://m.stock.naver.com/api/stock/{code}/etfAnalysis",
                            ref="https://m.stock.naver.com/"))
        top = []
        for c in j.get("etfTop10MajorConstituentAssets", []) or []:
            w = str(c.get("etfWeight", "")).replace("%", "").replace(",", "")
            try:
                w = float(w)
            except ValueError:
                continue
            if c.get("itemCode"):
                top.append({"code": str(c["itemCode"]), "name": c.get("itemName", ""), "weight": w})
        return {"listed": j.get("listedDate"), "issuer": j.get("issuerName"),
                "index": j.get("etfBaseIndex"), "top10": top}
    except Exception:
        return None


def main():
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] ETF 수급 수집 시작")
    prev = {}
    if OUTPUT_PATH.exists():
        try:
            prev = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
    prev_aum = {e["code"]: e.get("aum") for e in (prev.get("etfs") or [])}
    prev_codes = set(prev_aum)

    uni = fetch_universe()
    if not uni:
        print("  [경고] ETF 목록 0건 — 기존 파일 유지(exit 2)")
        sys.exit(2)
    uni.sort(key=lambda e: e["aum"], reverse=True)
    print(f"  국내 주식형 ETF: {len(uni)}개")

    # AUM 변화·신규 상장 판정
    for e in uni:
        pa = prev_aum.get(e["code"])
        e["aum_chg_pct"] = round((e["aum"] - pa) / pa * 100, 2) if (pa and pa > 0) else None
        e["is_new"] = (e["code"] not in prev_codes) if prev_codes else False

    # 수집 대상 = AUM 상위 N + 모든 액티브 ETF(③ 액티브 추종용)
    enrich = list(uni[:ENRICH_TOP])
    ecodes = {e["code"] for e in enrich}
    for e in uni:
        if "액티브" in e["name"] and e["code"] not in ecodes:
            enrich.append(e); ecodes.add(e["code"])

    holdings_by_etf = {}
    for i, e in enumerate(enrich):
        h = fetch_holdings(e["code"])
        if h:
            holdings_by_etf[e["code"]] = h
            e["listed"] = h.get("listed")
            e["index"] = h.get("index")
            e["top10"] = h.get("top10")
        time.sleep(0.15)
    print(f"  구성종목 수집: {len(holdings_by_etf)}/{len(enrich)} ETF (액티브 포함)")

    aum_map = {e["code"]: e["aum"] for e in uni}
    name_map = {e["code"]: e["name"] for e in uni}
    pressure = {}  # stockcode -> {name, pressure_eok, etfs:[(etf_name, weight)]}
    for etf_code, h in holdings_by_etf.items():
        etf_aum = aum_map.get(etf_code, 0)
        for hold in h["top10"]:
            p = pressure.setdefault(hold["code"], {"name": hold["name"], "pressure_eok": 0.0, "etfs": []})
            p["pressure_eok"] += hold["weight"] / 100 * etf_aum   # 억원
            p["etfs"].append({"etf": name_map.get(etf_code, etf_code), "weight": hold["weight"],
                              "etf_aum": etf_aum, "is_new": next((e["is_new"] for e in uni if e["code"] == etf_code), False)})
    etf_codes = set(aum_map)  # ETF가 구성종목인 경우(ETF-of-ETF) 제외 → 개별 종목만
    pressure_list = []
    for code, p in pressure.items():
        if code in etf_codes:
            continue
        pressure_list.append({
            "code": code, "name": p["name"],
            "pressure_eok": round(p["pressure_eok"], 0),
            "etf_count": len(p["etfs"]),
            "new_etf_count": sum(1 for x in p["etfs"] if x["is_new"]),
            "top_etfs": sorted(p["etfs"], key=lambda x: x["weight"] * x["etf_aum"], reverse=True)[:5],
        })
    pressure_list.sort(key=lambda x: x["pressure_eok"], reverse=True)

    # AUM 히스토리 누적
    history = prev.get("history") or {}
    for e in uni:
        h = history.setdefault(e["code"], [])
        h[:] = [x for x in h if x.get("date") != today]
        h.append({"date": today, "aum": e["aum"]})
        h[:] = sorted(h, key=lambda x: x["date"])[-HISTORY_KEEP:]

    new_listings = [e for e in uni if e.get("is_new")]
    aum_surge = sorted([e for e in uni if e.get("aum_chg_pct") is not None],
                       key=lambda e: e["aum_chg_pct"], reverse=True)[:20]

    # ③ 액티브 ETF TOP10 일별 변화(diff) — 전일 etf_flow의 top10과 비교
    prev_top10 = {}
    for pe in (prev.get("etfs") or []):
        if pe.get("top10"):
            prev_top10[pe["code"]] = {hh["code"]: hh for hh in pe["top10"]}
    active_changes = []
    for e in uni:
        if "액티브" not in e["name"] or not e.get("top10"):
            continue
        cur = {hh["code"]: hh for hh in e["top10"]}
        prv = prev_top10.get(e["code"])
        new_in, dropped, wchg = [], [], []
        if prv is not None:
            for code, hh in cur.items():
                if code not in prv:
                    new_in.append({"name": hh["name"], "weight": hh["weight"]})
                else:
                    delta = hh["weight"] - prv[code]["weight"]
                    if abs(delta) >= 0.5:
                        wchg.append({"name": hh["name"], "from": prv[code]["weight"],
                                     "to": hh["weight"], "delta": round(delta, 2)})
            for code, hh in prv.items():
                if code not in cur:
                    dropped.append({"name": hh.get("name", code), "weight": hh["weight"]})
        active_changes.append({
            "name": e["name"], "aum": e["aum"], "index": e.get("index"),
            "has_prev": prv is not None,
            "new_in": new_in, "dropped": dropped, "weight_changes": wchg,
            "change_n": len(new_in) + len(dropped) + len(wchg),
            "top10": e["top10"],
        })
    active_changes.sort(key=lambda x: (x["change_n"], x["aum"]), reverse=True)

    out = {
        "updated": now.strftime("%Y-%m-%d %H:%M"), "date": today,
        "count": len(uni),
        "etfs": uni,
        "new_listings": new_listings,
        "aum_surge": aum_surge,
        "pressure": pressure_list[:40],
        "active_changes": active_changes[:50],
        "active_count": sum(1 for e in uni if "액티브" in e["name"]),
        "enriched": len(holdings_by_etf),
        "history": history,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  저장: {OUTPUT_PATH} (ETF {len(uni)}, 매수압력 종목 {len(pressure_list)}, 신규 {len(new_listings)})")


if __name__ == "__main__":
    main()
