#!/bin/bash
# 매주 일요일 18:00 KST FRED 물가 지표 갱신 + git push
# FRED는 월 1회 갱신이지만 신규 발표(CPI/PPI/PCE)를 빨리 잡기 위해 주 1회

cd "$(dirname "$0")/.."

export PYTHONIOENCODING=utf-8
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
export PATH="/Users/yougsu1/Library/Python/3.9/bin:$PATH"

echo "[$(date)] FRED 물가 갱신 시작"

git pull --rebase origin main 2>/dev/null

python3 scripts/update_inflation.py

git add data/inflation_data.json
git diff --staged --quiet || (
    git commit -m "auto: FRED 물가 데이터 주간 갱신 $(date +%Y-%m-%d)"
    git push origin main
)

echo "[$(date)] 완료"
