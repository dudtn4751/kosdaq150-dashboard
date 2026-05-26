#!/bin/bash
# 인터넷 ready까지 최대 5분 대기. launchd가 절전 깨어난 직후 실행될 때 DNS 실패 방지.
# 사용: . scripts/_wait_network.sh (source)
MAX_WAIT=300
INTERVAL=5
elapsed=0
while [ $elapsed -lt $MAX_WAIT ]; do
    if curl -s --max-time 3 -o /dev/null -w "%{http_code}" https://api.github.com | grep -q "^[23]"; then
        echo "[net] 인터넷 OK (${elapsed}초 대기)"
        return 0 2>/dev/null || exit 0
    fi
    sleep $INTERVAL
    elapsed=$((elapsed + INTERVAL))
done
echo "[net] 인터넷 5분 대기 후에도 실패 — 작업 중단" >&2
return 1 2>/dev/null || exit 1
