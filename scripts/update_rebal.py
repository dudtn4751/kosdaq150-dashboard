"""패시브 리밸런싱 데이터 (ETF 수급 전략 ②).

지수별 리밸런싱 주기 + 다음 정기변경일 + 추종 ETF AUM(패시브 매매 규모) +
KOSDAQ150 정기 편입/편출 예측(기존 엔진) + 수시변경 위험(kosdaq150_risk.json).

출력: data/rebal.json
"""

import calendar
import json
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

warnings.filterwarnings("ignore")

KST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
OUTPUT_PATH = PROJECT_ROOT / "data" / "rebal.json"
ETF_FLOW_PATH = PROJECT_ROOT / "data" / "etf_flow.json"
RISK_PATH = PROJECT_ROOT / "data" / "kosdaq150_risk.json"

# 지수 리밸런싱 주기 (정적 레퍼런스). KOSPI200/KOSDAQ150 정기변경 연 2회(6·12월 동시만기 익영업일).
INDEX_REF = [
    {"name": "코스닥150", "match": "코스닥 150", "cycle": "정기 연 2회 (6·12월 동시만기일 익영업일)",
     "predict": True},
    {"name": "코스피200", "match": "코스피 200", "cycle": "정기 연 2회 (6·12월 동시만기일 익영업일)",
     "predict": False},
]


def second_thursday(year, month):
    days = [d for d in calendar.Calendar().itermonthdates(year, month)
            if d.month == month and d.weekday() == 3]
    return days[1]


def next_regular_change(today):
    cands = []
    for y in (today.year, today.year + 1):
        for m in (6, 12):
            d = second_thursday(y, m)
            if d >= today:
                cands.append(d)
    return min(cands).isoformat()


def etf_aum_by_index(match):
    """etf_flow에서 해당 지수 추종 ETF 합산 AUM·목록."""
    try:
        flow = json.loads(ETF_FLOW_PATH.read_text(encoding="utf-8"))
    except Exception:
        return 0.0, []
    etfs = []
    for e in flow.get("etfs", []):
        idx = e.get("index") or ""
        if match in idx:
            etfs.append({"name": e["name"], "aum": e["aum"], "index": idx})
    etfs.sort(key=lambda x: x["aum"], reverse=True)
    return round(sum(x["aum"] for x in etfs), 0), etfs


def kosdaq150_prediction():
    try:
        from data_collector import collect_all
        from selection_engine import predict_changes
        d = collect_all(skip_daily=True)
        r = predict_changes(d["kosdaq_listing"], d["gics_map"], d["current_150"], d.get("avg_data"))
        def clean(x):
            try:
                mc = float(x.get("marcap") or 0)
            except (ValueError, TypeError):
                mc = 0.0
            return {"code": str(x.get("code", "")), "name": str(x.get("name", "")),
                    "sector": str(x.get("sector", "")), "marcap": mc}
        return {
            "current_count": int(len(d["current_150"])),
            "additions": [clean(x) for x in r["additions"]],
            "removals": [clean(x) for x in r["removals"]],
        }
    except Exception as e:
        print(f"  [경고] KOSDAQ150 예측 실패: {type(e).__name__}: {str(e)[:120]}")
        return None


def main():
    now = datetime.now(KST)
    today = now.date()
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] 패시브 리밸런싱 데이터 수집")

    next_change = next_regular_change(today)
    indices = []
    for ref in INDEX_REF:
        aum, etfs = etf_aum_by_index(ref["match"])
        indices.append({
            "name": ref["name"], "cycle": ref["cycle"], "next_change": next_change,
            "etf_count": len(etfs), "etf_aum_eok": aum, "etfs": etfs[:15],
            "predict": ref["predict"],
        })
        print(f"  {ref['name']}: 추종 ETF {len(etfs)}개 / AUM {aum/1e4:.1f}조")

    kosdaq150 = kosdaq150_prediction()
    if kosdaq150:
        print(f"  KOSDAQ150 예측: 편입 {len(kosdaq150['additions'])} / 편출 {len(kosdaq150['removals'])}")

    risk = None
    try:
        risk = json.loads(RISK_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass

    out = {
        "updated": now.strftime("%Y-%m-%d %H:%M"), "date": today.isoformat(),
        "next_regular_change": next_change,
        "indices": indices,
        "kosdaq150": kosdaq150,
        "risk": risk,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  저장: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
