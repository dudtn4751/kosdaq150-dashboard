#!/bin/bash
# 매일 07:00 KST 미국 이벤트 수집 + Claude 해석 + git push
# 미장 마감(05:00 KST DST / 06:00 표준시) 1-2시간 후 실행

cd "$(dirname "$0")/.."

# 비-UTF8 로케일 / 백그라운드 실행 대응
export PYTHONIOENCODING=utf-8
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
export PATH="/Users/yougsu1/Library/Python/3.9/bin:$PATH"

echo "[$(date)] 미국 이벤트 갱신 시작"

# 인터넷 ready까지 최대 5분 대기 (절전 깨어난 직후 대비)
source scripts/_wait_network.sh || { echo "네트워크 없음 → 종료"; exit 1; }

# remote 동기화
git pull --rebase origin main 2>/dev/null

# 스크립트 실행. 실패하면(exit 1+) commit/push 건너뜀
if python3 scripts/update_us_events.py; then
    git add data/us_events.json
    git diff --staged --quiet || (
        git commit -m "auto: 미국 이벤트 해석 $(date +%Y-%m-%d)"
        git push origin main
    )
    echo "[$(date)] 완료"
else
    rc=$?
    echo "[$(date)] update_us_events.py 실패 (exit $rc) — commit/push 건너뜀"
    exit $rc
fi
