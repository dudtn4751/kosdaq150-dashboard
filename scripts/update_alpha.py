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


def fetch_prices(codes, verbose=False):
    """종목별 가격: 5/20/60일 수익률 + 60일 종가/거래대금 스파크 + 일별수익률(상관용).
    반환: (info dict, 일별수익률 DataFrame[date×code])."""
    start = (datetime.now(KST) - timedelta(days=120)).strftime("%Y-%m-%d")
    info, close_series = {}, {}
    for i, code in enumerate(codes):
        try:
            df = fdr.DataReader(code, start)
            c = df["Close"].dropna()
            if len(c) < 21:
                continue
            v = df["Volume"].reindex(c.index).fillna(0) if "Volume" in df.columns else None
            def ret(n):
                return (c.iloc[-1] / c.iloc[-n - 1] - 1) * 100 if len(c) > n else np.nan
            spark = [round(float(x), 1) for x in c.tail(60)]
            amt_spark = ([round(float(c.iloc[j] * v.iloc[j]) / 1e8, 0) for j in range(max(0, len(c) - 60), len(c))]
                         if v is not None else [])
            info[code] = {"ret_5": ret(5), "ret_20": ret(20), "ret_60": ret(60),
                          "spark": spark, "amt_spark": amt_spark}
            close_series[code] = c
        except Exception:
            pass
        if verbose and (i + 1) % 50 == 0:
            print(f"  가격 {i+1}/{len(codes)} (성공 {len(info)})")
        time.sleep(0.1)
    corr = pd.DataFrame()
    if len(close_series) >= 2:
        px = pd.DataFrame(close_series)
        corr = px.pct_change().dropna(how="all").tail(45).corr()
    return info, corr


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

    # ── 상대강도: 가격 수익률 + 상관(페어용) ──
    pinfo, corr = fetch_prices(df["code"].tolist(), verbose=True)
    df["ret_5"] = df["code"].map(lambda c: pinfo.get(c, {}).get("ret_5"))
    df["ret_20"] = df["code"].map(lambda c: pinfo.get(c, {}).get("ret_20"))
    df["ret_60"] = df["code"].map(lambda c: pinfo.get(c, {}).get("ret_60"))
    sector_ret20 = df.groupby("sector")["ret_20"].transform("mean")
    df["rs_20"] = df["ret_20"] - sector_ret20  # 업종 대비 상대강도
    print(f"  가격 수집: {len(pinfo)}/{len(df)} · 상관행렬 {corr.shape[0]}종목")

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

    name_map = dict(zip(df["code"], df["name"]))
    score_map = dict(zip(df["code"], df["score"]))
    sector_map = dict(zip(df["code"], df["sector"]))
    has_corr = corr.shape[0] >= 2

    def best_counterpart(code):
        """상관(헤지) × 점수 스프레드 최대인 반대편 종목. (롱이면 숏, 숏이면 롱)"""
        if not has_corr or code not in corr.columns:
            return None
        s = score_map.get(code, 0)
        best, bq = None, 0
        for other in corr.columns:
            if other == code or other not in score_map:
                continue
            cv = corr.at[code, other]
            if cv != cv or cv < 0.3:   # 헤지 가능한 상관만
                continue
            o = score_map[other]
            spread = s - o
            if (s >= 0 and spread <= 5) or (s < 0 and spread >= -5):  # 반대 극단만
                continue
            q = cv * abs(spread)
            if q > bq:
                bq, best = q, {"code": other, "name": name_map[other], "score": float(o),
                               "corr": round(float(cv), 2), "spread": round(abs(spread), 0),
                               "same_sector": sector_map.get(other) == sector_map.get(code)}
        return best

    pair_map = {c: best_counterpart(c) for c in df["code"]}

    def rec(r):
        code = r["code"]
        return {"code": code, "name": r["name"], "sector": r["sector"],
                "marcap": float(r["marcap"]) if r["marcap"] == r["marcap"] else 0,
                "score": float(r["score"]),
                "eps": float(r["score_eps"]), "rs": float(r["score_rs"]), "event": float(r["score_event"]),
                "rev_3m": None if pd.isna(r["rev_3m"]) else float(r["rev_3m"]),
                "yoy": None if pd.isna(r.get("yoy")) else round(float(r["yoy"]), 1),
                "ret_5": None if pd.isna(r["ret_5"]) else round(float(r["ret_5"]), 1),
                "ret_20": None if pd.isna(r["ret_20"]) else round(float(r["ret_20"]), 1),
                "ret_60": None if pd.isna(r["ret_60"]) else round(float(r["ret_60"]), 1),
                "rs_20": None if pd.isna(r["rs_20"]) else round(float(r["rs_20"]), 1),
                "pressure_eok": pressure.get(code),
                "tp": tp_dir.get(code),
                "index_event": ("add" if code in add_codes else ("remove" if code in rem_codes else None)),
                "spark": pinfo.get(code, {}).get("spark", []),
                "amt_spark": pinfo.get(code, {}).get("amt_spark", []),
                "pair": pair_map.get(code)}

    ranked = [rec(r) for _, r in df.iterrows()]
    longs = ranked[:25]
    shorts = ranked[::-1][:25]

    # ── 상관 기반 정밀 페어 (헤지 상관 × 점수 스프레드, 종목 중복 제거) ──
    pairs, used = [], set()
    for r in ranked:                          # 점수 높은 순(롱 후보)부터
        if r["score"] < 10 or r["code"] in used:
            continue
        cp = r.get("pair")
        if not cp or cp["code"] in used or cp["score"] > -5 or cp["corr"] < 0.4:
            continue
        used.add(r["code"]); used.add(cp["code"])
        pairs.append({"long": {"code": r["code"], "name": r["name"], "score": r["score"]},
                      "short": {"code": cp["code"], "name": cp["name"], "score": cp["score"]},
                      "corr": cp["corr"], "spread": cp["spread"],
                      "same_sector": cp["same_sector"], "sector": r["sector"],
                      "quality": round(cp["corr"] * cp["spread"], 0)})
    pairs.sort(key=lambda x: x["quality"], reverse=True)

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
