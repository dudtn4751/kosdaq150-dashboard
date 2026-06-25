"""종목별 외국인/기관 수급 (롱숏 알파 — 상대강도 알파의 수급 컴포넌트).

네이버 종목별 투자자 매매동향(frgn) → 최근 5/20일 기관·외국인 누적 순매수대금(억) + 외국인 보유율.
유니버스: consensus.json 종목(KOSPI200+KOSDAQ150).
출력: data/investor_flow.json
사용: python3 scripts/update_investor.py [--limit N]
"""

import argparse
import json
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

warnings.filterwarnings("ignore")

KST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).parent.parent
DATA = PROJECT_ROOT / "data"
OUTPUT_PATH = DATA / "investor_flow.json"


def fetch_flow(code):
    """네이버 frgn → 최근 5/20일 기관·외국인 누적 순매수대금(억) + 외국인 보유율."""
    url = f"https://finance.naver.com/item/frgn.naver?code={code}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                               "Referer": "https://finance.naver.com/"})
    html = urllib.request.urlopen(req, timeout=12).read().decode("euc-kr", "ignore")
    tbls = pd.read_html(StringIO(html))
    df = None
    for t in tbls:
        flat = ["_".join(str(x) for x in c) if isinstance(c, tuple) else str(c) for c in t.columns]
        if any("순매매량" in f for f in flat) and any("종가" in f for f in flat):
            t.columns = flat
            df = t
            break
    if df is None:
        return None
    def col(kw):
        for c in df.columns:
            if kw in c:
                return c
        return None
    c_close, c_inst, c_frgn, c_hold = col("종가"), col("기관"), col("외국인_순매매량"), col("보유율")
    if not (c_close and c_inst and c_frgn):
        return None
    d = df.dropna(subset=[c_close]).copy()
    for c in (c_close, c_inst, c_frgn):
        d[c] = pd.to_numeric(d[c].astype(str).str.replace(",", ""), errors="coerce")
    d = d.dropna(subset=[c_close, c_inst, c_frgn])
    if d.empty:
        return None
    # 순매수대금(억) = 순매매량(주) × 종가 / 1e8  (최신이 위)
    inst_amt = (d[c_inst] * d[c_close] / 1e8)
    frgn_amt = (d[c_frgn] * d[c_close] / 1e8)
    hold = None
    if c_hold:
        try:
            hold = float(str(d.iloc[0][c_hold]).replace("%", "").replace(",", ""))
        except (ValueError, TypeError):
            hold = None
    return {
        "inst_5": round(float(inst_amt.head(5).sum()), 0),
        "inst_20": round(float(inst_amt.head(20).sum()), 0),
        "frgn_5": round(float(frgn_amt.head(5).sum()), 0),
        "frgn_20": round(float(frgn_amt.head(20).sum()), 0),
        "frgn_hold": hold,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    now = datetime.now(KST)
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] 종목별 외국인/기관 수급 수집")

    prev = {}
    if OUTPUT_PATH.exists():
        try:
            prev = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        except Exception:
            prev = {}

    try:
        cons = json.loads((DATA / "consensus.json").read_text(encoding="utf-8"))
        codes = [(s["code"], s["name"]) for s in cons.get("stocks", [])]
    except Exception:
        codes = []
    if args.limit:
        codes = codes[:args.limit]
    if not codes:
        print("  [경고] 유니버스 없음(consensus.json 필요) — 중단(exit 2)")
        sys.exit(2)

    flows, ok = {}, 0
    for i, (code, name) in enumerate(codes):
        try:
            f = fetch_flow(code)
            if f:
                flows[code] = f
                ok += 1
        except Exception:
            pass
        if (i + 1) % 50 == 0:
            print(f"  수집 {i+1}/{len(codes)} (성공 {ok})")
        time.sleep(0.15)
    print(f"  수급 수집 완료: {ok}/{len(codes)}")

    # 안전장치: 성공률 너무 낮으면(차단) 기존 파일 유지
    if ok < max(20, len(codes) * 0.3):
        print(f"  [경고] 수집 {ok}건 — 차단/장애 의심. 기존 파일 유지(exit 2).")
        sys.exit(2)

    out = {"updated": now.strftime("%Y-%m-%d %H:%M"), "date": now.strftime("%Y-%m-%d"),
           "count": ok, "flows": flows}
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  저장: {OUTPUT_PATH} (수급 {ok}종목)")


if __name__ == "__main__":
    main()
