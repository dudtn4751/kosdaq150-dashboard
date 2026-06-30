"""
epsrev/adapters/fnspace_client.py
=================================
FnSpace(FnGuide) API 클라이언트 — "키 받으면 바로 연결되는 골격".

현 상태:
    - 실제 API 키/엔드포인트 미확정 → 호출은 None 반환(예외 X)이 정상.
    - 구독·콘솔 확인 후 **파일 최상단 설정 블록만** 채우면 바로 동작.

설계 원칙:
    - 엔드포인트/파라미터명/베이스URL은 최상단 설정 블록 한 곳에만 둔다.
      (다른 코드에 URL·파라미터 하드코딩 금지 — TODO[FNSPACE] 마커로 표시)
    - 키 없음/미설정/통신 실패 → 예외 대신 None.
    - 응답은 파일 캐시(종목+날짜+엔드포인트, TTL). 구성종목(universe)은
      1코인이 아니라 1000코인이므로 별도 장기 캐시(분기 1회).
    - 호출마다 예상 코인 소모를 로그로 남긴다.

이 파일은 "데이터 가져오기"만 책임진다. StockInput 변환은 fnspace.py(어댑터)에서.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except Exception:                       # 환경에 따라 경로 다를 수 있음
    Retry = None  # type: ignore

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


# =============================================================================
# ▼▼▼ 미확정 설정 블록 — 구독/콘솔 확인 후 여기'만' 채운다 (TODO[FNSPACE]) ▼▼▼
# =============================================================================
FNSPACE_BASE_URL = ""      # TODO[FNSPACE]: 구독 후 확인 (예: "https://www.fnspace.com/Api")

# 논리 엔드포인트명 → 실제 경로(베이스URL 뒤에 붙는 path 또는 전체 URL)
ENDPOINTS: dict[str, str] = {
    "forward":         "",   # TODO[FNSPACE]: 컨센서스-forward 지표 (12M Fwd EPS)
    "estimate_daily":  "",   # TODO[FNSPACE]: 추정실적-Daily (영업이익/당기순이익 일별)
    "estimate_fiscal": "",   # TODO[FNSPACE]: 추정실적-Fiscal (FY별 추정)
    "opinion_tp":      "",   # TODO[FNSPACE]: 투자의견 & 목표주가
    "financial":       "",   # TODO[FNSPACE]: 재무-종목별 재무정보 (어닝 서프라이즈)
    "universe":        "",   # TODO[FNSPACE]: 구성종목 (1000코인 — 장기 캐시 대상)
}

# 우리 코드가 쓰는 파라미터 '의미' → 실제 FnSpace 파라미터 '키 이름'
PARAMS: dict[str, str] = {
    "apikey": "apikey",      # TODO[FNSPACE]: 실제 키 파라미터명 확인 (예: "key"/"apikey")
    "code":   "",            # TODO[FNSPACE]: 종목코드 파라미터명 (예: "code")
    "item":   "",            # TODO[FNSPACE]: 항목 파라미터명 (예: "item"/"itm")
    "from":   "",            # TODO[FNSPACE]: 시작일 파라미터명
    "to":     "",            # TODO[FNSPACE]: 종료일 파라미터명
}

# 엔드포인트별 예상 코인 소모(가격표 기반 추정 — TODO[FNSPACE]: 콘솔에서 확정)
COIN_COST: dict[str, float] = {
    "forward":         0.125,
    "estimate_daily":  0.01,
    "estimate_fiscal": 0.01,
    "opinion_tp":      0.125,
    "financial":       0.125,
    "universe":        1000.0,   # 구성종목 — 분기 1회만 호출하도록 장기 캐시
}
# =============================================================================
# ▲▲▲ 설정 블록 끝 ▲▲▲
# =============================================================================


# ── 런타임 상수 ────────────────────────────────────────────────────────────────
API_KEY: str = os.environ.get("FNSPACE_API_KEY", "").strip()
FNSPACE_ENABLED: bool = bool(API_KEY)        # 키 없으면 비활성(호출 시 None)

TIMEOUT = 20                                  # 초
RETRY_TOTAL = 2
RETRY_BACKOFF = 0.5

CODE_PREFIX = "A"                             # FnGuide 종목코드 관례: 'A'+6자리 (TODO: 확인)

# 캐시
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "fnspace_cache"
DAILY_TTL_SEC = 12 * 3600                     # 일반 엔드포인트 TTL: 12시간
UNIVERSE_TTL_SEC = 90 * 24 * 3600             # 구성종목: 분기(≈90일)

logger = logging.getLogger("epsrev.fnspace")


# ── 세션(재시도/타임아웃) ───────────────────────────────────────────────────────
_session: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _session
    if _session is not None:
        return _session
    s = requests.Session()
    if Retry is not None:
        retry = Retry(
            total=RETRY_TOTAL,
            backoff_factor=RETRY_BACKOFF,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
        )
        adapter = HTTPAdapter(max_retries=retry)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
    _session = s
    return s


# ── 설정 검증 ─────────────────────────────────────────────────────────────────
def is_configured(endpoint: str) -> bool:
    """키·베이스URL·해당 엔드포인트 경로·필수 파라미터명이 모두 채워졌는지."""
    return bool(
        FNSPACE_ENABLED
        and FNSPACE_BASE_URL
        and ENDPOINTS.get(endpoint)
        and PARAMS.get("apikey")
        and PARAMS.get("code")
    )


def _build_url(endpoint: str) -> str:
    """ENDPOINTS 값이 절대 URL이면 그대로, 아니면 BASE_URL에 이어붙인다."""
    path = ENDPOINTS.get(endpoint, "")
    if path.startswith("http"):
        return path
    return f"{FNSPACE_BASE_URL.rstrip('/')}/{path.lstrip('/')}"


def _fmt_code(code: str) -> str:
    """'005930' → 'A005930' (이미 접두어 있으면 그대로)."""
    code = str(code).strip()
    if CODE_PREFIX and code and not code[0].isalpha():
        return f"{CODE_PREFIX}{code}"
    return code


# ── 코인 로그 ─────────────────────────────────────────────────────────────────
def _log_coin(endpoint: str, code: Optional[str], cached: bool) -> None:
    cost = COIN_COST.get(endpoint, 0.0)
    tag = "CACHE_HIT(0코인)" if cached else f"~{cost}코인"
    logger.info("[FNSPACE] %s code=%s 예상소모=%s", endpoint, code or "-", tag)


# ── 파일 캐시 ─────────────────────────────────────────────────────────────────
def _cache_path(endpoint: str, code: Optional[str], long_term: bool) -> Path:
    if long_term:
        q = (datetime.now().month - 1) // 3 + 1     # 분기 단위 키
        name = f"{endpoint}_{datetime.now().year}Q{q}.json"
    else:
        name = f"{endpoint}_{code or 'all'}_{date.today().isoformat()}.json"
    return CACHE_DIR / name


def _read_cache(path: Path, ttl_sec: int) -> Optional[Any]:
    try:
        if not path.exists():
            return None
        if (time.time() - path.stat().st_mtime) > ttl_sec:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_cache(path: Path, data: Any) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning("[FNSPACE] 캐시 저장 실패 %s: %s", path.name, e)


# ── 핵심 호출 ─────────────────────────────────────────────────────────────────
def call(
    endpoint: str,
    code: Optional[str] = None,
    *,
    item: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    long_term: bool = False,
    extra_params: Optional[dict] = None,
) -> Optional[Any]:
    """
    엔드포인트 호출 → 파싱된 JSON 반환. 실패/미설정/키없음 → None (예외 X).
    URL·파라미터는 전부 상단 설정 블록에서 가져온다(하드코딩 금지).
    """
    ttl = UNIVERSE_TTL_SEC if (long_term or endpoint == "universe") else DAILY_TTL_SEC
    is_long = long_term or endpoint == "universe"

    # 1) 캐시
    cpath = _cache_path(endpoint, code, is_long)
    cached = _read_cache(cpath, ttl)
    if cached is not None:
        _log_coin(endpoint, code, cached=True)
        return cached

    # 2) 미설정/비활성 → None (정상)
    if not is_configured(endpoint):
        if not FNSPACE_ENABLED:
            logger.debug("[FNSPACE] 키 없음 → None (FNSPACE_ENABLED=False)")
        else:
            logger.debug("[FNSPACE] '%s' 설정 미완료(TODO[FNSPACE]) → None", endpoint)
        return None

    # 3) 파라미터 조립 (의미→실제키 매핑)
    params: dict[str, str] = {PARAMS["apikey"]: API_KEY}
    if code and PARAMS.get("code"):
        params[PARAMS["code"]] = _fmt_code(code)
    if item and PARAMS.get("item"):
        params[PARAMS["item"]] = item
    if date_from and PARAMS.get("from"):
        params[PARAMS["from"]] = date_from
    if date_to and PARAMS.get("to"):
        params[PARAMS["to"]] = date_to
    if extra_params:
        params.update(extra_params)

    # 4) 호출
    _log_coin(endpoint, code, cached=False)
    try:
        r = _get_session().get(_build_url(endpoint), params=params, timeout=TIMEOUT)
        if r.status_code != 200:
            logger.warning("[FNSPACE] %s HTTP %s → None", endpoint, r.status_code)
            return None
        data = r.json()
    except Exception as e:
        logger.warning("[FNSPACE] %s 호출 실패: %s → None", endpoint, type(e).__name__)
        return None

    _write_cache(cpath, data)
    return data


# ── 얇은 래퍼(엔드포인트별) — 실제 파라미터는 설정 블록을 따른다 ───────────────────
def forward(code: str, item: Optional[str] = None) -> Optional[Any]:
    return call("forward", code, item=item)


def estimate_daily(code: str, date_from: Optional[str] = None,
                   date_to: Optional[str] = None, item: Optional[str] = None) -> Optional[Any]:
    return call("estimate_daily", code, item=item, date_from=date_from, date_to=date_to)


def estimate_fiscal(code: str, item: Optional[str] = None) -> Optional[Any]:
    return call("estimate_fiscal", code, item=item)


def opinion_tp(code: str) -> Optional[Any]:
    return call("opinion_tp", code)


def financial(code: str, item: Optional[str] = None) -> Optional[Any]:
    return call("financial", code, item=item)


def universe() -> Optional[Any]:
    """구성종목 — 1000코인. 분기 1회만 실제 호출(나머지는 장기 캐시)."""
    return call("universe", code=None, long_term=True)


# ── 자가 점검 ─────────────────────────────────────────────────────────────────
def status() -> dict:
    """현재 설정/활성 상태 요약 (디버그용)."""
    return {
        "FNSPACE_ENABLED": FNSPACE_ENABLED,
        "has_base_url": bool(FNSPACE_BASE_URL),
        "endpoints_set": {k: bool(v) for k, v in ENDPOINTS.items()},
        "configured": {k: is_configured(k) for k in ENDPOINTS},
        "cache_dir": str(CACHE_DIR),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import pprint
    print("=== FnSpace client 상태 ===")
    pprint.pprint(status())
    print("\n=== 호출 테스트(미설정이라 None 정상) ===")
    print("forward(005930) =>", forward("005930"))
    print("universe()      =>", universe())
