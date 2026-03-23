"""
매크로 일정 자동 업데이트 스크립트
GitHub Actions에서 매일 07:00 KST에 실행됩니다.

데이터 소스: investing.com 경제 캘린더
"""

import json
import os
import re
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
CALENDAR_PATH = os.path.join(PROJECT_ROOT, "data", "macro_calendar.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    ),
}

# ── 고정 일정 패턴 (매월/매주 반복되는 주요 지표) ──
KNOWN_RECURRING = {
    # 매월 1주차
    "美 비농업 고용지표": {"week": 1, "weekday": 4, "importance": "high"},
    "美 실업률": {"week": 1, "weekday": 4, "importance": "high"},
    "美 ISM 서비스업 PMI": {"week": 1, "weekday": 3, "importance": "high"},
    "美 JOLTS 구인건수": {"week": 1, "weekday": 1, "importance": "medium"},
    # 매월 2주차
    "美 CPI 소비자물가지수": {"week": 2, "weekday": 2, "importance": "high"},
    "美 PPI 생산자물가지수": {"week": 2, "weekday": 3, "importance": "high"},
    # 매월 3주차
    "美 소매판매": {"week": 3, "weekday": 1, "importance": "high"},
    "美 산업생산": {"week": 3, "weekday": 2, "importance": "medium"},
    # 매월 4주차
    "美 GDP (잠정/확정치)": {"week": 4, "weekday": 3, "importance": "high"},
    "美 PCE 물가지수": {"week": 4, "weekday": 4, "importance": "high"},
    "美 개인소득/소비지출": {"week": 4, "weekday": 4, "importance": "high"},
    "美 소비자 신뢰지수 (CB)": {"week": 4, "weekday": 1, "importance": "high"},
    "美 신규주택판매": {"week": 4, "weekday": 2, "importance": "medium"},
    # 매주 반복
    "美 신규 실업수당 청구건수": {"weekday": 3, "importance": "medium"},
    # 월말/월초
    "中 제조업 PMI": {"day": -1, "importance": "high"},
    "美 ISM 제조업 PMI": {"day": 1, "importance": "high"},
    "美 ADP 민간고용": {"week": 1, "weekday": 2, "importance": "high"},
}

# ── FOMC 2026 일정 ──
FOMC_2026 = [
    "2026-01-28", "2026-03-18", "2026-05-06",
    "2026-06-17", "2026-07-29", "2026-09-16",
    "2026-11-04", "2026-12-16",
]

WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]


def get_week_range(ref_date, offset_weeks=0):
    """ref_date 기준 offset_weeks 후 주의 월~금 범위"""
    monday = ref_date - timedelta(days=ref_date.weekday()) + timedelta(weeks=offset_weeks)
    friday = monday + timedelta(days=4)
    return monday, friday


def fetch_investing_calendar(start_date, end_date):
    """investing.com 경제 캘린더에서 주요 이벤트 스크래핑 시도"""
    events = []
    try:
        url = "https://www.investing.com/economic-calendar/"
        session = requests.Session()
        session.headers.update(HEADERS)
        r = session.get(url, timeout=15)
        if r.status_code != 200:
            return events

        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.select("tr.js-event-item")

        for row in rows:
            try:
                date_td = row.select_one("td.date")
                event_td = row.select_one("td.event a")
                bull_spans = row.select("td.sentiment i.grayFullBullishIcon")

                if not event_td:
                    continue

                event_name = event_td.text.strip()
                importance = "high" if len(bull_spans) >= 3 else (
                    "medium" if len(bull_spans) >= 2 else "low"
                )

                events.append({
                    "event": event_name,
                    "importance": importance,
                })
            except Exception:
                continue
    except Exception:
        pass

    return events


def generate_calendar_for_week(monday, friday):
    """특정 주간의 매크로 일정 생성"""
    events = []
    today = monday

    # FOMC 체크
    while today <= friday:
        date_str = today.strftime("%Y-%m-%d")
        day_label = f"{today.month}/{today.day} ({WEEKDAY_KR[today.weekday()]})"

        if date_str in FOMC_2026:
            events.append({
                "date": day_label,
                "event": "美 FOMC 금리결정",
                "importance": "high",
            })

        today += timedelta(days=1)

    # 고정 패턴 일정
    month_start = monday.replace(day=1)
    for event_name, pattern in KNOWN_RECURRING.items():
        target_date = None

        if "week" in pattern and "weekday" in pattern:
            # N번째 주 X요일
            first_day = month_start
            first_weekday = first_day.weekday()
            target_weekday = pattern["weekday"]
            days_ahead = (target_weekday - first_weekday) % 7
            first_occurrence = first_day + timedelta(days=days_ahead)
            target_date = first_occurrence + timedelta(weeks=pattern["week"] - 1)

        elif "day" in pattern:
            # 월말(-1) 또는 월초(1)
            if pattern["day"] == -1:
                next_month = (month_start.month % 12) + 1
                year = month_start.year + (1 if next_month == 1 else 0)
                last_day = datetime(year, next_month, 1) - timedelta(days=1)
                # 영업일 조정
                while last_day.weekday() >= 5:
                    last_day -= timedelta(days=1)
                target_date = last_day
            elif pattern["day"] == 1:
                next_month = (monday.month % 12) + 1
                year = monday.year + (1 if next_month == 1 else 0)
                target_date = datetime(year, next_month, 1)
                while target_date.weekday() >= 5:
                    target_date += timedelta(days=1)

        elif "weekday" in pattern:
            # 매주 X요일
            d = monday
            while d <= friday:
                if d.weekday() == pattern["weekday"]:
                    target_date = d
                    break
                d += timedelta(days=1)

        if target_date and monday <= target_date <= friday:
            day_label = f"{target_date.month}/{target_date.day} ({WEEKDAY_KR[target_date.weekday()]})"
            # 중복 체크
            if not any(e["event"] == event_name for e in events):
                events.append({
                    "date": day_label,
                    "event": event_name,
                    "importance": pattern.get("importance", "medium"),
                })

    # 날짜순 정렬
    events.sort(key=lambda e: e["date"])
    return events


def format_week_label(monday, friday):
    """주간 라벨 생성"""
    return (
        f"{monday.month}월 {(monday.day - 1) // 7 + 1}주차 "
        f"({monday.month}/{monday.day} ~ {friday.month}/{friday.day})"
    )


def main():
    today = datetime.now()
    print(f"[{today.strftime('%Y-%m-%d %H:%M')}] 매크로 일정 업데이트 시작")

    # 금주
    this_mon, this_fri = get_week_range(today, 0)
    this_events = generate_calendar_for_week(this_mon, this_fri)
    print(f"  금주 ({this_mon.strftime('%m/%d')}~{this_fri.strftime('%m/%d')}): {len(this_events)}건")

    # 차주
    next_mon, next_fri = get_week_range(today, 1)
    next_events = generate_calendar_for_week(next_mon, next_fri)
    print(f"  차주 ({next_mon.strftime('%m/%d')}~{next_fri.strftime('%m/%d')}): {len(next_events)}건")

    # investing.com 보충 시도
    extra = fetch_investing_calendar(this_mon, next_fri)
    if extra:
        print(f"  investing.com 추가: {len(extra)}건")

    calendar = {
        "updated": today.strftime("%Y-%m-%d"),
        "this_week": {
            "label": format_week_label(this_mon, this_fri),
            "events": this_events,
        },
        "next_week": {
            "label": format_week_label(next_mon, next_fri),
            "events": next_events,
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
