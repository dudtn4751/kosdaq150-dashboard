"""
물가 지표 자동 갱신 — FRED 공개 CSV API 사용 (API 키 불필요)
CPI, Core CPI, PCE, Core PCE, PPI, Core PPI 시리즈를 가져와 YoY 계산.

사용:
    python3 scripts/update_inflation.py
"""

import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import pandas as pd
import requests

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
OUTPUT_PATH = PROJECT_ROOT / "data" / "inflation_data.json"

# FRED 시리즈 (Seasonally Adjusted, monthly)
FRED_SERIES = {
    "CPI_YoY":      "CPIAUCSL",  # CPI All Urban Consumers
    "Core_CPI_YoY": "CPILFESL",  # CPI ex food & energy
    "PCE_YoY":      "PCEPI",     # PCE Price Index
    "Core_PCE_YoY": "PCEPILFE",  # Core PCE
    "PPI_YoY":      "PPIFIS",    # PPI Final Demand
    "Core_PPI_YoY": "PPIFES",    # PPI Final Demand ex food & energy
}

# 24개월치 표시
KEEP_MONTHS = 24


def fetch_fred_csv(series_id):
    """FRED 공개 CSV 다운로드 → date-indexed Series"""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"]).set_index("date").sort_index()
    return df["value"]


def calc_yoy(series):
    """월별 시리즈에서 YoY 변화율(%) 계산"""
    return (series / series.shift(12) - 1) * 100


def estimate_release_date(period_yyyymm, kind):
    """
    BLS/BEA 통상 발표 패턴 기반 추정 (정확하지는 않음, 추정 표시):
    - CPI/Core CPI: 다음 달 10-15일경
    - PPI/Core PPI: CPI보다 1-2일 늦은 다음 달 11-16일경
    - PCE/Core PCE: 다음 달 말 (~25-30일)
    """
    year, month = int(period_yyyymm[:4]), int(period_yyyymm[5:7])
    # 다음 달
    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1

    if kind == "CPI":
        day = 12
    elif kind == "PPI":
        day = 13
    elif kind == "PCE":
        day = 27
    else:
        day = 15
    return f"{next_year:04d}-{next_month:02d}-{day:02d}"


def main():
    now = datetime.now()
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] FRED 물가 데이터 갱신")

    # 기존 release date 유지용 로드
    old_releases = {}
    if OUTPUT_PATH.exists():
        try:
            with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
                old = json.load(f)
            for r in old.get("data", []):
                d = r.get("date")
                if d:
                    old_releases[d] = {
                        "CPI_release": r.get("CPI_release"),
                        "PCE_release": r.get("PCE_release"),
                        "PPI_release": r.get("PPI_release"),
                    }
        except Exception:
            pass

    # FRED에서 시리즈 fetch
    yoy_series = {}
    for col, series_id in FRED_SERIES.items():
        try:
            print(f"  {series_id} 다운로드 중...")
            raw = fetch_fred_csv(series_id)
            yoy_series[col] = calc_yoy(raw)
        except Exception as e:
            print(f"  [경고] {series_id} 실패: {e}")
            yoy_series[col] = pd.Series(dtype=float)

    # 월별로 병합
    df = pd.DataFrame(yoy_series).round(2)
    df = df.dropna(how="all").tail(KEEP_MONTHS)

    # 레코드 빌드
    records = []
    for idx, row in df.iterrows():
        date_str = idx.strftime("%Y-%m")
        rec = {"date": date_str}
        for col in FRED_SERIES.keys():
            v = row.get(col)
            rec[col] = round(v, 2) if pd.notna(v) else None

        # 발표일 — 기존 데이터 우선, 없으면 추정값
        old = old_releases.get(date_str, {})
        rec["CPI_release"] = old.get("CPI_release") or estimate_release_date(date_str, "CPI")
        rec["PCE_release"] = old.get("PCE_release") or estimate_release_date(date_str, "PCE")
        rec["PPI_release"] = old.get("PPI_release") or estimate_release_date(date_str, "PPI")
        records.append(rec)

    # 저장
    output = {
        "updated": now.strftime("%Y-%m-%d"),
        "source": "FRED (fred.stlouisfed.org)",
        "data": records,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 요약 출력
    latest = records[-1] if records else {}
    print(f"  저장 완료: {len(records)}개 레코드, 최신 {latest.get('date')}")
    print(f"    CPI YoY: {latest.get('CPI_YoY')}%  Core CPI: {latest.get('Core_CPI_YoY')}%")
    print(f"    PCE YoY: {latest.get('PCE_YoY')}%  Core PCE: {latest.get('Core_PCE_YoY')}%")
    print(f"    PPI YoY: {latest.get('PPI_YoY')}%  Core PPI: {latest.get('Core_PPI_YoY')}%")


if __name__ == "__main__":
    main()
