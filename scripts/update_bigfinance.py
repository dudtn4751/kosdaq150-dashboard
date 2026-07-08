"""빅파이낸스 실적 스냅샷 수집 — Mac 로컬 수동 실행 전용.

노트북에서 갱신일(분기 실적발표 후)에만 실행:
    python3 scripts/update_bigfinance.py            # 수집 → data/bf_financials.json 기록
    python3 scripts/update_bigfinance.py --commit   # 기록 + git add/commit/push (배포 반영)

로그인은 .env(BIGFINANCE_ID/PW)로 1회. 클라우드에서는 절대 실행하지 않음(차단 리스크).
배포 앱은 커밋된 data/bf_financials.json만 읽는다(로그인 코드 없음).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from epsrev.data.bigfinance_parse import parse_fscore          # noqa: E402
from epsrev.data.exports import SECTOR_EXPORT, parse_export_chart  # noqa: E402
from scripts.bigfinance_session import login, fetch_fscore, fetch_export_chart  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "bf_financials.json")
KEEP_Q = 24    # 최근 24분기(6년)
KEEP_A = 12    # 최근 12년


def _universe() -> list[str]:
    from epsrev.data.dashboard_data import SECTORS
    ts = set()
    for sec in SECTORS:
        for c in sec.get("cos", []):
            ts.add(str(c["t"]).zfill(6))
    return sorted(ts)


def _trim(d: dict) -> dict:
    return {"quarterly": (d.get("quarterly") or [])[-KEEP_Q:],
            "annual": (d.get("annual") or [])[-KEEP_A:]}


def _has_data(d: dict) -> bool:
    for r in (d.get("annual") or []) + (d.get("quarterly") or []):
        if r.get("rev") is not None or r.get("op") is not None:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="기록 후 git add/commit/push")
    ap.add_argument("--limit", type=int, default=0, help="테스트용 상위 N종목만")
    ap.add_argument("--sleep", type=float, default=0.15, help="요청 간 간격(초)")
    args = ap.parse_args()

    tickers = _universe()
    if args.limit:
        tickers = tickers[:args.limit]
    print(f"[bigfinance] 유니버스 {len(tickers)}종목 · 로그인 시도…")
    sess = login()
    print("[bigfinance] 로그인 성공. 수집 시작…")

    fin, ok, empty, fail = {}, 0, 0, 0
    for i, t in enumerate(tickers, 1):
        try:
            parsed = _trim(parse_fscore(fetch_fscore(sess, t)))
            if _has_data(parsed):
                fin[t] = parsed
                ok += 1
            else:
                empty += 1
        except Exception as e:
            fail += 1
            if fail <= 8:
                print(f"  ! {t} 실패: {type(e).__name__} {str(e)[:50]}")
        if i % 50 == 0:
            print(f"  … {i}/{len(tickers)}  (ok={ok} empty={empty} fail={fail})")
        time.sleep(args.sleep)

    snap = {
        "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": "bigfinance/fsCore",
        "count": len(fin),
        "financials": fin,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT)
    size_mb = os.path.getsize(OUT) / 1e6
    print(f"[bigfinance] 완료: {ok}종목 기록(empty={empty}, fail={fail}) · {OUT} ({size_mb:.1f}MB)")

    # ── 수출 데이터 스냅샷(launch-data/trade) ──
    _build_export(sess)

    if args.commit:
        _git_commit(snap["count"])


EXP_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "bf_export.json")


def _build_export(sess):
    """SECTOR_EXPORT 매핑 품목의 월별 수출 시계열 → data/bf_export.json."""
    from datetime import datetime, timezone
    pairs = {}
    for ic, pc, label in SECTOR_EXPORT.values():
        pairs[(ic, pc)] = label
    series, ok = {}, 0
    for (ic, pc), label in pairs.items():
        try:
            data = parse_export_chart(fetch_export_chart(sess, ic, pc), keep=24)
            if data:
                series[f"{ic}-{pc}"] = {"label": label, "data": data}
                ok += 1
        except Exception as e:
            print(f"  [export] {ic}-{pc} 실패: {type(e).__name__}")
    snap = {"updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "source": "bigfinance/launch-data/trade", "series": series}
    with open(EXP_OUT, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[bigfinance] 수출 스냅샷: {ok}개 시계열 → {EXP_OUT}")


def _git_commit(n):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        subprocess.run(["git", "-C", root, "add", "data/bf_financials.json",
                        "data/bf_export.json"], check=True)
        subprocess.run(["git", "-C", root, "commit", "-m",
                        f"data: 빅파이낸스 실적·수출 스냅샷 갱신 ({n}종목)"], check=True)
        subprocess.run(["git", "-C", root, "fetch", "-q", "origin"], check=True)
        subprocess.run(["git", "-C", root, "merge", "-X", "ours", "--no-edit", "origin/main"], check=False)
        subprocess.run(["git", "-C", root, "push", "origin", "main"], check=True)
        print("[bigfinance] git push 완료 — 배포 앱이 곧 반영합니다.")
    except subprocess.CalledProcessError as e:
        print(f"[bigfinance] git 실패: {e} — 수동으로 커밋/푸시하세요.")


if __name__ == "__main__":
    main()
