#!/bin/zsh
# daily CI 신선도 감시 래퍼 (launchd 09:00). ★로컬 전용.
set -u
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
PROJ="/Users/yougsu1/kosdaq150_predictor"
cd "$PROJ" || exit 1
mkdir -p logs
exec >> "$PROJ/logs/freshness_check.log" 2>&1
echo "──────── $(date '+%F %T %Z') ────────"
/usr/bin/python3 "$PROJ/scripts/check_data_freshness.py"
echo "exit=$?"
