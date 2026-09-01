#!/usr/bin/env python3
"""daily CI 신선도 감시 — CI가 *아예 안 돌아도* 알아채기 위한 로컬 감시자. ★로컬 전용.

워크플로 안의 실패 알림은 "실행됐는데 실패한" 경우만 잡는다. 스케줄이 비활성화되거나
Actions 사용량이 소진돼 아예 실행되지 않으면 아무 알림도 오지 않는다. 이 스크립트는
origin/main의 핵심 데이터 파일이 마지막으로 갱신된 날짜를 보고, 평일 기준으로 오늘치가
없으면 텔레그램으로 경고한다.

알림 라우팅 ★: TELEGRAM_CHAT_ID(수출 단체방)에는 **수출 데이터 관련 알림만** 간다.
비수출(daily CI 정체 등)은 TELEGRAM_OPS_CHAT_ID로만 보내고, 미설정이면 콘솔 출력에 그친다.
자격증명은 .env에서만 읽는다(하드코딩 금지).
또한 GitHub의 수출입 CSV 최신일 vs 배포(Render) /healthz가 신고하는 기준일·커밋을 대조해,
CSV는 올라갔는데 배포만 옛 데이터인 상태("배포가 데이터보다 뒤처짐")도 잡는다.

실행: python3 scripts/check_data_freshness.py [--max-age-days N] [--deploy-only]
"""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

WATCH = [
    "data/kr_market.json",
    "data/market_signal.json",
    "data/us_events.json",
    "data/research_reports.json",
]


def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=BASE_DIR, capture_output=True,
                          text=True).stdout.strip()


def last_commit_date(path: str):
    """origin/main 기준 해당 파일의 마지막 커밋 날짜(KST 기준 date)."""
    out = _git("log", "origin/main", "-1", "--format=%cd", "--date=format-local:%Y-%m-%d", "--", path)
    try:
        return datetime.strptime(out, "%Y-%m-%d").date()
    except ValueError:
        return None


TRADE_CHAT_ENV = "TELEGRAM_CHAT_ID"        # 수출 데이터 단체방 — 수출 관련 알림만 간다
OPS_CHAT_ENV = "TELEGRAM_OPS_CHAT_ID"      # 그 외 운영 알림(CI 정체 등). 미설정이면 콘솔만


def send_telegram(text: str, chat_env: str = TRADE_CHAT_ENV) -> bool:
    """★수출 단체방(TELEGRAM_CHAT_ID)에는 수출 데이터 관련 알림만 보낸다.
    비수출(daily CI 정체 등)은 OPS_CHAT_ENV로만 — 미설정이면 콘솔 출력에 그친다."""
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get(chat_env)
    if not (tok and chat):
        print(f"[정보] {chat_env} 미설정 — 콘솔 출력만 (전송 안 함)")
        return False
    try:
        import requests

        r = requests.post(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            data={"chat_id": chat, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True}, timeout=20,
        )
        ok = r.json().get("ok", False)
        print("[정보] 텔레그램 전송", "성공" if ok else f"실패: {str(r.text)[:120]}")
        return ok
    except Exception as e:
        print(f"[경고] 텔레그램 전송 예외: {type(e).__name__}: {str(e)[:120]}")
        return False



# ── 배포(Render) 최신성 대조 ──────────────────────────────────────────────────
# CI/스크래퍼가 CSV를 GitHub에 올렸어도 Render 배포가 실패·정체하면 팀원이 보는 화면만
# 옛 데이터로 남는다. 이 경우 위의 커밋 날짜 감시로는 절대 잡히지 않는다 —
# 배포된 /healthz가 스스로 신고하는 기준일·커밋을 origin/main과 직접 대조한다.
TRADE_CSV = {
    "decade_latest": "data/trade_dashboard/trade_history_decade_long.csv",
    "month_latest": "data/trade_dashboard/trade_history_long.csv",
    "company_latest": "data/trade_dashboard/company_trade_history_long.csv",
}


def _csv_latest_date(path: str, fmt: str):
    """origin/main에 올라간 CSV의 date 컬럼 최대값. 배포가 따라와야 할 목표치."""
    blob = _git("show", f"origin/main:{path}")
    if not blob:
        return None
    import csv
    import io

    rows = csv.DictReader(io.StringIO(blob))
    col = next((c for c in (rows.fieldnames or []) if c in ("date", "기준일")), None)
    if not col:
        return None
    best = max((r[col] for r in rows if r.get(col)), default=None)
    if not best:
        return None
    d = datetime.strptime(best[:10], "%Y-%m-%d").date()
    return d.strftime(fmt)


HEALTHZ_TIMEOUT = 60       # Render 무료 플랜 콜드스타트는 수십 초까지 걸린다
DEPLOY_GRACE_MIN = 15      # 방금 push한 커밋은 아직 배포 중 — 이 시간까진 뒤처짐으로 안 본다
HEALTHZ_RETRY_WAIT = 30   # 1차 요청이 인스턴스를 깨우므로, 그 시간을 주고 다시 묻는다


def _get_healthz(url: str, timeout: int):
    import requests

    r = requests.get(url.rstrip("/") + "/healthz", timeout=timeout)
    return r.json()


def fetch_healthz(url: str):
    """슬립 인지형 조회.

    Render 무료 플랜은 유휴 시 인스턴스를 재운다. 잠든 상태의 첫 요청은 콜드스타트를
    기다리다 타임아웃하기 쉬운데, 그 요청 자체가 기상 트리거다. 따라서 1차 실패는
    장애가 아니라 '자고 있었다'는 뜻일 뿐이므로 경보 대상이 아니다 —
    30초 뒤 2차까지 실패해야 진짜 응답 없음으로 본다."""
    try:
        return _get_healthz(url, HEALTHZ_TIMEOUT)
    except Exception as e:
        first = f"{type(e).__name__}: {str(e)[:120]}"

    print(f"[정보] healthz 1차 실패({first}) — 슬립 추정. "
          f"{HEALTHZ_RETRY_WAIT}초 대기 후 재시도합니다.")
    time.sleep(HEALTHZ_RETRY_WAIT)
    try:
        h = _get_healthz(url, HEALTHZ_TIMEOUT)
        print("[정보] healthz 2차 성공 — 슬립에서 기상. 경보 없음.")
        return h
    except Exception as e:
        return {"_error": f"1차 {first} / 2차 {type(e).__name__}: {str(e)[:120]}"}


def check_deploy() -> list:
    """배포 healthz vs origin/main 대조. 불일치 항목 리스트를 반환(빈 리스트=정상)."""
    url = (os.environ.get("TRADE_WEB_URL") or "").strip()
    if not url or url.startswith("http://127.0.0.1") or url.startswith("http://localhost"):
        print("[정보] TRADE_WEB_URL 미설정(또는 로컬) — 배포 대조 생략")
        return []

    h = fetch_healthz(url)
    if "_error" in h:
        # 여기까지 왔다면 1차·2차 모두 실패 — 슬립이 아니라 진짜 장애다.
        print(f"[경고] healthz 2회 연속 실패: {h['_error']}")
        return [f"배포 healthz 응답 없음 ({url}, {HEALTHZ_TIMEOUT}s×2회) — {h['_error']}"]

    problems = []
    if not h.get("ok", False):
        problems.append(f"배포 healthz ok=false — {h.get('error', '원인 미상')}")

    # (1) 데이터 기준일: GitHub CSV가 배포보다 앞서 있으면 배포가 뒤처진 것
    for key, path in TRADE_CSV.items():
        fmt = "%Y-%m-%d" if key == "decade_latest" else "%Y-%m"
        want, got = _csv_latest_date(path, fmt), h.get(key)
        if want and got and got < want:
            problems.append(f"{key}: 배포 <b>{got}</b> ← GitHub <b>{want}</b> (배포가 뒤처짐)")
        elif want and not got:
            problems.append(f"{key}: 배포가 값을 보고하지 않음(구버전 healthz일 수 있음)")
        else:
            print(f"[정보] {key}: 배포 {got} / GitHub {want}")

    # (2) 커밋 해시: 배포 커밋이 origin/main HEAD와 다르면 배포 정체
    head = _git("rev-parse", "origin/main")
    dep = h.get("commit")
    if head and dep and dep != head:
        behind = _git("rev-list", "--count", f"{dep}..{head}") or "?"
        # 배포에는 1~2분이 걸린다. 방금 push한 직후의 해시 불일치는 정상 상태이지
        # 정체가 아니므로, HEAD가 충분히 오래됐을 때만 경보한다(슬립 오인과 같은 부류).
        ts = _git("log", "-1", "--format=%ct", "origin/main")
        age_min = (time.time() - int(ts)) / 60 if ts.isdigit() else 1e9
        if age_min < DEPLOY_GRACE_MIN:
            print(f"[정보] 커밋: 배포 {dep[:7]} ← origin/main {head[:7]} — "
                  f"최신 커밋이 {age_min:.0f}분 전이라 배포 진행 중으로 간주"
                  f"(유예 {DEPLOY_GRACE_MIN}분). 경보 없음.")
        else:
            problems.append(f"커밋: 배포 <code>{dep[:7]}</code> ← origin/main <code>{head[:7]}</code> "
                            f"({behind}커밋 뒤처짐 · {age_min/60:.1f}시간 경과)")
    elif head and not dep:
        problems.append("커밋: 배포가 commit을 보고하지 않음(RENDER_GIT_COMMIT 미주입 또는 구버전)")
    else:
        print(f"[정보] 커밋: 배포 {(dep or '?')[:7]} == origin/main {(head or '?')[:7]}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-days", type=int, default=1,
                    help="이 일수보다 오래되면 경고(기본 1 — 어제까지는 허용)")
    ap.add_argument("--no-deploy-check", action="store_true",
                    help="배포(Render) healthz 대조를 건너뛴다")
    ap.add_argument("--deploy-only", action="store_true",
                    help="배포 대조만 수행(CI 커밋 날짜 감시 생략)")
    args = ap.parse_args()

    subprocess.run(["git", "fetch", "origin", "-q"], cwd=BASE_DIR, check=False)
    if args.deploy_only:
        WATCH.clear()
    today = datetime.now().date()
    # 주말엔 평일 마지막 갱신을 기준으로 판단(토=금, 일=금)
    ref = today - timedelta(days={5: 1, 6: 2}.get(today.weekday(), 0))

    stale, ages = [], []
    for path in WATCH:
        d = last_commit_date(path)
        if d is None:
            stale.append(f"{Path(path).name}: 커밋 이력 없음")
            continue
        age = (ref - d).days
        ages.append(f"{Path(path).name}={d}({age}일)")
        if age > args.max_age_days:
            stale.append(f"{Path(path).name}: 마지막 갱신 {d} ({age}일 경과)")

    print(f"[{datetime.now():%Y-%m-%d %H:%M}] 기준일 {ref} · " + " · ".join(ages))

    deploy = [] if args.no_deploy_check else check_deploy()

    if not stale and not deploy:
        print("✅ 데이터 신선 · 배포 최신 — 알림 없음")
        return 0

    ts = f"{datetime.now():%Y-%m-%d %H:%M} KST"

    # ── 수출 관련(배포 정체) → 수출 단체방 ──
    if deploy:
        msg = (f"🚨 <b>수출 대시보드 배포가 데이터보다 뒤처짐</b>\n{ts}\n\n"
               + "\n".join(f"• {s}" for s in deploy)
               + f"\n\nGitHub에는 최신 CSV가 있으나 {os.environ.get('TRADE_WEB_URL', '배포')} 는"
                 " 옛 데이터를 서빙 중입니다.\n확인: Render 대시보드 → Events/Logs (배포 실패·정체)")
        print(msg)
        send_telegram(msg, TRADE_CHAT_ENV)

    # ── 비수출(daily CI 정체) → 운영 채널만. 수출 단체방에는 절대 보내지 않는다 ──
    if stale:
        msg = (f"🚨 <b>daily CI 데이터 정체</b>\n{ts}\n\n"
               + "\n".join(f"• {s}" for s in stale)
               + "\n\nCI가 실행되지 않았거나(스케줄 비활성/사용량 소진) 커밋 단계가 막혔을 수 있습니다."
                 "\n확인: <code>gh run list --workflow=daily_update.yml --limit 5</code>")
        print(msg)
        send_telegram(msg, OPS_CHAT_ENV)

    return 1


if __name__ == "__main__":
    sys.exit(main())
