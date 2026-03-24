"""
코스닥 150 수시변경 위험 감지 스크립트
매일 07:00 GitHub Actions에서 실행

감지 항목:
1. 투자주의환기종목 지정
2. 관리종목 지정
3. 거래정지 (Volume=0)

감지 시 → 해당 섹터 차순위 편입 후보 산출 → JSON 저장
"""

import os
import sys
import json
from datetime import datetime, timezone, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd

KST = timezone(timedelta(hours=9))
RESULT_PATH = os.path.join(PROJECT_ROOT, "data", "kosdaq150_risk.json")


def main():
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    print(f"[{now}] 코스닥 150 수시변경 위험 감지 시작")

    # 1. 데이터 로드
    try:
        import FinanceDataReader as fdr
        dt = datetime.now(KST)
        # 최근 거래일
        for _ in range(7):
            if dt.hour < 16:
                dt -= timedelta(days=1)
            while dt.weekday() >= 5:
                dt -= timedelta(days=1)
            date = dt.strftime("%Y-%m-%d")
            df = fdr.StockListing("KOSDAQ", date)
            if not df.empty and "Close" in df.columns and df["Close"].notna().sum() > 100:
                break
            dt -= timedelta(days=1)
        print(f"  코스닥 종목: {len(df)}개")
    except Exception as e:
        print(f"  [에러] FDR 실패: {e}")
        df = pd.DataFrame()

    if df.empty:
        print("  데이터 없음, 종료")
        return

    # 2. 코스닥 150 구성종목 로드
    json_path = os.path.join(PROJECT_ROOT, "kosdaq150_constituents.json")
    with open(json_path, "r", encoding="utf-8") as f:
        constituents = json.load(f)
    codes_150 = {item["code"]: item["name"] for item in constituents["constituents"]}

    # 3. GICS 분류 로드
    gics_path = os.path.join(PROJECT_ROOT, "gics_cache.json")
    with open(gics_path, "r", encoding="utf-8") as f:
        gics_data = json.load(f)
    gics_map = gics_data.get("gics_map", {})

    # 4. 위험 종목 감지
    risk_stocks = []

    for _, row in df.iterrows():
        code = row["Code"]
        if code not in codes_150:
            continue

        name = row["Name"]
        dept = str(row.get("Dept", ""))
        volume = row.get("Volume", 1)
        marcap = row.get("Marcap", 0)

        risks = []
        if "투자주의" in dept or "환기" in dept:
            risks.append("투자주의환기종목")
        if "관리" in dept:
            risks.append("관리종목")
        if volume is not None and float(volume) == 0:
            risks.append("거래정지")

        if risks:
            sector = gics_map.get(code, "미분류")
            risk_stocks.append({
                "code": code,
                "name": name,
                "sector": sector,
                "dept": dept,
                "risks": risks,
                "marcap": float(marcap) if pd.notna(marcap) else 0,
            })

    print(f"  위험 종목: {len(risk_stocks)}개")
    for r in risk_stocks:
        print(f"    [{', '.join(r['risks'])}] {r['code']} {r['name']} ({r['sector']})")

    # 5. 편입 후보 산출 (위험 종목의 섹터에서 차순위)
    candidates = []
    if risk_stocks:
        # 숫자 변환
        for col in ["Close", "Marcap", "Volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        risk_sectors = {r["sector"] for r in risk_stocks}
        existing_codes = set(codes_150.keys())

        for sector in risk_sectors:
            # 해당 섹터의 전체 코스닥 종목 (시총 순)
            sector_stocks = []
            for _, row in df.iterrows():
                code = row["Code"]
                if gics_map.get(code) == sector and code not in existing_codes:
                    sector_stocks.append({
                        "code": code,
                        "name": row["Name"],
                        "sector": sector,
                        "marcap": float(row.get("Marcap", 0)),
                    })
            sector_stocks.sort(key=lambda x: x["marcap"], reverse=True)

            # 상위 3개 후보
            for s in sector_stocks[:3]:
                if s["marcap"] > 0:
                    candidates.append(s)

        print(f"  편입 후보: {len(candidates)}개")
        for c in candidates:
            print(f"    {c['code']} {c['name']} ({c['sector']}) 시총 {c['marcap']/1e12:.2f}조")

    # 6. 결과 저장
    result = {
        "checked_at": now,
        "risk_count": len(risk_stocks),
        "risk_stocks": risk_stocks,
        "candidates": candidates,
    }

    os.makedirs(os.path.dirname(RESULT_PATH), exist_ok=True)
    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"  저장 완료: {RESULT_PATH}")


if __name__ == "__main__":
    main()
