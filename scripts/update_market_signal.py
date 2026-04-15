"""
시장 시그널 — 장 마감 후 당일 종가 기준 데이터 수집
매일 15:40 KST에 실행 (launchd)
"""

import json
import os
import sys
import warnings
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FT

import pandas as pd
import FinanceDataReader as fdr

warnings.filterwarnings("ignore")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
SIGNAL_PATH = os.path.join(PROJECT_ROOT, "data", "market_signal.json")

MIN_CAP = 3e11  # 3000억
SURGE_PCT = 7.0


def fmt_cap(val):
    if pd.isna(val) or val == 0:
        return "-"
    if val >= 1e12:
        return f"{val/1e12:.1f}조"
    if val >= 1e8:
        return f"{val/1e8:.0f}억"
    return f"{val:,.0f}"


def load_today():
    """당일 전 종목 시세"""
    kospi = fdr.StockListing("KOSPI")
    kosdaq = fdr.StockListing("KOSDAQ")
    kospi["market"] = "KOSPI"
    kosdaq["market"] = "KOSDAQ"
    df = pd.concat([kospi, kosdaq], ignore_index=True)
    df = df.rename(columns={"Code": "code", "Name": "name", "Marcap": "marcap",
                            "ChagesRatio": "change_pct", "Close": "close",
                            "Open": "open", "High": "high", "Low": "low",
                            "Volume": "volume", "Amount": "amount"})
    df = df[df["close"] > 0].copy()
    return df


def fetch_52w(code, start_date):
    try:
        hist = fdr.DataReader(code, start_date)
        if hist is not None and not hist.empty:
            return code, hist["High"].max(), hist["Low"].min()
    except Exception:
        pass
    return code, None, None


def main():
    now = datetime.now()
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] 시장 시그널 수집 시작")

    today_df = load_today()
    filtered = today_df[today_df["marcap"] >= MIN_CAP].copy()
    print(f"  전체: {len(today_df)}종목, 필터(3000억+): {len(filtered)}종목")

    # 1) 급등/급락
    surge = filtered[filtered["change_pct"] >= SURGE_PCT].sort_values("change_pct", ascending=False)
    plunge = filtered[filtered["change_pct"] <= -SURGE_PCT].sort_values("change_pct")

    def to_record(row):
        return {
            "code": row["code"],
            "name": row["name"],
            "market": row["market"],
            "close": int(row["close"]),
            "change_pct": round(row["change_pct"], 2),
            "marcap": int(row["marcap"]),
            "marcap_str": fmt_cap(row["marcap"]),
        }

    surge_list = [to_record(r) for _, r in surge.iterrows()]
    plunge_list = [to_record(r) for _, r in plunge.iterrows()]
    print(f"  급등({SURGE_PCT}%+): {len(surge_list)}종목, 급락: {len(plunge_list)}종목")

    # 2) 52주 신고가/신저가
    codes = filtered["code"].tolist()
    start_date = (now - timedelta(days=365)).strftime("%Y-%m-%d")
    w52 = {}
    batch_size = 30

    import time as _time
    print(f"  52주 데이터 로딩 ({len(codes)}종목)...")
    done = 0
    t0 = _time.time()
    for b in range(0, len(codes), batch_size):
        batch = codes[b:b + batch_size]
        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = {ex.submit(fetch_52w, c, start_date): c for c in batch}
            batch_deadline = _time.time() + 30  # 배치당 30초 제한
            for fut in futures:
                remaining = max(0.1, batch_deadline - _time.time())
                try:
                    code, h52, l52 = fut.result(timeout=remaining)
                    if h52 is not None:
                        w52[code] = (h52, l52)
                except (FT, Exception):
                    pass
                done += 1
                if _time.time() > batch_deadline:
                    done += sum(1 for f in futures if not f.done())
                    break
        elapsed = _time.time() - t0
        print(f"    {done}/{len(codes)} ({len(w52)}개 성공, {elapsed:.0f}초)")

    new_highs = []
    new_lows = []
    for _, r in filtered.iterrows():
        data = w52.get(r["code"])
        if not data:
            continue
        h52, l52 = data
        rec = to_record(r)
        if r["high"] >= h52:
            rec["high_52w"] = int(h52)
            new_highs.append(rec)
        if r["low"] <= l52:
            rec["low_52w"] = int(l52)
            new_lows.append(rec)

    # 신고가는 등락률 내림차순, 신저가는 오름차순
    new_highs.sort(key=lambda x: x["change_pct"], reverse=True)
    new_lows.sort(key=lambda x: x["change_pct"])

    print(f"  52주 신고가: {len(new_highs)}종목, 신저가: {len(new_lows)}종목")

    # 저장
    result = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "date": now.strftime("%Y-%m-%d"),
        "min_cap": "3000억",
        "surge_pct": SURGE_PCT,
        "surge": surge_list,
        "plunge": plunge_list,
        "new_high": new_highs,
        "new_low": new_lows,
    }

    os.makedirs(os.path.dirname(SIGNAL_PATH), exist_ok=True)
    with open(SIGNAL_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"  저장 완료: {SIGNAL_PATH}")
    return result


if __name__ == "__main__":
    main()
