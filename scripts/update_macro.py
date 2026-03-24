"""
매크로 일정 자동 업데이트 스크립트
investing.com 경제 캘린더에서 별 2개 이상 이벤트 수집
GitHub Actions에서 매일 07:00 KST에 실행
"""

import json
import os
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
CALENDAR_PATH = os.path.join(PROJECT_ROOT, "data", "macro_calendar.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) "
        "Gecko/20100101 Firefox/119.0"
    ),
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.investing.com/economic-calendar/",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]

# 미국(5), 중국(37)
COUNTRY_IDS = ["5", "37"]

# 영문 → 한국어 이벤트명 매핑
EVENT_KR = {
    # 고용
    "Nonfarm Payrolls": "비농업 고용",
    "ADP Nonfarm Employment": "ADP 민간고용",
    "ADP Employment Change Weekly": "ADP 주간고용변동",
    "Unemployment Rate": "실업률",
    "Initial Jobless Claims": "신규 실업수당 청구건수",
    "Continuing Jobless Claims": "계속 실업수당 청구건수",
    "JOLTS Job Openings": "JOLTS 구인건수",
    # 물가
    "CPI": "소비자물가지수(CPI)",
    "Core CPI": "근원 소비자물가지수",
    "PPI": "생산자물가지수(PPI)",
    "Core PPI": "근원 생산자물가지수",
    "Core PCE Price Index": "근원 PCE 물가지수",
    "PCE Price index": "PCE 물가지수",
    "PCE Price Index": "PCE 물가지수",
    "Michigan Consumer Sentiment": "미시간 소비자심리지수",
    # GDP/생산
    "GDP": "GDP",
    "GDP Price Index": "GDP 물가지수",
    "Industrial Production": "산업생산",
    "Capacity Utilization Rate": "설비가동률",
    # ISM/PMI
    "ISM Manufacturing PMI": "ISM 제조업 PMI",
    "ISM Services PMI": "ISM 서비스업 PMI",
    "ISM Manufacturing Prices": "ISM 제조업 가격지수",
    "ISM Manufacturing Employment": "ISM 제조업 고용지수",
    "ISM Non-Manufacturing PMI": "ISM 비제조업 PMI",
    "S&P Global Manufacturing PMI": "S&P 제조업 PMI",
    "S&P Global Services PMI": "S&P 서비스업 PMI",
    "S&P Global Composite PMI": "S&P 종합 PMI",
    "Chicago PMI": "시카고 PMI",
    # 소비/소매
    "Retail Sales": "소매판매",
    "Core Retail Sales": "근원 소매판매",
    "Personal Income": "개인소득",
    "Personal Spending": "개인소비지출",
    "Consumer Confidence": "소비자 신뢰지수(CB)",
    "CB Consumer Confidence": "소비자 신뢰지수(CB)",
    # 주택
    "New Home Sales": "신규주택판매",
    "Existing Home Sales": "기존주택판매",
    "Building Permits": "건축허가건수",
    "Housing Starts": "주택착공건수",
    "S&P/CS Composite-20 HPI": "S&P/CS 주택가격지수",
    "Pending Home Sales": "잠정주택판매",
    # 무역/기타
    "Trade Balance": "무역수지",
    "Durable Goods Orders": "내구재 주문",
    "Core Durable Goods Orders": "근원 내구재 주문",
    "Factory Orders": "공장주문",
    "Construction Spending": "건설지출",
    # 연준
    "Fed Interest Rate Decision": "FOMC 금리결정",
    "FOMC Statement": "FOMC 성명서",
    "FOMC Minutes": "FOMC 의사록",
    "FOMC Press Conference": "FOMC 기자회견",
    "Fed Chair Powell Speaks": "파월 의장 발언",
    "U.S. President Trump Speaks": "트럼프 대통령 발언",
    "Atlanta Fed GDPNow": "애틀랜타 연은 GDPNow",
    # 중국
    "Manufacturing PMI": "제조업 PMI",
    "Non-Manufacturing PMI": "비제조업 PMI",
    "Chinese Composite PMI": "종합 PMI",
    "RatingDog Manufacturing PMI": "Caixin 제조업 PMI",
    "RatingDog Services PMI": "Caixin 서비스업 PMI",
    "Exports": "수출",
    "Imports": "수입",
    "Industrial Production": "산업생산",
    "Retail Sales": "소매판매",
}


def translate_event(name):
    """영문 이벤트명을 한국어로 번역"""
    # 정확히 매칭되는 키 찾기 (기간 정보 제거 후)
    clean = name.strip()
    for eng, kor in EVENT_KR.items():
        if eng in clean:
            # 기간 정보 유지 (예: (Mar), (Feb), (Q4))
            period = ""
            if "(" in clean:
                parts = clean.split("(")
                for p in parts[1:]:
                    period += f"({p.strip()}) " if not p.strip().endswith(")") else f"({p.strip()} "
                # 간단히: 마지막 괄호 내용만
                import re
                periods = re.findall(r'\(([^)]+)\)', clean)
                period = " ".join(f"({p})" for p in periods)
            result = kor
            if period:
                result = f"{kor} {period}"
            # Final/Preliminary 처리
            if "Final" in clean:
                result += " 확정치"
            elif "Preliminary" in clean or "Flash" in clean:
                result += " 잠정치"
            return result.strip()
    return clean


def get_week_range(ref_date, offset_weeks=0):
    monday = ref_date - timedelta(days=ref_date.weekday()) + timedelta(weeks=offset_weeks)
    friday = monday + timedelta(days=4)
    return monday, friday


def fetch_investing_calendar(date_from, date_to):
    """investing.com 경제 캘린더 AJAX API에서 이벤트 수집 (별 2개 이상)"""
    session = requests.Session()
    session.headers.update(HEADERS)

    payload = {
        "country[]": COUNTRY_IDS,
        "importance[]": ["2", "3"],
        "dateFrom": date_from.strftime("%Y-%m-%d"),
        "dateTo": date_to.strftime("%Y-%m-%d"),
        "timeZone": "88",  # KST
        "timeFilter": "timeRemain",
        "currentTab": "custom",
        "limit_from": "0",
    }

    import time

    html = ""
    for attempt in range(3):
        try:
            r = session.post(
                "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData",
                data=payload,
                timeout=20,
            )
            if r.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f"  [재시도] Rate limit, {wait}초 대기... ({attempt+1}/3)")
                time.sleep(wait)
                continue
            data = r.json()
            html = data.get("data", "")
            break
        except Exception as e:
            print(f"  [경고] investing.com 접속 실패: {e}")
            if attempt < 2:
                time.sleep(5)
            continue

    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("tr")

    events = []
    for row in rows:
        event_a = row.select_one("td.event a")
        if not event_a:
            continue

        name = event_a.text.strip()
        bulls = row.select("td.sentiment i.grayFullBullishIcon")
        stars = len(bulls)
        dt_str = row.get("data-event-datetime", "")

        # 국가 확인
        country_span = row.select_one("td.flagCur span")
        country = country_span.get("title", "") if country_span else ""

        # Forecast / Previous
        forecast = ""
        previous = ""
        for td in row.select("td"):
            cls = td.get("class", [])
            if "fore" in cls:
                forecast = td.text.strip()
            if "prev" in cls:
                previous = td.text.strip()

        # 날짜 파싱 (KST 기준)
        try:
            event_dt = datetime.strptime(dt_str, "%Y/%m/%d %H:%M:%S")
        except (ValueError, TypeError):
            continue

        # 날짜 범위 필터
        if event_dt.date() < date_from.date() or event_dt.date() > date_to.date():
            continue

        # 국가 접두사
        if "United States" in country:
            prefix = "美"
        elif "China" in country:
            prefix = "中"
        else:
            prefix = ""

        day_label = f"{event_dt.month}/{event_dt.day} ({WEEKDAY_KR[event_dt.weekday()]})"
        translated = translate_event(name)

        events.append({
            "date": day_label,
            "event": f"{prefix} {translated}" if prefix else translated,
            "importance": "high" if stars >= 3 else "medium",
            "consensus": forecast if forecast and forecast != "\xa0" else "-",
            "previous": previous if previous and previous != "\xa0" else "-",
            "sort_key": event_dt.strftime("%Y%m%d%H%M"),
        })

    # 정렬 후 sort_key 제거
    events.sort(key=lambda e: e["sort_key"])
    for e in events:
        del e["sort_key"]

    # 같은 날짜+이벤트 중복 제거
    seen = set()
    unique = []
    for e in events:
        key = (e["date"], e["event"])
        if key not in seen:
            seen.add(key)
            unique.append(e)

    return unique


def format_week_label(monday, friday):
    return (
        f"{monday.month}월 {(monday.day - 1) // 7 + 1}주차 "
        f"({monday.month}/{monday.day} ~ {friday.month}/{friday.day})"
    )


def main():
    today = datetime.now()
    print(f"[{today.strftime('%Y-%m-%d %H:%M')}] 매크로 일정 업데이트 시작")

    # 금주
    this_mon, this_fri = get_week_range(today, 0)
    this_events = fetch_investing_calendar(this_mon, this_fri)
    print(f"  금주 ({this_mon.strftime('%m/%d')}~{this_fri.strftime('%m/%d')}): {len(this_events)}건")

    import time
    time.sleep(5)

    # 차주
    next_mon, next_fri = get_week_range(today, 1)
    next_events = fetch_investing_calendar(next_mon, next_fri)
    print(f"  차주 ({next_mon.strftime('%m/%d')}~{next_fri.strftime('%m/%d')}): {len(next_events)}건")

    # 이전 데이터 로드 (API 실패 시 유지)
    old_calendar = {}
    try:
        with open(CALENDAR_PATH, "r", encoding="utf-8") as f:
            old_calendar = json.load(f)
    except Exception:
        pass

    calendar = {
        "updated": today.strftime("%Y-%m-%d"),
        "this_week": {
            "label": format_week_label(this_mon, this_fri),
            "events": this_events if this_events else old_calendar.get("this_week", {}).get("events", []),
        },
        "next_week": {
            "label": format_week_label(next_mon, next_fri),
            "events": next_events if next_events else old_calendar.get("next_week", {}).get("events", []),
        },
    }

    os.makedirs(os.path.dirname(CALENDAR_PATH), exist_ok=True)
    with open(CALENDAR_PATH, "w", encoding="utf-8") as f:
        json.dump(calendar, f, ensure_ascii=False, indent=2)

    print(f"  저장 완료: {CALENDAR_PATH}")
    return calendar


if __name__ == "__main__":
    result = main()
    print(json.dumps(result, ensure_ascii=False, indent=2))
