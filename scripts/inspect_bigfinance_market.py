"""빅파이낸스 /market 도메인 대차/공매도 데이터 정찰 (일회용) — Mac 로컬 전용.

목적: /market(및 dashboard 수급) 하위에서 대차잔고·공매도잔고 시계열이 제공되는지
카탈로그만 확인. 풀 데이터 미접근(스키마 1건만). 스크레이프 아님(읽기·확인).

방법: SPA 번들에서 이미 확인한 market/수급 API 맵을 라이브 프로브 → 200·유효 JSON과
대차/공매도 관련 여부·파라미터를 열거. 종목별 시계열 엔드포인트는 스키마 1건 확인.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bigfinance_session import login, BASE  # noqa: E402

DELAY = 0.5
TIMEOUT = 45
TK = "005930"   # 스키마 확인용 종목(삼성전자)

# 번들 API 맵에서 추출한 /market·수급 엔드포인트 (라이브 프로브 대상)
# {t}=type, {a}=option/category, {s}=code. An(t): fx-rates→fxRates / virtual-assets→virtualAssets
PROBES = [
    # (설명, 경로, params)
    ("지수 요약(kospi)",        "/market/kospi/summary", None),
    ("지수(kospi)",             "/market/kospi/index", None),
    ("투자자 순매매 표(kospi)",  "/market/kospi/investor/net/topNetTrades", None),
    ("52주 시세표(kospi)",       "/market/kospi/historicalStocks/52weeks", None),
    ("히트맵 히스토리",          "/market/stock-map/stock/histories/v1", None),
    ("Top50 수익률",            "/market/topFiftyRevenuePercentage", None),
    ("Others 카테고리(fx)",      "/market/fxRates", None),
    ("Others 카테고리(가상자산)", "/market/virtualAssets", None),
    # 수급(dashboard) — 종목별 시계열 후보(대차/공매도에 가장 근접)
    ("기관 순매수(005930)",      f"/dashboard/institutionNetBuyingVolumes/{TK}", None),
    ("외국인 순매수(005930)",    f"/dashboard/foreignNetBuyingVolumes/{TK}", None),
    # 대차/공매도 직접 후보(있으면 대박, 없으면 404 — 존재확인용)
    ("대차잔고 후보1",           f"/market/{TK}/loan-balance", None),
    ("공매도잔고 후보1",         f"/market/{TK}/short-balance", None),
    ("공매도 후보2",             f"/dashboard/shortBalance/{TK}", None),
    ("대차 후보2",               f"/dashboard/loanBalance/{TK}", None),
]

LOAN_SHORT_KEYS = ("loan", "short", "borrow", "lend", "balance", "대차", "공매도", "잔고")


def _get(session, path, params=None):
    time.sleep(DELAY)
    xsrf = urllib.parse.unquote(session.cookies.get("XSRF-TOKEN", "") or "")
    r = session.get(BASE + "/api" + path, params=params,
                    headers={"X-XSRF-TOKEN": xsrf} if xsrf else {}, timeout=TIMEOUT)
    ct = r.headers.get("content-type", "")
    body = r.json() if ct.startswith("application/json") else r.text[:120]
    return r.status_code, body


def _shape(d):
    if isinstance(d, list):
        return f"list(len={len(d)}, first={json.dumps(d[0], ensure_ascii=False)[:90] if d else '[]'})"
    if isinstance(d, dict):
        return f"dict(keys={list(d.keys())[:10]})"
    return f"{type(d).__name__}: {str(d)[:80]}"


def _mentions_loan_short(d) -> bool:
    blob = json.dumps(d, ensure_ascii=False).lower() if isinstance(d, (dict, list)) else str(d).lower()
    return any(k.lower() in blob for k in LOAN_SHORT_KEYS)


def main():
    print("[market 정찰] 로그인...")
    s = login(timeout=TIMEOUT)
    print("      OK · 번들 확인: /market others = fxRates·virtualAssets (대차/공매도 아님),")
    print("      번들 문자열 '대차/공매도/loan/short' 출현 0 → labeled 기능 부재 추정. 라이브 확인:\n")

    print(f"{'상태':>4}  {'설명':<22} {'경로'}")
    print("=" * 96)
    found_loan_short, schema_shown = [], set()
    for desc, path, params in PROBES:
        try:
            st, body = _get(s, path, params)
        except Exception as ex:
            print(f"  ERR  {desc:<22} {path} — {type(ex).__name__}")
            continue
        mark = ""
        if st == 200 and isinstance(body, (list, dict)):
            if _mentions_loan_short(body):
                mark = "  ★대차/공매도 관련 필드 포함"
                found_loan_short.append((desc, path))
            # 종목별 시계열 스키마 1건 표시(수급 등)
            if ("NetBuying" in path or "balance" in path.lower()) and path not in schema_shown:
                schema_shown.add(path)
                mark += f"\n         └ 스키마: {_shape(body)}"
        print(f"  {st:>3}  {desc:<22} {path}{mark}")

    print("\n" + "=" * 96)
    print("결론")
    print("=" * 96)
    if found_loan_short:
        print("대차/공매도 관련 필드가 포함된 엔드포인트:")
        for desc, path in found_loan_short:
            print(f"  · {desc} — {path}")
    else:
        print("• /market 및 dashboard 수급 어디에도 '대차잔고/공매도잔고' 전용 시계열 없음.")
        print("• /market others = 환율(fxRates)·가상자산(virtualAssets)뿐, 수급은 순매수(net buying)만 제공.")
        print("• 번들에도 대차/공매도/loan/short 문자열 부재 → 빅파이낸스는 대차/공매도 미제공으로 판단.")
        print("  → 대차잔고 소스는 pykrx(get_shorting_balance_by_date) 또는 co['sb'] 폴백 유지가 맞음.")


if __name__ == "__main__":
    main()
