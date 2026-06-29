"""
universe.py
-----------
섹터 유니버스 로더 — 종목_유니버스_260628.csv 기반
기존 하드코딩 UNIVERSE 딕셔너리를 대체합니다.

사용법:
    from epsrev.universe import get_universe, get_sector_tickers, SECTORS
"""

from __future__ import annotations

import re
from pathlib import Path
from functools import lru_cache

import pandas as pd
import streamlit as st

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
# 이 파일 기준 상대 경로. 실제 위치에 맞게 수정하세요.
_CSV_PATH = Path(__file__).parent / "data" / "종목_유니버스_260628.csv"

# ── 섹터 목록 (순서 고정) ──────────────────────────────────────────────────────
SECTORS: list[str] = [
    "반도체",
    "전기전자",
    "2차전지·배터리소재",
    "자동차·모빌리티",
    "조선·방산·우주항공",
    "전력기기·전력인프라·원전",
    "바이오·의료기기",
    "K소비재·유통",
    "인터넷·소프트웨어·게임·콘텐츠",
    "금융·지주",
    "철강·비철금속",
    "정유·화학·석유화학",
    "건설·운송·상사",
]


def _is_special_ticker(code: str) -> bool:
    """알파벳이 섞인 우선주/전환주 코드 여부 (ex. 00680K, 0126Z0)."""
    return bool(re.search(r"[A-Za-z]", code))


def _normalize_ticker(code: str) -> str:
    """
    종목코드 정규화:
    - 일반 코드 → 6자리 zero-padding  (5930 → 005930)
    - 특수 코드 (알파벳 포함) → 그대로 유지  (00680K → 00680K)
    """
    code = str(code).strip()
    if _is_special_ticker(code):
        return code
    return code.zfill(6)


@st.cache_data(ttl=3600, show_spinner=False)
def get_universe(include_special: bool = False) -> pd.DataFrame:
    """
    유니버스 DataFrame 반환.

    Parameters
    ----------
    include_special : bool
        True면 알파벳 포함 특수 코드(우선주 등)도 포함.
        False면 순수 6자리 숫자 코드만 반환 (기본값).

    Returns
    -------
    pd.DataFrame
        columns: [종목코드, 종목명, 시가총액, 섹터]
        종목코드는 모두 정규화된 문자열.
    """
    df = pd.read_csv(_CSV_PATH, dtype=str, encoding="utf-8-sig")

    # 컬럼명 정리 (앞뒤 공백 제거)
    df.columns = df.columns.str.strip()

    # 필요한 컬럼만 추출 — '섹터분류' 열은 참고용이므로 제외
    df = df[["종목코드", "종목명", "시가총액", "섹터"]].copy()

    # 빈 행 제거
    df = df.dropna(subset=["종목코드", "섹터"])
    df = df[df["종목코드"].str.strip() != ""]
    df = df[df["섹터"].str.strip() != ""]

    # 종목코드 정규화
    df["종목코드"] = df["종목코드"].apply(_normalize_ticker)

    # 시가총액 숫자 변환
    df["시가총액"] = pd.to_numeric(df["시가총액"], errors="coerce")

    # 특수 코드 필터
    if not include_special:
        mask = df["종목코드"].apply(lambda x: not _is_special_ticker(x))
        df = df[mask]

    # 섹터 컬럼을 Categorical로 — 정렬/필터 성능 향상
    sector_order = [s for s in SECTORS if s in df["섹터"].unique()]
    df["섹터"] = pd.Categorical(df["섹터"], categories=sector_order, ordered=True)

    return df.reset_index(drop=True)


def get_sector_tickers(sector: str, include_special: bool = False) -> list[str]:
    """
    특정 섹터의 종목코드 리스트 반환.

    Example
    -------
    >>> tickers = get_sector_tickers("반도체")
    >>> # ['005930', '000660', '042700', ...]
    """
    df = get_universe(include_special=include_special)
    return df.loc[df["섹터"] == sector, "종목코드"].tolist()


def get_ticker_sector(ticker: str) -> str | None:
    """종목코드 → 섹터명 반환. 유니버스에 없으면 None."""
    ticker = _normalize_ticker(ticker)
    df = get_universe(include_special=True)
    row = df[df["종목코드"] == ticker]
    if row.empty:
        return None
    return row.iloc[0]["섹터"]


def get_ticker_name(ticker: str) -> str | None:
    """종목코드 → 종목명 반환. 유니버스에 없으면 None."""
    ticker = _normalize_ticker(ticker)
    df = get_universe(include_special=True)
    row = df[df["종목코드"] == ticker]
    if row.empty:
        return None
    return row.iloc[0]["종목명"]


def sector_summary() -> pd.DataFrame:
    """섹터별 종목 수 + 시가총액 합계 요약 DataFrame."""
    df = get_universe()
    summary = (
        df.groupby("섹터", observed=True)
        .agg(
            종목수=("종목코드", "count"),
            시가총액합계=("시가총액", "sum"),
        )
        .reset_index()
        .sort_values("시가총액합계", ascending=False)
    )
    summary["시가총액합계_조"] = (summary["시가총액합계"] / 1e12).round(1)
    return summary


# ── 기존 UNIVERSE 딕셔너리 호환 레이어 ─────────────────────────────────────────
@lru_cache(maxsize=1)
def _build_legacy_universe() -> dict[str, list[str]]:
    """
    기존 코드가 UNIVERSE[sector] 형태로 접근하는 경우를 위한 호환 딕셔너리.
    CSV 기반으로 자동 생성하므로 하드코딩 불필요.

    Example (기존 코드 그대로 동작)
    --------------------------------
    from epsrev.universe import UNIVERSE
    tickers = UNIVERSE["반도체"]
    """
    df = get_universe()
    return {
        sector: df.loc[df["섹터"] == sector, "종목코드"].tolist()
        for sector in SECTORS
        if sector in df["섹터"].values
    }


class _UniverseProxy(dict):
    """UNIVERSE 딕셔너리를 지연 로딩하는 프록시."""
    def __missing__(self, key):
        self.update(_build_legacy_universe())
        return self[key]

    def __repr__(self):
        self.update(_build_legacy_universe())
        return super().__repr__()


# 기존 코드에서 `from universe import UNIVERSE` 사용 가능
UNIVERSE = _UniverseProxy()