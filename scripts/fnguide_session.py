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
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes, serialization
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
        pub = serialization.load_pem_public_key(_pem_reflow(mk.group(1)).encode())
        # JS rsaEncrypt = RSA-OAEP(SHA-256, MGF1-SHA256), 평문 UTF-8 → base64
        enc = base64.b64encode(pub.encrypt(
            pw.encode("utf-8"),
            padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                         algorithm=hashes.SHA256(), label=None),
        )).decode()
        def _submit(login_type):
            files = {"loginType": (None, login_type), "userId": (None, uid),
                     "userPassword": (None, enc)}
            resp = s.post(LOGIN_POST, files=files, timeout=15, headers={"Referer": LOGIN_PAGE})
            try:
                return resp, str(resp.json().get("returnCode"))
            except Exception:
                return resp, ("0" if '"returnCode":"0"' in resp.text else "?")

        r, code = _submit("1")
        # 80115/80116: 다른 기기 세션 존재 → loginType=2 강제 로그인(다른 기기 로그아웃).
        # FNGUIDE_FORCE=0 이면 강제 안 함(브라우저 세션 보호). 기본 강제(무인 자동화용).
        if code in ("80115", "80116") and os.environ.get("FNGUIDE_FORCE", "1") == "1":
            r, code = _submit("2")
        if code != "0":
            print(f"FnGuide 로그인 실패 returnCode={code}")
        ok = code == "0"
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


# ── 리서치 리포트 (SearchReport / GetReports / GetPdfFile) ─────────────────────
REPORTS_URL = "https://www.fnguide.com/Research/GetReports"
VIEWER_URL = "https://www.fnguide.com/Research/PdfViewer"
GETPDF_URL = "https://www.fnguide.com/Research/GetPdfFile"
_SR_REFERER = "https://www.fnguide.com/Research/SearchReport"


def fetch_reports(session, payload=None):
    """GetReports → 리포트 메타 리스트(dataSet.reports). 실패 시 []."""
    try:
        r = session.post(REPORTS_URL, timeout=20,
                         headers={"X-Requested-With": "XMLHttpRequest", "Referer": _SR_REFERER},
                         data=payload)
        ds = r.json().get("dataSet")
        return (ds or {}).get("reports", []) if ds else []
    except Exception:
        return None if False else []


def fetch_recent_company_reports(session, max_pages=4, per_page=100):
    """기업 탭(menuCd=1010) 최근 리포트를 페이지네이션으로 전 종목 수집(TYP==1).

    워치리스트 불필요 — 나온 리포트를 매일 넓게 긁어 merge하면 종목당 최신 3개가 누적됨.
    max_pages×per_page 만큼 최근 리포트를 훑음(당일 종목별 클러스터 포착용). 실패 시 [].
    """
    import time as _t
    out = []
    for page in range(1, max_pages + 1):
        files = {"menuCd": (None, "1010"), "curPage": (None, str(page)),
                 "perPage": (None, str(per_page))}
        try:
            r = session.post(REPORTS_URL, timeout=25,
                             headers={"X-Requested-With": "XMLHttpRequest", "Referer": _SR_REFERER},
                             files=files)
            reps = (r.json().get("dataSet") or {}).get("reports", [])
        except Exception:
            break
        if not reps:
            break
        out.extend(x for x in reps if (x.get("CATEGORY") or {}).get("TYP") == 1)
        if len(reps) < per_page:
            break
        _t.sleep(0.5)
    return out


def fetch_stock_reports(session, code, per_page=3):
    """종목코드 → 그 종목의 최신 리포트 per_page개(기업 탭 srchCode 검색, 날짜 내림차순).

    payload: menuCd=1010(기업 탭), srchCode=종목코드, srchTyp=1(코드검색). 실패 시 [].
    """
    files = {
        "menuCd":   (None, "1010"),
        "srchCode": (None, str(code).zfill(6)),
        "srchTyp":  (None, "1"),
        "curPage":  (None, "1"),
        "perPage":  (None, str(per_page)),
    }
    try:
        r = session.post(REPORTS_URL, timeout=20,
                         headers={"X-Requested-With": "XMLHttpRequest", "Referer": _SR_REFERER},
                         files=files)
        ds = r.json().get("dataSet")
        return (ds or {}).get("reports", []) if ds else []
    except Exception:
        return []


def get_report_pdf(session, rpt_id):
    """rptId → PDF bytes. PdfViewer에서 documentData(HTML 이스케이프됨) 추출 →
    GetPdfFile POST → data-URI base64 디코드. 실패 시 None."""
    import html as _html
    try:
        vhtml = session.get(f"{VIEWER_URL}?rptId={rpt_id}", timeout=20,
                            headers={"Referer": _SR_REFERER}).text
        m = re.search(r'name="documentData"[^>]*value="([^"]*)"', vhtml)
        if not m:
            return None
        dd = _html.unescape(m.group(1))
        r = session.post(GETPDF_URL, timeout=40,
                         headers={"Origin": "https://www.fnguide.com",
                                  "X-Requested-With": "XMLHttpRequest",
                                  "Referer": f"{VIEWER_URL}?rptId={rpt_id}"},
                         files={"documentData": (None, dd)})
        if r.status_code != 200:
            return None
        data = r.json().get("dataSet", "")
        if isinstance(data, str) and "base64," in data:
            return base64.b64decode(data.split("base64,", 1)[1])
        return None
    except Exception:
        return None


def get_report_pdf_text(session, rpt_id):
    """rptId → PDF 본문 텍스트(pdfplumber). 실패/스캔본이면 ''."""
    import io
    pdf = get_report_pdf(session, rpt_id)
    if not pdf:
        return ""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf)) as doc:
            return "\n".join((p.extract_text() or "") for p in doc.pages).strip()
    except Exception:
        return ""


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
