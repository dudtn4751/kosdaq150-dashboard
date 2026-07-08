#!/bin/zsh
# FnGuide 리포트 자동 수집 래퍼 (Mac launchd 전용 — 클라우드 금지)
# 트리거: 노트북 켤 때(RunAtLoad) + 매일 07:00(백업). 하루 1회만 실제 실행.
# 공유 계정 보호: FNGUIDE_FORCE=0 → 세션 사용중(팀원 접속)이면 강제 로그아웃 안 하고 건너뜀.
# 흐름: (가드) → 네트워크 대기 → git pull → 수집·요약 → 변경 시 commit·push → 성공표시

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export FNGUIDE_FORCE=1            # 사용자 허가: 80115면 강제 로그인(팀원 세션 로그아웃)

REPO="/Users/yougsu1/kosdaq150_predictor"
PY="/usr/bin/python3"
LOG="$REPO/logs/fnguide_daily.log"
MARK="$REPO/logs/last_success_date"

cd "$REPO" || { echo "repo 없음"; exit 1; }
mkdir -p "$REPO/logs"
TODAY=$(date '+%Y-%m-%d')

# 상호배제 락: 밤 백필 등 다른 FnGuide 작업과 동시 로그인 방지(80115 예방)
LOCK="$REPO/logs/fnguide.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
    echo "$(date '+%H:%M') 다른 FnGuide 작업 실행중 — 스킵" >> "$LOG"
    exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

# 하루 1회 가드: 오늘 이미 성공했으면 종료(로그인/재시작 반복 중복 방지)
if [ -f "$MARK" ] && [ "$(cat "$MARK")" = "$TODAY" ]; then
    echo "$(date '+%H:%M') 오늘 이미 갱신 완료 — 스킵" >> "$LOG"
    exit 0
fi

echo "" >> "$LOG"
echo "========== $(date '+%Y-%m-%d %H:%M:%S') 시작 ==========" >> "$LOG"

# 네트워크 대기(로그인 직후 wifi 지연 대비, 최대 ~90초)
for i in {1..18}; do
    curl -s -m 5 -o /dev/null https://github.com && break
    echo "  네트워크 대기 ($i/18)..." >> "$LOG"
    sleep 5
done

# 원격 최신 반영(한경 GH Action 등). data/ 로컬 드리프트는 폐기.
git checkout -- data/ 2>/dev/null || true
git pull --rebase --autostash >> "$LOG" 2>&1   # 로컬 트리 변경 있어도 pull 안 막히게

# 요약량: 미요약 백로그가 남아있으면 백필모드(300), 거의 없으면 40/일.
# (공유계정 세션이 중간에 끊겨 1회에 다 못 하므로, 백로그 소진까지 매 실행 크게 시도)
GAP=$("$PY" -c "import json;r=json.load(open('data/research_reports.json')).get('reports',[]);c=set(json.load(open('data/report_summaries.json')).keys());print(sum(1 for x in r if str(x.get('report_id') or '') and str(x.get('report_id')) not in c))" 2>/dev/null || echo 0)
if [ "${GAP:-0}" -gt 60 ]; then
    export FNGUIDE_SUM_LIMIT=300
    echo "  백필 모드(미요약 ${GAP}건, SUM_LIMIT=300)" >> "$LOG"
else
    export FNGUIDE_SUM_LIMIT=40
    echo "  증분 모드(미요약 ${GAP}건, SUM_LIMIT=40)" >> "$LOG"
fi

# 수집·요약 (로그인 → 최근 리포트 → 미요약분 백필 → research_reports.json 병합)
"$PY" scripts/update_fnguide_reports.py >> "$LOG" 2>&1
RC=$?
echo "  update 종료코드: $RC" >> "$LOG"

if [ $RC -ne 0 ]; then
    echo "  → 로그인 실패/세션 사용중(80115) 가능 — 오늘 미완료. 다음 로그인/07시 재시도(마커 미기록)" >> "$LOG"
    exit $RC                     # 마커 안 남김 → 나중에 재시도
fi

if ! git diff --quiet -- data/research_reports.json data/report_summaries.json; then
    git add data/research_reports.json data/report_summaries.json >> "$LOG" 2>&1
    git commit -m "chore: FnGuide 리포트 갱신 $TODAY" >> "$LOG" 2>&1
    git push origin main >> "$LOG" 2>&1
    echo "  → commit·push 완료" >> "$LOG"
else
    echo "  → 변경 없음 → commit 스킵" >> "$LOG"
fi

echo "$TODAY" > "$MARK"           # 성공 → 오늘 완료 표시(하루 1회 가드)
echo "========== $(date '+%Y-%m-%d %H:%M:%S') 완료 ==========" >> "$LOG"
