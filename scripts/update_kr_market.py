"""
한국 시장 대시보드 + MARKET REGIME 점수 생성
모닝 마켓 체크의 '한국 시장 현황' + '시장 레짐' 섹션 데이터

소스: FinanceDataReader (지수 KS11/KQ11 + 전종목 StockListing), yfinance(글로벌 매크로 보조)
출력: data/kr_market.json

레짐 산식 (레퍼런스 이식):
  가중 평균 점수(0~100) → <40 Risk-off / 40~60 Neutral / >60 Risk-on
  구성: 상승하락(1.2) 지수(1.1) 거래대금(1.0) 매크로(1.0) 랭킹(0.9) 대형주집중(0.8)
  ※ 외국인/기관 수급(가중 1.1)은 데이터 소스 부재로 현재 제외 → 커버리지 표기

사용:
    python3 scripts/update_kr_market.py
"""

import json
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import FinanceDataReader as fdr

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_PATH = PROJECT_ROOT / "data" / "kr_market.json"

SAMSUNG, SK = "005930", "000660"


def clamp(x, lo=0, hi=100):
    return max(lo, min(hi, x))


def index_block(symbol, days=40):
    df = fdr.DataReader(symbol, (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d"))
    if df is None or df.empty or len(df) < 2:
        return None
    last = float(df["Close"].iloc[-1])
    prev = float(df["Close"].iloc[-2])
    chg = last - prev
    pct = chg / prev * 100 if prev else 0.0
    spark = [round(float(x), 2) for x in df["Close"].iloc[-20:].tolist()]
    return {"close": round(last, 2), "change": round(chg, 2), "change_pct": round(pct, 2),
            "spark": spark, "date": df.index[-1].strftime("%Y-%m-%d")}


def listing(market):
    df = fdr.StockListing(market)
    # 숫자형 보정
    for c in ["Close", "ChagesRatio", "Amount", "Marcap"]:
        if c in df.columns:
            df[c] = df[c].astype(float)
    return df


def main():
    now = datetime.now()
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] 한국 시장 데이터 수집")

    # 1. 지수
    kospi = index_block("KS11")
    kosdaq = index_block("KQ11")
    print(f"  코스피 {kospi['close'] if kospi else '-'} / 코스닥 {kosdaq['close'] if kosdaq else '-'}")

    # 2. 전종목 스냅샷
    lk = listing("KOSPI")
    lq = listing("KOSDAQ")
    allk = lk._append(lq) if hasattr(lk, "_append") else lk.append(lq)
    print(f"  종목수: KOSPI {len(lk)} / KOSDAQ {len(lq)} / 합계 {len(allk)}")

    def breadth(df):
        up = int((df["ChagesRatio"] > 0).sum())
        down = int((df["ChagesRatio"] < 0).sum())
        flat = int((df["ChagesRatio"] == 0).sum())
        return {"up": up, "flat": flat, "down": down}

    br_k, br_q, br_all = breadth(lk), breadth(lq), breadth(allk)

    def value_sum(df):
        return float(df["Amount"].sum())
    val_k, val_q = value_sum(lk), value_sum(lq)

    # 시총 집중도
    kospi_marcap = float(lk["Marcap"].sum())
    ss_cap = float(lk[lk["Code"] == SAMSUNG]["Marcap"].sum())
    sk_cap = float(lk[lk["Code"] == SK]["Marcap"].sum())
    ss_pct = ss_cap / kospi_marcap * 100 if kospi_marcap else 0
    sk_pct = sk_cap / kospi_marcap * 100 if kospi_marcap else 0
    conc_pct = ss_pct + sk_pct

    def marcap_str(v):
        jo = v / 1e12
        return f"{jo:,.1f}조" if jo >= 1 else f"{v/1e8:,.0f}억"

    def amount_str(v):
        jo = v / 1e12
        return f"{jo:,.1f}조" if jo >= 1 else f"{v/1e8:,.0f}억"

    def rec(r, i):
        return {
            "rank": i, "code": str(r["Code"]), "name": str(r["Name"]),
            "market": str(r.get("Market", "")), "close": float(r["Close"]),
            "change_pct": round(float(r["ChagesRatio"]), 2),
            "marcap": float(r["Marcap"]), "marcap_str": marcap_str(float(r["Marcap"])),
            "amount_str": amount_str(float(r["Amount"])), "volume": int(r["Volume"]),
        }

    # 필터 탭용 랭킹: 시장(전체/코스피/코스닥) × 기준(시총/거래대금/상승/하락/거래량) TOP 20
    CRITERIA = {
        "시가총액": ("Marcap", False), "거래대금": ("Amount", False),
        "상승": ("ChagesRatio", False), "하락": ("ChagesRatio", True),
        "거래량": ("Volume", False),
    }
    def build_rankings(df_by_market):
        out = {}
        for mkt, df in df_by_market.items():
            out[mkt] = {}
            for crit, (col, asc) in CRITERIA.items():
                top = df.sort_values(col, ascending=asc).head(20)
                out[mkt][crit] = [rec(r, i) for i, (_, r) in enumerate(top.iterrows(), 1)]
        return out

    rankings_stock = build_rankings({"전체": allk, "코스피": lk, "코스닥": lq})
    ranking = rankings_stock["전체"]["시가총액"][:15]  # 대시보드 요약용

    # ETF 랭킹 (컬럼명이 달라 정규화)
    rankings_etf = None
    try:
        etf = fdr.StockListing("ETF/KR").rename(
            columns={"Symbol": "Code", "Price": "Close", "ChangeRate": "ChagesRatio"})
        etf["Market"] = "ETF"
        etf["Marcap"] = etf["MarCap"].astype(float) * 1e8   # 억원 → 원
        etf["Amount"] = etf["Amount"].astype(float) * 1e6   # 백만원 → 원
        etf["Volume"] = etf["Volume"].astype(float)
        etf["Close"] = etf["Close"].astype(float)
        etf["ChagesRatio"] = etf["ChagesRatio"].astype(float)
        rankings_etf = build_rankings({"전체": etf})
        print(f"  ETF: {len(etf)}종목")
    except Exception as e:
        print(f"  [경고] ETF 목록 실패: {str(e)[:80]}")

    # 3. 글로벌 매크로 보조 점수 (yfinance)
    global_score = None
    try:
        import yfinance as yf
        sp = yf.Ticker("^GSPC").history(period="7d")["Close"]
        vix = yf.Ticker("^VIX").history(period="7d")["Close"]
        sp5d = (sp.iloc[-1] / sp.iloc[-6] - 1) * 100 if len(sp) >= 6 else 0
        vix_lv = float(vix.iloc[-1]) if len(vix) else 20
        # S&P 5일 수익률 + VIX 레벨 → 0~100
        s = 50 + sp5d * 4              # +5% → 70, -5% → 30
        s -= max(0, vix_lv - 18) * 1.5  # VIX 18 초과분 감점
        global_score = round(clamp(s), 0)
    except Exception as e:
        print(f"  [경고] 글로벌 매크로 점수 실패: {e}")

    # 3-b. 외국인 시각: 해외상장 한국주(ADR/GDR) 간밤 평균 등락 → 수급 프록시
    overseas_score = None
    overseas_avg = None
    try:
        import yfinance as yf
        OVS = ["SMSN.IL", "SMSD.IL", "PKX", "KB", "SHG", "WF", "LPL", "KT", "SKM", "KEP"]
        rets = []
        for t in OVS:
            h = yf.Ticker(t).history(period="5d")["Close"]
            if len(h) >= 2 and h.iloc[-2]:
                rets.append((h.iloc[-1] / h.iloc[-2] - 1) * 100)
        if rets:
            overseas_avg = sum(rets) / len(rets)
            overseas_score = round(clamp(50 + overseas_avg * 5), 0)
    except Exception as e:
        print(f"  [경고] 외국인 시각(해외상장) 점수 실패: {e}")

    # 4. 거래대금 증감 (전일 kr_market.json 있으면)
    value_chg_pct = None
    if OUTPUT_PATH.exists():
        try:
            prev = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
            pk = prev.get("value", {}).get("kospi")
            pq = prev.get("value", {}).get("kosdaq")
            if pk and pq:
                ck = (val_k - pk) / pk * 100
                cq = (val_q - pq) / pq * 100
                value_chg_pct = (ck + cq) / 2
        except Exception:
            pass

    # ── MARKET REGIME 산식 ──
    comps = []
    # 상승/하락 (1.2)
    tot = br_all["up"] + br_all["down"]
    breadth_score = round(br_all["up"] / tot * 100, 0) if tot else 50
    comps.append({"name": "상승/하락 종목", "score": breadth_score, "weight": 1.2,
                  "detail": f"상승 {br_all['up']} / 하락 {br_all['down']}"})
    # 지수 등락 (1.1)
    avg_idx = ((kospi["change_pct"] if kospi else 0) + (kosdaq["change_pct"] if kosdaq else 0)) / 2
    idx_score = round(clamp(50 + avg_idx * 10), 0)
    comps.append({"name": "KOSPI/KOSDAQ 등락", "score": idx_score, "weight": 1.1,
                  "detail": f"KOSPI {kospi['change_pct'] if kospi else 0:+.2f}% / KOSDAQ {kosdaq['change_pct'] if kosdaq else 0:+.2f}%"})
    # 거래대금 증감 (1.0)
    if value_chg_pct is not None:
        v_score = round(clamp(50 + value_chg_pct * 5), 0)
        comps.append({"name": "거래대금 증감", "score": v_score, "weight": 1.0,
                      "detail": f"전일 대비 평균 {value_chg_pct:+.1f}%"})
    # 외국인 시각: 해외상장(ADR/GDR) 간밤 (1.1) — 수급 프록시
    if overseas_score is not None:
        comps.append({"name": "외국인 시각", "score": overseas_score, "weight": 1.1,
                      "detail": f"해외상장 간밤 평균 {overseas_avg:+.1f}%"})
    # 글로벌 매크로 (1.0)
    if global_score is not None:
        comps.append({"name": "글로벌 매크로", "score": global_score, "weight": 1.0,
                      "detail": "S&P 5D + VIX 기반"})
    # 시장 랭킹 모멘텀 (0.9)
    top_up = sum(1 for r in ranking if r["change_pct"] > 0)
    rank_score = round(top_up / len(ranking) * 100, 0) if ranking else 50
    comps.append({"name": "시장 랭킹 모멘텀", "score": rank_score, "weight": 0.9,
                  "detail": f"TOP15 중 양수 {top_up}개"})
    # 대형주 집중도 (0.8) — 고집중일수록 감점
    conc_score = round(clamp(100 - (conc_pct - 8) / 22 * 100), 0)
    comps.append({"name": "대형주 집중도", "score": conc_score, "weight": 0.8,
                  "detail": f"삼성+SK {conc_pct:.2f}%"})

    wsum = sum(c["weight"] for c in comps)
    regime_score = round(sum(c["score"] * c["weight"] for c in comps) / wsum, 0) if wsum else 50
    if regime_score >= 60:
        label = "Risk-on"
    elif regime_score >= 40:
        label = "Neutral"
    else:
        label = "Risk-off"
    coverage = round(len(comps) / 7 * 100)  # 레퍼런스 기준 7개 지표

    output = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "date": kospi["date"] if kospi else now.strftime("%Y-%m-%d"),
        "kospi": kospi, "kosdaq": kosdaq,
        "breadth": {"kospi": br_k, "kosdaq": br_q, "total": br_all},
        "value": {"kospi": val_k, "kosdaq": val_q, "total": val_k + val_q,
                  "kospi_str": marcap_str(val_k), "kosdaq_str": marcap_str(val_q)},
        "concentration": {"samsung_sk_pct": round(conc_pct, 2), "samsung_pct": round(ss_pct, 2),
                          "sk_pct": round(sk_pct, 2), "kospi_marcap": kospi_marcap},
        "ranking": ranking,
        "rankings": {"주식": rankings_stock, "ETF": rankings_etf},
        "ranking_criteria": list(CRITERIA.keys()),
        "overseas": {"avg": round(overseas_avg, 2) if overseas_avg is not None else None},
        "regime": {"label": label, "score": regime_score, "coverage": coverage,
                   "components": comps,
                   "note": "외국인 시각=해외상장(ADR/GDR) 간밤 등락 프록시 (literal 순매수 데이터 부재)"},
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  레짐: {label} {regime_score}점 (커버리지 {coverage}%) / 구성 {len(comps)}개")
    print(f"  저장: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
