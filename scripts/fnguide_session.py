"""FnGuide 로그인 세션 + 컨센서스 추정 트렌드 수집 (① 다년 추정).

FnGuide 로그인 역설계 결과(2026-06 확인):
  - 로그인 폼: https://www.fnguide.com/Users/Login  (캡차·2FA 없음)
  - 제출: POST https://www.fnguide.com/Users/UserLogin (multipart FormData)
    필드: loginType=1, userId, userPassword=RSA_PKCS1v1.5(공개키, 비번)→base64, __RequestVerificationToken
    공개키·CSRF토큰은 로그인 페이지 HTML에 임베드. 성공 시 JSON {"returnCode":"0"}.
  - 추정 트렌드(로그인 필요): https://cdn.fnguide.com/SVO/Handbook_New/xml/svd_con_finan_trd_data.asp
    ?chart_gicode=A<code>&chart_data_type=<2영업이익|5EPS>&chart_report_gb=D&chart_gs_gb=
    (비로그인은 500)

자격증명: 환경변수 FNGUIDE_ID / FNGUIDE_PW (GitHub Secret). 없으면 비활성(None).
※ 비밀번호는 코드/대화에 두지 말 것. requests·rsa 필요.
※ 인증 후 트렌드 응답 포맷은 첫 인증 실행에서 확정(parse_trend). self-test: python scripts/fnguide_session.py
"""

import base64
import os
import re

try:
    import requests
    import rsa
    _DEPS = True
except Exception:
    _DEPS = False

LOGIN_PAGE = "https://www.fnguide.com/Users/Login"
LOGIN_POST = "https://www.fnguide.com/Users/UserLogin"
TREND_URL = "https://cdn.fnguide.com/SVO/Handbook_New/xml/svd_con_finan_trd_data.asp"
UA = "Mozilla/5.0"


def _pem_reflow(pem):
    body = pem.replace("-----BEGIN PUBLIC KEY-----", "").replace("-----END PUBLIC KEY-----", "").strip()
    return ("-----BEGIN PUBLIC KEY-----\n"
            + "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
            + "\n-----END PUBLIC KEY-----\n")


def login():
    """FNGUIDE_ID/PW로 로그인 → 인증된 requests.Session 반환. 실패/미설정 시 None."""
    if not _DEPS:
        return None
    uid, pw = os.environ.get("FNGUIDE_ID"), os.environ.get("FNGUIDE_PW")
    if not uid or not pw:
        return None
    try:
        s = requests.Session()
        s.headers["User-Agent"] = UA
        html = s.get(LOGIN_PAGE, timeout=15).text
        mk = re.search(r'publicKey\s*=\s*"([^"]+)"', html)
        if not mk:
            return None
        pub = rsa.PublicKey.load_pkcs1_openssl_pem(_pem_reflow(mk.group(1)).encode())
        enc = base64.b64encode(rsa.encrypt(pw.encode(), pub)).decode()
        tok_m = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', html)
        token = tok_m.group(1) if tok_m else ""
        # JS는 FormData(multipart)로 전송 → files= 사용
        files = {"loginType": (None, "1"), "userId": (None, uid), "userPassword": (None, enc)}
        if token:
            files["__RequestVerificationToken"] = (None, token)
        r = s.post(LOGIN_POST, files=files, timeout=15,
                   headers={"Referer": LOGIN_PAGE, "RequestVerificationToken": token})
        try:
            ok = r.json().get("returnCode") == "0"
        except Exception:
            ok = "returnCode" in r.text and '"0"' in r.text
        return s if ok else None
    except Exception:
        return None


def fetch_trend_raw(session, code, data_type):
    """추정 트렌드 원시 응답(인증 세션). data_type: 2=영업이익, 5=EPS. 실패 시 None."""
    try:
        params = {"chart_gicode": f"A{code}", "chart_data_type": str(data_type),
                  "chart_report_gb": "D", "chart_gs_gb": ""}
        r = session.get(TREND_URL, params=params, timeout=15,
                        headers={"Referer": "https://comp.fnguide.com/SVO2/ASP/SVD_Consensus.asp"})
        txt = r.text
        return None if ("<title>500" in txt or len(txt) < 30) else txt
    except Exception:
        return None


def parse_trend(raw):
    """트렌드 응답 → {연도/시점: 값} 파싱. 인증 응답 포맷 확정 후 구현(현재 raw 길이만 반환)."""
    # TODO: 첫 인증 실행에서 fetch_trend_raw 출력 포맷 확인 후 정밀 파서 작성.
    return None


if __name__ == "__main__":
    if not _DEPS:
        print("requests/rsa 미설치 — pip install requests rsa")
        raise SystemExit(1)
    sess = login()
    if not sess:
        print("로그인 실패/미설정 — FNGUIDE_ID/FNGUIDE_PW 환경변수 확인")
        raise SystemExit(1)
    print("로그인 성공. 추정 트렌드 응답 샘플(005930, 영업이익):")
    raw = fetch_trend_raw(sess, "005930", 2)
    print(f"  len={len(raw) if raw else 0}")
    if raw:
        print(raw[:800])
