"""빅파이낸스 Industry 섹션 카탈로그 정찰 (일회용) — Mac 로컬 전용, 클라우드/CI 금지.

목적: Industry 섹션에서 "어떤 산업 데이터가 제공되는지" 목록(카탈로그)만 열거.
풀 시계열 스크레이프 금지 — 목록/메타 엔드포인트만 호출, 호출 간 0.4s 간격.

흐름:
  1) bigfinance_session.login() 1회 (.env BIGFINANCE_ID/PW)
  2) 산업 목록 후보 엔드포인트 순차 프로빙 (404/403 → 다음 후보)
  3) 산업별 상세항목(product) 목록 엔드포인트 프로빙 후 열거
  4) data/bf_industry_catalog.json 저장 + 섹터/산업 트리 콘솔 출력

실행: python3 scripts/inspect_bigfinance_industry.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bigfinance_session import login, api_get  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_PATH = BASE_DIR / "data" / "bf_industry_catalog.json"
DELAY = 0.4  # 호출 간 간격(부하 최소화)

# 산업(카탈로그) 목록 후보 — 무역 차트 경로(/api/launch-data/trade/industries/{ic}/{pc}/{kind}/export/chart) 유추
LIST_CANDIDATES = [
    "/api/launch-data/trade/industries",          # industry_code 없이 → 전체 목록?
    "/api/launch-data/industries",
    "/api/launch-data/industry",
    "/api/launch-data/industry/categories",
    "/api/launch-data/industries/categories",
    "/api/launch-data/trade/categories",
    "/api/launch-data/categories",
    "/api/launch-data/industry/list",
    "/api/industries",
]

# 산업별 상세항목 목록 후보 ({code} 치환)
PRODUCT_CANDIDATES = [
    "/api/launch-data/trade/industries/{code}",
    "/api/launch-data/trade/industries/{code}/products",
    "/api/launch-data/industries/{code}/products",
    "/api/launch-data/industry/{code}/products",
    "/api/launch-data/industry/{code}",
]

# 메타 키 후보(실측: industryCode/industryName + products[{productCode, productName}])
NAME_KEYS = ("industryName", "productName", "name", "industry_name", "title", "label", "korName", "nm")
CODE_KEYS = ("industryCode", "productCode", "code", "industry_code", "id", "key", "cd")
META_KEYS = ("unit", "frequency", "freq", "latest", "latest_date", "latestMonth", "latestDate",
             "category", "sector", "group", "kind", "source", "updated_at", "updatedAt")
# ※ 목록 엔드포인트 응답에 unit/frequency/최신월 메타는 없음(실측) — 그 메타는 개별
#   chart 엔드포인트에서만 나오는 것으로 보이며, 풀 데이터 호출 금지 방침에 따라 미수집.


def _probe(session, path: str):
    """GET 1회. (status, json|None). HTTP 에러여도 상태코드 기록."""
    time.sleep(DELAY)
    try:
        data = api_get(session, path)
        return 200, data
    except requests.HTTPError as e:
        return (e.response.status_code if e.response is not None else -1), None
    except Exception:
        return -1, None


def _listify(data):
    """응답에서 목록 후보 추출: list 그대로, dict면 값 중 첫 list."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("data", "items", "list", "industries", "categories", "result", "results"):
            v = data.get(k)
            if isinstance(v, list) and v:
                return v
        for v in data.values():
            if isinstance(v, list) and v:
                return v
    return None


def _pick(d: dict, keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return None


def _entry_meta(d: dict) -> dict:
    """항목 dict → {name, code, ...메타}. 스키마 미상이라 있는 키만."""
    out = {"name": _pick(d, NAME_KEYS), "code": _pick(d, CODE_KEYS)}
    for k in META_KEYS:
        if d.get(k) not in (None, ""):
            out[k] = d[k]
    return out


def main():
    print("[1/4] 로그인...")
    s = login()
    print("      OK")

    # ---- 산업 목록 탐색 ----
    print("[2/4] 산업 목록 엔드포인트 프로빙:")
    industries, list_path, raw_list = None, None, None
    for path in LIST_CANDIDATES:
        code, data = _probe(s, path)
        items = _listify(data) if data is not None else None
        n = len(items) if items else 0
        print(f"      {code:>4}  {path}" + (f"  → 항목 {n}개" if n else ""))
        if code == 200 and items:
            industries, list_path, raw_list = items, path, data
            break
    if not industries:
        print("\n⚠️ 산업 목록 엔드포인트를 찾지 못했습니다.")
        print("   크롬 개발자도구 Network 탭에서 Industry 화면 로드 시 /api/... 경로를 확인해")
        print("   LIST_CANDIDATES에 추가 후 재실행해주세요.")
        sys.exit(1)

    sample = industries[0]
    print(f"      채택: {list_path} (샘플 키: {list(sample.keys()) if isinstance(sample, dict) else type(sample).__name__})")

    # ---- 상세항목 엔드포인트 모양 탐색 (첫 산업으로 1회씩만) ----
    print("[3/4] 상세항목(product) 엔드포인트 프로빙:")
    first_code = _pick(sample, CODE_KEYS) if isinstance(sample, dict) else None
    product_tpl = None
    if first_code is not None:
        for tpl in PRODUCT_CANDIDATES:
            code, data = _probe(s, tpl.format(code=first_code))
            items = _listify(data) if data is not None else None
            n = len(items) if items else 0
            print(f"      {code:>4}  {tpl}" + (f"  → 항목 {n}개" if n else ""))
            if code == 200 and items:
                product_tpl = tpl
                break
    if product_tpl is None:
        print("      (상세항목 별도 엔드포인트 없음 — 산업 목록 응답에 내장돼 있을 수 있어 그대로 정리)")

    # ---- 카탈로그 구성 (메타만) ----
    catalog = []
    for ind in industries:
        if not isinstance(ind, dict):
            catalog.append({"raw": ind})
            continue
        entry = _entry_meta(ind)
        # 응답에 내장된 하위 목록(children/products 등)이 있으면 그걸 쓰고, 없으면 엔드포인트 호출
        embedded = None
        for k in ("products", "children", "items", "sub", "details", "list"):
            if isinstance(ind.get(k), list) and ind[k]:
                embedded = ind[k]
                break
        if embedded is not None:
            entry["products"] = [_entry_meta(p) if isinstance(p, dict) else {"raw": p} for p in embedded]
        elif product_tpl and entry.get("code") is not None:
            code, data = _probe(s, product_tpl.format(code=entry["code"]))
            items = _listify(data) if data is not None else None
            entry["products"] = ([_entry_meta(p) if isinstance(p, dict) else {"raw": p} for p in items]
                                 if items else [])
        catalog.append(entry)

    # ---- 저장 + 트리 출력 ----
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps({"list_endpoint": list_path, "product_endpoint": product_tpl,
                    "industries": catalog, "raw_list_sample": raw_list if isinstance(raw_list, dict) else None},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[4/4] 저장: {OUT_PATH.relative_to(BASE_DIR)} (산업 {len(catalog)}개)\n")

    # 섹터/카테고리 그룹핑 트리
    print("=" * 70)
    print("빅파이낸스 Industry 카탈로그")
    print("=" * 70)
    by_group = {}
    for e in catalog:
        g = e.get("category") or e.get("sector") or e.get("group") or "(미분류)"
        by_group.setdefault(str(g), []).append(e)
    for g in sorted(by_group):
        print(f"\n■ {g}")
        for e in by_group[g]:
            meta_bits = [str(e[k]) for k in ("unit", "frequency", "latest", "latest_date", "latestMonth") if e.get(k)]
            suffix = f"  [{' · '.join(meta_bits)}]" if meta_bits else ""
            print(f"  ├─ {e.get('name') or e.get('code') or '?'} (code={e.get('code')}){suffix}")
            for p in (e.get("products") or [])[:50]:
                pm = [str(p[k]) for k in ("unit", "frequency", "latest", "latest_date") if p.get(k)]
                ps = f"  [{' · '.join(pm)}]" if pm else ""
                print(f"  │    └─ {p.get('name') or p.get('code') or p.get('raw', '?')} (code={p.get('code')}){ps}")


if __name__ == "__main__":
    main()
