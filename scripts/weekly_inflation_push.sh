#!/bin/bash
# 매주 일요일 18:00 KST FRED 물가 지표 갱신 + git push

cd "$(dirname "$0")/.."

export PYTHONIOENCODING=utf-8
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
export PATH="/Users/yougsu1/Library/Python/3.9/bin:$PATH"

echo "[$(date)] FRED 물가 갱신 시작"

source scripts/_wait_network.sh || { echo "네트워크 없음 → 종료"; exit 1; }

BACKUP=$(mktemp)
cp data/inflation_data.json "$BACKUP" 2>/dev/null

git pull --rebase origin main 2>/dev/null

if python3 scripts/update_inflation.py; then
    NEW_SIZE=$(wc -c < data/inflation_data.json)
    OLD_SIZE=$(wc -c < "$BACKUP" 2>/dev/null || echo 0)
    if [ "$OLD_SIZE" -gt 1000 ] && [ "$NEW_SIZE" -lt $((OLD_SIZE / 2)) ]; then
        echo "[$(date)] 결과 크기 의심($NEW_SIZE vs 기존 $OLD_SIZE) — 백업 복원"
        cp "$BACKUP" data/inflation_data.json
        rm -f "$BACKUP"
        exit 2
    fi
    rm -f "$BACKUP"

    git add data/inflation_data.json
    git diff --staged --quiet || (
        git commit -m "auto: FRED 물가 데이터 주간 갱신 $(date +%Y-%m-%d)"
        git push origin main
    )
    echo "[$(date)] 완료"
else
    rc=$?
    echo "[$(date)] update_inflation.py 실패 (exit $rc) — 백업 복원"
    [ -s "$BACKUP" ] && cp "$BACKUP" data/inflation_data.json
    rm -f "$BACKUP"
    exit $rc
fi
