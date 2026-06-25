"""섹터별 이익 컨센서스 추이 및 변화 (프로젝트 1).

유니버스: KOSPI 시총 상위 200 + KOSDAQ 상위 150 (KOSPI200/KOSDAQ150 근사).
소스: FnGuide 기업분석(comp.fnguide.com) — 종목별 예상 영업이익 컨센서스 + 3개월전 대비 변화율.
섹터(GICS, gics_cache.json)로 집계해 섹터별 컨센서스 상/하향을 산출하고 매일 추이를 누적.

출력: data/consensus.json
사용: python3 scripts/update_consensus.py [--limit N]
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import warnings
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import FinanceDataReader as fdr

warnings.filterwarnings("ignore")

KST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_PATH = PROJECT_ROOT / "data" / "consensus.json"
GICS_PATH = PROJECT_ROOT / "gics_cache.json"
# 유니버스: 시총 하한(원). 롱숏 차입(숏 가능)·유동성 확보되는 ~3천억 이상.
MARCAP_FLOOR = 3e11
UNIVERSE_CAP = 1000  # 안전 상한(스크레이프 폭주 방지)
HISTORY_KEEP = 30  # 섹터 추이 보관 일수


def load_gics():
    try:
        return json.loads(GICS_PATH.read_text(encoding="utf-8")).get("gics_map", {})
    except Exception:
        return {}


def build_universe():
    """KOSPI+KOSDAQ 시총 ≥ MARCAP_FLOOR (롱숏 차입·유동성 확보 구간). 시총 내림차순, 상한 UNIVERSE_CAP."""
    uni = []
    for mkt in ("KOSPI", "KOSDAQ"):
        try:
            df = fdr.StockListing(mkt)
            df["Marcap"] = pd.to_numeric(df["Marcap"], errors="coerce")
            df = df.dropna(subset=["Marcap"])
            df = df[df["Marcap"] >= MARCAP_FLOOR].sort_values("Marcap", ascending=False)
            # 우선주·스팩 제외(보통주 페어/숏 대상 정합성)
            df = df[~df["Name"].astype(str).str.contains(r"우[A-Z]?$|스팩|제\d+호", regex=True, na=False)]
            for _, r in df.iterrows():
                uni.append({"code": str(r["Code"]), "name": str(r["Name"]),
                            "market": mkt, "marcap": float(r["Marcap"])})
        except Exception as e:
            print(f"  [경고] {mkt} StockListing 실패: {str(e)[:60]}")
    uni.sort(key=lambda x: x["marcap"], reverse=True)
    if len(uni) > UNIVERSE_CAP:
        uni = uni[:UNIVERSE_CAP]
    return uni


def _get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Referer": "https://comp.fnguide.com/"})
    return urllib.request.urlopen(url=req, timeout=15).read().decode("utf-8", "ignore")


def fetch_consensus(code, retries=2):
    """FnGuide 기업분석 → 예상 영업이익(억) + 3개월전 대비 변화% + 전년동기대비%."""
    url = (f"https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?pGB=1&gicode=A{code}"
           f"&cID=&MenuYn=Y&ReportGB=&NewMenuID=11&stkGb=701")
    for attempt in range(retries + 1):
        try:
            html = _get(url)
            tbls = pd.read_html(StringIO(html))
            for t in tbls:
                cols = [str(c) for c in t.columns]
                if any("영업이익" in c for c in cols) and any("3개월전" in c for c in cols):
                    row = t.iloc[0]
                    def col(key):
                        for c in t.columns:
                            if key in str(c):
                                return c
                        return None
                    op = pd.to_numeric(str(row[col("영업이익")]).replace(",", ""), errors="coerce")
                    rev = pd.to_numeric(str(row[col("3개월전")]).replace(",", ""), errors="coerce")
                    yoy_c = col("전년동기")
                    yoy = pd.to_numeric(str(row[yoy_c]).replace(",", ""), errors="coerce") if yoy_c else None
                    if op == op:  # not NaN
                        return {"op_est": float(op),
                                "rev_3m": float(rev) if rev == rev else None,
                                "yoy": float(yoy) if (yoy is not None and yoy == yoy) else None}
            return None
        except Exception:
            if attempt < retries:
                time.sleep(0.6)
            else:
                return None
    return None


def aggregate_by_sector(stocks):
    """섹터별 집계: 종목수·평균 리비전·상향/하향 수·예상 영업이익 합."""
    by = {}
    for s in stocks:
        if s.get("rev_3m") is None and s.get("op_est") is None:
            continue
        by.setdefault(s["sector"], []).append(s)
    out = []
    for sec, items in by.items():
        revs = [x["rev_3m"] for x in items if x.get("rev_3m") is not None]
        avg_rev = round(sum(revs) / len(revs), 2) if revs else None
        up = sum(1 for r in revs if r > 0)
        down = sum(1 for r in revs if r < 0)
        op_sum = sum(x["op_est"] for x in items if x.get("op_est") is not None)
        out.append({
            "sector": sec, "count": len(items), "covered": len(revs),
            "avg_rev_3m": avg_rev, "up": up, "down": down,
            "op_sum": round(op_sum, 0),
            "direction": ("up" if (avg_rev or 0) > 0 else ("down" if (avg_rev or 0) < 0 else "flat")),
        })
    out.sort(key=lambda x: (x["avg_rev_3m"] if x["avg_rev_3m"] is not None else -1e9), reverse=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="유니버스 상위 N개만 (테스트용)")
    args = ap.parse_args()

    now = datetime.now(KST)
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] 섹터 컨센서스 수집 시작")
    prev = {}
    if OUTPUT_PATH.exists():
        try:
            prev = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        except Exception:
            prev = {}

    gics = load_gics()
    uni = build_universe()
    if args.limit:
        uni = uni[:args.limit]
    print(f"  유니버스: {len(uni)}종목 / GICS 섹터맵: {len(gics)}")

    stocks, ok = [], 0
    for i, u in enumerate(uni):
        sec = gics.get(u["code"], "기타")
        c = fetch_consensus(u["code"])
        rec = {**u, "sector": sec}
        if c:
            rec.update(c); ok += 1
        stocks.append(rec)
        if (i + 1) % 50 == 0:
            print(f"  수집 {i+1}/{len(uni)} (성공 {ok})")
        time.sleep(0.2)
    print(f"  컨센서스 수집 완료: {ok}/{len(uni)}")

    # 안전장치: 성공률이 너무 낮으면(차단 의심) 기존 파일 유지
    if ok < max(20, len(uni) * 0.3):
        print(f"  [경고] 수집 성공 {ok}건 — 차단/장애 의심. 기존 consensus.json 유지(exit 2).")
        sys.exit(2)

    sectors = aggregate_by_sector(stocks)

    # 섹터별 추이 누적 (avg_rev_3m)
    history = (prev.get("history") or {})
    today = now.strftime("%Y-%m-%d")
    for s in sectors:
        h = history.setdefault(s["sector"], [])
        h[:] = [x for x in h if x.get("date") != today]
        h.append({"date": today, "avg_rev_3m": s["avg_rev_3m"], "op_sum": s["op_sum"]})
        h[:] = sorted(h, key=lambda x: x["date"])[-HISTORY_KEEP:]

    # 팔로우업 유니버스 전체 출력 (컨센서스 없는 종목도 포함 — 섹터별 추적 종목 표시용)
    for s in stocks:
        s["covered"] = s.get("rev_3m") is not None
    out = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "date": today,
        "universe": len(uni), "covered": ok,
        "sectors": sectors,
        "stocks": sorted(stocks, key=lambda s: s.get("marcap", 0), reverse=True),
        "history": history,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  저장: {OUTPUT_PATH} (섹터 {len(sectors)}개, 커버 {ok}종목)")


if __name__ == "__main__":
    main()
