"""
대시보드 홈 페이지 — 매크로 대시보드 + 분석 도구
"""

import os
import json
import streamlit as st
import pandas as pd

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from style import COLORS, PLOTLY_LAYOUT, styled_plotly
import plotly.graph_objects as go

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ──────────────────────────────────────────────
# 매크로 지표 로드
# ──────────────────────────────────────────────
MACRO_TICKERS = {
    "S&P 500": {"ticker": "^GSPC", "fmt": ",.0f", "unit": ""},
    "NASDAQ": {"ticker": "^IXIC", "fmt": ",.0f", "unit": ""},
    "Dow Jones": {"ticker": "^DJI", "fmt": ",.0f", "unit": ""},
    "US 10Y 금리": {"ticker": "^TNX", "fmt": ".2f", "unit": "%"},
    "USD/KRW": {"ticker": "KRW=X", "fmt": ",.0f", "unit": "원"},
    "WTI 유가": {"ticker": "CL=F", "fmt": ".1f", "unit": "$"},
    "브렌트유": {"ticker": "BZ=F", "fmt": ".1f", "unit": "$"},
    "천연가스": {"ticker": "NG=F", "fmt": ".2f", "unit": "$"},
    "금": {"ticker": "GC=F", "fmt": ",.0f", "unit": "$"},
    "달러 인덱스": {"ticker": "DX-Y.NYB", "fmt": ".1f", "unit": ""},
}


@st.cache_data(ttl=900, show_spinner=False)
def load_macro_data():
    """yfinance에서 매크로 지표 조회 (15분 캐시)"""
    if not HAS_YF:
        return {}

    results = {}
    for name, info in MACRO_TICKERS.items():
        try:
            t = yf.Ticker(info["ticker"])
            hist = t.history(period="5d")
            if hist.empty:
                continue
            last = hist["Close"].iloc[-1]
            prev = hist["Close"].iloc[-2] if len(hist) > 1 else last
            chg = (last - prev) / prev * 100 if prev != 0 else 0
            results[name] = {
                "value": last,
                "change": chg,
                "fmt": info["fmt"],
                "unit": info["unit"],
            }
        except Exception:
            pass
    return results


SECTOR_ETFS = {
    "Technology": {"etf": "XLK", "top": ["AAPL", "MSFT", "NVDA", "AVGO", "AMD"]},
    "Healthcare": {"etf": "XLV", "top": ["UNH", "LLY", "JNJ"]},
    "Financials": {"etf": "XLF", "top": ["BRK-B", "JPM", "V"]},
    "Consumer Disc.": {"etf": "XLY", "top": ["AMZN", "TSLA", "HD"]},
    "Communication": {"etf": "XLC", "top": ["META", "GOOGL", "NFLX"]},
    "Industrials": {"etf": "XLI", "top": ["GE", "CAT", "RTX"]},
    "Consumer Staples": {"etf": "XLP", "top": ["PG", "KO", "PEP"]},
    "Energy": {"etf": "XLE", "top": ["XOM", "CVX", "COP"]},
    "Utilities": {"etf": "XLU", "top": ["NEE", "DUK", "SO"]},
    "Real Estate": {"etf": "XLRE", "top": ["PLD", "AMT", "EQIX"]},
    "Materials": {"etf": "XLB", "top": ["LIN", "APD", "SHW"]},
}

# 항상 포함할 섹터
ALWAYS_SHOW = ["Technology"]
# 특징적 섹터 기준 (절대 수익률 기준)
NOTABLE_THRESHOLD = 1.0


@st.cache_data(ttl=900, show_spinner=False)
def load_us_sector_data():
    """미국 섹터별 일간 수익률 + 특징적 섹터 뉴스 분석"""
    if not HAS_YF:
        return None

    all_sectors = []
    for sector, info in SECTOR_ETFS.items():
        try:
            t = yf.Ticker(info["etf"])
            h = t.history(period="5d")
            if len(h) < 2:
                continue
            ret = (h["Close"].iloc[-1] / h["Close"].iloc[-2] - 1) * 100

            # 대표 종목 수익률
            top_results = []
            for s in info["top"]:
                try:
                    st_h = yf.Ticker(s).history(period="5d")
                    if len(st_h) >= 2:
                        s_ret = (st_h["Close"].iloc[-1] / st_h["Close"].iloc[-2] - 1) * 100
                        top_results.append({"ticker": s, "return": round(s_ret, 2)})
                except Exception:
                    pass

            all_sectors.append({
                "sector": sector,
                "etf": info["etf"],
                "return": round(ret, 2),
                "top_stocks": top_results,
                "news": [],
            })
        except Exception:
            pass

    all_sectors.sort(key=lambda x: x["return"], reverse=True)

    # 특징적 섹터 선별: 항상 포함 + 상위/하위 급등락
    notable = set(ALWAYS_SHOW)
    for s in all_sectors:
        if abs(s["return"]) >= NOTABLE_THRESHOLD:
            notable.add(s["sector"])
    # 최소 상위 2 + 하위 2 포함
    if len(all_sectors) >= 4:
        notable.add(all_sectors[0]["sector"])
        notable.add(all_sectors[1]["sector"])
        notable.add(all_sectors[-1]["sector"])
        notable.add(all_sectors[-2]["sector"])

    # 특징적 섹터에만 뉴스 가져오기 (API 호출 최소화)
    for s in all_sectors:
        if s["sector"] in notable:
            try:
                t = yf.Ticker(s["etf"])
                raw_news = t.news or []
                for n in raw_news[:3]:
                    content = n.get("content", {})
                    if isinstance(content, dict):
                        title = content.get("title", "")
                        if title:
                            s["news"].append(title)
            except Exception:
                pass

    return {"all": all_sectors, "notable": notable}


def _translate_event_inline(name):
    """영문 이벤트명 → 한글 번역 (인라인 갱신용)"""
    import re
    _MAP = {
        "Nonfarm Payrolls": "비농업 고용", "ADP Nonfarm Employment": "ADP 민간고용",
        "ADP Employment Change Weekly": "ADP 주간고용변동", "Unemployment Rate": "실업률",
        "Initial Jobless Claims": "신규 실업수당 청구건수", "Continuing Jobless Claims": "계속 실업수당 청구건수",
        "JOLTS Job Openings": "JOLTS 구인건수", "CPI": "소비자물가지수(CPI)",
        "Core CPI": "근원 소비자물가지수", "PPI": "생산자물가지수(PPI)", "Core PPI": "근원 생산자물가지수",
        "Core PCE Price Index": "근원 PCE 물가지수", "PCE Price Index": "PCE 물가지수",
        "PCE Price index": "PCE 물가지수", "PCE price index": "PCE 물가지수",
        "Core PCE Prices": "근원 PCE 물가", "Michigan Consumer Sentiment": "미시간 소비자심리지수",
        "GDP": "GDP", "GDP Price Index": "GDP 물가지수", "Industrial Production": "산업생산",
        "Capacity Utilization Rate": "설비가동률", "ISM Manufacturing PMI": "ISM 제조업 PMI",
        "ISM Services PMI": "ISM 서비스업 PMI", "ISM Manufacturing Prices": "ISM 제조업 가격지수",
        "ISM Manufacturing Employment": "ISM 제조업 고용지수", "ISM Non-Manufacturing PMI": "ISM 비제조업 PMI",
        "ISM Non-Manufacturing Employment": "ISM 비제조업 고용지수",
        "ISM Non-Manufacturing Prices": "ISM 비제조업 가격지수",
        "S&P Global Manufacturing PMI": "S&P 제조업 PMI", "S&P Global Services PMI": "S&P 서비스업 PMI",
        "S&P Global Composite PMI": "S&P 종합 PMI", "Chicago PMI": "시카고 PMI",
        "Retail Sales": "소매판매", "Core Retail Sales": "근원 소매판매",
        "Personal Income": "개인소득", "Personal Spending": "개인소비지출",
        "Consumer Confidence": "소비자 신뢰지수(CB)", "CB Consumer Confidence": "소비자 신뢰지수(CB)",
        "New Home Sales": "신규주택판매", "Existing Home Sales": "기존주택판매",
        "Building Permits": "건축허가건수", "Housing Starts": "주택착공건수",
        "S&P/CS Composite-20 HPI": "S&P/CS 주택가격지수", "Pending Home Sales": "잠정주택판매",
        "Trade Balance": "무역수지", "Durable Goods Orders": "내구재 주문",
        "Core Durable Goods Orders": "근원 내구재 주문", "Factory Orders": "공장주문",
        "Construction Spending": "건설지출", "Fed Interest Rate Decision": "FOMC 금리결정",
        "FOMC Statement": "FOMC 성명서", "FOMC Minutes": "FOMC 의사록",
        "FOMC Meeting Minutes": "FOMC 의사록", "FOMC Press Conference": "FOMC 기자회견",
        "Fed Chair Powell Speaks": "파월 의장 발언",
        "U.S. President Trump Speaks": "트럼프 대통령 발언",
        "Atlanta Fed GDPNow": "애틀랜타 연은 GDPNow",
        "Crude Oil Inventories": "원유 재고", "Cushing Crude Oil Inventories": "쿠싱 원유 재고",
        "API Weekly Crude Oil Stock": "API 주간 원유 재고",
        "EIA Short-Term Energy Outlook": "EIA 단기 에너지 전망",
        "OPEC Monthly Report": "OPEC 월간 보고서", "IEA Monthly Report": "IEA 월간 보고서",
        "WASDE Report": "WASDE 보고서",
        "NY Empire State Manufacturing Index": "NY 엠파이어 제조업지수",
        "Philadelphia Fed Manufacturing Index": "필라델피아 연은 제조업지수",
        "Philly Fed Employment": "필라델피아 연은 고용지수",
        "Export Price Index": "수출물가지수", "Import Price Index": "수입물가지수",
        "Retail Control": "소매 통제그룹", "Business Inventories": "기업 재고",
        "Retail Inventories Ex Auto": "소매 재고(자동차 제외)",
        "3-Year Note Auction": "3년물 국채 입찰", "10-Year Note Auction": "10년물 국채 입찰",
        "30-Year Bond Auction": "30년물 국채 입찰", "Consumer Credit": "소비자 신용",
        "Beige Book": "베이지북", "TIC Net Long-Term Transactions": "TIC 장기 자본 순유입",
        "Michigan 1-Year Inflation Expectations": "미시간 1년 기대인플레이션",
        "Michigan 5-Year Inflation Expectations": "미시간 5년 기대인플레이션",
        "Michigan Consumer Expectations": "미시간 소비자기대지수",
        "NY Fed 1-Year Consumer Inflation Expectations": "NY 연은 1년 기대인플레이션",
        "Fed's Balance Sheet": "연준 대차대조표",
    }
    # FOMC Member / Fed 발언 패턴
    fomc_match = re.match(r'FOMC Member (\w+) Speaks', name)
    if fomc_match:
        return f"FOMC 위원 {fomc_match.group(1)} 발언"
    fed_match = re.match(r'Fed (\w+) Speaks', name)
    if fed_match:
        return f"연준 {fed_match.group(1)} 발언"

    clean = name.strip()
    for eng, kor in _MAP.items():
        if eng in clean:
            periods = re.findall(r'\(([^)]+)\)', clean)
            period_str = " ".join(f"({p})" for p in periods) if periods else ""
            result = kor
            if period_str:
                result = f"{kor} {period_str}"
            if "Final" in clean:
                result += " 확정치"
            elif "Preliminary" in clean or "Flash" in clean:
                result += " 잠정치"
            return result.strip()
    return clean


def _try_refresh_macro_calendar(path):
    """매크로 일정이 오래되었으면 investing.com에서 실시간 갱신 시도"""
    from datetime import datetime, timedelta
    import requests
    from bs4 import BeautifulSoup

    try:
        with open(path, "r", encoding="utf-8") as f:
            old = json.load(f)
        updated = datetime.strptime(old.get("updated", "2000-01-01"), "%Y-%m-%d")
        now = datetime.now()
        # 같은 주(월~일)에 갱신된 데이터면 유지, 주가 바뀌면 갱신
        updated_monday = updated - timedelta(days=updated.weekday())
        current_monday = now - timedelta(days=now.weekday())
        if updated_monday.date() == current_monday.date() and (now - updated).days < 1:
            return old  # 같은 주 + 당일이면 갱신 불필요
    except Exception:
        old = {}

    # investing.com에서 갱신 시도
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/119.0",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.investing.com/economic-calendar/",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    weekday_kr = ["월", "화", "수", "목", "금", "토", "일"]
    today = datetime.now()

    def fetch_week(offset):
        monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
        friday = monday + timedelta(days=4)
        payload = {
            "country[]": ["5"],
            "importance[]": ["2", "3"],
            "dateFrom": monday.strftime("%Y-%m-%d"),
            "dateTo": friday.strftime("%Y-%m-%d"),
            "timeZone": "88",
            "timeFilter": "timeRemain",
            "currentTab": "custom",
            "limit_from": "0",
        }
        try:
            r = requests.post(
                "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData",
                data=payload, headers=headers, timeout=20,
            )
            html = r.json().get("data", "")
        except Exception:
            return monday, friday, []

        soup = BeautifulSoup(html, "html.parser")
        events = []
        for row in soup.select("tr"):
            event_a = row.select_one("td.event a")
            if not event_a:
                continue
            name = event_a.text.strip()
            bulls = row.select("td.sentiment i.grayFullBullishIcon")
            dt_str = row.get("data-event-datetime", "")
            country_span = row.select_one("td.flagCur span")
            country = country_span.get("title", "") if country_span else ""
            forecast, previous = "", ""
            for td in row.select("td"):
                cls = td.get("class", [])
                if "fore" in cls:
                    forecast = td.text.strip()
                if "prev" in cls:
                    previous = td.text.strip()
            try:
                event_dt = datetime.strptime(dt_str, "%Y/%m/%d %H:%M:%S")
            except (ValueError, TypeError):
                continue
            if "United States" not in country:
                continue  # 미국만
            day_label = f"{event_dt.month}/{event_dt.day} ({weekday_kr[event_dt.weekday()]})"
            translated = _translate_event_inline(name)
            events.append({
                "date": day_label,
                "event": f"美 {translated}",
                "importance": "high" if len(bulls) >= 3 else "medium",
                "consensus": forecast if forecast and forecast != "\xa0" else "-",
                "previous": previous if previous and previous != "\xa0" else "-",
                "sort_key": event_dt.strftime("%Y%m%d%H%M"),
            })
        events.sort(key=lambda e: e["sort_key"])
        for e in events:
            del e["sort_key"]
        seen = set()
        unique = []
        for e in events:
            key = (e["date"], e["event"])
            if key not in seen:
                seen.add(key)
                unique.append(e)
        return monday, friday, unique

    this_mon, this_fri, this_events = fetch_week(0)
    import time
    time.sleep(2)
    next_mon, next_fri, next_events = fetch_week(1)

    if not this_events and not next_events:
        return old  # API 실패 시 기존 데이터 유지

    def week_label(m, f):
        return f"{m.month}월 {(m.day - 1) // 7 + 1}주차 ({m.month}/{m.day} ~ {f.month}/{f.day})"

    calendar = {
        "updated": today.strftime("%Y-%m-%d"),
        "this_week": {
            "label": week_label(this_mon, this_fri),
            "events": this_events if this_events else old.get("this_week", {}).get("events", []),
        },
        "next_week": {
            "label": week_label(next_mon, next_fri),
            "events": next_events if next_events else old.get("next_week", {}).get("events", []),
        },
    }

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(calendar, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return calendar


def load_macro_calendar():
    """매크로 일정 JSON 로드 (3일 이상 오래되면 자동 갱신 시도)"""
    path = os.path.join(PROJECT_ROOT, "data", "macro_calendar.json")
    try:
        return _try_refresh_macro_calendar(path)
    except Exception:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None


def section_header(text):
    st.markdown(
        f'<div class="section-header">{text}</div>',
        unsafe_allow_html=True,
    )
    st.markdown("")


# ──────────────────────────────────────────────
# 히어로 헤더
# ──────────────────────────────────────────────
st.markdown(
    f'<div style="margin-bottom:32px; padding:20px 0;">'
    f'<h1 style="color:#FFFFFF; font-size:2.2rem; font-weight:800; margin:0; line-height:1.2;">'
    f'ARK IMPACT 분석 대시보드</h1>'
    f'<p style="color:{COLORS["accent"]}; font-size:1rem; font-weight:500;'
    f'letter-spacing:0.02em; margin:4px 0 0 0;">'
    f'금융 데이터 분석 · 지수 예측 · 투자 인사이트</p>'
    f'</div>',
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────
# 1. 매크로 지표
# ──────────────────────────────────────────────
section_header("주요 매크로 지표")

macro = load_macro_data()

if macro:
    TC = COLORS["text"]
    TM = COLORS["text_muted"]
    AC = COLORS["accent"]
    BD = COLORS["border"]
    BG = COLORS["bg_card"]
    GR = COLORS["accent_green"]
    RD = COLORS["accent_red"]

    # 5열 그리드
    cols = st.columns(5)
    for i, (name, data) in enumerate(macro.items()):
        col = cols[i % 5]
        val = data["value"]
        chg = data["change"]
        fmt = data["fmt"]
        unit = data["unit"]
        formatted = f"{val:{fmt}}"

        chg_color = GR if chg >= 0 else RD
        chg_arrow = "▲" if chg >= 0 else "▼"

        col.markdown(
            f'<div style="background:{BG}; border:1px solid {BD}; border-radius:10px; '
            f'padding:16px; margin-bottom:12px;">'
            f'<div style="color:{TM}; font-size:0.78rem; font-weight:500; margin-bottom:6px;">{name}</div>'
            f'<div style="color:{TC}; font-size:1.35rem; font-weight:700;">{formatted}<span style="font-size:0.75rem; color:{TM};"> {unit}</span></div>'
            f'<div style="color:{chg_color}; font-size:0.82rem; font-weight:600;">{chg_arrow} {chg:+.2f}%</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    from style import now_kst
    st.markdown(
        f'<div style="color:{COLORS["text_muted"]}; font-size:0.78rem; margin-top:8px;">'
        f'15분 간격 자동 갱신 · 최근 업데이트: {now_kst()} (KST) · Source: Yahoo Finance'
        f'</div>',
        unsafe_allow_html=True,
    )
else:
    st.info("매크로 지표를 불러오는 중... yfinance 설치가 필요합니다.")

st.markdown("")

# ──────────────────────────────────────────────
# 2. 금주 / 차주 주요 일정
# ──────────────────────────────────────────────
calendar = load_macro_calendar()

if calendar:
    TC = COLORS["text"]
    TM = COLORS["text_muted"]
    AC = COLORS["accent"]
    BD = COLORS["border"]
    BG = COLORS["bg_card"]

    importance_colors = {
        "high": COLORS["accent_red"],
        "medium": COLORS["accent_yellow"],
        "low": TM,
    }
    importance_labels = {
        "high": "●",
        "medium": "●",
        "low": "●",
    }

    def render_calendar_card(title, week_data):
        # 테이블 헤더
        events_html = (
            f'<div style="display:flex; padding:8px 0; border-bottom:2px solid {BD}; margin-bottom:4px;">'
            f'<span style="color:{AC}; flex:1; font-size:0.75rem; font-weight:600;">이벤트</span>'
            f'<span style="color:{AC}; min-width:70px; font-size:0.75rem; font-weight:600; text-align:right;">컨센서스</span>'
            f'<span style="color:{AC}; min-width:70px; font-size:0.75rem; font-weight:600; text-align:right;">이전</span>'
            f'</div>'
        )

        prev_date = None
        for ev in week_data.get("events", []):
            imp = ev.get("importance", "low")
            dot_color = importance_colors.get(imp, TM)
            cons = ev.get("consensus", "-")
            prev_val = ev.get("previous", "-")
            if not cons:
                cons = "-"
            if not prev_val:
                prev_val = "-"

            # 요일 구분 헤더
            cur_date = ev["date"]
            if cur_date != prev_date:
                events_html += (
                    f'<div style="display:flex; align-items:center; margin-top:{12 if prev_date else 4}px; '
                    f'margin-bottom:4px; padding:6px 10px; '
                    f'background:rgba(0,210,255,0.08); border-radius:6px;">'
                    f'<span style="color:{AC}; font-size:0.82rem; font-weight:700;">{cur_date}</span>'
                    f'</div>'
                )
                prev_date = cur_date

            events_html += (
                f'<div style="display:flex; align-items:center; padding:6px 0; padding-left:10px; '
                f'border-bottom:1px solid rgba(45,55,72,0.5);">'
                f'<span style="color:{dot_color}; margin-right:6px; font-size:0.55rem;">●</span>'
                f'<span style="color:#FFFFFF; flex:1; font-size:0.84rem; font-weight:{"600" if imp == "high" else "400"};">{ev["event"]}</span>'
                f'<span style="color:#FFFFFF; min-width:70px; font-size:0.82rem; text-align:right; font-weight:500;">{cons}</span>'
                f'<span style="color:{TM}; min-width:70px; font-size:0.82rem; text-align:right;">{prev_val}</span>'
                f'</div>'
            )

        st.markdown(
            f'<div style="background:{BG}; border:1px solid {BD}; border-radius:12px; '
            f'padding:24px; height:100%;">'
            f'<div style="color:{AC}; font-size:1rem; font-weight:700; margin-bottom:4px;">{title}</div>'
            f'<div style="color:{TM}; font-size:0.8rem; margin-bottom:16px;">{week_data.get("label", "")}</div>'
            f'{events_html}'
            f'<div style="margin-top:14px; display:flex; gap:16px; font-size:0.75rem; color:#FFFFFF;">'
            f'<span><span style="color:{importance_colors["high"]};">●</span> 중요</span>'
            f'<span><span style="color:{importance_colors["medium"]};">●</span> 보통</span>'
            f'<span><span style="color:{importance_colors["low"]};">●</span> 참고</span>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    col_this, col_next = st.columns(2)
    with col_this:
        section_header("금주 주요 매크로 일정")
        render_calendar_card("This Week", calendar.get("this_week", {}))
    with col_next:
        section_header("차주 주요 매크로 일정")
        render_calendar_card("Next Week", calendar.get("next_week", {}))

    st.markdown(
        f'<div style="color:{COLORS["text_muted"]}; font-size:0.78rem; margin-top:12px;">'
        f'매일 오전 07:00 자동 업데이트 · 최종 갱신: {calendar.get("updated", "-")}'
        f' · Source: investing.com Economic Calendar'
        f'</div>',
        unsafe_allow_html=True,
    )

st.markdown("")

# ──────────────────────────────────────────────
# 3. 전일 미국 특징 섹터
# ──────────────────────────────────────────────
section_header("전일 미국 특징 섹터")

us_data = load_us_sector_data()

if us_data:
    all_sectors = us_data["all"]
    notable = us_data["notable"]
    TC = COLORS["text"]
    TM = COLORS["text_muted"]
    AC = COLORS["accent"]
    BD = COLORS["border"]
    BG = COLORS["bg_card"]
    GR = COLORS["accent_green"]
    RD = COLORS["accent_red"]

    # 특징적 섹터만 카드로 표시 (Tech 항상 포함)
    notable_sectors = [s for s in all_sectors if s["sector"] in notable]

    for s in notable_sectors:
        color = GR if s["return"] >= 0 else RD
        arrow = "▲" if s["return"] >= 0 else "▼"

        # 대표 종목 HTML
        stocks_html = ""
        for ts in s["top_stocks"]:
            ts_color = GR if ts["return"] >= 0 else RD
            stocks_html += (
                f'<span style="display:inline-block; margin-right:14px; margin-top:4px;">'
                f'<span style="color:#FFFFFF; font-weight:500;">{ts["ticker"]}</span> '
                f'<span style="color:{ts_color}; font-weight:600;">{ts["return"]:+.2f}%</span>'
                f'</span>'
            )

        # 뉴스 HTML
        news_html = ""
        if s["news"]:
            for title in s["news"][:2]:
                news_html += (
                    f'<div style="color:{TM}; font-size:0.8rem; margin-top:4px; '
                    f'line-height:1.5; padding-left:8px; border-left:2px solid {BD};">'
                    f'{title[:100]}</div>'
                )

        is_tech = s["sector"] == "Technology"
        border_color = AC if is_tech else (color if abs(s["return"]) >= NOTABLE_THRESHOLD else BD)
        border_style = f"border:2px solid {AC};" if is_tech else f"border:1px solid {border_color}; border-left:4px solid {border_color};"
        radius = "12px" if is_tech else "0 12px 12px 0"
        icon = "⚡ " if is_tech else ""
        news_block = f'<div style="margin-top:10px;">{news_html}</div>' if news_html else ""

        card_html = (
            f'<div style="background:{BG}; {border_style} border-radius:{radius}; '
            f'padding:18px 22px; margin-bottom:12px;">'
            f'<div style="display:flex; justify-content:space-between; align-items:center;">'
            f'<div style="color:#FFFFFF; font-size:1.05rem; font-weight:700;">'
            f'{icon}{s["sector"]}'
            f'<span style="color:{TM}; font-size:0.82rem; font-weight:400; margin-left:8px;">{s["etf"]}</span>'
            f'</div>'
            f'<div style="color:{color}; font-size:1.3rem; font-weight:800;">'
            f'{arrow} {s["return"]:+.2f}%</div>'
            f'</div>'
            f'<div style="margin-top:8px;">{stocks_html}</div>'
            f'{news_block}'
            f'</div>'
        )
        st.markdown(card_html, unsafe_allow_html=True)

    # 나머지 섹터 요약 (한 줄씩)
    rest = [s for s in all_sectors if s["sector"] not in notable]
    if rest:
        rest_html = ""
        for s in rest:
            color = GR if s["return"] >= 0 else RD
            rest_html += (
                f'<span style="display:inline-block; margin-right:20px; margin-bottom:6px;">'
                f'<span style="color:{TM}; font-size:0.85rem;">{s["sector"]}</span> '
                f'<span style="color:{color}; font-size:0.85rem; font-weight:600;">'
                f'{s["return"]:+.2f}%</span></span>'
            )
        st.markdown(
            f'<div style="background:{BG}; border:1px solid {BD}; border-radius:10px; '
            f'padding:14px 18px; margin-top:4px;">'
            f'<div style="color:{TM}; font-size:0.78rem; margin-bottom:6px;">기타 섹터</div>'
            f'{rest_html}</div>',
            unsafe_allow_html=True,
        )

    from style import now_kst
    st.markdown(
        f'<div style="color:{COLORS["text_muted"]}; font-size:0.78rem; margin-top:10px;">'
        f'전일 종가 기준 · 최근 업데이트: {now_kst()} (KST) · Source: Yahoo Finance</div>',
        unsafe_allow_html=True,
    )

st.markdown("")

# ──────────────────────────────────────────────
# 4. 분석 도구 카드
# ──────────────────────────────────────────────
section_header("분석 도구")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown(
        '<div class="ark-card">'
        '<div class="card-icon">📊</div>'
        "<h3>코스닥 150 분석</h3>"
        "<p>KRX 방법론 기반으로 코스닥 150 지수의 편입/편출 종목을 예측합니다.</p>"
        "<ul>"
        "<li>편입/편출 예상 종목</li>"
        "<li>섹터별 심층 분석</li>"
        "<li>편입/편출 원인 진단</li>"
        "<li>KRX 방법론 가이드</li>"
        "</ul></div>",
        unsafe_allow_html=True,
    )

with col2:
    st.markdown(
        '<div class="ark-card">'
        '<div class="card-icon">🛬</div>'
        "<h3>인바운드 데이터 분석</h3>"
        "<p>인바운드 관광 및 카지노 산업 데이터를 모니터링합니다.</p>"
        "<ul>"
        "<li>입국자 추이 (전체/일본/중국)</li>"
        "<li>카지노 산업 합산/기업별</li>"
        "<li>제주 입도객 · 롯데관광</li>"
        "<li>월별 업데이트</li>"
        "</ul></div>",
        unsafe_allow_html=True,
    )

with col3:
    st.markdown(
        '<div class="ark-card" style="opacity: 0.5;">'
        '<div class="card-icon">🔍</div>'
        "<h3>종목 스크리너</h3>"
        "<p>다양한 조건으로 종목을 필터링하고 비교 분석합니다.</p>"
        "<ul>"
        "<li>재무 지표 필터</li>"
        "<li>기술적 분석</li>"
        "<li>밸류에이션 비교</li>"
        "<li><em>준비 중</em></li>"
        "</ul></div>",
        unsafe_allow_html=True,
    )

# 시스템 상태
status_path = os.path.join(PROJECT_ROOT, "data", "healthcheck_status.json")
try:
    with open(status_path, "r", encoding="utf-8") as f:
        hc_status = json.load(f)
    last_check = hc_status.get("last_check", "-")
    all_pass = hc_status.get("all_pass", False)
    status_icon = "✅" if all_pass else "⚠️"
    status_text = "정상" if all_pass else "일부 오류"
    st.markdown(
        f'<div style="color:{COLORS["text_muted"]}; font-size:0.78rem; margin-top:20px; text-align:center;">'
        f'{status_icon} 시스템 상태: {status_text} · 최근 점검: {last_check}'
        f'</div>',
        unsafe_allow_html=True,
    )
except Exception:
    pass

# 푸터
st.markdown(
    '<div class="ark-footer">'
    "ARK IMPACT 분석 대시보드 v1.1 · Powered by Streamlit & Plotly"
    "</div>",
    unsafe_allow_html=True,
)
