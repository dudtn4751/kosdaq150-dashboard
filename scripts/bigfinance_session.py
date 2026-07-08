"""빅파이낸스(에픽 파이낸스, bigfinance.co.kr) 로그인 세션 — Mac 로컬 전용.

클라우드 실행 금지(단일세션·차단 리스크). 노트북에서 수동 온디맨드로만 실행.

인증 흐름(Laravel Sanctum 스타일 더블서브밋 CSRF):
  1. GET  /api/csrf-cookie            → XSRF-TOKEN 쿠키 발급(401이지만 쿠키는 심어짐)
  2. POST /api/login/enterprise       헤더 X-XSRF-TOKEN=쿠키값, JSON {username,password}
  3. 이후 API 호출은 세션 쿠키로 인증

자격증명은 .env(BIGFINANCE_ID / BIGFINANCE_PW)에서만 읽는다. 채팅/커맨드라인 금지.
"""
from __future__ import annotations

import os
import urllib.parse

import requests

BASE = "https://bigfinance.co.kr"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")


def _creds():
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except Exception:
        pass
    uid = os.environ.get("BIGFINANCE_ID")
    pw = os.environ.get("BIGFINANCE_PW")
    if not uid or not pw:
        raise RuntimeError("BIGFINANCE_ID / BIGFINANCE_PW 환경변수(.env)가 필요합니다.")
    return uid, pw


def login(timeout: int = 20) -> requests.Session:
    """로그인된 requests.Session 반환. 실패 시 RuntimeError."""
    uid, pw = _creds()
    s = requests.Session()
    s.headers.update({
        "User-Agent": _UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": BASE,
        "Referer": f"{BASE}/login",
    })
    # 1) CSRF 쿠키
    s.get(f"{BASE}/api/csrf-cookie", timeout=timeout)
    xsrf = urllib.parse.unquote(s.cookies.get("XSRF-TOKEN", "") or "")
    if not xsrf:
        raise RuntimeError("XSRF-TOKEN 쿠키 발급 실패")
    # 2) 로그인
    r = s.post(
        f"{BASE}/api/login/enterprise",
        json={"username": uid, "password": pw},
        headers={"X-XSRF-TOKEN": xsrf, "Content-Type": "application/json"},
        timeout=timeout,
    )
    if r.status_code != 200:
        msg = ""
        try:
            msg = r.json().get("errorMessage", "")
        except Exception:
            msg = r.text[:120]
        raise RuntimeError(f"로그인 실패({r.status_code}): {msg}")
    return s


def api_get(session: requests.Session, path: str, params: dict | None = None,
            timeout: int = 20):
    """로그인 세션으로 내부 API GET → JSON. path는 '/api/...' 또는 절대URL."""
    url = path if path.startswith("http") else f"{BASE}{path}"
    # 매 요청 XSRF 헤더 갱신(쿠키 회전 대비)
    xsrf = urllib.parse.unquote(session.cookies.get("XSRF-TOKEN", "") or "")
    headers = {"X-XSRF-TOKEN": xsrf} if xsrf else {}
    r = session.get(url, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _bf_code(ticker: str) -> str:
    """'005930' → 'A005930'. 이미 A로 시작하면 그대로."""
    t = str(ticker).strip().upper()
    return t if t.startswith("A") else "A" + t.zfill(6)


def fetch_fscore(session: requests.Session, ticker: str, timeout: int = 20) -> dict:
    """실적(fsCore) 원본 JSON. 종목코드(6자리) 자동으로 A접두 처리."""
    code = _bf_code(ticker)
    return api_get(session, f"/api/fsCore/{code}",
                   params=None, timeout=timeout)


def fetch_export_chart(session: requests.Session, industry_code: int, product_code: int,
                       kind: str = "confirm", timeout: int = 20):
    """산업/제품 월별 수출 시계열 원본 [[YYYYMM, USD, yoy], ...].
    kind: confirm(확정치)/provisional(잠정치)."""
    return api_get(session,
                   f"/api/launch-data/trade/industries/{industry_code}/{product_code}/{kind}/export/chart",
                   params=None, timeout=timeout)


if __name__ == "__main__":
    # 스모크 테스트: 로그인만 확인(자격증명 값은 출력 안 함)
    try:
        sess = login()
        print("로그인 성공 · 세션 쿠키:", [k for k in sess.cookies.keys()])
    except Exception as e:
        print("로그인 실패:", e)
