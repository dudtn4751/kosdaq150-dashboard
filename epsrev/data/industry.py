"""epsrev/data/industry.py — 산업 데이터 provider 스텁.

seam: get_industry_data(ticker) 하나가 산업 데이터를 책임진다.
현재 미연동 → 빈 스키마 반환. UI는 '산업 데이터 연동 예정' 플레이스홀더.

TODO[INDUSTRY]: 빅파이낸스 Industry 섹션 연동 시 이 함수를 실제 조회로 교체.
  - 로그인 세션(scripts/bigfinance_session.py)으로 산업 지표 수집 → 스냅샷(data/*.json) → 여기서 읽기
  - 소비 지점: epsrev/pages/3_company_detail.py [5] 관련 데이터 섹션
  - 반환 예정 스키마: {"series": [{"m": "25.01", "val": ..., "yoy": ...}, ...], "unit": str, "note": str|None}
"""
from __future__ import annotations


def get_industry_data(ticker: str) -> dict:
    """종목 관련 산업 데이터. 미연동 → 빈 스키마(series 비어있음)."""
    # TODO[INDUSTRY]: 빅파이낸스 Industry 엔드포인트 연동 후 실제 데이터 반환
    return {"series": [], "unit": "", "note": None}
