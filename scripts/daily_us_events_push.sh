#!/bin/bash
# 매일 07:00 KST 미국 이벤트 수집 + Claude 해석 + git push
# 미장 마감(05:00 KST DST / 06:00 표준시) 1-2시간 후 실행

cd "$(dirname "$0")/.."

# 비-UTF8 로케일 / 백그라운드 실행 대응
export PYTHONIOENCODING=utf-8
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8

# user-site에 설치된 패키지(anthropic 등) 사용
export PATH="/Users/yougsu1/Library/Python/3.9/bin:$PATH"

echo "[$(date)] 미국 이벤트 갱신 시작"

# remote 동기화
git pull --rebase origin main 2>/dev/null

python3 scripts/update_us_events.py

# data/us_events.json은 LLM 해석 포함이라 항상 commit
git add data/us_events.json
git diff --staged --quiet || (
    git commit -m "auto: 미국 이벤트 해석 $(date +%Y-%m-%d)"
    git push origin main
)

echo "[$(date)] 완료"
