"""
ARK IMPACT 대시보드 자동 복구 스크립트
헬스체크 실패 시 자동으로 캐시 데이터를 재생성합니다.

복구 가능 항목:
1. 코스닥 종목 캐시 (kosdaq_cache.csv) 재생성
2. GICS 분류 캐시 (gics_cache.json) 재생성
3. 매크로 캘린더 (macro_calendar.json) 재생성
4. 코스닥 150 구성종목 JSON 검증/복원
"""

import os
import sys
import json
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd


def repair_kosdaq_cache():
    """코스닥 종목 캐시 재생성"""
    cache_path = os.path.join(PROJECT_ROOT, "kosdaq_cache.csv")
    print("  [복구] 코스닥 캐시 재생성 시도...")

    try:
        import FinanceDataReader as fdr
        from datetime import datetime, timedelta

        dt = datetime.now()
        for _ in range(7):
            while dt.weekday() >= 5:
                dt -= timedelta(days=1)
            date = dt.strftime("%Y-%m-%d")
            df = fdr.StockListing("KOSDAQ", date)
            if not df.empty and "Close" in df.columns and df["Close"].notna().sum() > 100:
                df = df.rename(columns={
                    "Code": "code", "Name": "name", "Close": "close",
                    "Open": "open", "High": "high", "Low": "low",
                    "Volume": "volume", "Amount": "amount",
                    "Marcap": "marcap", "Stocks": "shares",
                })
                df = df[["code", "name", "close", "open", "high", "low",
                         "volume", "amount", "marcap", "shares"]].copy()
                for col in ["close", "open", "high", "low", "volume", "amount", "marcap", "shares"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
                for col in ["close", "open", "high", "low", "volume"]:
                    df[col] = df[col].astype(int)
                df = df[df["close"] > 0].reset_index(drop=True)
                df.to_csv(cache_path, index=False)
                print(f"  [복구 성공] kosdaq_cache.csv: {len(df)}종목")
                return True
            dt -= timedelta(days=1)
    except Exception as e:
        print(f"  [복구 실패] FDR 실패: {e}")

    # 기존 캐시 유효성 확인
    try:
        df = pd.read_csv(cache_path)
        if len(df) > 100:
            print(f"  [유지] 기존 캐시 유효 ({len(df)}종목)")
            return True
    except Exception:
        pass

    print("  [복구 실패] 코스닥 캐시 복구 불가")
    return False


def repair_gics_cache():
    """GICS 분류 캐시 재생성"""
    cache_path = os.path.join(PROJECT_ROOT, "gics_cache.json")
    print("  [복구] GICS 캐시 재생성 시도...")

    try:
        import requests
        from data_collector import _find_recent_trading_date, SESSION_HEADERS

        date = _find_recent_trading_date()
        gics_codes = {
            "G10": "에너지", "G15": "소재", "G20": "산업재",
            "G25": "자유소비재", "G30": "필수소비재", "G35": "헬스케어",
            "G40": "금융", "G45": "정보기술", "G50": "커뮤니케이션서비스",
            "G55": "유틸리티", "G60": "부동산",
        }

        session = requests.Session()
        session.headers.update(SESSION_HEADERS)
        sector_map = {}

        for code, name in gics_codes.items():
            try:
                url = f"https://www.wiseindex.com/Index/GetIndexComponets?ceil_yn=0&dt={date}&sec_cd={code}"
                r = session.get(url, timeout=15)
                data = r.json()
                for item in data.get("list", []):
                    sector_map[item["CMP_CD"]] = name
            except Exception:
                pass

        if len(sector_map) > 100:
            # 기존 캐시의 수동 보정 항목 병합
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    old = json.load(f)
                old_map = old.get("gics_map", {})
                for code, sector in old_map.items():
                    if code not in sector_map:
                        sector_map[code] = sector
            except Exception:
                pass

            from datetime import datetime
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"updated": datetime.now().strftime("%Y-%m-%d"), "gics_map": sector_map},
                          f, ensure_ascii=False, indent=2)
            print(f"  [복구 성공] gics_cache.json: {len(sector_map)}종목")
            return True
    except Exception as e:
        print(f"  [복구 실패] WISE API 실패: {e}")

    # 기존 캐시 유효성 확인
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        count = len(data.get("gics_map", {}))
        if count > 100:
            print(f"  [유지] 기존 캐시 유효 ({count}종목)")
            return True
    except Exception:
        pass

    print("  [복구 실패] GICS 캐시 복구 불가")
    return False


def repair_macro_calendar():
    """매크로 캘린더 재생성"""
    print("  [복구] 매크로 캘린더 재생성 시도...")
    try:
        script = os.path.join(PROJECT_ROOT, "scripts", "update_macro.py")
        result = subprocess.run(
            [sys.executable, script],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            print("  [복구 성공] macro_calendar.json 재생성")
            return True
        else:
            print(f"  [복구 실패] {result.stderr[:200]}")
    except Exception as e:
        print(f"  [복구 실패] {e}")
    return False


def repair_kosdaq150_json():
    """코스닥 150 구성종목 JSON 검증"""
    json_path = os.path.join(PROJECT_ROOT, "kosdaq150_constituents.json")
    print("  [검증] 코스닥 150 구성종목 JSON...")

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        count = len(data.get("constituents", []))
        if count >= 140:
            print(f"  [정상] {count}종목")
            return True
        else:
            print(f"  [경고] {count}종목 — Git에서 복원 시도")
    except Exception as e:
        print(f"  [손상] {e} — Git에서 복원 시도")

    # Git에서 마지막 정상 버전 복원
    try:
        result = subprocess.run(
            ["git", "checkout", "HEAD", "--", "kosdaq150_constituents.json"],
            capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=10,
        )
        if result.returncode == 0:
            print("  [복구 성공] Git에서 복원")
            return True
    except Exception:
        pass

    print("  [복구 실패] 구성종목 JSON 복구 불가")
    return False


def main():
    print("=" * 50)
    print("ARK IMPACT 자동 복구")
    print("=" * 50)

    repairs = [
        ("코스닥 종목 캐시", repair_kosdaq_cache),
        ("GICS 분류 캐시", repair_gics_cache),
        ("매크로 캘린더", repair_macro_calendar),
        ("코스닥 150 구성종목", repair_kosdaq150_json),
    ]

    all_ok = True
    for name, func in repairs:
        print(f"\n[{name}]")
        if not func():
            all_ok = False

    print("\n" + "=" * 50)
    if all_ok:
        print("결과: 모든 복구 완료")
    else:
        print("결과: 일부 복구 실패 — 수동 조치 필요")
    print("=" * 50)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
