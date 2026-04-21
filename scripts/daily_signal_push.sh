#!/bin/bash
# 평일 15:35 장 마감 후 시장 시그널 수집 + git push
cd "$(dirname "$0")/.."

# 주말이면 실행하지 않음 (1=월 ~ 5=금)
DOW=$(date +%u)
if [ "$DOW" -gt 5 ]; then
    echo "[$(date)] 주말 — 스킵"
    exit 0
fi

echo "[$(date)] 시장 시그널 수집 시작"

# remote 동기화
git pull --rebase origin main 2>/dev/null

python3 scripts/update_market_signal.py

git add data/market_signal.json
git diff --staged --quiet || (
    git commit -m "auto: 시장 시그널 $(date +%Y-%m-%d)"
    git push origin main
)

echo "[$(date)] 완료"
