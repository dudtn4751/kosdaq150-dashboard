#!/bin/zsh
# FnGuide 리포트 일일 자동 수집 래퍼 (Mac launchd 전용 — 클라우드 금지)
# 흐름: git pull(한경 GH Action 반영) → FnGuide 수집 → 변경 시 commit·push
# 로그: logs/fnguide_daily.log

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

REPO="/Users/yougsu1/kosdaq150_predictor"
PY="/usr/bin/python3"
LOG="$REPO/logs/fnguide_daily.log"

cd "$REPO" || { echo "repo 없음: $REPO"; exit 1; }

echo "" >> "$LOG"
echo "========== $(date '+%Y-%m-%d %H:%M:%S') FnGuide 일일 시작 ==========" >> "$LOG"

# 1) 원격 최신 반영 (05:00 한경 GH Action 갱신분 먼저).
#    data/ 로컬 드리프트는 폐기 — research_reports.json은 아래 수집에서 새로 생성하고,
#    macro_calendar.json 등은 GH Action이 소유(로컬 변경 붙들면 pull 충돌 유발).
git checkout -- data/ 2>/dev/null || true
git pull --rebase >> "$LOG" 2>&1

# 2) FnGuide 수집 (오늘자 종목 리포트 전체 → 요약 + EPS → research_reports.json 병합)
"$PY" scripts/update_fnguide_reports.py >> "$LOG" 2>&1
RC=$?
echo "  update_fnguide_reports 종료코드: $RC" >> "$LOG"

# 3) data/research_reports.json 변경이 있을 때만 커밋·푸시
if ! git diff --quiet -- data/research_reports.json; then
    git add data/research_reports.json >> "$LOG" 2>&1
    git commit -m "chore: FnGuide 리포트 일일 수집 $(date '+%Y-%m-%d')" >> "$LOG" 2>&1
    git push origin main >> "$LOG" 2>&1
    echo "  → research_reports.json 변경 → commit·push 완료" >> "$LOG"
else
    echo "  → research_reports.json 변경 없음 → commit 스킵" >> "$LOG"
fi

echo "========== $(date '+%Y-%m-%d %H:%M:%S') FnGuide 일일 완료 ==========" >> "$LOG"
