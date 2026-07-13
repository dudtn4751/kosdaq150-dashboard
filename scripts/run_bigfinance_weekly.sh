#!/bin/zsh
# 빅파이낸스 산업/신용카드 스냅샷 주간 갱신 래퍼 (Mac launchd 전용 — 클라우드/CI 금지)
# 트리거: 매주 월 07:30 (com.kosdaq.bigfinance-weekly.plist). 로컬 로그인 스크레이프.
# 흐름: git pull --rebase --autostash → update_industry → update_creditcard
#       → bf_industry.json / bf_creditcard.json 변경 있을 때만 자격증명 검사 → commit → push
# trade_scores.json 재계산은 daily CI(update_trade_scores)가 처리 → 로컬 생략.

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

REPO="/Users/yougsu1/kosdaq150_predictor"
PY="/usr/bin/python3"
TS="$(date '+%Y-%m-%d %H:%M:%S')"
LOG="$REPO/logs/bigfinance_weekly.log"

cd "$REPO" || { echo "[$TS] repo 없음: $REPO"; exit 1; }
mkdir -p "$REPO/logs"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "===== 빅파이낸스 주간 갱신 시작 ====="

# 1) 최신 반영 (로컬 변경은 autostash로 잠시 치웠다가 rebase 후 복원)
if git pull --rebase --autostash origin main >>"$LOG" 2>&1; then
  log "git pull --rebase OK"
else
  log "⚠️ git pull 실패 — 갱신 계속(로컬 스냅샷 생성 후 재시도)"
fi

# 2) 스크레이프 (로컬 로그인 — .env BIGFINANCE_ID/PW)
log "update_industry.py 실행..."
"$PY" scripts/update_industry.py >>"$LOG" 2>&1 && log "update_industry OK" || log "⚠️ update_industry 오류"
log "update_creditcard.py 실행..."
"$PY" scripts/update_creditcard.py >>"$LOG" 2>&1 && log "update_creditcard OK" || log "⚠️ update_creditcard 오류"

# 3) 변경 있을 때만 커밋·푸시
SNAP="data/bf_industry.json data/bf_creditcard.json"
if git diff --quiet -- $SNAP; then
  log "스냅샷 변경 없음 — 커밋 생략 (EPIC 신규 데이터 없음, 정상)"
  log "===== 종료(변경 없음) ====="
  exit 0
fi

# 3-1) 커밋 전 자격증명/세션쿠키 흔적 검사 (스테이징 diff)
git add -- $SNAP
LEAK=$(git diff --cached -- $SNAP | grep -iE "BIGFINANCE_(ID|PW)|xsrf|laravel_session|set-cookie|Bearer |password" | head -1)
if [ -n "$LEAK" ]; then
  log "❌ 자격증명/쿠키 흔적 감지 — 커밋 중단, 스테이징 해제. 수동 확인 필요."
  git reset -q -- $SNAP
  log "===== 종료(누출 의심) ====="
  exit 1
fi

git commit -m "빅파이낸스 스냅파일 주간 갱신(산업/신용카드) $(date '+%Y-%m-%d')" >>"$LOG" 2>&1
if git push origin main >>"$LOG" 2>&1; then
  log "✅ commit + push 완료"
else
  log "⚠️ push 실패 — 1회 재시도(pull --rebase 후)"
  git pull --rebase --autostash origin main >>"$LOG" 2>&1
  git push origin main >>"$LOG" 2>&1 && log "✅ 재시도 push 완료" || log "❌ push 재시도 실패 — 다음 주기 or 수동"
fi

log "===== 종료 ====="
