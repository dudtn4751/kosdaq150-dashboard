#!/bin/zsh
# ─────────────────────────────────────────────────────────────────────────────
# run_trade_export.sh — 갱신일에 맞는 스크래퍼만 실행.
#   01     : 월별(기업 포함, scrape_bigfinance.py) + 10일 단위(scrape_bigfinance_items.py)
#   11, 21 : 10일 단위(scrape_bigfinance_items.py)만
# ※ 2026-08-27 일정 정정: '15일 확정 발표' 가정 폐기 — 월별·기업 데이터는 1일에만 갱신된다.
# ★로컬 전용 — LaunchAgent(사용자 로그인 세션)에서만 실행. 절대 클라우드/CI 금지.
#
# 사용:  ./run_trade_export.sh            # 오늘 날짜 기준
#        ./run_trade_export.sh 15         # 테스트용: 특정 일(day) 강제
# ─────────────────────────────────────────────────────────────────────────────
set -u

export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
PROJ="/Users/yougsu1/kosdaq150_predictor"
PY="/usr/bin/python3"
cd "$PROJ" || { echo "cd 실패: $PROJ"; exit 1; }

# 신선도 게이트 상수 (선판정·재시도 판정 공용 — set -u라 사용 전에 정의돼야 한다)
STATE_FILE="$PROJ/logs/.trade_gate_state"     # "YYYY-MM-DD count"
ALERTED_FILE="$PROJ/logs/.trade_gate_alerted" # 지연 알림 보낸 날짜 — 같은 날 재알림 방지
STALE_MAX_ATTEMPTS=7                          # 09:30~11:30 20분 슬롯 7개
GATE_DEADLINE=1130                            # 이 시각 이후 STALE이면 회차와 무관하게 소진
LOCK_DIR="$PROJ/logs/.trade_export.lock"

# 타임스탬프 로그 (logs/ 아래). 이후 모든 출력을 여기로.
mkdir -p logs
LOG="logs/trade_export_$(date +%Y%m%d_%H%M%S).log"
exec >> "$LOG" 2>&1

echo "════════════════════════════════════════════════════════════"
echo "[$(date '+%F %T %Z')] run_trade_export 시작"

# 실행일 (인자로 override 가능 — 테스트용)
D="${1:-$(date +%d)}"
echo "대상 일(day) = $D"

# ── 중복 실행 방지 락 (2026-09-11) ──
# 달력 슬롯 실행과 수동 실행(다른 세션 포함)이 겹치면 스크래퍼 두 벌이 같은 CSV를 쓰고
# 둘 다 커밋·브리핑을 시도한다. mkdir은 원자적이라 락으로 쓴다. 겹친 회차는 조용히
# 빠지며 게이트 카운터도 올리지 않는다(다음 슬롯이 이어받음).
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  holder="$(cat "$LOCK_DIR/pid" 2>/dev/null)"
  if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then
    echo "[생략] 다른 실행(pid $holder)이 진행 중 — 이번 회차 무동작(exit 0)"
    exit 0
  fi
  echo "[정보] 주인 없는 락(pid ${holder:-?}) 회수"
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" 2>/dev/null || { echo "[생략] 락 획득 경합 — 무동작"; exit 0; }
fi
echo $$ > "$LOCK_DIR/pid"
trap 'rm -rf "$LOCK_DIR"' EXIT

# ── 스크래퍼 실행 헬퍼 ────────────────────────────────────────────────────────
# ★ 시도마다 **새 크롬 프로필**을 쓴다 (2026-09-01 실측).
#   재사용된 프로필은 스크래핑 세션을 한 번 끝낸 뒤부터 Download.save_as가
#   TargetClosedError("Target page, context or browser has been closed")로 즉시 죽는다.
#   페이지는 살아 있고 다운로드 이벤트도 정상 수신되는데 컨텍스트만 닫히는 형태라
#   같은 프로필로 재시도해봐야 소용없다(6/6회 첫 품목에서 동일 실패).
#   빈 프로필이면 정상 동작하며, 로그인은 .env 자격증명으로 자동 수행된다(약 13초).
#   → SingletonLock 청소도 불필요해졌다(프로필을 공유하지 않으므로).
_attempt() {
  local script="$1" headless="$2" label="$3"
  local profile rc
  profile="$(mktemp -d "${TMPDIR:-/tmp}/epic_profile_XXXXXX")"
  echo "──── $script ($label · profile=$(basename "$profile")) ────"
  TRADE_SCRAPE_HEADLESS="$headless" TRADE_CHROME_PROFILE_DIR="$profile" "$PY" "$script"
  rc=$?
  rm -rf "$profile"
  return $rc
}

run_scraper() {
  local script="$1"
  if _attempt "$script" 1 "headless 시도"; then
    echo "──── $script 완료(headless) ────"; return 0
  fi
  if _attempt "$script" 0 "창 모드 재시도"; then
    echo "──── $script 완료(창 모드) ────"; return 0
  fi
  echo "──── $script 두 번 실패 → 60초 후 1회 재시도 ────"
  sleep 60
  if _attempt "$script" 1 "최종 재시도"; then
    echo "──── $script 완료(재시도) ────"; return 0
  fi
  echo "──── $script 최종 실패 ────"
  return 1
}

# ── 네트워크 대기 (절전 복귀 직후 Wi-Fi 지연 대비, 최대 ~5분) ──
# 2026-08-21 실제 사고: 스케줄 시각에 오프라인이라 EPIC·git·telegram 전부 실패하고
# 재시도가 없어 8/20 스냅샷이 통째로 누락됐다.
net_ok=0
for i in $(seq 1 30); do
  if curl -s -m 5 -o /dev/null https://bigfinance.co.kr/; then net_ok=1; break; fi
  echo "  네트워크 대기 ($i/30)..."
  sleep 10
done
if [ "$net_ok" = 0 ]; then
  echo "[중단] 네트워크 없음 — 스크래핑 생략(다음 실행/재시도에서 처리)"
  exit 75          # EX_TEMPFAIL: launchd 재시도 신호
fi

# ── 방어: 이전 실행이 rebase 중 중단/충돌로 남긴 잔재 정리(공용 헬퍼) ──
# stdout이 이미 로그로 리다이렉트돼 있으므로 인자 없이 호출(→ 로그로 기록).
source "$PROJ/scripts/git_rebase_guard.sh"
guard_stuck_rebase

# ── 원격 최신화 (로컬 변경은 autostash로 보존) ──
echo "── git pull --rebase --autostash ──"
git pull --rebase --autostash origin main || echo "[경고] git pull 실패 — 계속 진행(로컬 스크랩)"

# ── 선판정 (2026-09-11): 오늘 기대 스냅샷이 이미 반영돼 있으면 EPIC을 긁지 않는다 ──
# 재시도가 20분 간격 달력 슬롯으로 돌기 때문에, 앞 슬롯·수동 실행·다른 세션이 이미
# FRESH로 커밋했다면 뒤 슬롯은 할 일이 없다. git pull 직후의 커밋된 CSV로 판정하므로
# 어디서 반영됐든 잡힌다. 오늘 지연 알림을 이미 보냈으면 남은 슬롯도 무동작.
case "$D" in
  01|1|11|21)
    PRE_OUT="$("$PY" "$PROJ/scripts/check_trade_freshness.py" "$D" 2>&1)"; PRE_RC=$?
    if [ "$PRE_RC" = 0 ]; then
      echo "[생략] 오늘분 이미 반영됨 — $PRE_OUT"
      rm -f "$STATE_FILE"
      exit 0
    fi
    if [ "$(cat "$ALERTED_FILE" 2>/dev/null)" = "$(date +%F)" ]; then
      echo "[생략] 오늘 지연 알림 발송 완료(재시도 소진) — 남은 슬롯 무동작 · $PRE_OUT"
      exit 0
    fi
    echo "── 선판정: $PRE_OUT → 스크랩 진행 ──"
    ;;
esac

# ── 실행일별 스크래퍼 분기 ──
ran_any=0; failed=0
case "$D" in
  01|1)
    echo "[분기] 1일 → 월별(기업 포함) + 10일 단위"
    run_scraper "$PROJ/scrape_bigfinance.py"       || failed=1; ran_any=1
    run_scraper "$PROJ/scrape_bigfinance_items.py" || failed=1; ran_any=1
    ;;
  11|21)
    echo "[분기] ${D}일 → 10일 단위"
    run_scraper "$PROJ/scrape_bigfinance_items.py" || failed=1; ran_any=1
    ;;
  *)
    echo "[분기] $D 일은 갱신일(1·11·21) 아님 — 실행 안 함"
    ;;
esac

if [ "$ran_any" = 0 ]; then
  echo "[$(date '+%F %T')] 실행 대상 없음 — 종료"
  exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
# ★ 신선도 게이트 (2026-09-11) — '10:05 전 완료' 체계.
#   스크랩이 끝나도, 그날 기대한 새 스냅샷(1일=전월말+월별 새 달 / 11일=당월10일 /
#   21일=당월20일)이 실제로 들어왔을 때만 커밋·푸시·브리핑한다. EPIC 상류가 아직
#   안 올렸으면(옛 데이터) 커밋·브리핑 없이 종료하고 다음 달력 슬롯(20분 간격,
#   09:30~11:30)에서 재시도. STALE_MAX_ATTEMPTS회 또는 GATE_DEADLINE 경과 시 텔레그램 1회 알림.
#   ※ 재시도를 launchd KeepAlive 재발사에 맡기지 않는다 — 2026-09-11 3차 누락 참고(plist 주석).
# ─────────────────────────────────────────────────────────────────────────────
# (STATE_FILE·STALE_MAX_ATTEMPTS·GATE_DEADLINE은 스크립트 상단에서 정의)
source "$PROJ/scripts/lib_trade_gate.sh"     # gate_decide (카운터 로직, 테스트와 공유)

_retry_or_alert() {   # $1: 사유 문자열
  local reason="$1" decision verb cnt
  decision="$(gate_decide)"          # STATE_FILE 카운터 증가 → "RETRY n" | "ALERT n"
  verb="${decision%% *}"; cnt="${decision##* }"
  # 슬롯이 절전·락·스폰 실패로 빠지면 카운터가 7에 못 미친 채 11:30을 넘길 수 있다.
  # 마감 이후면 회차와 무관하게 소진으로 본다(알림이 아예 안 나가는 사고 방지).
  if [ "$verb" = RETRY ] && [ "$((10#$(date +%H%M)))" -ge "$GATE_DEADLINE" ]; then
    verb=ALERT
  fi
  if [ "$verb" = RETRY ]; then
    echo "[$reason — ${cnt}차 대기] 다음 달력 슬롯(20분 뒤)에서 재시도(exit 75) · 최대 ${STALE_MAX_ATTEMPTS}회·마감 ${GATE_DEADLINE}"
    exit 75
  fi
  echo "[$reason — ${cnt}차, 재시도 소진] 텔레그램 1회 알림 후 종료(exit 0)"
  "$PY" "$PROJ/scripts/notify_trade_delay.py" "$D" "$reason" || echo "[경고] 지연 알림 실패 — 무시"
  date +%F > "$ALERTED_FILE"
  rm -f "$STATE_FILE"
  exit 0
}

# 스크래핑이 한 번이라도 실패했으면 완전한 데이터가 아니므로 커밋 안 하고 재시도.
if [ "$failed" = 1 ]; then
  echo "── 스크래핑 실패 회차 → 게이트: 재시도 경로 ──"
  _retry_or_alert "스크래핑 실패"
fi

# ── 신선도 판정 (그날 기대 스냅샷 존재?) ──
FRESH_OUT="$("$PY" "$PROJ/scripts/check_trade_freshness.py" "$D" 2>&1)"; FRESH_RC=$?
echo "── 신선도: $FRESH_OUT ──"

if [ "$FRESH_RC" != 0 ]; then
  # 옛 데이터 = EPIC 상류 미갱신 → 커밋·브리핑 없이 재시도
  _retry_or_alert "EPIC 미갱신"
fi

# ── 신선 → 커밋·푸시(변경 있을 때만) + 브리핑, 재시도 상태 초기화 ──
rm -f "$STATE_FILE"
echo "── 변경 확인: data/trade_dashboard/*.csv ──"
git add -- "data/trade_dashboard/"*.csv
if git diff --cached --quiet -- "data/trade_dashboard/"*.csv; then
  echo "신선하나 CSV 변경 없음 — 커밋·브리핑 스킵(이미 반영·발송됨)"
  echo "[$(date '+%F %T')] run_trade_export 종료(신선·무변경)"
  exit 0
fi
echo "변경 감지 — commit/push"
git commit -m "auto(trade): 수출입 데이터 갱신 $(date +%F) (day $D)"
if git push origin main; then
  echo "push 성공"
else
  echo "[경고] push 실패 — 다음 실행 때 pull 후 재시도됨"
fi

echo "── 텔레그램 브리핑 (day $D) ──"
"$PY" "$PROJ/scripts/send_trade_briefing.py" "$D" || echo "[경고] 브리핑 전송 실패 — 무시하고 계속"

echo "[$(date '+%F %T')] run_trade_export 종료(신선·커밋 완료)"
exit 0
