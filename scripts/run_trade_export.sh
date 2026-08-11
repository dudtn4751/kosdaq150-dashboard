#!/bin/zsh
# ─────────────────────────────────────────────────────────────────────────────
# run_trade_export.sh — 관세청 수출 발표일(1·11·15·21)에 맞는 스크래퍼만 실행.
#   01     : 월간 잠정(scrape_bigfinance.py) + 순별(scrape_bigfinance_items.py)
#   11, 21 : 순별(scrape_bigfinance_items.py)
#   15     : 월간 확정(scrape_bigfinance.py)
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

# 타임스탬프 로그 (logs/ 아래). 이후 모든 출력을 여기로.
mkdir -p logs
LOG="logs/trade_export_$(date +%Y%m%d_%H%M%S).log"
exec >> "$LOG" 2>&1

echo "════════════════════════════════════════════════════════════"
echo "[$(date '+%F %T %Z')] run_trade_export 시작"

# 실행일 (인자로 override 가능 — 테스트용)
D="${1:-$(date +%d)}"
echo "대상 일(day) = $D"

# ── 스크래퍼 실행 헬퍼: headless=True 우선, 실패 시 창 모드 폴백 ──
run_scraper() {
  local script="$1"
  echo "──── $script (headless 시도) ────"
  if TRADE_SCRAPE_HEADLESS=1 "$PY" "$script"; then
    echo "──── $script 완료(headless) ────"
    return 0
  fi
  echo "──── $script headless 실패(exit=$?) → 창 모드 재시도 ────"
  if TRADE_SCRAPE_HEADLESS=0 "$PY" "$script"; then
    echo "──── $script 완료(창 모드) ────"
    return 0
  fi
  echo "──── $script 창 모드도 실패(exit=$?) ────"
  return 1
}

# ── 방어: 이전 실행이 rebase 중 중단/충돌로 남긴 잔재 정리(공용 헬퍼) ──
# stdout이 이미 로그로 리다이렉트돼 있으므로 인자 없이 호출(→ 로그로 기록).
source "$PROJ/scripts/git_rebase_guard.sh"
guard_stuck_rebase

# ── 원격 최신화 (로컬 변경은 autostash로 보존) ──
echo "── git pull --rebase --autostash ──"
git pull --rebase --autostash origin main || echo "[경고] git pull 실패 — 계속 진행(로컬 스크랩)"

# ── 실행일별 스크래퍼 분기 ──
ran_any=0
case "$D" in
  01|1)
    echo "[분기] 1일 → 월간 잠정 + 순별"
    run_scraper "$PROJ/scrape_bigfinance.py";       ran_any=1
    run_scraper "$PROJ/scrape_bigfinance_items.py"; ran_any=1
    ;;
  11|21)
    echo "[분기] ${D}일 → 순별"
    run_scraper "$PROJ/scrape_bigfinance_items.py"; ran_any=1
    ;;
  15)
    echo "[분기] 15일 → 월간 확정"
    run_scraper "$PROJ/scrape_bigfinance.py";       ran_any=1
    ;;
  *)
    echo "[분기] $D 일은 수출 발표일 아님 — 실행 안 함"
    ;;
esac

if [ "$ran_any" = 0 ]; then
  echo "[$(date '+%F %T')] 실행 대상 없음 — 종료"
  exit 0
fi

# ── 수출입 CSV 변경 있으면 커밋·푸시 (변경 없으면 스킵) ──
# 먼저 stage(신규 untracked 파일도 잡히게) 후 staged diff로 판정 — git diff만으론
# 새로 생성된 decade CSV 같은 untracked 파일을 못 잡는다.
echo "── 변경 확인: data/trade_dashboard/*.csv ──"
git add -- "data/trade_dashboard/"*.csv
if git diff --cached --quiet -- "data/trade_dashboard/"*.csv; then
  echo "변경 없음 — 커밋 스킵 (EPIC에 신규 데이터 없거나 동일값)"
else
  echo "변경 감지 — commit/push"
  git commit -m "auto(trade): 수출입 데이터 갱신 $(date +%F) (day $D)"
  if git push origin main; then
    echo "push 성공"
  else
    echo "[경고] push 실패 — 다음 실행 때 pull 후 재시도됨"
  fi
fi

echo "[$(date '+%F %T')] run_trade_export 종료"
