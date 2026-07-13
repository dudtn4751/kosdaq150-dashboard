"""빅파이낸스 데이터 도메인 정찰 (일회용 2차) — Mac 로컬 전용, 클라우드/CI 금지.

목적: 수출(trade/export) 외 어떤 데이터 도메인(판매·산업지표·신용카드소비·기업리포트 등)을
제공하는지 카탈로그(목록)만 열거. 풀 시계열 미접근 — 목록/카탈로그 엔드포인트만 호출,
시계열 차트 본문은 저장하지 않는다.

방법(브라우저 개발자도구 대체 — 더 완전):
  1) SPA 번들(/assets/index-*.js)에서 API 클라이언트 맵을 정적 추출
     (name:(args)=>B.get(`/path`) 패턴) → 전 도메인 엔드포인트 목록 확보.
  2) 도메인 접두어(/industry, /launch-data/credit-card, /vaon, /market, /trade ...)로 분류.
  3) 카탈로그(목록) 성격의 파라미터 없는 GET만 실제 호출해 200·유효 JSON 확인 후
     트리로 열거. 파라미터 필요/권한 필요(400·403)는 '메타만' 기록.

실행: python3 scripts/inspect_bigfinance_domains.py
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bigfinance_session import login, BASE  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_PATH = BASE_DIR / "data" / "bf_domain_catalog.json"
DELAY = 0.4

# 도메인 분류(접두어 → 사람이 읽는 이름)
DOMAIN_LABELS = {
    "/launch-data/trade": "수출입(TRASS 무역) — 1차 정찰 완료",
    "/launch-data/credit-card": "신용카드 소비(판매) 데이터",
    "/industry": "산업지표(가격·생산 등 산업통계)",
    "/dashboard/industry": "산업 대시보드(지표·차트)",
    "/vaon": "리서치/공시(VAON 리포트·filings)",
    "/market": "시장(지수·투자자·히트맵)",
    "/partnersAndCompetitor": "경쟁사/실적 비교",
    "/companies": "기업 기본정보",
    "/fsCore": "재무(fsCore)",
}

# 카탈로그(목록) 성격 — 파라미터 없이 호출해 트리 열거를 시도할 엔드포인트
CATALOG_ENDPOINTS = [
    "/industry/codes",                        # 산업지표 카테고리 목록(updateDate 포함)
    "/industry/categories",                   # 산업지표 상위 카테고리
    "/launch-data/trade/industries",          # 무역 산업 목록(1차와 동일 — 교차확인)
    "/launch-data/credit-card/company-coverage",   # 카드소비 커버 기업
    "/launch-data/credit-card/searchable-companies",
    "/vaon/industries",
    "/vaon/market-reports",
]


def _extract_api_map(js: str):
    pat = re.compile(r'(\w{4,60})\s*:\s*\(([^)]*)\)\s*=>\s*B\.(get|post|put|delete)\('
                     r'\s*[`"\']([^`"\']+)[`"\']')
    rows, seen = [], set()
    for m in pat.finditer(js):
        verb, path = m.group(3).upper(), m.group(4)
        if path in seen:
            continue
        seen.add(path)
        rows.append({"name": m.group(1), "verb": verb, "path": path,
                     "has_param": ("${" in path) or bool(m.group(2).strip())})
    return rows


def _fetch_bundle_js(session):
    html = session.get(BASE + "/", timeout=20).text
    js_files = re.findall(r'(?:src|href)="(/assets/[^"]+\.js)"', html)
    combined = ""
    for f in js_files:
        try:
            combined += session.get(BASE + f, timeout=30).text + "\n"
        except Exception:
            pass
    return combined


def _get(session, api_path):
    time.sleep(DELAY)
    xsrf = urllib.parse.unquote(session.cookies.get("XSRF-TOKEN", "") or "")
    url = BASE + "/api" + api_path if api_path.startswith("/") else BASE + "/api/" + api_path
    r = session.get(url, headers={"X-XSRF-TOKEN": xsrf} if xsrf else {}, timeout=20)
    ctype = r.headers.get("content-type", "")
    body = r.json() if ctype.startswith("application/json") else r.text[:200]
    return r.status_code, body


def _classify(path):
    for pref, label in DOMAIN_LABELS.items():
        if path.startswith(pref) or path.startswith(pref.lstrip("/")):
            return pref, label
    return path.split("/")[1] if path.strip("/").count("/") else path, "(기타)"


def main():
    print("[1/3] 로그인 + SPA 번들에서 API 맵 정적 추출...")
    s = login()
    js = _fetch_bundle_js(s)
    api_map = _extract_api_map(js)
    print(f"      번들에서 {len(api_map)}개 API 엔드포인트 추출")

    # 도메인별 그룹핑
    domains = {}
    for e in api_map:
        pref, label = _classify(e["path"])
        domains.setdefault((pref, label), []).append(e)

    print("[2/3] 카탈로그(목록) 엔드포인트 실제 호출:")
    catalog_results = {}
    for path in CATALOG_ENDPOINTS:
        try:
            st, body = _get(s, path)
        except Exception as ex:
            print(f"      ERR  {path}: {str(ex)[:60]}")
            continue
        n = len(body) if isinstance(body, (list, dict)) else 0
        kind = "list" if isinstance(body, list) else "dict" if isinstance(body, dict) else "text"
        print(f"      {st:>3}  {path}  → {kind}({n})")
        catalog_results[path] = {"status": st, "kind": kind,
                                 "sample": body if st == 200 and isinstance(body, (list, dict)) else None}

    out = {
        "note": "카탈로그(목록)만. 시계열 본문 미저장. 도메인 맵은 SPA 번들 정적 추출.",
        "domains": [{"prefix": p, "label": lb, "endpoints": eps}
                    for (p, lb), eps in sorted(domains.items())],
        "catalogs": catalog_results,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[3/3] 저장: {OUT_PATH.relative_to(BASE_DIR)}\n")

    # ---- 도메인 트리 출력 ----
    print("=" * 74)
    print("빅파이낸스 데이터 도메인 (SPA API 맵 기준)")
    print("=" * 74)
    for (pref, label), eps in sorted(domains.items(), key=lambda kv: -len(kv[1])):
        cat = [e for e in eps if not e["has_param"]]
        print(f"\n■ {label}   [{pref}]  · 엔드포인트 {len(eps)}개")
        for e in eps[:24]:
            tag = "" if e["has_param"] else "  ← 파라미터 없이 호출 가능(목록성)"
            print(f"   {e['verb']:4s} {e['path']}{tag}")

    # ---- 카탈로그 실호출 결과 트리 ----
    print("\n" + "=" * 74)
    print("카탈로그(목록) 실호출 결과")
    print("=" * 74)
    for path, r in catalog_results.items():
        if r["status"] != 200 or r["sample"] is None:
            print(f"\n▷ {path}  (status={r['status']} — 파라미터/권한 필요, 목록 아님)")
            continue
        s_ = r["sample"]
        if path == "/industry/codes" and isinstance(s_, list):
            print(f"\n▷ 산업지표 카테고리 {len(s_)}개  [{path}]")
            for it in s_:
                print(f"   ├─ {it.get('name')} (code={it.get('code')}, 갱신={it.get('updateDate')})")
        elif path == "/industry/categories" and isinstance(s_, dict):
            cats = s_.get("categories") or []
            print(f"\n▷ 산업지표 상위 카테고리 {len(cats)}개  [{path}]")
            for c in cats:
                nm = c.get("name") if isinstance(c, dict) else c
                print(f"   ├─ {nm}")
        elif isinstance(s_, list):
            head = s_[:20]
            print(f"\n▷ {path}  → 목록 {len(s_)}개 (상위 20)")
            for it in head:
                print(f"   ├─ {json.dumps(it, ensure_ascii=False)[:90] if not isinstance(it, str) else it}")
        else:
            print(f"\n▷ {path}  → dict keys={list(s_.keys())[:10]}")


if __name__ == "__main__":
    main()
