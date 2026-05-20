"""
시장 시그널 — 장 마감 후 당일 종가 기준 데이터 수집
매일 15:40 KST에 실행 (launchd)
"""

import json
import os
import signal
import sys
import warnings
from datetime import datetime, timedelta

import pandas as pd
import FinanceDataReader as fdr

warnings.filterwarnings("ignore")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)
from utils.sectors import SECTOR_CONSOLIDATION

SIGNAL_PATH = os.path.join(PROJECT_ROOT, "data", "market_signal.json")

MIN_CAP = 3e11  # 3000억
SURGE_PCT = 7.0
SECTOR_MAP_PATH = os.path.join(PROJECT_ROOT, "data", "sector_map.json")


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
    # High/Low가 0인 경우 종가로 대체 (장 시작 전 또는 비정상 데이터)
    df.loc[df["high"] <= 0, "high"] = df.loc[df["high"] <= 0, "close"]
    df.loc[df["low"] <= 0, "low"] = df.loc[df["low"] <= 0, "close"]
    return df


class _Timeout(Exception):
    pass

def _alarm_handler(signum, frame):
    raise _Timeout()

def fetch_52w(code, start_date, timeout_sec=8):
    """signal.alarm 기반 타임아웃 fetch (메인스레드 전용)"""
    old = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(timeout_sec)
    try:
        hist = fdr.DataReader(code, start_date)
        signal.alarm(0)
        if hist is not None and not hist.empty:
            valid = hist[(hist["High"] > 0) & (hist["Low"] > 0)]
            if not valid.empty:
                return code, valid["High"].max(), valid["Low"].min()
    except _Timeout:
        pass
    except Exception:
        pass
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)
    return code, None, None


def main():
    now = datetime.now()
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] 시장 시그널 수집 시작")

    today_df = load_today()
    filtered = today_df[today_df["marcap"] >= MIN_CAP].copy()
    print(f"  전체: {len(today_df)}종목, 필터(3000억+): {len(filtered)}종목")

    # 섹터 매핑 로드
    sector_raw = {}
    try:
        with open(SECTOR_MAP_PATH, "r", encoding="utf-8") as f:
            sector_raw = json.load(f)
    except Exception:
        pass

    # 1) 급등/급락
    surge = filtered[filtered["change_pct"] >= SURGE_PCT].sort_values("change_pct", ascending=False)
    plunge = filtered[filtered["change_pct"] <= -SURGE_PCT].sort_values("change_pct")

    def to_record(row):
        detail = sector_raw.get(row["code"], "기타")
        sector = SECTOR_CONSOLIDATION.get(detail, detail)
        return {
            "code": row["code"],
            "name": row["name"],
            "market": row["market"],
            "close": int(row["close"]),
            "change_pct": round(row["change_pct"], 2),
            "marcap": int(row["marcap"]),
            "marcap_str": fmt_cap(row["marcap"]),
            "sector": sector,
            "sector_detail": detail,
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
    print(f"  52주 데이터 로딩 ({len(codes)}종목, 순차+alarm)...")
    t0 = _time.time()
    for i, code in enumerate(codes):
        _, h52, l52 = fetch_52w(code, start_date, timeout_sec=8)
        if h52 is not None:
            w52[code] = (h52, l52)
        if (i + 1) % 50 == 0 or (i + 1) == len(codes):
            elapsed = _time.time() - t0
            print(f"    {i+1}/{len(codes)} ({len(w52)}개 성공, {elapsed:.0f}초)")

    new_highs = []
    new_lows = []
    for _, r in filtered.iterrows():
        # 당일 거래가 없는 종목(volume=0) 제외
        if r.get("volume", 0) <= 0:
            continue
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
