"""수출·산업 모멘텀 스코어 배치 산출 → data/trade_scores.json (PHASE D).

★ 클라우드 안전: 스크레이핑 없음 — 원격 수출 CSV(공개 raw URL)와 리포 내 스냅샷
  (bf_industry.json/bf_creditcard.json)을 읽어 계산만 한다. daily_update.yml 등재 가능.
  스냅샷이 없으면 E렌즈(수출)만으로 graceful 동작(r_I=0).

출력 스키마 (모달/페이지가 recompute 없이 바로 읽는 용도):
  {generated_at, as_of,
   sectors:          {수출카테고리: SectorScore dict},   # E렌즈(수출 실측) 섹터
   industry_sectors: {앱섹터(secName): SectorScore dict}, # I렌즈(산업지표) 섹터
   companies:        {ticker: CompanyScore dict}}         # 유니버스 전 종목
  각 dict는 dataclass 전체 필드(점수·축·가중·프로파일·신뢰도·flags·insight).

실행: python3 scripts/update_trade_scores.py
"""
from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

OUT_PATH = BASE_DIR / "data" / "trade_scores.json"
KST = timezone(timedelta(hours=9))


def _round_floats(obj, nd: int = 4):
    """직렬화 전 float 반올림(파일 크기·diff 노이즈 절감)."""
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, dict):
        return {k: _round_floats(v, nd) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v, nd) for v in obj]
    return obj


def main():
    from epsrev.trade_score.pipeline import (compute_all,
                                             build_industry_sector_context)
    from epsrev.trade_score.loaders import load_industry_snapshot
    from epsrev.data.dashboard_data import CO

    tickers = sorted(CO.keys())
    print(f"[trade_scores] 유니버스 {len(tickers)}종목 배치 산출...")
    out = compute_all(tickers=tickers)

    # I렌즈 앱섹터 점수(모달 컨텍스트용) — compute_all 내부와 동일 스냅샷으로 재산출
    ind_ctx = build_industry_sector_context(load_industry_snapshot(), as_of=out["as_of"])

    payload = {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "as_of": f"{out['as_of']:%Y-%m}",
        "sectors": {sec: dataclasses.asdict(s) for sec, s in out["sectors"].items()},
        "industry_sectors": {sec: dataclasses.asdict(s)
                             for sec, s in ind_ctx["scores"].items()},
        "companies": {tk: dataclasses.asdict(c) for tk, c in out["companies"].items()},
    }
    payload = _round_floats(payload)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    n_scored = sum(1 for c in payload["companies"].values()
                   if c["company_score"] is not None)
    n_div = sum(1 for c in payload["companies"].values() if "divergence" in c["flags"])
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"  저장: {OUT_PATH.relative_to(BASE_DIR)} ({size_kb:,.0f}KB)")
    print(f"  as_of {payload['as_of']} · 수출섹터 {len(payload['sectors'])} · "
          f"산업섹터 {len(payload['industry_sectors'])} · "
          f"기업 {len(payload['companies'])}(점수 {n_scored}·발산 {n_div})")


if __name__ == "__main__":
    main()
