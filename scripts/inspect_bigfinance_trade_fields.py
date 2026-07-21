"""빅파이낸스 수출 필드 ↔ 수출입 CSV 스키마 매핑 검증 (일회용) — Mac 로컬 전용.

목적: 대시보드가 쓰는 CSV(trade_history_long / company_trade_history_long)의 컬럼을
빅파이낸스 JSON API(export/chart)로 재현 가능한지 필드만 검증. 풀 데이터 미수집.

검증 결과 요약(2026-07-21):
- export/chart 응답은 [YYYYMM, 금액USD, YoY] 3필드뿐 — 단가/물량 없음. measure/type/metric
  쿼리 파라미터는 무시되고, price/volume/quantity 전용 direction은 전부 404.
  → 단가(unit_price)는 팀 스크래퍼(scrape_bigfinance.py)가 UI 모달의 '수출 단가' 지표를
    별도 다운로드해 채운다(JSON API로는 재현 불가). 물량(export_volume)은 CSV에 컬럼
    자체가 없고, metrics의 volume_yoy는 금액/단가로 파생.
- 기업별(company_trade_history_long): JSON breakdown 엔드포인트 없음. industries/{ic}/{pc}/
  addresses·estimate/export는 '지역(주소)' 단위(강원 강릉시 등)이고, custom/groups는 사용자
  품목 커스텀 그룹이다. 기업별은 EPIC '품목 커스텀 설정' 모달의 '하위 기업'뿐 → UI 스크레이프.

실행: python3 scripts/inspect_bigfinance_trade_fields.py
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
from bigfinance_session import login, fetch_export_chart, BASE  # noqa: E402

DELAY = 0.5
# 샘플 품목: 반도체 총계(industry_code=1, product_code=3), 자동차 총계(2,1)
SAMPLES = [(1, 3, "반도체: 총계"), (2, 1, "자동차: 자동차 총계")]


def _get(session, path, params=None):
    time.sleep(DELAY)
    x = urllib.parse.unquote(session.cookies.get("XSRF-TOKEN", "") or "")
    r = session.get(BASE + "/api" + path, params=params,
                    headers={"X-XSRF-TOKEN": x} if x else {}, timeout=25)
    ct = r.headers.get("content-type", "")
    return r.status_code, (r.json() if ct.startswith("application/json") else r.text[:150])


def _shape_series(data):
    if isinstance(data, list) and data:
        first, last = data[0], data[-1]
        width = len(first) if isinstance(first, (list, tuple)) else "scalar/dict"
        return f"list(len={len(data)}, 행폭={width}, 첫={first}, 끝={last})"
    return f"{type(data).__name__}: {str(data)[:80]}"


def main():
    print("[수출 필드 검증] 로그인...")
    s = login()
    print("      OK\n")

    print("=" * 78)
    print("① export/chart 응답 필드 (금액 외 단가/물량 있나)")
    print("=" * 78)
    for ic, pc, label in SAMPLES:
        try:
            data = fetch_export_chart(s, ic, pc, kind="confirm")
            print(f"  [{label}] confirm/export/chart → {_shape_series(data)}")
        except Exception as e:
            print(f"  [{label}] ERR: {type(e).__name__} {str(e)[:60]}")

    print("\n" + "=" * 78)
    print("② 단가/물량 전용 kind·direction·measure 탐색 (반도체 총계 1/3)")
    print("=" * 78)
    variants = [
        ("confirm/export", "/launch-data/trade/industries/1/3/confirm/export/chart"),
        ("price 추정", "/launch-data/trade/industries/1/3/confirm/price/chart"),
        ("volume 추정", "/launch-data/trade/industries/1/3/confirm/volume/chart"),
        ("quantity 추정", "/launch-data/trade/industries/1/3/confirm/quantity/chart"),
        ("weight 추정", "/launch-data/trade/industries/1/3/confirm/weight/chart"),
    ]
    for name, path in variants:
        st, d = _get(s, path)
        ok = st == 200 and isinstance(d, list) and d
        print(f"  {st:>3}  {name:<14} {path}" + (f"  → {_shape_series(d)}" if ok else ""))
    for q in ({"measure": "price"}, {"measure": "quantity"}, {"type": "unitPrice"}, {"metric": "price"}):
        st, d = _get(s, "/launch-data/trade/industries/1/3/confirm/export/chart", q)
        print(f"  {st:>3}  export/chart?params={q}" + (f"  → {_shape_series(d)}" if st == 200 and isinstance(d, list) else ""))

    print("\n" + "=" * 78)
    print("③ 기업별(company breakdown) JSON 엔드포인트 — addresses/estimate/custom 분류")
    print("=" * 78)
    for name, p in [("industries/1/3/addresses", "/launch-data/trade/industries/1/3/addresses"),
                    ("industries/1/3/estimate/export", "/launch-data/trade/industries/1/3/estimate/export"),
                    ("custom/groups", "/launch-data/trade/custom/groups")]:
        st, d = _get(s, p)
        if isinstance(d, dict):
            head = {k: (d[k][:2] if isinstance(d[k], list) else d[k]) for k in list(d)[:5]}
            print(f"  {st}  {name} → dict {json.dumps(head, ensure_ascii=False)[:160]}")
        elif isinstance(d, list):
            print(f"  {st}  {name} → list({len(d)}) 첫={json.dumps(d[0], ensure_ascii=False)[:120] if d else '[]'}")
        else:
            print(f"  {st}  {name} → {d}")

    print("\n" + "=" * 78)
    print("④ CSV 컬럼 ↔ 빅파이낸스 필드 매핑")
    print("=" * 78)
    print("""  trade_history_long.csv (품목명·대분류·기준일·수출금액·단가):
    기준일     ← export/chart 행[0] YYYYMM → 월말 변환
    수출금액    ← export/chart 행[1] USD  ✔ JSON API 재현 가능
    단가       ← UI 모달 '수출 단가' 지표 별도 다운로드  ✘ JSON API엔 없음
    (export_volume 컬럼 없음 — volume_yoy는 금액÷단가로 파생)
    품목명/대분류 ← /launch-data/trade/industries (industryName/productName)

  company_trade_history_long.csv (품목명·기업명·기준일·수출금액·단가):
    기업별      ← EPIC '품목 커스텀 설정' 모달의 하위 기업  ✘ JSON breakdown 없음(UI 전용)
    (addresses/estimate=지역 단위, custom/groups=사용자 커스텀 그룹)""")


if __name__ == "__main__":
    main()
