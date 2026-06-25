"""롱숏 알파 스코어 (1단계: EPS Revision + 상대강도 + 이벤트).

문서 프레임워크 기반 멀티팩터 L-S 점수:
  - EPS Revision (30%): 영업이익 컨센서스 3개월 리비전(consensus) + 리포트 TP 방향(research)
  - 상대강도   (15%): RS = 종목 20일 수익률 - 업종(섹터) 20일 평균 (5/60일 확인)
  - 이벤트     (10%): 코스닥150 편입/편출 예측(rebal) + ETF 매수압력/신규 편입(etf_flow)
  (대체데이터 25% · 퀄리티 20%는 소스 확보 후 — 현재 가용 알파끼리 비중 재정규화)

종합 점수(-100~+100) → 롱(고점수)/숏(저점수) 후보 + 섹터 내 페어.
출력: data/alpha.json
사용: python3 scripts/update_alpha.py [--limit N]
"""

import argparse
import json
import sys
import time
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd
import FinanceDataReader as fdr

warnings.filterwarnings("ignore")

KST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).parent.parent
DATA = PROJECT_ROOT / "data"
OUTPUT_PATH = DATA / "alpha.json"

# 가용 알파 비중 (문서: EPS30/대체25/퀄리티20/RS15/이벤트10) — 현재 EPS·RS·이벤트만 → 재정규화
WEIGHTS = {"eps": 30, "rs": 15, "event": 10}
PENDING = {"대체데이터": 25, "퀄리티/저베타": 20}


def _load(name):
    p = DATA / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def zscore_clip(series, lo=-2.0, hi=2.0):
    s = pd.to_numeric(series, errors="coerce")
    mu, sd = s.mean(), s.std()
    if not sd or sd != sd:
        return pd.Series(0.0, index=s.index)
    return ((s - mu) / sd).clip(lo, hi).fillna(0.0)


def fetch_returns(codes, verbose=False):
    """종목별 5/20/60일 수익률 (fdr). 실패 종목은 NaN."""
    start = (datetime.now(KST) - timedelta(days=110)).strftime("%Y-%m-%d")
    rows = {}
    for i, code in enumerate(codes):
        try:
            df = fdr.DataReader(code, start)
            c = df["Close"].dropna()
            if len(c) < 21:
                continue
            def ret(n):
                return (c.iloc[-1] / c.iloc[-n - 1] - 1) * 100 if len(c) > n else np.nan
            rows[code] = {"ret_5": ret(5), "ret_20": ret(20), "ret_60": ret(60)}
        except Exception:
            pass
        if verbose and (i + 1) % 50 == 0:
            print(f"  가격 {i+1}/{len(codes)} (성공 {len(rows)})")
        time.sleep(0.1)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    now = datetime.now(KST)
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] 롱숏 알파 스코어 산출")

    consensus = _load("consensus.json")
    research = _load("research_reports.json")
    rebal = _load("rebal.json")
    etf_flow = _load("etf_flow.json")

    stocks = consensus.get("stocks") or []
    if args.limit:
        stocks = stocks[:args.limit]
    if len(stocks) < 20:
        print("  [경고] 유니버스 부족(consensus.json 필요) — 중단(exit 2)")
        sys.exit(2)
    df = pd.DataFrame([{"code": s["code"], "name": s["name"], "sector": s.get("sector", "기타"),
                        "marcap": s.get("marcap", 0), "rev_3m": s.get("rev_3m"),
                        "yoy": s.get("yoy")} for s in stocks])
    print(f"  유니버스: {len(df)}종목")

    # ── 이벤트/리포트/수급 맵 ──
    tp_dir = {}
    for r in research.get("reports", []):
        if r.get("code") and r.get("direction") in ("up", "down"):
            tp_dir[r["code"]] = r["direction"]
    add_codes = {x["code"] for x in (rebal.get("kosdaq150") or {}).get("additions", [])}
    rem_codes = {x["code"] for x in (rebal.get("kosdaq150") or {}).get("removals", [])}
    pressure = {p["code"]: p["pressure_eok"] for p in etf_flow.get("pressure", [])}
    active_new = set()
    for a in etf_flow.get("active_changes", []):
        for x in a.get("new_in", []):
            pass  # new_in has name only; skip code-level for now

    # ── 상대강도: 가격 수익률 ──
    rets = fetch_returns(df["code"].tolist(), verbose=True)
    df["ret_5"] = df["code"].map(lambda c: rets.get(c, {}).get("ret_5"))
    df["ret_20"] = df["code"].map(lambda c: rets.get(c, {}).get("ret_20"))
    df["ret_60"] = df["code"].map(lambda c: rets.get(c, {}).get("ret_60"))
    sector_ret20 = df.groupby("sector")["ret_20"].transform("mean")
    df["rs_20"] = df["ret_20"] - sector_ret20  # 업종 대비 상대강도
    print(f"  가격 수집: {len(rets)}/{len(df)}")

    # ── 서브스코어 (-100~+100) ──
    df["score_eps"] = (zscore_clip(df["rev_3m"]) * 45).round(1)
    df["score_eps"] += df["code"].map(lambda c: 15 if tp_dir.get(c) == "up" else (-15 if tp_dir.get(c) == "down" else 0))
    df["score_eps"] = df["score_eps"].clip(-100, 100)

    df["score_rs"] = (zscore_clip(df["rs_20"]) * 45).round(1)
    df["score_rs"] += (zscore_clip(df["ret_60"]) * 10).round(1)  # 중기 확인
    df["score_rs"] = df["score_rs"].clip(-100, 100)

    ev = pd.Series(0.0, index=df.index)
    ev += df["code"].map(lambda c: 60 if c in add_codes else (-60 if c in rem_codes else 0))
    ev += (zscore_clip(df["code"].map(lambda c: pressure.get(c, 0))) * 25)
    df["score_event"] = ev.clip(-100, 100).round(1)

    # ── 종합 (가용 알파 재정규화) ──
    wsum = sum(WEIGHTS.values())
    df["score"] = ((df["score_eps"] * WEIGHTS["eps"] + df["score_rs"] * WEIGHTS["rs"]
                    + df["score_event"] * WEIGHTS["event"]) / wsum).round(1)
    coverage = round(wsum / (wsum + sum(PENDING.values())) * 100)

    df = df.sort_values("score", ascending=False).reset_index(drop=True)

    def rec(r):
        return {"code": r["code"], "name": r["name"], "sector": r["sector"],
                "marcap": float(r["marcap"]) if r["marcap"] == r["marcap"] else 0,
                "score": float(r["score"]),
                "eps": float(r["score_eps"]), "rs": float(r["score_rs"]), "event": float(r["score_event"]),
                "rev_3m": None if pd.isna(r["rev_3m"]) else float(r["rev_3m"]),
                "yoy": None if pd.isna(r.get("yoy")) else round(float(r["yoy"]), 1),
                "ret_5": None if pd.isna(r["ret_5"]) else round(float(r["ret_5"]), 1),
                "ret_20": None if pd.isna(r["ret_20"]) else round(float(r["ret_20"]), 1),
                "ret_60": None if pd.isna(r["ret_60"]) else round(float(r["ret_60"]), 1),
                "rs_20": None if pd.isna(r["rs_20"]) else round(float(r["rs_20"]), 1),
                "pressure_eok": pressure.get(r["code"]),
                "tp": tp_dir.get(r["code"]),
                "index_event": ("add" if r["code"] in add_codes else ("remove" if r["code"] in rem_codes else None))}

    ranked = [rec(r) for _, r in df.iterrows()]
    longs = ranked[:25]
    shorts = ranked[::-1][:25]

    # ── 섹터 내 페어 (롱 고점수 vs 숏 저점수, 시장중립) ──
    pairs = []
    for sec, g in df.groupby("sector"):
        g = g.sort_values("score", ascending=False)
        if len(g) < 2:
            continue
        lo_row, sh_row = g.iloc[0], g.iloc[-1]
        spread = lo_row["score"] - sh_row["score"]
        if spread < 30:  # 의미있는 스프레드만
            continue
        pairs.append({"sector": sec, "spread": round(float(spread), 1),
                      "long": {"code": lo_row["code"], "name": lo_row["name"], "score": float(lo_row["score"])},
                      "short": {"code": sh_row["code"], "name": sh_row["name"], "score": float(sh_row["score"])}})
    pairs.sort(key=lambda x: x["spread"], reverse=True)

    out = {
        "updated": now.strftime("%Y-%m-%d %H:%M"), "date": now.strftime("%Y-%m-%d"),
        "universe": len(df), "coverage_pct": coverage,
        "weights": WEIGHTS, "pending": PENDING,
        "longs": longs, "shorts": shorts, "pairs": pairs[:20],
        "ranked": ranked,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  저장: {OUTPUT_PATH} (롱{len(longs)}/숏{len(shorts)}/페어{len(pairs)}, 커버리지 {coverage}%)")


if __name__ == "__main__":
    main()
