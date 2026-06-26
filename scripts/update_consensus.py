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
HIST_PATH = PROJECT_ROOT / "data" / "consensus_hist.json"  # 종목별 컨센서스 스냅샷 누적(변화율 산출용)
GICS_PATH = PROJECT_ROOT / "gics_cache.json"
STOCK_HIST_KEEP = 90      # 종목별 스냅샷 보관 일수
REV_LOOKBACK = 20         # 변화율 비교 기준(영업일 ~1개월 전)
LAG_1M = 20               # 1개월 시점(스냅샷 수) — op/eps 실측 lag
LAG_3M = 60               # 3개월 시점
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
    # 코드 중복 제거(StockListing 중복행 방지) — 시총 큰 행 유지
    seen, dedup = set(), []
    for u in uni:
        if u["code"] in seen:
            continue
        seen.add(u["code"])
        dedup.append(u)
    if len(dedup) > UNIVERSE_CAP:
        dedup = dedup[:UNIVERSE_CAP]
    return dedup


def _get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Referer": "https://comp.fnguide.com/"})
    return urllib.request.urlopen(url=req, timeout=15).read().decode("utf-8", "ignore")


WISE_URL = "https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd={code}"


def fetch_broker_tp(code, retries=1):
    """네이버 wisereport → 증권사별 목표주가 컨센서스 + 직전 대비 변동률(TP 리비전).
    반환: {n, tp_avg, up, down, avg_chg, recent:[{broker,date,tp,prev,chg,opinion}]}."""
    req = urllib.request.Request(WISE_URL.format(code=code),
                                 headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/"})
    for attempt in range(retries + 1):
        try:
            html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore")
            for t in pd.read_html(StringIO(html)):
                cols = [str(c) for c in t.columns]
                if "목표가" in cols and "직전목표가" in cols and "변동률(%)" in cols:
                    df = t.copy()
                    df["_tp"] = pd.to_numeric(df["목표가"], errors="coerce")
                    df["_chg"] = pd.to_numeric(df["변동률(%)"], errors="coerce")
                    df = df.dropna(subset=["_tp"])
                    if df.empty:
                        return None
                    recent = []
                    for _, r in df.head(6).iterrows():
                        recent.append({
                            "broker": str(r.get("제공처", "")), "date": str(r.get("최종일자", "")),
                            "tp": int(r["_tp"]),
                            "prev": int(pd.to_numeric(r.get("직전목표가"), errors="coerce"))
                                    if pd.notna(pd.to_numeric(r.get("직전목표가"), errors="coerce")) else None,
                            "chg": None if pd.isna(r["_chg"]) else round(float(r["_chg"]), 1),
                            "opinion": str(r.get("투자의견", "")),
                        })
                    return {"n": int(len(df)), "tp_avg": int(round(df["_tp"].mean())),
                            "up": int((df["_chg"] > 0).sum()), "down": int((df["_chg"] < 0).sum()),
                            "avg_chg": None if df["_chg"].notna().sum() == 0 else round(float(df["_chg"].mean()), 1),
                            "recent": recent}
            return None
        except Exception:
            if attempt < retries:
                time.sleep(0.4)
            else:
                return None
    return None


def _num(x):
    try:
        return float(str(x).replace(",", "").replace("%", ""))
    except (ValueError, TypeError):
        return None


def parse_annual_fin(tbls):
    """연간 실적 추이(IFRS 연결, 추정치 E 포함) — 매출액·영업이익·당기순이익. 최근 6개 연도."""
    best, best_n = None, 0
    for t in tbls:
        cols = [str(c) for c in t.columns]
        if not cols or "IFRS(연결)" not in cols[0]:
            continue
        anns = [c for c in t.columns if "Annual" in str(c)]
        r0 = [str(x).strip() for x in t.iloc[:, 0].tolist()]
        if len(anns) >= 4 and any("매출액" in x for x in r0) and any("영업이익" in x for x in r0):
            if len(anns) > best_n:
                best, best_n = t, len(anns)
    if best is None:
        return None
    ann_cols = [c for c in best.columns if "Annual" in str(c)]
    yrs = []
    for c in ann_cols:
        m = re.search(r"(\d{4})/\d{2}(\(E\))?", str(c))
        yrs.append((m.group(1) + ("E" if m.group(2) else "")) if m else str(c))

    def row(name):
        for i, x in enumerate(best.iloc[:, 0].tolist()):
            if str(x).strip() == name:
                return [_num(best.iloc[i][c]) for c in ann_cols]
        return None
    rev, op, np_ = row("매출액"), row("영업이익"), row("당기순이익")
    if not op:
        return None
    # FnGuide SVD_Main의 추정(E) 컬럼은 값이 비정상(검증 결과 8~14배 점프) → 실제 보고 실적만 사용.
    act = [i for i, y in enumerate(yrs) if not str(y).endswith("E")]
    if len(act) < 2:
        return None
    act = act[-5:]  # 최근 5개 보고 연도
    pick = lambda arr: [arr[i] if (arr and i < len(arr)) else None for i in act]
    return {"years": [yrs[i] for i in act], "actual_only": True,
            "rev": pick(rev), "op": pick(op), "np": pick(np_)}


def fetch_consensus(code, retries=2):
    """FnGuide 기업분석 → 예상 영업이익(억)·3개월 리비전·전년동기 + 컨센서스 스냅샷(목표주가·EPS·투자의견·추정기관수)."""
    url = (f"https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?pGB=1&gicode=A{code}"
           f"&cID=&MenuYn=Y&ReportGB=&NewMenuID=11&stkGb=701")
    for attempt in range(retries + 1):
        try:
            html = _get(url)
            tbls = pd.read_html(StringIO(html))
            out = {}
            for t in tbls:
                cols = [str(c) for c in t.columns]
                # 영업이익 예상 + 3개월전 대비 + 전년동기
                if any("영업이익" in c for c in cols) and any("3개월전" in c for c in cols):
                    row = t.iloc[0]
                    def col(key):
                        for c in t.columns:
                            if key in str(c):
                                return c
                        return None
                    op = _num(row[col("영업이익")])
                    if op is not None:
                        out["op_est"] = op
                        out["rev_3m"] = _num(row[col("3개월전")])
                        yc = col("전년동기")
                        out["yoy"] = _num(row[yc]) if yc else None
                # 컨센서스 스냅샷: 투자의견·목표주가·EPS·PER·추정기관수
                if "목표주가" in cols and "EPS" in cols and "추정기관수" in cols:
                    r = t.iloc[0]
                    out["tp"] = _num(r["목표주가"])
                    out["eps"] = _num(r["EPS"])
                    out["opinion"] = _num(r["투자의견"]) if "투자의견" in cols else None
                    out["per"] = _num(r["PER"]) if "PER" in cols else None
                    out["n_est"] = _num(r["추정기관수"])
            fin = parse_annual_fin(tbls)
            if fin:
                out["fin"] = fin
            return out or None
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
            # 컨센서스 커버 종목만 증권사 TP 테이블 추가 수집(미커버는 브로커 없음)
            bt = fetch_broker_tp(u["code"])
            if bt:
                rec["broker_tp"] = bt
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

    # ── 종목별 컨센서스 스냅샷 히스토리 → TP/EPS/투자의견 변화율 산출 ──
    try:
        shist = json.loads(HIST_PATH.read_text(encoding="utf-8")).get("hist", {})
    except Exception:
        shist = {}

    def chg_pct(cur, old):
        if cur is None or old is None or old == 0:
            return None
        return round((cur / old - 1) * 100, 1)

    for s in stocks:
        if s.get("tp") is None and s.get("eps") is None and s.get("op_est") is None:
            continue
        h = shist.setdefault(s["code"], [])
        h[:] = [x for x in h if x.get("d") != today]
        h.append({"d": today, "op": s.get("op_est"), "tp": s.get("tp"),
                  "eps": s.get("eps"), "opi": s.get("opinion")})
        h[:] = sorted(h, key=lambda x: x["d"])[-STOCK_HIST_KEEP:]
        # 기준 시점: REV_LOOKBACK 이전(없으면 가장 오래된 것)
        base = h[-(REV_LOOKBACK + 1)] if len(h) > REV_LOOKBACK else (h[0] if len(h) > 1 else None)
        if base:
            s["tp_chg"] = chg_pct(s.get("tp"), base.get("tp"))
            s["eps_chg"] = chg_pct(s.get("eps"), base.get("eps"))
            s["opinion_chg"] = (round(s["opinion"] - base["opi"], 2)
                                if (s.get("opinion") is not None and base.get("opi") is not None) else None)
            s["chg_days"] = (datetime.strptime(today, "%Y-%m-%d").date()
                             - datetime.strptime(base["d"], "%Y-%m-%d").date()).days
        # ② 누적 시계열: 1M(~20 스냅샷 전)·3M(~60 전) 시점의 op/eps 실측값(없으면 None, 누적되며 채워짐)
        def _at(lag):
            return h[-(lag + 1)] if len(h) > lag else None
        m1, m3 = _at(LAG_1M), _at(LAG_3M)
        s["op_h1m"] = m1.get("op") if m1 else None
        s["op_h3m"] = m3.get("op") if m3 else None
        s["eps_h1m"] = m1.get("eps") if m1 else None
        s["eps_h3m"] = m3.get("eps") if m3 else None
        # 컨센서스 추정치 추이(스파크라인용): 최근 12개 스냅샷의 EPS·목표주가
        tail = h[-12:]
        s["est_hist"] = {"d": [x["d"][5:] for x in tail],
                         "eps": [x.get("eps") for x in tail],
                         "tp": [x.get("tp") for x in tail]}

    HIST_PATH.write_text(json.dumps({"updated": now.strftime("%Y-%m-%d %H:%M"), "hist": shist},
                                    ensure_ascii=False), encoding="utf-8")
    nhist = sum(1 for v in shist.values() if len(v) > 1)
    print(f"  컨센서스 히스토리: {len(shist)}종목 (변화율 산출가능 {nhist}종목)")

    # ①③ 클린 다년추정·분기 서프라이즈 ingest(data/fnguide_estimates.json 있으면 병합)
    try:
        from fnguide_estimates import merge_into as _merge_fn
        nfn = _merge_fn(stocks)
        if nfn:
            print(f"  FnGuide 추정 ingest: {nfn}종목 병합(FY1/FY2·서프라이즈)")
    except Exception as e:
        print(f"  [경고] FnGuide 추정 ingest 건너뜀: {str(e)[:80]}")

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
