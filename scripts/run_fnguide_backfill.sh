#!/bin/zsh
# FnGuide 요약 1회성 대량 백필 (밀린 ~360건). 조용한 시간(예약 02:00)에 단독 실행.
# 성공 시 logs/backfill_done 마커 → 이후 재실행 스킵. 일일 래퍼와 락 공유(동시 로그인 방지).

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export FNGUIDE_SUM_LIMIT=600      # 밀린 미요약분 전량
export FNGUIDE_FORCE=1            # 새벽엔 팀원 접속 거의 없음 → 강제로그인 허용(완주 보장)

REPO="/Users/yougsu1/kosdaq150_predictor"
PY="/usr/bin/python3"
LOG="$REPO/logs/fnguide_backfill.log"
DONE="$REPO/logs/backfill_done"
MARK="$REPO/logs/last_success_date"
LOCK="$REPO/logs/fnguide.lock"

cd "$REPO" || exit 1
mkdir -p "$REPO/logs"

# 이미 백필 완료했으면 종료(1회성)
[ -f "$DONE" ] && { echo "$(date '+%F %H:%M') 백필 이미 완료 — 스킵" >> "$LOG"; exit 0; }

# 상호배제 락(일일 래퍼와 공유)
if ! mkdir "$LOCK" 2>/dev/null; then
    echo "$(date '+%F %H:%M') 다른 FnGuide 작업 실행중 — 스킵(다음 예약에 재시도)" >> "$LOG"
    exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

echo "" >> "$LOG"; echo "========== $(date '+%F %T') 백필 시작 ==========" >> "$LOG"

for i in {1..18}; do
    curl -s -m 5 -o /dev/null https://github.com && break
    sleep 5
done

git checkout -- data/ 2>/dev/null || true
git pull --rebase >> "$LOG" 2>&1

"$PY" scripts/update_fnguide_reports.py >> "$LOG" 2>&1
RC=$?
echo "  update 종료코드: $RC" >> "$LOG"
if [ $RC -ne 0 ]; then
    echo "  → 실패(로그인/세션) — 마커 미기록, 다음 예약에 재시도" >> "$LOG"
    exit $RC
fi

if ! git diff --quiet -- data/research_reports.json data/report_summaries.json; then
    git add data/research_reports.json data/report_summaries.json >> "$LOG" 2>&1
    git commit -m "chore: FnGuide 요약 대량 백필 $(date '+%Y-%m-%d')" >> "$LOG" 2>&1
    git push origin main >> "$LOG" 2>&1
    echo "  → commit·push 완료" >> "$LOG"
fi

date '+%Y-%m-%d' > "$DONE"        # 백필 완료 표시(재실행 방지)
date '+%Y-%m-%d' > "$MARK"        # 당일 일일 래퍼도 스킵
echo "========== $(date '+%F %T') 백필 완료 ==========" >> "$LOG"
