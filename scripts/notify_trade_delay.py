#!/usr/bin/env python3
"""수출입 데이터 지연 알림 — 신선도 게이트 재시도 소진 시 텔레그램 1회.

사용: python3 notify_trade_delay.py <day> [사유]
send_trade_briefing.send() 재사용(토큰/chat_id 없으면 graceful 스킵).
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from dotenv import load_dotenv
    load_dotenv(str(Path(__file__).resolve().parent.parent / ".env"))
except Exception:
    pass

from send_trade_briefing import send  # noqa: E402


def main() -> int:
    day = sys.argv[1] if len(sys.argv) > 1 else "?"
    reason = sys.argv[2] if len(sys.argv) > 2 else "EPIC 미갱신"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = (
        f"<b>⚠️ 수출입 데이터 지연</b>\n"
        f"{now} · {day}일 갱신분\n"
        f"사유: {reason} — 오전(~11:30) 재시도 모두 소진.\n"
        f"EPIC 상류가 아직 새 스냅샷을 올리지 않았습니다. "
        f"업로드되면 다음 예약 실행 또는 수동 재실행으로 반영됩니다."
    )
    ok = send(html)
    print("지연 알림 전송:", "성공" if ok else "스킵/실패")
    return 0


if __name__ == "__main__":
    sys.exit(main())
