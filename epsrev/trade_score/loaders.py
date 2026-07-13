"""입력 로더 연결(STEP 0: 배선만, 계산 없음).

소스 4종:
  1) 수출(실측)  : trade_utils_data.compute_item_metrics / compute_company_metrics
  2) 산업지표    : data/bf_industry.json      (다음 PHASE 스크레이프 산출물 — 없으면 빈 스키마)
  3) 신용카드    : data/bf_creditcard.json    (동상 — 없으면 빈 스키마)
  4) 매핑 config : epsrev/data/industry_config (SECTOR_INDUSTRY·SECTOR_CREDITCARD·
                   COMPANY_CREDITCARD — 각 지표에 src·series_type·freq 필드 포함)
"""
from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # repo root
DATA_DIR = BASE_DIR / "data"
INDUSTRY_JSON = DATA_DIR / "bf_industry.json"
CREDITCARD_JSON = DATA_DIR / "bf_creditcard.json"

# 빈 스냅샷 스키마(파일 부재 시 반환) — 스크레이퍼 산출 스키마와 동일 골격
_EMPTY_INDUSTRY = {"generated_at": None, "series": {}}   # series: {"{code}/{sub}": {"label","freq","series_type","points":[[ym,val],...]}}
_EMPTY_CREDITCARD = {"generated_at": None, "sectors": {}, "companies": {}}  # "{lCode}/{mCode}" / "{ticker}"


def load_export_metrics():
    """수출(실측): (item_metrics_df, company_metrics_df). trade_utils_data 재사용.
    yoy·mom·price_yoy·volume_yoy·ma3_yoy·ma3_yoy_prev 컬럼 포함."""
    from trade_utils_data import (load_history, load_company_history,
                                  compute_item_metrics, compute_company_metrics)
    df, _ = load_history()
    item_m = compute_item_metrics(df)
    comp_m = compute_company_metrics(load_company_history())
    return item_m, comp_m


def load_industry_snapshot() -> dict:
    """산업지표 스냅샷. 파일 없으면 빈 스키마(graceful — I렌즈 r_I=0 경로)."""
    if not INDUSTRY_JSON.exists():
        return dict(_EMPTY_INDUSTRY)
    try:
        return json.loads(INDUSTRY_JSON.read_text(encoding="utf-8"))
    except Exception:
        return dict(_EMPTY_INDUSTRY)


def load_creditcard_snapshot() -> dict:
    """신용카드 소비 스냅샷. 파일 없으면 빈 스키마(graceful)."""
    if not CREDITCARD_JSON.exists():
        return dict(_EMPTY_CREDITCARD)
    try:
        return json.loads(CREDITCARD_JSON.read_text(encoding="utf-8"))
    except Exception:
        return dict(_EMPTY_CREDITCARD)


def load_mapping_config():
    """매핑 config: (SECTOR_INDUSTRY, SECTOR_CREDITCARD, COMPANY_CREDITCARD).
    SECTOR_INDUSTRY 항목엔 src("industry"|"trade")·series_type("growth"|"level")·freq 포함."""
    from epsrev.data.industry_config import (SECTOR_INDUSTRY, SECTOR_CREDITCARD,
                                             COMPANY_CREDITCARD)
    return SECTOR_INDUSTRY, SECTOR_CREDITCARD, COMPANY_CREDITCARD
