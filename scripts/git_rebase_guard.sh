#!/bin/zsh
# ─────────────────────────────────────────────────────────────────────────────
# git_rebase_guard.sh — 자동 커밋 래퍼(FnGuide·수출입 등) 공용 git 방어 로직.
#
# 자동잡이 rebase 도중 충돌/중단(노트북 sleep·launchd kill·네트워크 끊김)으로
# 남긴 .git/rebase-merge | .git/rebase-apply 잔재를 실행 시작 시 정리한다.
# 이 잔재가 남으면 이후 모든 git pull --rebase 가 "already a rebase-merge
# directory" 로 실패하고 저장소가 detached 상태로 갈라진다(실측 2026-08-06).
#
# 사용: cd <repo> 후
#         source /abs/path/scripts/git_rebase_guard.sh
#         guard_stuck_rebase "$LOGFILE"     # 인자 없으면 stdout
# ─────────────────────────────────────────────────────────────────────────────
guard_stuck_rebase() {
    local log="${1:-/dev/stdout}"
    if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; then
        echo "  [git-guard] 멈춘 rebase 잔재(.git/rebase-merge|apply) 발견 → 정리" >> "$log" 2>&1
        if git rebase --abort >> "$log" 2>&1; then
            echo "  [git-guard] git rebase --abort 완료" >> "$log" 2>&1
        else
            echo "  [git-guard] abort 실패 → rebase 디렉토리 강제 제거(git 안내대로 rm -rf)" >> "$log" 2>&1
            rm -rf .git/rebase-merge .git/rebase-apply
        fi
        # abort가 detached HEAD로 남길 수 있으니 main 브랜치 보장.
        git checkout main >> "$log" 2>&1 || true
    fi
}
