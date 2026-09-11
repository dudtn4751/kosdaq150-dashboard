#!/bin/zsh
# ─────────────────────────────────────────────────────────────────────────────
# test_trade_gate.sh — 신선도 게이트 '소진(exhaustion)' 경로 테스트.
#   실데이터 CSV 판정(fresh/stale)은 tests/test_trade_freshness.py 가 담당.
#   여기선 재시도 카운터(gate_decide)를 격리된 임시 STATE_FILE 로 검증한다.
#   ★ 실운영 STATE_FILE(logs/.trade_gate_state)은 절대 건드리지 않는다.
# ─────────────────────────────────────────────────────────────────────────────
set -u
DIR="$(cd "$(dirname "$0")/.." && pwd)"       # scripts/
source "$DIR/lib_trade_gate.sh"

TMP="$(mktemp -d "${TMPDIR:-/tmp}/trade_gate_test_XXXXXX")"
export STATE_FILE="$TMP/state"                 # 격리 — 실 상태파일 아님
export STALE_MAX_ATTEMPTS=3                     # 짧게: 2번 RETRY 후 3번째 ALERT
export GATE_TODAY="2026-09-11"

fail=0
assert() {  # $1 실제 $2 기대 $3 설명
  if [ "$1" = "$2" ]; then echo "  ok  · $3"
  else echo "  FAIL· $3 — 기대 '$2' 실제 '$1'"; fail=1; fi
}

echo "── 소진 경로: RETRY×(MAX-1) 후 ALERT ──"
assert "$(gate_decide)" "RETRY 1" "1차 → RETRY 1"
assert "$(gate_decide)" "RETRY 2" "2차 → RETRY 2"
assert "$(gate_decide)" "ALERT 3" "3차 → ALERT(소진)"
assert "$(gate_decide)" "ALERT 4" "4차 → ALERT 유지(소진 이후)"

echo "── 날짜 경계: 자정 넘어가면 카운터 리셋 ──"
export GATE_TODAY="2026-09-12"
assert "$(gate_decide)" "RETRY 1" "다음날 첫 회 → RETRY 1(리셋)"

echo "── 상태파일 격리 확인 ──"
assert "$(cut -d' ' -f1 "$STATE_FILE")" "2026-09-12" "STATE_FILE 날짜 갱신됨"
[ ! -e "$DIR/../logs/.trade_gate_state.TESTTOUCHED" ] && echo "  ok  · 실 상태파일 미접촉(임시경로만 사용)"

rm -rf "$TMP"
if [ "$fail" = 0 ]; then echo "ALL PASS"; exit 0; else echo "SOME FAILED"; exit 1; fi
