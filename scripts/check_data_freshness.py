#!/usr/bin/env python3
"""daily CI 신선도 감시 — CI가 *아예 안 돌아도* 알아채기 위한 로컬 감시자. ★로컬 전용.

워크플로 안의 실패 알림은 "실행됐는데 실패한" 경우만 잡는다. 스케줄이 비활성화되거나
Actions 사용량이 소진돼 아예 실행되지 않으면 아무 알림도 오지 않는다. 이 스크립트는
origin/main의 핵심 데이터 파일이 마지막으로 갱신된 날짜를 보고, 평일 기준으로 오늘치가
없으면 텔레그램으로 경고한다.

자격증명: .env 의 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (없으면 콘솔 출력만).
실행: python3 scripts/check_data_freshness.py [--max-age-days N]
"""

import argparse
import os
import subprocess
import sys
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


def send_telegram(text: str) -> bool:
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        print("[정보] 텔레그램 토큰/chat_id 없음 — 콘솔 출력만")
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-days", type=int, default=1,
                    help="이 일수보다 오래되면 경고(기본 1 — 어제까지는 허용)")
    args = ap.parse_args()

    subprocess.run(["git", "fetch", "origin", "-q"], cwd=BASE_DIR, check=False)
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
    if not stale:
        print("✅ 데이터 신선 — 알림 없음")
        return 0

    body = "\n".join(f"• {s}" for s in stale)
    msg = (f"🚨 <b>daily CI 데이터 정체 감지</b>\n{datetime.now():%Y-%m-%d %H:%M} KST\n\n{body}\n\n"
           f"CI가 실행되지 않았거나(스케줄 비활성/사용량 소진) 커밋 단계가 막혔을 수 있습니다.\n"
           f"확인: gh run list --workflow=daily_update.yml --limit 5")
    print(msg)
    send_telegram(msg)
    return 1


if __name__ == "__main__":
    sys.exit(main())
