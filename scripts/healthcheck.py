"""
ARK IMPACT 대시보드 헬스체크 스크립트
GitHub Actions에서 매일 07:10 KST에 실행됩니다.

검사 항목:
1. 코스닥 종목 데이터 로드 (FDR or 캐시)
2. GICS 분류 데이터 로드 (API or 캐시)
3. 코스닥 150 구성종목 로드 (JSON)
4. 선정 엔진 실행
5. 인바운드 데이터 파일 존재
6. 매크로 캘린더 JSON 유효성
"""

import os
import sys
import json
import traceback

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def check(name, func):
    """개별 검사 실행, 결과 반환"""
    try:
        result = func()
        print(f"  [PASS] {name}: {result}")
        return True, result
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")
        traceback.print_exc()
        return False, str(e)


def check_kosdaq_data():
    from data_collector import get_kosdaq_listing
    df = get_kosdaq_listing()
    count = len(df)
    if count < 100:
        raise RuntimeError(f"코스닥 종목 {count}개 (최소 100개 필요)")
    return f"{count}종목"


def check_gics_data():
    from data_collector import get_gics_sector_map
    gics = get_gics_sector_map()
    count = len(gics)
    if count < 100:
        raise RuntimeError(f"GICS 분류 {count}개 (최소 100개 필요)")
    return f"{count}종목"


def check_kosdaq150_constituents():
    from data_collector import get_current_kosdaq150
    codes = get_current_kosdaq150()
    count = len(codes)
    if count < 140:
        raise RuntimeError(f"구성종목 {count}개 (최소 140개 필요)")
    return f"{count}종목"


def check_selection_engine():
    from data_collector import get_kosdaq_listing, get_gics_sector_map, get_current_kosdaq150
    from selection_engine import predict_changes

    kosdaq = get_kosdaq_listing()
    gics = get_gics_sector_map()
    current = get_current_kosdaq150()
    result = predict_changes(kosdaq, gics, current)

    selected = len(result.get("new_selected", []))
    additions = len(result.get("additions", []))
    removals = len(result.get("removals", []))

    if selected < 100:
        raise RuntimeError(f"선정 종목 {selected}개 (최소 100개 필요)")
    return f"선정 {selected}, 편입 {additions}, 편출 {removals}"


def check_inbound_data():
    data_dir = os.path.join(PROJECT_ROOT, "data", "inbound")
    files = [f for f in os.listdir(data_dir) if f.endswith(".xlsx")]
    if not files:
        raise RuntimeError("인바운드 엑셀 파일 없음")
    return f"{len(files)}개 파일"


def check_macro_calendar():
    cal_path = os.path.join(PROJECT_ROOT, "data", "macro_calendar.json")
    with open(cal_path, "r", encoding="utf-8") as f:
        cal = json.load(f)
    updated = cal.get("updated", "")
    this_week = len(cal.get("this_week", {}).get("events", []))
    next_week = len(cal.get("next_week", {}).get("events", []))
    if this_week == 0 and next_week == 0:
        raise RuntimeError("매크로 일정이 비어있음")
    return f"갱신일 {updated}, 금주 {this_week}건, 차주 {next_week}건"


def _days_old(date_str):
    """'YYYY-MM-DD' 또는 'YYYY-MM-DD HH:MM' 문자열의 경과 일수 (KST 기준). 파싱 실패 시 None."""
    from datetime import datetime, timedelta, timezone
    if not date_str:
        return None
    head = str(date_str).strip().split(" ")[0]
    try:
        d = datetime.strptime(head, "%Y-%m-%d").date()
    except ValueError:
        return None
    today = (datetime.now(timezone.utc) + timedelta(hours=9)).date()  # KST
    return (today - d).days


def check_us_events():
    """매크로 이슈 / 섹터별 이슈 데이터 신선도 + 완전성."""
    path = os.path.join(PROJECT_ROOT, "data", "us_events.json")
    if not os.path.exists(path):
        raise RuntimeError("us_events.json 없음")
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    groups = d.get("groups", []) or []
    updated = d.get("updated") or d.get("date", "")
    age = _days_old(updated)
    # 주말 스킵(일·월) 고려 → 5일 이상 지났으면 갱신 중단으로 간주
    if age is not None and age > 5:
        raise RuntimeError(f"us_events 갱신 {age}일 경과 (updated={updated}) — 자동 갱신 중단 의심")
    if len(groups) < 4:
        raise RuntimeError(f"섹터 group {len(groups)}개 (최소 4개 기대) — 분석 일부 실패 의심")
    ids = {g.get("id") for g in groups}
    missing = [s for s in ("tech_semi", "energy_materials", "software_platform") if s not in ids]
    if missing:
        raise RuntimeError(f"중요 섹터 누락: {missing}")
    return f"갱신 {updated}, group {len(groups)}개"


def check_kr_market():
    """한국 시장(지수·시장 랭킹) 데이터 신선도."""
    path = os.path.join(PROJECT_ROOT, "data", "kr_market.json")
    if not os.path.exists(path):
        raise RuntimeError("kr_market.json 없음")
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    updated = d.get("updated") or d.get("date", "")
    age = _days_old(updated)
    if age is not None and age > 5:
        raise RuntimeError(f"kr_market 갱신 {age}일 경과 (updated={updated}) — 자동 갱신 중단 의심")
    if not (d.get("kospi") and d.get("kosdaq")):
        raise RuntimeError("코스피/코스닥 지수 데이터 없음")
    rk = d.get("rankings") or d.get("ranking") or {}
    return f"갱신 {updated}, 지수 OK, 랭킹 {'있음' if rk else '없음'}"


def save_status(results):
    """헬스체크 결과를 JSON으로 저장 (대시보드에서 표시용)"""
    from datetime import datetime
    status_path = os.path.join(PROJECT_ROOT, "data", "healthcheck_status.json")
    status = {
        "last_check": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "all_pass": all(r["passed"] for r in results),
        "checks": [
            {"name": r["name"], "passed": r["passed"], "detail": r["detail"]}
            for r in results
        ],
    }
    os.makedirs(os.path.dirname(status_path), exist_ok=True)
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    print(f"  상태 저장: {status_path}")


def main():
    print("=" * 50)
    print("ARK IMPACT 대시보드 헬스체크")
    print("=" * 50)

    checks = [
        ("코스닥 종목 데이터", check_kosdaq_data),
        ("GICS 분류 데이터", check_gics_data),
        ("코스닥 150 구성종목", check_kosdaq150_constituents),
        ("선정 엔진 실행", check_selection_engine),
        ("인바운드 데이터 파일", check_inbound_data),
        ("매크로 캘린더", check_macro_calendar),
        ("매크로/섹터 이슈 신선도", check_us_events),
        ("한국 시장 데이터 신선도", check_kr_market),
    ]

    results = []
    for name, func in checks:
        passed, detail = check(name, func)
        results.append({"name": name, "passed": passed, "detail": detail})

    # 상태 저장
    save_status(results)

    print("\n" + "=" * 50)
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed

    if failed == 0:
        print(f"결과: ALL PASS ({passed}/{total})")
        print("=" * 50)
        return 0
    else:
        print(f"결과: {failed}건 FAIL ({passed}/{total})")
        print("\n실패 항목:")
        for r in results:
            if not r["passed"]:
                print(f"  - {r['name']}: {r['detail']}")
        print("=" * 50)
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
