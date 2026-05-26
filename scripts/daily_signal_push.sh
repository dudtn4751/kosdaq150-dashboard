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

# 인터넷 ready까지 대기 (절전 깨어난 직후 KRX DNS 실패 방지)
source scripts/_wait_network.sh || { echo "네트워크 없음 → 종료"; exit 1; }

# 결과 크기 검증용 백업
BACKUP=$(mktemp)
cp data/market_signal.json "$BACKUP" 2>/dev/null

# remote 동기화
git pull --rebase origin main 2>/dev/null

# 실행. 실패하면 백업 복원 + commit/push 건너뜀
if python3 scripts/update_market_signal.py; then
    # 신뢰 가능한 크기인지 검증 (백업보다 50% 이하면 의심)
    NEW_SIZE=$(wc -c < data/market_signal.json)
    OLD_SIZE=$(wc -c < "$BACKUP" 2>/dev/null || echo 0)
    if [ "$OLD_SIZE" -gt 1000 ] && [ "$NEW_SIZE" -lt $((OLD_SIZE / 2)) ]; then
        echo "[$(date)] 결과 크기 의심($NEW_SIZE vs 기존 $OLD_SIZE) — 백업 복원, push 안 함"
        cp "$BACKUP" data/market_signal.json
        rm -f "$BACKUP"
        exit 2
    fi
    rm -f "$BACKUP"

    git add data/market_signal.json
    git diff --staged --quiet || (
        git commit -m "auto: 시장 시그널 $(date +%Y-%m-%d)"
        git push origin main
    )
    echo "[$(date)] 완료"
else
    rc=$?
    echo "[$(date)] update_market_signal.py 실패 (exit $rc) — 백업 복원, push 건너뜀"
    [ -s "$BACKUP" ] && cp "$BACKUP" data/market_signal.json
    rm -f "$BACKUP"
    exit $rc
fi
