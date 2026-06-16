"""데이터 계약 검증 게이트.

매일 갱신 후(커밋 전) 실행. 하나라도 ERROR면 exit 1 → 워크플로 실패 → 이슈 자동 생성.
WARN은 통과시키되 출력에 남김(주말 stale 등 정상 케이스 포함).

사용: python3 scripts/validate_data.py
"""

import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from data_contract import VALIDATORS, LABELS, check  # noqa: E402


def main():
    print("=" * 56)
    print("데이터 계약 검증 (data contract)")
    print("=" * 56)
    any_error = False
    for name in VALIDATORS:
        path = os.path.join(PROJECT_ROOT, "data", f"{name}.json")
        label = LABELS.get(name, name)
        if not os.path.exists(path):
            print(f"  [ERROR] {label} ({name}.json) 파일 없음")
            any_error = True
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"  [ERROR] {label} ({name}.json) 읽기 실패: {e}")
            any_error = True
            continue
        r = check(name, data)
        tag = {"ok": "PASS", "warn": "WARN", "error": "ERROR"}[r["level"]]
        detail = "; ".join(r["issues"]) if r["issues"] else "정상"
        print(f"  [{tag}] {label}: {detail}")
        if not r["ok"]:
            any_error = True

    print("=" * 56)
    if any_error:
        print("결과: ERROR — 계약 위반 발견 (커밋/배포 차단 권장)")
        return 1
    print("결과: 모든 데이터 계약 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
