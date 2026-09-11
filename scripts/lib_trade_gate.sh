# ─────────────────────────────────────────────────────────────────────────────
# lib_trade_gate.sh — 신선도 게이트 재시도 카운터(소스용).
#   run_trade_export.sh 와 tests/test_trade_gate.sh 가 공유하는 순수 로직.
#   exit·텔레그램은 호출자가 결정한다(테스트 용이 — 함수는 판정만 반환).
#
# 필요 환경변수:
#   STATE_FILE           "YYYY-MM-DD count" 를 저장할 경로.
#   STALE_MAX_ATTEMPTS   이 회차 이상이면 소진(ALERT).
#   GATE_TODAY           (선택) 날짜 오버라이드 — 테스트용. 없으면 date +%F.
#
# gate_decide "<사유>": STATE_FILE 의 오늘 카운터를 1 증가시키고 판정을 stdout으로.
#   "RETRY <cnt>"  (cnt <  STALE_MAX_ATTEMPTS)
#   "ALERT <cnt>"  (cnt >= STALE_MAX_ATTEMPTS)
#   날짜가 바뀌면 카운터를 1부터 다시 센다.
# ─────────────────────────────────────────────────────────────────────────────
gate_decide() {
  local today cnt=0 sd sc
  today="${GATE_TODAY:-$(date +%F)}"
  if [ -f "$STATE_FILE" ]; then
    sd="$(cut -d' ' -f1 "$STATE_FILE" 2>/dev/null)"
    sc="$(cut -d' ' -f2 "$STATE_FILE" 2>/dev/null)"
    [ "$sd" = "$today" ] && cnt="${sc:-0}"
  fi
  cnt=$((cnt + 1))
  echo "$today $cnt" > "$STATE_FILE"
  if [ "$cnt" -lt "$STALE_MAX_ATTEMPTS" ]; then
    echo "RETRY $cnt"
  else
    echo "ALERT $cnt"
  fi
}
