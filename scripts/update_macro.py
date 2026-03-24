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

        events.append({
            "date": day_label,
            "event": f"{prefix} {name}" if prefix else name,
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
