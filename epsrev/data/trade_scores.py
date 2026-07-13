"""data/trade_scores.json 로더 — 수출·산업 모멘텀 스코어 배치 결과 읽기 전용.

recompute 없음(엔진 실행 X — scripts/update_trade_scores.py 산출물만 읽는다).
파일 부재/파싱 실패 → 빈 dict graceful (호출부는 '—' 표시).
streamlit 무의존(모듈 전역 캐시) — dashboard_data 등 import 시점에도 안전.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "trade_scores.json"
_CACHE: dict = {"mtime": None, "data": None}


def load_trade_scores() -> dict:
    """전체 스냅샷. 파일 mtime 기준 캐시(같은 프로세스 내 재파싱 방지)."""
    try:
        mtime = _PATH.stat().st_mtime
    except OSError:
        return {}
    if _CACHE["data"] is not None and _CACHE["mtime"] == mtime:
        return _CACHE["data"]
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    _CACHE.update(mtime=mtime, data=data)
    return data


def get_trade_score(ticker: str) -> Optional[dict]:
    """companies[ticker] (CompanyScore dict) 또는 None."""
    return (load_trade_scores().get("companies") or {}).get(str(ticker).zfill(6))


def get_export_sector(category: str) -> Optional[dict]:
    """수출 카테고리 SectorScore dict (E렌즈 컨텍스트)."""
    return (load_trade_scores().get("sectors") or {}).get(category)


def get_industry_sector(secname: str) -> Optional[dict]:
    """앱 섹터 SectorScore dict (I렌즈 컨텍스트)."""
    return (load_trade_scores().get("industry_sectors") or {}).get(secname)


def data_score_bucket(company_score, max_pts: int = 35) -> Optional[int]:
    """company_score(−100~+100) → 기존 데이터 점수 버킷(0~max_pts) 매핑."""
    if company_score is None:
        return None
    v = max(-100.0, min(100.0, float(company_score)))
    return int(round((v + 100.0) / 200.0 * max_pts))


def bucket_inverse(bucket_val, max_pts: int = 35) -> Optional[float]:
    """버킷 점수(0~max_pts) → −100~+100 역산. 없으면 None. [-100,100] 클립."""
    if bucket_val is None:
        return None
    return max(-100.0, min(100.0, float(bucket_val) / max_pts * 200.0 - 100.0))


def combined_alpha(eps, data) -> Optional[int]:
    """EPS·DATA(각 −100~+100) 동일 가중 평균 → round·clip[-100,100].
    한쪽 결측이면 나머지 단독(가중 1 재정규화). 둘 다 None이면 None."""
    parts = [float(p) for p in (eps, data) if p is not None]
    if not parts:
        return None
    return int(max(-100, min(100, round(sum(parts) / len(parts)))))
