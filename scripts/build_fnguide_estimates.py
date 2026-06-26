"""DataGuide 추정 엑셀 → data/fnguide_estimates.json 변환기 (① 다년추정·③ 분기 서프라이즈).

팀원 작업용 — 별도 사전지식 없이 그대로 실행 가능.

사용법:
  1) 템플릿 생성:   python3 scripts/build_fnguide_estimates.py --template
        → data/fnguide_estimates_input.xlsx (헤더 + 예시행) 생성. DataGuide 값으로 채운다.
  2) 변환:          python3 scripts/build_fnguide_estimates.py
        → data/fnguide_estimates.json 생성(파이프라인이 자동 사용).
     (입력 파일 지정:  python3 scripts/build_fnguide_estimates.py 경로.xlsx)

입력 한 행 = 한 종목. 빈 칸은 비워두면 됨(자동 None 처리, 0으로 채우지 말 것).
단위: 영업이익(op_*)·서프라이즈·ytd_op = 억원, EPS(eps_*) = 원.

컬럼 (헤더 이름 그대로 유지):
  code           6자리 종목코드(필수)            예) 005930
  name           종목명(선택, 가독용)
  op_fy1_now/_1m/_3m   당해 영업이익 컨센서스: 현재 / 1개월전 / 3개월전 (억원)
  op_fy2_now/_1m/_3m   차기 영업이익 컨센서스
  eps_fy1_now/_1m/_3m  당해 EPS 컨센서스: 현재/1M전/3M전 (원)
  eps_fy2_now/_1m/_3m  차기 EPS 컨센서스
  sup_q1_act/_con .. sup_q4_act/_con   최근 4개 분기 잠정 영업이익(act) vs 직전 컨센(con) (억원). q1=가장 최근
  est_std, est_mean    추정치 표준편차·평균(분산도; 신뢰도 게이트)
  est_age_days         추정치 평균 경과일수
  ytd_op               연초누계 영업이익(선택, 억원)
  fy_roll              회계연도 롤오버 구간 여부(TRUE/FALSE, 선택)
"""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "data" / "fnguide_estimates_input.xlsx"
OUTPUT = PROJECT_ROOT / "data" / "fnguide_estimates.json"
KST = timezone(timedelta(hours=9))

COLUMNS = [
    "code", "name",
    "op_fy1_now", "op_fy1_1m", "op_fy1_3m", "op_fy2_now", "op_fy2_1m", "op_fy2_3m",
    "eps_fy1_now", "eps_fy1_1m", "eps_fy1_3m", "eps_fy2_now", "eps_fy2_1m", "eps_fy2_3m",
    "sup_q1_act", "sup_q1_con", "sup_q2_act", "sup_q2_con",
    "sup_q3_act", "sup_q3_con", "sup_q4_act", "sup_q4_con",
    "est_std", "est_mean", "est_age_days", "ytd_op", "fy_roll",
]
EXAMPLE = {
    "code": "005930", "name": "삼성전자",
    "op_fy1_now": 868414, "op_fy1_1m": 850000, "op_fy1_3m": 820000,
    "op_fy2_now": 1050000, "op_fy2_1m": 1040000, "op_fy2_3m": 1010000,
    "eps_fy1_now": 44459, "eps_fy1_1m": 43500, "eps_fy1_3m": 42000,
    "eps_fy2_now": 52000, "eps_fy2_1m": 51500, "eps_fy2_3m": 50000,
    "sup_q1_act": 121661, "sup_q1_con": 118000, "sup_q2_act": 200737, "sup_q2_con": 195000,
    "sup_q3_act": 90000, "sup_q3_con": 88000, "sup_q4_act": 110000, "sup_q4_con": 105000,
    "est_std": 35000, "est_mean": 868414, "est_age_days": 18, "ytd_op": 322398, "fy_roll": False,
}


def _num(v):
    """숫자화. 빈칸/NaN → None. 콤마·% 제거."""
    if v is None:
        return None
    if isinstance(v, float) and v != v:  # NaN
        return None
    s = str(v).strip().replace(",", "").replace("%", "")
    if s == "" or s.lower() in ("nan", "none", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _bool(v):
    if v is None or (isinstance(v, float) and v != v):
        return None
    s = str(v).strip().lower()
    if s in ("true", "1", "y", "yes", "예", "o"):
        return True
    if s in ("false", "0", "n", "no", "아니오", "x", ""):
        return False
    return None


def _block(row, prefix):
    """op_fy1 류 {now,m1,m3} 블록. 전부 비면 None."""
    b = {"now": _num(row.get(f"{prefix}_now")), "m1": _num(row.get(f"{prefix}_1m")),
         "m3": _num(row.get(f"{prefix}_3m"))}
    return b if any(v is not None for v in b.values()) else None


def make_template(path):
    df = pd.DataFrame([EXAMPLE], columns=COLUMNS)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".csv":
        df.to_csv(path, index=False, encoding="utf-8-sig")
    else:
        df.to_excel(path, index=False)
    print(f"템플릿 생성: {path}")
    print("  → 예시행(삼성전자)을 참고해 종목별로 채운 뒤, 인자 없이 다시 실행하면 JSON으로 변환됩니다.")


def convert(in_path):
    if not in_path.exists():
        print(f"[오류] 입력 파일 없음: {in_path}\n  먼저 --template 로 템플릿을 생성해 채우세요.")
        sys.exit(1)
    df = pd.read_csv(in_path) if in_path.suffix.lower() == ".csv" else pd.read_excel(in_path)
    missing = [c for c in ("code",) if c not in df.columns]
    if missing:
        print(f"[오류] 필수 컬럼 누락: {missing} (헤더 이름을 템플릿과 동일하게 유지하세요)")
        sys.exit(1)

    estimates, skipped = {}, 0
    for _, row in df.iterrows():
        raw_code = row.get("code")
        if raw_code is None or (isinstance(raw_code, float) and raw_code != raw_code):
            continue
        code = str(raw_code).strip().split(".")[0].zfill(6)   # 숫자형 5930 → '005930'
        if len(code) != 6 or not code.isdigit():
            skipped += 1
            continue
        e = {}
        for key, pref in [("op_fy1", "op_fy1"), ("op_fy2", "op_fy2"),
                          ("eps_fy1", "eps_fy1"), ("eps_fy2", "eps_fy2")]:
            blk = _block(row, pref)
            if blk:
                e[key] = blk
        sup = []
        for q in range(1, 5):
            a, c = _num(row.get(f"sup_q{q}_act")), _num(row.get(f"sup_q{q}_con"))
            if a is not None and c is not None:
                sup.append([a, c])
        if sup:
            e["surprise"] = sup
        for k, col in [("std", "est_std"), ("mean", "est_mean"), ("age_days", "est_age_days"),
                       ("ytd_op", "ytd_op")]:
            v = _num(row.get(col))
            if v is not None:
                e[k] = v
        fr = _bool(row.get("fy_roll"))
        if fr is not None:
            e["fy_roll"] = fr
        if e:
            estimates[code] = e

    out = {"updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "count": len(estimates),
           "estimates": estimates}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    have = lambda k: sum(1 for v in estimates.values() if k in v)
    print(f"변환 완료: {OUTPUT}")
    print(f"  종목 {len(estimates)}개 (op_fy1 {have('op_fy1')} · op_fy2 {have('op_fy2')} · "
          f"eps_fy1 {have('eps_fy1')} · 서프라이즈 {have('surprise')})" + (f" · 건너뜀 {skipped}행" if skipped else ""))
    print("  → 이 파일을 커밋하면 다음 갱신부터 EPS Revision 모듈에 자동 반영됩니다.")


def main():
    ap = argparse.ArgumentParser(description="DataGuide 추정 엑셀 → fnguide_estimates.json")
    ap.add_argument("input", nargs="?", default=str(DEFAULT_INPUT), help="입력 엑셀/CSV 경로")
    ap.add_argument("--template", action="store_true", help="빈 템플릿(예시행 포함) 생성")
    args = ap.parse_args()
    if args.template:
        make_template(Path(args.input))
    else:
        convert(Path(args.input))


if __name__ == "__main__":
    main()
