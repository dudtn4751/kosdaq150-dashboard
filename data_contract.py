"""데이터 계약(contract) — 대시보드가 의존하는 JSON들의 불변식을 한 곳에서 정의.

세 곳에서 동일하게 강제:
  1) 생성 스크립트: 계산 결과가 계약 위반(ERROR)이면 기존 정상 파일을 덮어쓰지 않음.
  2) CI(scripts/validate_data.py): 위반 시 워크플로 실패 → 이슈 자동 생성.
  3) 앱: 로드 시 검증 → 위반/오래됨을 화면에 명시(조용히 0/stale 표시 방지).

각 검증기는 issue 리스트 반환: (severity, message). severity ∈ {"error","warn"}.
ERROR = 화면이 깨지거나 0/빈값이 보이는 치명적 결손. WARN = 오래됨/부분 결손.
"""

from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
STALE_WARN_DAYS = 5  # 주말·휴장 여유 포함. 이보다 오래되면 자동 갱신 중단 의심.


def days_old(date_str):
    """'YYYY-MM-DD' 또는 'YYYY-MM-DD HH:MM' → KST 기준 경과 일수. 파싱 실패 시 None."""
    if not date_str:
        return None
    head = str(date_str).strip().split(" ")[0]
    try:
        d = datetime.strptime(head, "%Y-%m-%d").date()
    except ValueError:
        return None
    return (datetime.now(KST).date() - d).days


def _g(d, *path, default=None):
    cur = d
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
    return cur if cur is not None else default


# ── 개별 계약 ──────────────────────────────────────────
def validate_kr_market(d):
    issues = []
    if not isinstance(d, dict):
        return [("error", "kr_market 데이터 없음/형식 오류")]
    for k in ("kospi", "kosdaq"):
        close = _g(d, k, "close", default=0)
        if not close or close <= 0:
            issues.append(("error", f"{k} 종가 없음"))
    tot = _g(d, "breadth", "total", default={}) or {}
    up, down = tot.get("up", 0), tot.get("down", 0)
    if (up + down) <= 0:
        issues.append(("error", "상승/하락 종목수 0 (breadth 결손)"))
    cap = _g(d, "rankings", "주식", "전체", "시가총액", default=[]) or []
    if len(cap) < 5:
        issues.append(("error", f"시장 랭킹 비어있음(시총상위 {len(cap)}종목)"))
    age = days_old(d.get("date") or d.get("updated"))
    if age is not None and age > STALE_WARN_DAYS:
        issues.append(("warn", f"한국 시장 데이터 {age}일 경과"))
    return issues


def validate_us_events(d):
    issues = []
    if not isinstance(d, dict):
        return [("error", "us_events 데이터 없음/형식 오류")]
    groups = d.get("groups") or []
    if len(groups) < 4:
        issues.append(("error", f"섹터 group {len(groups)}개 (분석 일부 실패 의심)"))
    ids = {g.get("id") for g in groups}
    missing = [s for s in ("tech_semi", "energy_materials", "software_platform") if s not in ids]
    if missing:
        issues.append(("warn", f"중요 섹터 누락: {missing}"))
    if not _g(d, "brief", "market_read"):
        issues.append(("warn", "시장 총평(brief) 없음"))
    age = days_old(d.get("updated") or d.get("date"))
    if age is not None and age > STALE_WARN_DAYS:
        issues.append(("warn", f"매크로/섹터 이슈 {age}일 경과"))
    return issues


def validate_market_signal(d):
    issues = []
    if not isinstance(d, dict):
        return [("error", "market_signal 데이터 없음/형식 오류")]
    if not isinstance(d.get("surge"), list) or not isinstance(d.get("plunge"), list):
        issues.append(("error", "급등/급락 리스트 결손"))
    age = days_old(d.get("date") or d.get("updated"))
    if age is not None and age > STALE_WARN_DAYS:
        issues.append(("warn", f"한국 수급·특징주 {age}일 경과"))
    return issues


def validate_macro_calendar(d):
    issues = []
    if not isinstance(d, dict):
        return [("error", "macro_calendar 데이터 없음/형식 오류")]
    tw = len(_g(d, "this_week", "events", default=[]) or [])
    nw = len(_g(d, "next_week", "events", default=[]) or [])
    if tw == 0 and nw == 0:
        issues.append(("warn", "매크로 일정 비어있음"))
    return issues


def validate_research(d):
    issues = []
    if not isinstance(d, dict):
        return [("error", "research_reports 데이터 없음/형식 오류")]
    reps = d.get("reports") or []
    if len(reps) == 0:
        issues.append(("error", "증권사 리포트 0건"))
    age = days_old(d.get("date") or d.get("updated"))
    if age is not None and age > STALE_WARN_DAYS:
        issues.append(("warn", f"증권사 리포트 {age}일 경과"))
    return issues


def validate_consensus(d):
    issues = []
    if not isinstance(d, dict):
        return [("error", "consensus 데이터 없음/형식 오류")]
    secs = d.get("sectors") or []
    if len(secs) < 5:
        issues.append(("error", f"섹터 집계 {len(secs)}개 (최소 5개 기대)"))
    if (d.get("covered") or 0) < 20:
        issues.append(("error", f"컨센서스 커버 종목 {d.get('covered',0)}개 (수집 실패 의심)"))
    age = days_old(d.get("date") or d.get("updated"))
    if age is not None and age > STALE_WARN_DAYS:
        issues.append(("warn", f"섹터 컨센서스 {age}일 경과"))
    return issues


VALIDATORS = {
    "kr_market": validate_kr_market,
    "us_events": validate_us_events,
    "market_signal": validate_market_signal,
    "macro_calendar": validate_macro_calendar,
    "research_reports": validate_research,
    "consensus": validate_consensus,
}

# 사용자에게 보일 한글 라벨
LABELS = {
    "kr_market": "한국 시장 현황·시장 랭킹",
    "us_events": "매크로·섹터 이슈",
    "market_signal": "한국 수급·특징주",
    "macro_calendar": "경제 일정",
    "research_reports": "증권사 리포트·목표주가",
    "consensus": "섹터 이익 컨센서스",
}


def check(name, data):
    """단일 데이터 검증 → {ok, level, errors, warns, issues}."""
    issues = VALIDATORS.get(name, lambda _d: [])(data)
    errors = [m for sev, m in issues if sev == "error"]
    warns = [m for sev, m in issues if sev == "warn"]
    level = "error" if errors else ("warn" if warns else "ok")
    return {"ok": not errors, "level": level, "errors": errors, "warns": warns,
            "issues": [m for _s, m in issues]}
