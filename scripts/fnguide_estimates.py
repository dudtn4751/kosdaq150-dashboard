"""① 다년 추정(FY1/FY2) + ③ 분기 서프라이즈 ingest — EPS Revision 모듈 빈칸 채우기.

클린 추정(무료 스크레이프로 못 얻는 다년·분기 컨센)을 `data/fnguide_estimates.json`에서 읽어
update_consensus가 각 종목 s['fn_est'](+surprise/dispersion/ytd)로 병합한다.
파일이 없으면 조용히 무시 → 무료 경로(히스토리 누적·역산) 유지. 파이프라인 안전.

estimates 파일 스키마:
  {"updated": "...", "estimates": { "<code>": {
      "op_fy1": {"now":.., "m1":.., "m3":..}, "op_fy2": {...},
      "eps_fy1": {"now":.., "m1":.., "m3":..}, "eps_fy2": {...},
      "surprise": [[actual_op, consensus_op], ...],   # 최근 4Q (③)
      "std":.., "mean":.., "age_days":..,             # dispersion(신뢰도)
      "ytd_op":.., "fy_roll": false                   # 선택
  }}}

획득 경로(택1):
  (A) DataGuide 엑셀 add-in으로 추정 export → 위 스키마 JSON으로 저장(권장, 약관·자격증명 안전).
  (B) FnGuide 로그인 수집: FNGUIDE_ID/FNGUIDE_PW 환경변수(GitHub Secret) 설정 시 fetch_via_login() 활성.
      ※ 비밀번호는 코드/대화에 두지 말고 Secret으로만. 자동수집은 약관·캡차·2FA 확인 필요.
"""

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
EST_PATH = PROJECT_ROOT / "data" / "fnguide_estimates.json"

_FN_KEYS = ("op_fy1", "op_fy2", "eps_fy1", "eps_fy2", "std", "mean", "age_days")


def load_estimates():
    """data/fnguide_estimates.json → {code: estimate}. 없거나 오류면 {}."""
    try:
        d = json.loads(EST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return d.get("estimates", d) if isinstance(d, dict) else {}


def fetch_via_login():
    """(B) 로그인 자동수집. FNGUIDE_ID/PW Secret 있으면 로그인(역설계 완료: RSA+CSRF).

    로그인은 구현·검증 완료(scripts/fnguide_session.py). 단 인증 후 트렌드 응답 포맷은
    첫 인증 실행에서 확정 예정 → parse_trend 구현 전까지는 {} 반환(안전). 활성 시 채워짐.
    """
    if not (os.environ.get("FNGUIDE_ID") and os.environ.get("FNGUIDE_PW")):
        return {}
    try:
        from fnguide_session import login, fetch_trend_raw, parse_trend  # noqa: F401
        sess = login()
        if not sess:
            print("  [fnguide] 로그인 실패 — 자격증명/약관 확인")
            return {}
        print("  [fnguide] 로그인 성공 — 추정 트렌드 파서 확정 후 수집 활성화(현재 보류)")
        # TODO: parse_trend 확정 후 종목별 fetch_trend_raw→parse_trend로 estimates 구성
        return {}
    except Exception as e:
        print(f"  [fnguide] 로그인 수집 건너뜀: {str(e)[:80]}")
        return {}


def merge_into(stocks):
    """stocks(consensus 종목 리스트)에 클린 추정을 병합. 반환: 병합 종목 수."""
    est = load_estimates() or fetch_via_login()
    if not est:
        return 0
    n = 0
    for s in stocks:
        e = est.get(s.get("code"))
        if not e:
            continue
        fn = {k: e[k] for k in _FN_KEYS if e.get(k) is not None}
        if fn:
            s["fn_est"] = fn
        if e.get("surprise"):
            s["surprise"] = [list(x)[:2] for x in e["surprise"] if x]
        if e.get("ytd_op") is not None:
            s["ytd_op"] = e["ytd_op"]
        if e.get("fy_roll") is not None:
            s["fy_roll"] = e["fy_roll"]
        n += 1
    return n
