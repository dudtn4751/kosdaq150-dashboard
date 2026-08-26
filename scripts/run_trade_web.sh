#!/bin/zsh
# 수출입 Flask 앱 (waitress) 로컬 기동. ★로컬 전용.
set -u
export PATH="/opt/homebrew/bin:/usr/bin:/bin:$PATH"
PROJ="/Users/yougsu1/kosdaq150_predictor"
PORT="${1:-5100}"
cd "$PROJ" || exit 1
mkdir -p logs
echo "[$(date '+%F %T')] trade_web 기동 → http://127.0.0.1:$PORT"
exec /usr/bin/python3 -m waitress --host=127.0.0.1 --port="$PORT" --call apps.trade_web.app:create_app 2>&1
