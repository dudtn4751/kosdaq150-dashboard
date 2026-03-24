"""
코스닥 150 데이터 자동 수집 모듈

데이터 소스:
- FinanceDataReader: 코스닥 전체 종목 리스트, 시가총액, 거래대금, 일별 OHLCV
- WISE Index API: GICS 11개 산업군 분류
- investing.com: 현재 코스닥 150 구성종목 리스트
"""

import os
import warnings
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup
import FinanceDataReader as fdr

warnings.filterwarnings("ignore")

SESSION_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    )
}

# investing.com에서 가격 매칭 실패 시 사용하는 수동 영문->한글 매핑
_MANUAL_ENG_KOR_MAP = {
    "Incar Financial Service": "인카금융서비스",
    "Yuilrobotics": "유일로보틱스",
    "Gaonchips": "가온칩스",
    "Voronoi": "보로노이",
    "HPSP": "HPSP",
    "Lunit": "루닛",
    "SungEel HiTech": "성일하이텍",
    "GI Innovation": "지아이이노베이션",
    "Curiox BioSystems": "큐리옥스바이오시스템즈",
    "LS Materials": "LS머트리얼즈",
    "DND PharmaTech": "디앤디파마텍",
    "Higen RNM": "하이젠알앤엠",
    "Clobot": "클로봇",
    "Aimed Bio": "에임드바이오",
}


def get_kosdaq_listing() -> pd.DataFrame:
    """코스닥 전체 종목 리스트 (최근 거래일 시가총액, 거래대금 포함)"""
    df = pd.DataFrame()

    # 1차: FDR API로 최근 거래일 데이터 시도
    try:
        dt = datetime.now()
        for _ in range(7):
            while dt.weekday() >= 5:
                dt -= timedelta(days=1)
            date = dt.strftime("%Y-%m-%d")
            df = fdr.StockListing("KOSDAQ", date)
            if not df.empty and "Close" in df.columns and df["Close"].notna().sum() > 100:
                break
            dt -= timedelta(days=1)
            df = pd.DataFrame()
    except Exception as e:
        print(f"  [경고] FDR StockListing 실패: {e}")
        df = pd.DataFrame()

    # 2차: FDR 실패 시 캐시 파일 사용
    if df.empty or ("Close" in df.columns and df["Close"].notna().sum() < 100):
        print("  [경고] FDR 데이터 부족, 캐시 파일 사용")
        cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "kosdaq_cache.csv")
        try:
            df = pd.read_csv(cache_path)
            print(f"  -> 캐시에서 {len(df)}종목 로드")
            return df
        except Exception:
            print("  [경고] 캐시 파일 로드 실패")
            return pd.DataFrame()

    df = df.rename(columns={
        "Code": "code",
        "Name": "name",
        "Close": "close",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Volume": "volume",
        "Amount": "amount",
        "Marcap": "marcap",
        "Stocks": "shares",
    })
    df = df[["code", "name", "close", "open", "high", "low",
             "volume", "amount", "marcap", "shares"]].copy()
    numeric_cols = ["close", "open", "high", "low", "volume", "amount", "marcap", "shares"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    int_cols = ["close", "open", "high", "low", "volume"]
    for col in int_cols:
        df[col] = df[col].astype(int)
    df = df[df["close"] > 0].reset_index(drop=True)
    return df


def get_gics_sector_map(date: str = None) -> dict:
    """WISE Index API에서 GICS 섹터별 종목 분류를 가져와 {종목코드: 섹터명} 딕셔너리 반환

    Args:
        date: 조회 날짜 (YYYYMMDD). None이면 최근 거래일 자동 탐색.
    """
    if date is None:
        date = _find_recent_trading_date()

    gics_codes = {
        "G10": "에너지",
        "G15": "소재",
        "G20": "산업재",
        "G25": "자유소비재",
        "G30": "필수소비재",
        "G35": "헬스케어",
        "G40": "금융",
        "G45": "정보기술",
        "G50": "커뮤니케이션서비스",
        "G55": "유틸리티",
        "G60": "부동산",
    }

    session = requests.Session()
    session.headers.update(SESSION_HEADERS)

    sector_map = {}
    for code, name in gics_codes.items():
        url = (
            f"https://www.wiseindex.com/Index/GetIndexComponets"
            f"?ceil_yn=0&dt={date}&sec_cd={code}"
        )
        try:
            r = session.get(url, timeout=15)
            data = r.json()
            for item in data.get("list", []):
                sector_map[item["CMP_CD"]] = name
        except Exception:
            print(f"  [경고] GICS 섹터 '{name}' 데이터 수집 실패")

    # 캐시 파일 로드
    import json
    cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "gics_cache.json")
    cache_map = {}
    cache_updated = "?"
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
        cache_map = cache.get("gics_map", {})
        cache_updated = cache.get("updated", "?")
    except Exception:
        pass

    if len(sector_map) < 100:
        # API 실패 시 캐시 전체 사용
        print("  [경고] WISE Index API 수집 부족, 캐시 파일 사용")
        sector_map = cache_map
        print(f"  -> 캐시에서 {len(sector_map)}종목 로드 (갱신일: {cache_updated})")
    else:
        # API 성공 시에도 캐시의 수동 보정 분류를 병합 (캐시 우선)
        for code, sector in cache_map.items():
            if code not in sector_map:
                sector_map[code] = sector

    return sector_map


def get_current_kosdaq150(kosdaq_df: pd.DataFrame = None) -> list:
    """코스닥 150 구성종목 코드 리스트를 가져옴

    정적 JSON 파일을 1차 소스로 사용합니다.
    (코스닥 150은 연 1회 6월에만 변경되므로 정적 파일이 가장 안정적)

    Args:
        kosdaq_df: 미사용 (하위 호환용으로 유지)

    Returns:
        종목코드 리스트 (6자리 문자열)
    """
    import json

    # 정적 파일에서 로드
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "kosdaq150_constituents.json")
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        codes = [item["code"] for item in data.get("constituents", [])]
        if codes:
            print(f"  -> 정적 파일에서 {len(codes)}종목 로드 (갱신일: {data.get('updated', '?')})")
            return codes
    except Exception:
        pass

    print("  [경고] 정적 파일 로드 실패")
    return []


def get_daily_data(code: str, start: str, end: str) -> pd.DataFrame:
    """개별 종목 일별 OHLCV 데이터 조회

    Args:
        code: 종목코드 (6자리)
        start: 시작일 (YYYY-MM-DD)
        end: 종료일 (YYYY-MM-DD)

    Returns:
        DataFrame (Date index, Open/High/Low/Close/Volume 컬럼)
    """
    return fdr.DataReader(code, start, end)


def calc_6month_averages(
    kosdaq_df: pd.DataFrame,
    end_date: str = None,
    progress: bool = True,
) -> pd.DataFrame:
    """코스닥 전 종목의 6개월 일평균시가총액 및 일평균거래대금 계산

    Args:
        kosdaq_df: get_kosdaq_listing() 결과 (shares 컬럼 필수)
        end_date: 심사기준일 (YYYY-MM-DD). None이면 최근 거래일.
        progress: 진행 상황 출력 여부

    Returns:
        DataFrame with columns: code, name, avg_marcap, avg_amount
    """
    if end_date is None:
        end_date = _find_recent_trading_date(fmt="dash")

    end_dt = pd.to_datetime(end_date)
    start_dt = end_dt - timedelta(days=180)
    start_date = start_dt.strftime("%Y-%m-%d")

    results = []
    total = len(kosdaq_df)

    for i, (_, row) in enumerate(kosdaq_df.iterrows()):
        code = row["code"]
        name = row["name"]
        shares = row["shares"]

        if progress and (i + 1) % 100 == 0:
            print(f"  [{i+1}/{total}] 일별 데이터 수집 중...")

        try:
            daily = fdr.DataReader(code, start_date, end_date)
            if daily.empty:
                continue

            avg_marcap = (daily["Close"] * shares).mean()
            avg_amount = (
                (daily["Open"] + daily["High"] + daily["Low"] + daily["Close"])
                / 4
                * daily["Volume"]
            ).mean()

            results.append({
                "code": code,
                "name": name,
                "avg_marcap": avg_marcap,
                "avg_amount": avg_amount,
                "trading_days": len(daily),
            })
        except Exception:
            continue

        # API 과부하 방지
        if (i + 1) % 50 == 0:
            time.sleep(1)

    return pd.DataFrame(results)


def _match_stock_code(
    kosdaq_df: pd.DataFrame, eng_name: str, price: int, high: int, low: int
) -> Optional[str]:
    """investing.com 영문 종목명과 가격을 이용하여 종목코드 매칭"""
    # 1차: 종가 + 고가 + 저가 정확 매칭
    c = kosdaq_df[
        (kosdaq_df["close"] == price)
        & (kosdaq_df["high"] == high)
        & (kosdaq_df["low"] == low)
    ]
    if len(c) >= 1:
        return c.iloc[0]["code"]

    # 2차: 종가만 매칭
    c = kosdaq_df[kosdaq_df["close"] == price]
    if len(c) == 1:
        return c.iloc[0]["code"]
    elif len(c) > 1:
        # 고가/저가로 추가 필터
        c2 = c[(c["high"] == high) | (c["low"] == low)]
        if len(c2) >= 1:
            return c2.iloc[0]["code"]
        return c.iloc[0]["code"]

    # 3차: 고가/저가 매칭
    c = kosdaq_df[(kosdaq_df["high"] == high) & (kosdaq_df["low"] == low)]
    if len(c) >= 1:
        return c.iloc[0]["code"]

    # 4차: 수동 매핑
    if eng_name in _MANUAL_ENG_KOR_MAP:
        kor_name = _MANUAL_ENG_KOR_MAP[eng_name]
        m = kosdaq_df[kosdaq_df["name"].str.contains(kor_name, na=False)]
        if len(m) >= 1:
            return m.iloc[0]["code"]

    return None


def _find_recent_trading_date(fmt: str = "compact") -> str:
    """최근 거래일을 찾아서 반환 (주말 제외, 당일 장전이면 전일)"""
    dt = datetime.now()
    # 장 마감(15:30) 전이면 전일 사용
    if dt.hour < 16:
        dt -= timedelta(days=1)
    # 주말이면 금요일로
    while dt.weekday() >= 5:
        dt -= timedelta(days=1)
    if fmt == "dash":
        return dt.strftime("%Y-%m-%d")
    return dt.strftime("%Y%m%d")


# --- 편의 함수 ---

def collect_all(end_date: str = None, skip_daily: bool = False):
    """모든 데이터를 한 번에 수집하여 딕셔너리로 반환

    Args:
        end_date: 심사기준일 (YYYY-MM-DD)
        skip_daily: True면 6개월 일별 평균 계산을 건너뜀 (빠른 테스트용)

    Returns:
        dict with keys:
            - kosdaq_listing: 코스닥 전체 종목 DataFrame
            - gics_map: {종목코드: GICS 섹터명}
            - current_150: 현재 코스닥150 구성종목 코드 리스트
            - avg_data: 6개월 일평균 시가총액/거래대금 DataFrame (skip_daily=False일 때)
    """
    print("[1/4] 코스닥 전체 종목 리스트 수집...")
    kosdaq = get_kosdaq_listing()
    print(f"  -> {len(kosdaq)}종목")

    print("[2/4] GICS 산업군 분류 수집...")
    gics_map = get_gics_sector_map()
    kosdaq_with_gics = sum(1 for c in kosdaq["code"] if c in gics_map)
    print(f"  -> {kosdaq_with_gics}/{len(kosdaq)}종목 분류 완료")

    print("[3/4] 현재 코스닥 150 구성종목 수집...")
    current_150 = get_current_kosdaq150(kosdaq)
    print(f"  -> {len(current_150)}종목")

    result = {
        "kosdaq_listing": kosdaq,
        "gics_map": gics_map,
        "current_150": current_150,
    }

    if not skip_daily:
        print("[4/4] 6개월 일평균 시가총액/거래대금 계산...")
        print("  (전 종목 대상, 시간이 다소 소요됩니다)")
        avg = calc_6month_averages(kosdaq, end_date)
        result["avg_data"] = avg
        print(f"  -> {len(avg)}종목 계산 완료")
    else:
        print("[4/4] 6개월 일별 계산 건너뜀 (skip_daily=True)")

    return result


if __name__ == "__main__":
    data = collect_all(skip_daily=True)

    print("\n=== 수집 결과 요약 ===")
    print(f"코스닥 전체: {len(data['kosdaq_listing'])}종목")
    print(f"GICS 분류: {len(data['gics_map'])}종목")
    print(f"코스닥 150: {len(data['current_150'])}종목")

    # 현재 구성종목 출력
    kosdaq = data["kosdaq_listing"]
    gics = data["gics_map"]
    print(f"\n=== 현재 코스닥 150 구성종목 (시가총액 순) ===")
    rows = []
    for code in data["current_150"]:
        info = kosdaq[kosdaq["code"] == code]
        if info.empty:
            continue
        rows.append({
            "code": code,
            "name": info.iloc[0]["name"],
            "marcap": info.iloc[0]["marcap"],
            "sector": gics.get(code, "미분류"),
        })
    df = pd.DataFrame(rows).sort_values("marcap", ascending=False)
    for i, (_, r) in enumerate(df.iterrows()):
        print(f"  {i+1:>3}. {r['code']} {r['name']:<15} "
              f"{r['sector']:<12} {r['marcap']/1e12:.1f}조")
