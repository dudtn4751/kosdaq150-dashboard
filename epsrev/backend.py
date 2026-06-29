"""
리서치 대시보드 백엔드
─────────────────────────────────────────────────────────────────────
데이터 흐름:
  DataGuide Excel  →  parse_dataguide()  →  /api/company/{ticker}
  KRX API          →  parse_krx_short()  →  /api/short/{ticker}
  KITA K-stat API  →  parse_kita()       →  /api/export/{ticker}
  Naver Finance    →  crawl_news()        →  /api/news/{ticker}

실행:
  pip install fastapi uvicorn pandas openpyxl httpx beautifulsoup4
  uvicorn backend:app --reload --port 8000
"""

from __future__ import annotations
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Research Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 로컬 개발용. 배포 시 도메인 지정
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────
# 1. 데이터 경로 설정
#    DataGuide에서 내려받은 Excel 파일들을 data/ 폴더에 넣으세요.
# ─────────────────────────────────────────────────────────────────────

DATA_DIR = Path("data")                   # 엑셀 파일 저장 폴더
CACHE_DIR = Path("cache")                 # 파싱 결과 캐시 (Parquet)
CACHE_DIR.mkdir(exist_ok=True)

# HS코드 매핑 테이블 (ticker → 관세청 HS코드)
# 주요 종목 먼저 채우고 점진적으로 확장
HS_MAP: dict[str, list[str]] = {
    "000660": ["854232", "854231"],   # SK하이닉스 → D램, 낸드
    "058470": ["847330"],             # 리노공업    → 반도체 소켓
    "373220": ["850760", "850780"],   # LG에너지솔루션 → 리튬이온전지
    "005380": ["870380", "870390"],   # 현대차      → 전기차, 승용차
    "000270": ["870380", "870390"],   # 기아
    "207940": ["300215"],             # 삼성바이오  → 바이오의약품
    "012450": ["930690", "890111"],   # 한화에어로  → 항공기부품, 함정
    "329180": ["890190"],             # HD현대중공업 → 선박
    # 필요한 종목 계속 추가
}


# ─────────────────────────────────────────────────────────────────────
# 2. DataGuide Excel 파서
# ─────────────────────────────────────────────────────────────────────

class DataGuideParser:
    """
    DataGuide Pro에서 내려받은 Excel 파일을 파싱합니다.

    DataGuide 내보내기 방법:
    1. 재무제표: DataGuide → 재무 → 분기실적 → Excel 저장
       파일명 규칙: financial_YYYYMMDD.xlsx
    2. 컨센서스: DataGuide → 컨센서스 → 영업이익 예상 → Excel 저장
       파일명 규칙: consensus_YYYYMMDD.xlsx
    3. 리포트 요약: DataGuide → 리서치 → 애널리스트 의견 → Excel 저장
       파일명 규칙: reports_YYYYMMDD.xlsx
    """

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir

    def get_latest_file(self, prefix: str) -> Optional[Path]:
        """날짜 접미사 기준 가장 최신 파일 반환"""
        files = sorted(self.data_dir.glob(f"{prefix}_*.xlsx"), reverse=True)
        return files[0] if files else None

    # ── 2-1. 분기 실적 ──────────────────────────────────────────────
    def parse_financials(self, ticker: str) -> list[dict]:
        """
        반환 형식 (React FinChart가 기대하는 구조):
        [
          { "q": "25Q2", "rev": 17800, "op": 3600, "opm": 20 },
          ...
        ]
        """
        path = self.get_latest_file("financial")
        if not path:
            raise FileNotFoundError("financial_YYYYMMDD.xlsx 파일이 없습니다")

        df = pd.read_excel(path, sheet_name="분기실적", header=3, index_col=0)

        # DataGuide는 종목코드를 열 이름으로, 항목을 행으로 내보냅니다.
        # 열 이름 예: "A005930/삼성전자" → "005930" 추출
        col = next((c for c in df.columns if ticker in str(c)), None)
        if col is None:
            return []

        co_df = df[col].dropna()

        results = []
        # 행 인덱스는 "2024/3Q 매출액", "2024/3Q 영업이익" 형식
        quarters = {}
        for idx, val in co_df.items():
            m = re.match(r"(\d{4})/(\dQ)\s(.+)", str(idx))
            if not m:
                continue
            year, q, item = m.groups()
            key = f"{str(year)[2:]}{q}"       # "24Q3"
            quarters.setdefault(key, {})["q"] = key
            if "매출" in item:
                quarters[key]["rev"] = int(val / 1e8)    # 원 → 억원
            elif "영업이익" in item:
                quarters[key]["op"] = int(val / 1e8)

        for q_data in sorted(quarters.values(), key=lambda x: x["q"]):
            rev = q_data.get("rev", 0)
            op  = q_data.get("op", 0)
            q_data["opm"] = round(op / rev * 100, 1) if rev else 0
            results.append(q_data)

        return results[-8:]   # 최근 8분기

    # ── 2-2. 컨센서스 ───────────────────────────────────────────────
    def parse_consensus(self, ticker: str) -> list[dict]:
        """
        반환 형식 (React ConsChart가 기대하는 구조):
        [
          { "m": "25.07", "fy1": 14200, "fy2": 17800 },
          ...
        ]
        """
        path = self.get_latest_file("consensus")
        if not path:
            raise FileNotFoundError("consensus_YYYYMMDD.xlsx 파일이 없습니다")

        df = pd.read_excel(path, sheet_name="영업이익", header=2, index_col=0)
        col = next((c for c in df.columns if ticker in str(c)), None)
        if col is None:
            return []

        co_df = df[[col]].dropna()
        co_df.index = pd.to_datetime(co_df.index)
        co_df.columns = ["value"]

        # FY1/FY2 구분: DataGuide 컨센서스는 FY별로 시트가 나뉠 수 있음
        # 여기서는 단순화하여 FY1=당해연도, FY2=차기연도로 처리
        results = []
        for dt, row in co_df.iterrows():
            results.append({
                "m":   dt.strftime("%y.%m"),
                "fy1": int(row["value"] / 1e8),
                "fy2": int(row["value"] / 1e8 * 1.15),   # FY2는 별도 시트에서 가져오길 권장
            })

        return results[-12:]   # 최근 12개월

    # ── 2-3. 최신 리포트 ────────────────────────────────────────────
    def parse_latest_report(self, ticker: str) -> Optional[dict]:
        """
        반환 형식:
        {
          "an": "이민준 (NH투자)", "d": "2026.06.10",
          "tp": 260000, "r": "BUY", "s": "요약문..."
        }
        """
        path = self.get_latest_file("reports")
        if not path:
            return None

        df = pd.read_excel(path, sheet_name="애널리스트의견", header=2)

        # 종목코드 열 찾기
        code_col = next((c for c in df.columns if "코드" in str(c) or "Code" in str(c)), None)
        if code_col is None:
            return None

        co_df = df[df[code_col].astype(str).str.contains(ticker)].copy()
        if co_df.empty:
            return None

        co_df["date_parsed"] = pd.to_datetime(co_df.get("날짜", co_df.get("Date", pd.NaT)), errors="coerce")
        latest = co_df.sort_values("date_parsed", ascending=False).iloc[0]

        return {
            "an":  str(latest.get("애널리스트", latest.get("Analyst", ""))),
            "d":   latest["date_parsed"].strftime("%Y.%m.%d") if pd.notna(latest["date_parsed"]) else "",
            "tp":  int(latest.get("목표주가", latest.get("TargetPrice", 0)) or 0),
            "r":   str(latest.get("투자의견", latest.get("Rating", "HOLD"))),
            "s":   str(latest.get("요약", latest.get("Summary", ""))),
        }

    # ── 2-4. 주가/시총 ──────────────────────────────────────────────
    def parse_price(self, ticker: str) -> dict:
        """
        반환 형식:
        { "price": 198500, "priceChange": 2.3, "marketCap": 144300 }
        """
        path = self.get_latest_file("price")
        if not path:
            return {"price": 0, "priceChange": 0.0, "marketCap": 0}

        df = pd.read_excel(path, sheet_name="주가", header=2, index_col=0)
        col = next((c for c in df.columns if ticker in str(c)), None)
        if col is None:
            return {"price": 0, "priceChange": 0.0, "marketCap": 0}

        recent = df[col].dropna().tail(2)
        if len(recent) < 2:
            return {"price": 0, "priceChange": 0.0, "marketCap": 0}

        today_price = int(recent.iloc[-1])
        prev_price  = int(recent.iloc[-2])
        change_pct  = round((today_price - prev_price) / prev_price * 100, 1)

        # 시가총액은 별도 시트 or 가격 * 상장주식수
        mkt_col = next((c for c in df.columns if ticker in str(c) and "시총" in str(c)), None)
        mkt_cap = int(df[mkt_col].dropna().iloc[-1] / 1e8) if mkt_col else 0

        return {"price": today_price, "priceChange": change_pct, "marketCap": mkt_cap}


# ─────────────────────────────────────────────────────────────────────
# 3. KRX 대차잔고 API 파서
# ─────────────────────────────────────────────────────────────────────

class KRXParser:
    """
    KRX 데이터포털 (data.krx.co.kr) REST API 연동.
    회원가입 → 오픈API 신청 → 인증키 발급 필요 (무료).
    """

    BASE = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key   # 발급받은 인증키

    def _isin(self, ticker: str) -> str:
        """종목코드 6자리 → KR로 시작하는 ISIN 변환 (간략 버전)"""
        # 실제 ISIN은 KRX API에서 조회하거나 별도 매핑 테이블 사용
        return f"KR{ticker}0000"

    async def get_short_balance(self, ticker: str, months: int = 9) -> list[dict]:
        """
        대차잔고 조회.
        반환 형식 (React SbChart가 기대하는 구조):
        [
          { "m": "25.10", "bal": 8200, "ratio": 1.2 },
          ...
        ]
        """
        end_date   = date.today()
        start_date = end_date - timedelta(days=months * 31)

        params = {
            "bld":         "dbms/MDC/STAT/standard/MDCSTAT30001",
            "isuCd":       self._isin(ticker),
            "strtDd":      start_date.strftime("%Y%m%d"),
            "endDd":       end_date.strftime("%Y%m%d"),
            "share":       "1",
            "money":       "1",
            "csvxls_isNo": "false",
        }
        if self.api_key:
            params["AUTH_KEY"] = self.api_key

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(self.BASE, data=params)
            data = resp.json()

        rows = data.get("output", [])
        result = []
        for row in rows:
            # 월말 데이터만 추출
            dt = pd.to_datetime(row.get("TRD_DD", ""), format="%Y/%m/%d", errors="coerce")
            if pd.isna(dt) or dt.day < 20:
                continue
            bal_raw    = float(str(row.get("LEND_SHRS", "0")).replace(",", "") or 0)
            bal_bil    = round(bal_raw * float(str(row.get("TDD_CLSPRC", "0")).replace(",", "") or 0) / 1e8, 0)
            ratio_raw  = float(str(row.get("LEND_SHR_RT", "0")).replace(",", "") or 0)
            result.append({
                "m":     dt.strftime("%y.%m"),
                "bal":   int(bal_bil),
                "ratio": round(ratio_raw, 2),
            })

        return result[-months:]

    async def get_daily_short(self, ticker: str) -> list[dict]:
        """
        일별 공매도 데이터 (차입비용 추정용).
        반환: [{ "date": "2026-06-25", "short_ratio": 1.2, "borrow_rate": 0.8 }, ...]
        """
        end_date   = date.today()
        start_date = end_date - timedelta(days=60)

        params = {
            "bld":    "dbms/MDC/STAT/standard/MDCSTAT30401",
            "isuCd":  self._isin(ticker),
            "strtDd": start_date.strftime("%Y%m%d"),
            "endDd":  end_date.strftime("%Y%m%d"),
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(self.BASE, data=params)
            data = resp.json()

        return [
            {
                "date":         row.get("TRD_DD", ""),
                "short_ratio":  float(str(row.get("SHORT_SELS_TRND_RT", "0")).replace(",", "") or 0),
                "borrow_rate":  None,  # KRX에서 직접 차입비용 미제공 → 증권사 API 필요
            }
            for row in data.get("output", [])
        ]


# ─────────────────────────────────────────────────────────────────────
# 4. 수출입 데이터 파서 (KITA K-stat API)
# ─────────────────────────────────────────────────────────────────────

class KITAParser:
    """
    KITA K-stat (www.kita.net) 무역통계 API 연동.
    회원가입 후 API 키 발급 (무료).

    대안: 관세청 TRASS (unipass.customs.go.kr)
    """

    BASE = "https://stat.kita.net/openapi/service/ItemStatsService/getExptItemStats"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    async def get_export_monthly(self, hs_codes: list[str], months: int = 9) -> list[dict]:
        """
        HS코드 기준 월별 수출 데이터.
        반환 형식 (React ExpChart가 기대하는 구조):
        [
          { "m": "25.10", "val": 2800, "yoy": 12 },
          ...
        ]
        여러 HS코드의 합산 처리.
        """
        results_by_month: dict[str, dict] = {}

        async with httpx.AsyncClient(timeout=20) as client:
            for hs in hs_codes:
                params = {
                    "serviceKey": self.api_key,
                    "hsSgn":      hs,
                    "strtYymm":   (date.today().replace(day=1) - timedelta(days=months * 31)).strftime("%Y%m"),
                    "endYymm":    date.today().strftime("%Y%m"),
                    "type":       "json",
                }
                try:
                    resp = await client.get(self.BASE, params=params, timeout=15)
                    data = resp.json()
                    items = data.get("response", {}).get("body", {}).get("items", {}).get("item", [])
                    for item in (items if isinstance(items, list) else [items]):
                        ym = str(item.get("strdYymm", ""))
                        if len(ym) != 6:
                            continue
                        key = f"{ym[2:4]}.{ym[4:]}"
                        exp_val = int(str(item.get("expDlr", "0")).replace(",", "") or 0) // 1000000  # USD → 백만달러
                        yoy_val = float(str(item.get("expDlrIncDcRt", "0")).replace(",", "") or 0)
                        if key not in results_by_month:
                            results_by_month[key] = {"m": key, "val": 0, "yoy": yoy_val}
                        results_by_month[key]["val"] += exp_val
                except Exception:
                    continue  # 특정 HS코드 조회 실패 시 다음 코드로

        return sorted(results_by_month.values(), key=lambda x: x["m"])


# ─────────────────────────────────────────────────────────────────────
# 5. 뉴스 크롤러 (Naver Finance)
# ─────────────────────────────────────────────────────────────────────

async def crawl_news(ticker: str, limit: int = 5) -> list[dict]:
    """
    네이버 금융 뉴스 크롤링.
    반환 형식:
    [{ "t": "뉴스 제목", "d": "06.25" }, ...]
    """
    url = f"https://finance.naver.com/item/news_news.naver?code={ticker}&page=1"
    headers = {"User-Agent": "Mozilla/5.0 (compatible)"}

    async with httpx.AsyncClient(headers=headers, timeout=10) as client:
        resp = await client.get(url)

    # BeautifulSoup 파싱 (설치: pip install beautifulsoup4)
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.select("table.type5 tr")
        news = []
        for row in rows:
            title_tag = row.select_one("td.title a")
            date_tag  = row.select_one("td.date")
            if not title_tag or not date_tag:
                continue
            dt_str = date_tag.text.strip()   # "2026.06.25 09:30"
            dt_short = dt_str[5:10].replace(".", "/") if len(dt_str) >= 10 else ""
            news.append({
                "t": title_tag.text.strip(),
                "d": dt_short,
            })
            if len(news) >= limit:
                break
        return news
    except ImportError:
        return [{"t": "뉴스 조회 실패 (pip install beautifulsoup4 필요)", "d": ""}]


# ─────────────────────────────────────────────────────────────────────
# 6. 스코어 계산기
#    실제 데이터를 받아 점수로 변환합니다.
#    지금은 예시 로직 — 섹터별 가중치는 추후 설정값으로 분리 권장
# ─────────────────────────────────────────────────────────────────────

def calc_earnings_score(fin: list[dict], cons: list[dict]) -> int:
    """실적 점수 (max 40)"""
    if not fin or len(fin) < 2:
        return 0

    latest  = fin[-1]
    prev    = fin[-2]
    prev_yr = next((f for f in fin if f["q"][:2] == latest["q"][:2] and
                    f["q"][-2:] == latest["q"][-2:] and f != latest), None)

    score = 0

    # QoQ 매출 성장 (0~10점)
    if prev.get("rev", 0) > 0:
        qoq_rev = (latest.get("rev", 0) - prev["rev"]) / prev["rev"]
        score += min(10, max(0, int(qoq_rev * 50)))

    # YoY 매출 성장 (0~10점)
    if prev_yr and prev_yr.get("rev", 0) > 0:
        yoy_rev = (latest.get("rev", 0) - prev_yr["rev"]) / prev_yr["rev"]
        score += min(10, max(0, int(yoy_rev * 30)))

    # OPM 방향 (0~10점)
    if latest.get("opm", 0) > prev.get("opm", 0):
        score += min(10, latest.get("opm", 0))

    # 컨센서스 상향 여부 (0~10점)
    if cons and len(cons) >= 4:
        c_now  = cons[-1].get("fy1", 0)
        c_3m   = cons[-4].get("fy1", 0)
        if c_3m > 0 and c_now > c_3m:
            upward_pct = (c_now - c_3m) / c_3m
            score += min(10, int(upward_pct * 50))

    return min(40, score)


def calc_data_score(exp: list[dict]) -> int:
    """데이터 점수 (max 35) - 수출입 기준"""
    if not exp:
        return 0

    recent = exp[-3:]
    avg_yoy = sum(r.get("yoy", 0) for r in recent) / len(recent)

    # YoY 성장률 기반 선형 변환
    score = min(35, max(0, int(avg_yoy * 1.5 + 17)))
    return score


def calc_supply_score(short: list[dict]) -> int:
    """수급 점수 (max 25) - 대차잔고 기준 (역방향)"""
    if not short or len(short) < 2:
        return 12   # 데이터 없으면 중립

    latest   = short[-1]
    month_ago = short[-2] if len(short) < 5 else short[-5]

    ratio_chg = latest.get("ratio", 0) - month_ago.get("ratio", 0)
    # 대차잔고 비율 감소 → 수급 개선 → 높은 점수
    score = min(25, max(0, int(12 - ratio_chg * 20)))
    return score


# ─────────────────────────────────────────────────────────────────────
# 7. 파사드: 종목별 전체 데이터 조립
# ─────────────────────────────────────────────────────────────────────

dg  = DataGuideParser()
krx = KRXParser(api_key="YOUR_KRX_API_KEY")       # 발급받은 키 입력
kit = KITAParser(api_key="YOUR_KITA_API_KEY")      # 발급받은 키 입력

# 섹터 정보 (고정값 — 대시보드와 동기화)
SECTOR_MAP = {
    "000660": {"secId": "semi",   "secName": "반도체",   "secColor": "#4f8eff"},
    "058470": {"secId": "semi",   "secName": "반도체",   "secColor": "#4f8eff"},
    "319660": {"secId": "semi",   "secName": "반도체",   "secColor": "#4f8eff"},
    "373220": {"secId": "bat",    "secName": "2차전지",  "secColor": "#00c87a"},
    "247540": {"secId": "bat",    "secName": "2차전지",  "secColor": "#00c87a"},
    "003670": {"secId": "bat",    "secName": "2차전지",  "secColor": "#00c87a"},
    "005380": {"secId": "auto",   "secName": "자동차",   "secColor": "#ffaa00"},
    "000270": {"secId": "auto",   "secName": "자동차",   "secColor": "#ffaa00"},
    "012330": {"secId": "auto",   "secName": "자동차",   "secColor": "#ffaa00"},
    "207940": {"secId": "health", "secName": "헬스케어", "secColor": "#b07aff"},
    "128940": {"secId": "health", "secName": "헬스케어", "secColor": "#b07aff"},
    "000100": {"secId": "health", "secName": "헬스케어", "secColor": "#b07aff"},
    "012450": {"secId": "def",    "secName": "방산",     "secColor": "#ff6b3d"},
    "064350": {"secId": "def",    "secName": "방산",     "secColor": "#ff6b3d"},
    "079550": {"secId": "def",    "secName": "방산",     "secColor": "#ff6b3d"},
    "329180": {"secId": "ship",   "secName": "조선",     "secColor": "#00d4c8"},
    "010140": {"secId": "ship",   "secName": "조선",     "secColor": "#00d4c8"},
    "042660": {"secId": "ship",   "secName": "조선",     "secColor": "#00d4c8"},
}


# ─────────────────────────────────────────────────────────────────────
# 8. API 라우트
# ─────────────────────────────────────────────────────────────────────

@app.get("/api/company/{ticker}")
async def get_company(ticker: str):
    """
    기업 상세 데이터 전체 반환.
    React 대시보드의 CO[ticker] 구조와 1:1 매핑.
    """
    if ticker not in SECTOR_MAP:
        raise HTTPException(status_code=404, detail="등록되지 않은 종목코드")

    try:
        # 병렬로 데이터 수집 가능하지만 순서대로 수집 (디버깅 용이)
        fin    = dg.parse_financials(ticker)
        cons   = dg.parse_consensus(ticker)
        rpt    = dg.parse_latest_report(ticker)
        price  = dg.parse_price(ticker)
        short  = await krx.get_short_balance(ticker)
        hs     = HS_MAP.get(ticker, [])
        exp    = await kit.get_export_monthly(hs) if hs else []
        news   = await crawl_news(ticker)

        # 점수 계산
        sc_e = calc_earnings_score(fin, cons)
        sc_d = calc_data_score(exp)
        sc_s = calc_supply_score(short)

        sec = SECTOR_MAP[ticker]

        return {
            "t":         ticker,
            "n":         rpt.get("an", "").split("(")[0].strip() if rpt else ticker,  # 임시
            "secId":     sec["secId"],
            "secName":   sec["secName"],
            "secColor":  sec["secColor"],
            "p":         price["price"],
            "pc":        price["priceChange"],
            "mkt":       price["marketCap"],
            "sc":        {"e": sc_e, "d": sc_d, "s": sc_s},
            "total":     sc_e + sc_d + sc_s,
            "ev":        [],      # 이벤트는 수동 등록 — /api/events/{ticker} 참고
            "bonus":     0,
            "fin":       fin,
            "cons":      cons,
            "sb":        short,
            "exp":       exp,
            "news":      news,
            "rpt":       rpt,
        }

    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"데이터 수집 오류: {e}")


@app.get("/api/sectors")
async def get_sectors():
    """
    섹터별 종목 목록 + 점수 요약.
    React 메인 화면의 SECTORS 배열 대체.
    """
    # 각 종목의 점수만 빠르게 로드 (캐시 사용 권장)
    result = {}
    for ticker, sec in SECTOR_MAP.items():
        sid = sec["secId"]
        result.setdefault(sid, {
            "id":     sid,
            "name":   sec["secName"],
            "color":  sec["secColor"],
            "tickers": [],
        })
        result[sid]["tickers"].append(ticker)

    return list(result.values())


@app.get("/api/short/{ticker}")
async def get_short(ticker: str):
    """대차잔고만 별도 조회"""
    data = await krx.get_short_balance(ticker)
    return data


@app.get("/api/export/{ticker}")
async def get_export(ticker: str):
    """수출입 데이터만 별도 조회"""
    hs   = HS_MAP.get(ticker, [])
    data = await kit.get_export_monthly(hs) if hs else []
    return data


@app.get("/api/news/{ticker}")
async def get_news(ticker: str):
    """뉴스만 별도 조회"""
    return await crawl_news(ticker)


# ── 이벤트 관리 (수동 등록 / CRUD) ────────────────────────────────
import json as _json
EVENTS_FILE = Path("data/events.json")   # { "000660": [{ "txt": "...", "pts": 5, "exp": "2026-07-31" }] }

@app.get("/api/events/{ticker}")
async def get_events(ticker: str):
    if not EVENTS_FILE.exists():
        return []
    data = _json.loads(EVENTS_FILE.read_text())
    today = date.today().isoformat()
    return [e for e in data.get(ticker, []) if e.get("exp", "9999") >= today]

@app.post("/api/events/{ticker}")
async def add_event(ticker: str, txt: str, pts: int = 5, days: int = 45):
    data = _json.loads(EVENTS_FILE.read_text()) if EVENTS_FILE.exists() else {}
    exp  = (date.today() + timedelta(days=days)).isoformat()
    data.setdefault(ticker, []).append({"txt": txt, "pts": pts, "exp": exp})
    EVENTS_FILE.write_text(_json.dumps(data, ensure_ascii=False, indent=2))
    return {"ok": True, "exp": exp}


# ─────────────────────────────────────────────────────────────────────
# 9. 스코어 이력 적재 (cron으로 하루 1회 실행 권장)
# ─────────────────────────────────────────────────────────────────────

async def snapshot_scores():
    """
    매일 장 마감 후 호출하여 점수 이력을 Parquet에 저장.
    crontab 예시: 0 16 * * 1-5 python -c "import asyncio; from backend import snapshot_scores; asyncio.run(snapshot_scores())"
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    records = []
    today = date.today().isoformat()
    for ticker in SECTOR_MAP:
        try:
            fin   = dg.parse_financials(ticker)
            cons  = dg.parse_consensus(ticker)
            short = await krx.get_short_balance(ticker)
            hs    = HS_MAP.get(ticker, [])
            exp   = await kit.get_export_monthly(hs) if hs else []
            records.append({
                "date":    today,
                "ticker":  ticker,
                "sc_e":    calc_earnings_score(fin, cons),
                "sc_d":    calc_data_score(exp),
                "sc_s":    calc_supply_score(short),
            })
        except Exception as e:
            print(f"[WARN] {ticker} 스냅샷 실패: {e}")

    path = CACHE_DIR / "score_history.parquet"
    new_df = pd.DataFrame(records)

    if path.exists():
        old_df = pd.read_parquet(path)
        combined = pd.concat([old_df, new_df]).drop_duplicates(["date", "ticker"])
    else:
        combined = new_df

    combined.to_parquet(path, index=False)
    print(f"[INFO] 점수 스냅샷 완료 ({len(records)}개 종목)")


@app.get("/api/score-history/{ticker}")
async def get_score_history(ticker: str):
    """
    점수 1년 추이 — snapshot_scores()로 쌓인 Parquet 조회.
    반환: [{ "m": "25.07", "score": 68 }, ...]
    """
    path = CACHE_DIR / "score_history.parquet"
    if not path.exists():
        return []

    df = pd.read_parquet(path, filters=[("ticker", "=", ticker)])
    df["date"] = pd.to_datetime(df["date"])
    df["m"] = df["date"].dt.strftime("%y.%m")
    df["score"] = df["sc_e"] + df["sc_d"] + df["sc_s"]

    one_year_ago = (date.today() - timedelta(days=365)).isoformat()
    df = df[df["date"] >= one_year_ago]

    return df[["m", "score"]].to_dict(orient="records")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend:app", host="0.0.0.0", port=8000, reload=True)
