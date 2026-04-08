#!/bin/bash
# 매주 일요일 매크로 일정 갱신 + git push
cd "$(dirname "$0")/.."

echo "[$(date)] 매크로 일정 갱신 시작"

# 매크로 업데이트 실행
python3 scripts/update_macro.py

# 변경사항 커밋 & 푸시
git add data/macro_calendar.json
git diff --staged --quiet || (
    git commit -m "auto: 매크로 일정 주간 갱신 $(date +%Y-%m-%d)"
    git push origin main
)

echo "[$(date)] 완료"
