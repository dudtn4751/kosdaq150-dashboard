"""빅파이낸스 산업지표 subCodes + 신용카드 카탈로그 정찰 (일회용) — Mac 로컬 전용.

클라우드/CI 금지. 목록/메타만 — 풀 시계열 미접근.

1) /industry/categories 1회 호출로 23개 카테고리 → subCategories → dataCategories
   전체 트리를 얻는다(별도 카테고리당 호출 불필요 — 이 엔드포인트가 통째로 반환).
   각 subCategory의 갱신일(updateDate)·데이터타입(industryDataType) 포함.
2) credit-card: searchable-companies(163개) + company-coverage 목록 저장,
   소비 시리즈/랭킹 엔드포인트의 필수 파라미터(기간·타입)를 SPA 번들에서 확인해 문서화.

결과 → data/bf_industry_subcodes.json, data/bf_creditcard_catalog.json

실행: python3 scripts/inspect_bigfinance_industry_subcodes.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bigfinance_session import login, api_get, BASE  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
IND_OUT = BASE_DIR / "data" / "bf_industry_subcodes.json"
CC_OUT = BASE_DIR / "data" / "bf_creditcard_catalog.json"
DELAY = 0.4

# 유니버스와 무관 → 트리 출력에서 접기(저장은 함). 스펙: 교육13·벤처21·환경22
SKIP_CODES = {13, 21, 22}

# credit-card 소비/랭킹 엔드포인트 필수 파라미터 (SPA 번들에서 확인한 실제 시그니처)
CC_PARAM_DOC = {
    "/launch-data/credit-card/{type}/date-range": {
        "path_params": {"type": "결제유형(예: total 등) — 경로 세그먼트"},
        "note": "해당 type의 가용 조회 기간(from~to) 반환 → 랭킹/차트 호출 전 기간 확보용",
    },
    "/launch-data/credit-card/{type}": {
        "path_params": {"type": "결제유형"},
        "note": "getLaunchDataPaymentTrendsByType — 유형별 결제 추이",
    },
    "/launch-data/credit-card/sectors/ranking": {
        "query_params": {"(params 객체)": "기간·정렬 등 — 정확 키는 UI 상태 기반(date/period 추정)"},
        "note": "400=파라미터 필수. sectors/{lCode}/{mCode}/trends로 섹터 코드 확보 후 사용",
    },
    "/launch-data/credit-card/brands/ranking": {
        "query_params": {"(params 객체)": "기간·정렬 등"},
        "note": "400=파라미터 필수. brands/{id}/{period}/chart로 개별 시계열",
    },
    "/launch-data/credit-card/sectors/{lCode}/{mCode}/trends": {
        "path_params": {"lCode": "대분류 섹터코드", "mCode": "중분류 코드"},
    },
    "/launch-data/credit-card/companies/{id}/trends": {
        "path_params": {"id": "companyId (searchable-companies의 companyId)"},
    },
    "/launch-data/credit-card/{type}/change-rate/{period}": {
        "path_params": {"type": "결제유형", "period": "기간(예: 1m/3m/12m 추정)"},
        "query_params": {"(params 객체)": "추가 필터"},
    },
    "/launch-data/credit-card/compare-chart": {
        "params": "없음(파라미터 없이 200) — 전체 카드결제 월별 시계열 [[YYYYMM, amount, count], ...]",
    },
}


def _get(session, path):
    time.sleep(DELAY)
    xsrf = urllib.parse.unquote(session.cookies.get("XSRF-TOKEN", "") or "")
    r = session.get(BASE + "/api" + path, headers={"X-XSRF-TOKEN": xsrf} if xsrf else {}, timeout=20)
    ct = r.headers.get("content-type", "")
    return r.status_code, (r.json() if ct.startswith("application/json") else r.text[:200])


def _categories(payload):
    """전체 카테고리(23개)는 payload['categories']에 있고 구조는
    category → groups[] → subCategories[] → dataCategories[]. (payload['recent']는
    최근 갱신 16개 요약본이라 무시하고 categories만 사용)."""
    if not isinstance(payload, dict):
        return []
    cats = payload.get("categories", []) or []
    return sorted([c for c in cats if isinstance(c, dict)], key=lambda c: c.get("code", 0))


def main():
    print("[1/3] 로그인...")
    s = login()
    print("      OK")

    # ---- 1) 산업지표 트리 (1회 호출) ----
    print("[2/3] /industry/categories 1회 호출 → 전체 subCodes 트리:")
    st, payload = _get(s, "/industry/categories")
    cats = _categories(payload)
    print(f"      status={st} · 카테고리 {len(cats)}개")

    ind_tree = []
    for c in cats:
        groups = []
        for g in c.get("groups", []) or []:
            subs = []
            for sc in g.get("subCategories", []) or []:
                subs.append({
                    "subCode": sc.get("subCode"),
                    "subName": sc.get("subName"),
                    "updateDate": sc.get("updateDate"),
                    "dataType": sc.get("industryDataType"),
                    "dataCategories": [
                        {"dataCode": d.get("dataCode"), "dataName": d.get("dataName"),
                         "lastUpdate": d.get("lastUpdateDatetime")}
                        for d in (sc.get("dataCategories", []) or [])
                    ],
                })
            groups.append({"groupId": g.get("groupId"), "groupName": g.get("groupName"),
                           "subCategories": subs})
        ind_tree.append({"code": c.get("code"), "name": c.get("name"),
                         "updateDate": c.get("latestUpdateDate"), "groups": groups})

    IND_OUT.write_text(json.dumps({"source": "/api/industry/categories", "categories": ind_tree},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
    n_sub = sum(len(g["subCategories"]) for c in ind_tree for g in c["groups"])
    n_data = sum(len(sc["dataCategories"]) for c in ind_tree for g in c["groups"] for sc in g["subCategories"])
    print(f"      저장: {IND_OUT.relative_to(BASE_DIR)} (group {sum(len(c['groups']) for c in ind_tree)} · subCategory {n_sub} · dataCategory {n_data})")

    # ---- 2) credit-card 카탈로그 ----
    print("[3/3] credit-card 목록 + 파라미터 문서화:")
    st1, searchable = _get(s, "/launch-data/credit-card/searchable-companies")
    st2, coverage = _get(s, "/launch-data/credit-card/company-coverage")
    print(f"      searchable-companies status={st1} ({len(searchable) if isinstance(searchable, list) else '?'})")
    print(f"      company-coverage    status={st2} ({len(coverage) if isinstance(coverage, list) else '?'})")

    CC_OUT.write_text(json.dumps({
        "searchable_companies": searchable if isinstance(searchable, list) else None,
        "company_coverage": coverage if isinstance(coverage, list) else None,
        "endpoint_params": CC_PARAM_DOC,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      저장: {CC_OUT.relative_to(BASE_DIR)}")

    # ================= 콘솔 트리 =================
    print("\n" + "=" * 78)
    print("① 산업지표 카탈로그 (카테고리 → 상세지표(subCategory) → 데이터항목)")
    print("=" * 78)
    for c in ind_tree:
        n_sub_c = sum(len(g["subCategories"]) for g in c["groups"])
        skip = c["code"] in SKIP_CODES
        head = f"\n■ [{c['code']}] {c['name']}  (갱신 {c.get('updateDate')}) · 상세지표 {n_sub_c}개"
        if skip:
            print(head + "   … (유니버스 무관 — 접음)")
            continue
        print(head)
        for g in c["groups"]:
            print(f"   ▸ {g['groupName']}  (group={g['groupId']})")
            for sc in g["subCategories"]:
                dn = len(sc["dataCategories"])
                print(f"      ├─ {sc['subName']}  (subCode={sc['subCode']}, {sc['dataType']}, 갱신 {sc['updateDate']}, 항목 {dn})")
                preview = sc["dataCategories"][:8]
                names = ", ".join(str(d["dataName"]) for d in preview)
                more = f" …+{dn - 8}" if dn > 8 else ""
                if names:
                    print(f"      │     {names}{more}")

    print("\n" + "=" * 78)
    print("② 신용카드 소비 카탈로그")
    print("=" * 78)
    if isinstance(searchable, list):
        print(f"\n▷ 시계열 조회 가능 기업(searchable-companies): {len(searchable)}개 (A코드·companyId)")
        for it in searchable[:15]:
            print(f"   ├─ {it.get('companyName')} ({it.get('companyCode')}, id={it.get('companyId')})")
        print(f"   … 외 {max(0, len(searchable) - 15)}개 (전체는 {CC_OUT.name})")
    if isinstance(coverage, list):
        print(f"\n▷ 커버 브랜드(company-coverage): {len(coverage)}개")
        print("   " + ", ".join(str(x) for x in coverage[:24]) + f" …외 {max(0, len(coverage) - 24)}")

    print("\n▷ 소비 시리즈/랭킹 엔드포인트 필수 파라미터:")
    for ep, doc in CC_PARAM_DOC.items():
        print(f"   • {ep}")
        for k, v in doc.items():
            print(f"       - {k}: {v}")


if __name__ == "__main__":
    main()
