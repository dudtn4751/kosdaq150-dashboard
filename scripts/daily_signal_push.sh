#!/bin/bash
# 매일 15:40 장 마감 후 시장 시그널 수집 + git push
cd "$(dirname "$0")/.."

echo "[$(date)] 시장 시그널 수집 시작"

python3 scripts/update_market_signal.py

git add data/market_signal.json
git diff --staged --quiet || (
    git commit -m "auto: 시장 시그널 $(date +%Y-%m-%d)"
    git push origin main
)

echo "[$(date)] 완료"
