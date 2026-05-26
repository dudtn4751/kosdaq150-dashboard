#!/bin/bash
# 매주 일요일 매크로 일정 갱신 + git push
cd "$(dirname "$0")/.."

echo "[$(date)] 매크로 일정 갱신 시작"

source scripts/_wait_network.sh || { echo "네트워크 없음 → 종료"; exit 1; }

BACKUP=$(mktemp)
cp data/macro_calendar.json "$BACKUP" 2>/dev/null

if python3 scripts/update_macro.py; then
    NEW_SIZE=$(wc -c < data/macro_calendar.json)
    OLD_SIZE=$(wc -c < "$BACKUP" 2>/dev/null || echo 0)
    if [ "$OLD_SIZE" -gt 1000 ] && [ "$NEW_SIZE" -lt $((OLD_SIZE / 2)) ]; then
        echo "[$(date)] 결과 크기 의심($NEW_SIZE vs 기존 $OLD_SIZE) — 백업 복원"
        cp "$BACKUP" data/macro_calendar.json
        rm -f "$BACKUP"
        exit 2
    fi
    rm -f "$BACKUP"

    git add data/macro_calendar.json
    git diff --staged --quiet || (
        git commit -m "auto: 매크로 일정 주간 갱신 $(date +%Y-%m-%d)"
        git push origin main
    )
    echo "[$(date)] 완료"
else
    rc=$?
    echo "[$(date)] update_macro.py 실패 (exit $rc) — 백업 복원"
    [ -s "$BACKUP" ] && cp "$BACKUP" data/macro_calendar.json
    rm -f "$BACKUP"
    exit $rc
fi
