"""
epsrev/adapters/fnspace_parser.py
=================================
원시 FnSpace JSON(fnspace_client 응답 / fixtures)  →  정규화 중간표현(fnspace_types).

설계:
    - 원시 JSON의 **필드명 문자열은 전부 상단 FIELDS dict 한 곳**에만 둔다(TODO[FNSPACE]).
      파서 본문은 FIELDS만 참조 — 다른 곳에 키 이름 하드코딩 금지.
      실제 응답 확인 후 FIELDS만 고치면 파서 본문은 불변.
    - 입력이 None/구조 불일치여도 예외 대신 None(또는 빈 시계열) 반환.
    - 일별 시계열에서 '오늘/1M전/3M전' 값을 뽑는 유틸 제공(가장 가까운 영업일 매칭).

상태:
    [DONE] 원시 → 정규화 파싱 (이 파일)
    [TODO] 정규화 → fnspace_extra 변환  ← 다음 STEP (fnspace.py)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from epsrev.adapters.fnspace_types import (
    DatedValue,
    EstimateDailySeries,
    FinancialActuals,
    FiscalEstimate,
    FnSpaceNormalized,
    ForwardEPSSeries,
    OpinionTargetPrice,
    QuarterActual,
    TPRevisionCounts,
)

# =============================================================================
# ▼▼▼ 원시 필드명 — 실제 응답 확인 후 여기'만' 교정 (TODO[FNSPACE]) ▼▼▼
# 값(예: "FY1","1M","UP")까지 응답에 종속이므로 함께 모음.
# =============================================================================
FIELDS: dict[str, dict[str, str]] = {
    "envelope": {
        "dataset": "dataset",      # TODO[FNSPACE]: 응답 봉투의 레코드 배열 키
    },
    "forward": {                    # 12M Fwd EPS 일별
        "rows":  "DATA",            # TODO[FNSPACE]
        "code":  "CODE",            # TODO[FNSPACE]
        "date":  "DATE",            # TODO[FNSPACE]
        "value": "VAL",             # TODO[FNSPACE]
    },
    "estimate_daily": {             # 영업이익/당기순이익 추정 일별
        "rows": "DATA",             # TODO[FNSPACE]
        "code": "CODE",             # TODO[FNSPACE]
        "date": "DATE",             # TODO[FNSPACE]
        "op":   "OP_EST",           # TODO[FNSPACE]
        "np":   "NP_EST",           # TODO[FNSPACE]
    },
    "estimate_fiscal": {            # FY1/FY2 추정
        "rows":     "FISCAL",       # TODO[FNSPACE]
        "code":     "CODE",         # TODO[FNSPACE]
        "term":     "TERM",         # TODO[FNSPACE]
        "fy":       "FY",           # TODO[FNSPACE]
        "op":       "OP_EST",       # TODO[FNSPACE]
        "eps":      "EPS_EST",      # TODO[FNSPACE]
        "term_fy1": "FY1",          # TODO[FNSPACE]: TERM 컬럼의 FY1 표기값
        "term_fy2": "FY2",          # TODO[FNSPACE]: TERM 컬럼의 FY2 표기값
    },
    "opinion_tp": {                 # 목표주가 / 투자의견
        "code":      "CODE",        # TODO[FNSPACE]
        "tp_rows":   "TP_DAILY",    # TODO[FNSPACE]
        "date":      "DATE",        # TODO[FNSPACE]
        "tp":        "TP_ADJ",      # TODO[FNSPACE]
        "analyst_n": "ANALYST_N",   # TODO[FNSPACE]
        "revision":  "TP_REVISION", # TODO[FNSPACE]
        "p_1w":      "1W",          # TODO[FNSPACE]
        "p_1m":      "1M",          # TODO[FNSPACE]
        "p_3m":      "3M",          # TODO[FNSPACE]
        "up":        "UP",          # TODO[FNSPACE]
        "down":      "DOWN",        # TODO[FNSPACE]
        "total":     "TOTAL",       # TODO[FNSPACE]
    },
    "financial": {                  # 최근 4분기 실적/서프라이즈
        "rows":      "QUARTERLY",   # TODO[FNSPACE]
        "code":      "CODE",        # TODO[FNSPACE]
        "quarter":   "Q",           # TODO[FNSPACE]
        "actual_op": "OP_ACTUAL",   # TODO[FNSPACE]
        "cons_op":   "OP_CONSENSUS",# TODO[FNSPACE]
        "surprise":  "SURPRISE_PCT",# TODO[FNSPACE]
    },
}
# =============================================================================
# ▲▲▲ 필드 매핑 끝 ▲▲▲
# =============================================================================

TOL_DAYS = 20            # 시점 매칭 허용 오차(일). 초과하면 결측(None).
DATE_FMT = "%Y-%m-%d"    # TODO[FNSPACE]: 실제 날짜 포맷 확인

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


# ── 시점 추출 유틸 ──────────────────────────────────────────────────────────────
@dataclass
class TimePoints:
    """일별 시계열에서 뽑은 오늘/1M전/3M전 값. 결측은 None."""
    now: Optional[float] = None
    m1: Optional[float] = None
    m3: Optional[float] = None


def pick_timepoints(
    points: list[DatedValue],
    asof: Optional[date] = None,
    tol_days: int = TOL_DAYS,
) -> TimePoints:
    """
    points(일별 시계열)에서 asof(기준일)·1개월전·3개월전에 '가장 가까운' 영업일 값을 뽑는다.
    - asof=None이면 시계열의 최신일을 기준으로 사용(데이터의 as-of).
    - 목표일과의 거리가 tol_days를 넘으면 결측(None).
    """
    valid: list[tuple[date, float]] = []
    for p in points:
        d = _parse_date(p.date)
        if d is not None:
            valid.append((d, p.value))
    if not valid:
        return TimePoints()
    valid.sort(key=lambda t: t[0])

    if asof is None:
        asof = valid[-1][0]

    def nearest(target: date) -> Optional[float]:
        best_v: Optional[float] = None
        best_diff: Optional[int] = None
        for d, v in valid:
            diff = abs((d - target).days)
            if best_diff is None or diff < best_diff:
                best_diff, best_v = diff, v
        if best_diff is not None and best_diff <= tol_days:
            return best_v
        return None

    return TimePoints(
        now=nearest(asof),
        m1=nearest(asof - timedelta(days=30)),
        m3=nearest(asof - timedelta(days=90)),
    )


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────
def _dataset_first(raw: Optional[dict]) -> Optional[dict]:
    """봉투에서 첫 레코드(dataset[0])를 꺼낸다. 구조 불일치 시 None."""
    if not isinstance(raw, dict):
        return None
    ds = raw.get(FIELDS["envelope"]["dataset"])
    if isinstance(ds, list) and ds and isinstance(ds[0], dict):
        return ds[0]
    return None


def _to_float(x: Any) -> Optional[float]:
    try:
        if x is None or x == "":
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _to_int(x: Any) -> Optional[int]:
    f = _to_float(x)
    return int(f) if f is not None else None


def _parse_date(s: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(s), DATE_FMT).date()
    except (TypeError, ValueError):
        return None


def _norm_code(raw_code: Any) -> str:
    """'A005930' → '005930' (선행 알파벳 접두 제거)."""
    c = str(raw_code or "").strip()
    return c[1:] if (c[:1].isalpha() and len(c) > 1) else c


def _dated_series(rows: Any, date_key: str, val_key: str) -> list[DatedValue]:
    out: list[DatedValue] = []
    if isinstance(rows, list):
        for r in rows:
            if not isinstance(r, dict):
                continue
            d = r.get(date_key)
            v = _to_float(r.get(val_key))
            if d is not None and v is not None:
                out.append(DatedValue(str(d), v))
    out.sort(key=lambda p: p.date)
    return out


def _rev_counts(node: Any, F: dict) -> Optional[TPRevisionCounts]:
    if not isinstance(node, dict):
        return None
    return TPRevisionCounts(
        up=_to_int(node.get(F["up"])) or 0,
        down=_to_int(node.get(F["down"])) or 0,
        total=_to_int(node.get(F["total"])) or 0,
    )


# ── 엔드포인트별 파서 ────────────────────────────────────────────────────────────
def parse_forward(raw: Optional[dict]) -> Optional[ForwardEPSSeries]:
    rec = _dataset_first(raw)
    if rec is None:
        return None
    F = FIELDS["forward"]
    return ForwardEPSSeries(
        code=_norm_code(rec.get(F["code"])),
        points=_dated_series(rec.get(F["rows"]), F["date"], F["value"]),
    )


def parse_estimate_daily(raw: Optional[dict]) -> Optional[EstimateDailySeries]:
    rec = _dataset_first(raw)
    if rec is None:
        return None
    F = FIELDS["estimate_daily"]
    rows = rec.get(F["rows"])
    return EstimateDailySeries(
        code=_norm_code(rec.get(F["code"])),
        op=_dated_series(rows, F["date"], F["op"]),
        np=_dated_series(rows, F["date"], F["np"]),
    )


def parse_estimate_fiscal(raw: Optional[dict]) -> Optional[FiscalEstimate]:
    rec = _dataset_first(raw)
    if rec is None:
        return None
    F = FIELDS["estimate_fiscal"]
    out = FiscalEstimate(code=_norm_code(rec.get(F["code"])))
    rows = rec.get(F["rows"])
    if isinstance(rows, list):
        for r in rows:
            if not isinstance(r, dict):
                continue
            term = str(r.get(F["term"], ""))
            if term == F["term_fy1"]:
                out.fy1_tag = str(r.get(F["fy"], ""))
                out.fy1_op = _to_float(r.get(F["op"]))
                out.fy1_eps = _to_float(r.get(F["eps"]))
            elif term == F["term_fy2"]:
                out.fy2_tag = str(r.get(F["fy"], ""))
                out.fy2_op = _to_float(r.get(F["op"]))
                out.fy2_eps = _to_float(r.get(F["eps"]))
    return out


def parse_opinion_tp(raw: Optional[dict]) -> Optional[OpinionTargetPrice]:
    rec = _dataset_first(raw)
    if rec is None:
        return None
    F = FIELDS["opinion_tp"]
    rev = rec.get(F["revision"]) if isinstance(rec.get(F["revision"]), dict) else {}
    return OpinionTargetPrice(
        code=_norm_code(rec.get(F["code"])),
        tp_points=_dated_series(rec.get(F["tp_rows"]), F["date"], F["tp"]),
        analyst_n=_to_int(rec.get(F["analyst_n"])),
        rev_1w=_rev_counts(rev.get(F["p_1w"]), F),
        rev_1m=_rev_counts(rev.get(F["p_1m"]), F),
        rev_3m=_rev_counts(rev.get(F["p_3m"]), F),
    )


def parse_financial(raw: Optional[dict]) -> Optional[FinancialActuals]:
    rec = _dataset_first(raw)
    if rec is None:
        return None
    F = FIELDS["financial"]
    out = FinancialActuals(code=_norm_code(rec.get(F["code"])))
    rows = rec.get(F["rows"])
    if isinstance(rows, list):
        for r in rows:
            if not isinstance(r, dict):
                continue
            out.quarters.append(QuarterActual(
                quarter=str(r.get(F["quarter"], "")),
                actual_op=_to_float(r.get(F["actual_op"])),
                consensus_op=_to_float(r.get(F["cons_op"])),
                surprise_pct=_to_float(r.get(F["surprise"])),
            ))
    out.quarters.sort(key=lambda q: q.quarter)
    return out


def parse_all(
    code: str,
    raw_forward: Optional[dict] = None,
    raw_estimate_daily: Optional[dict] = None,
    raw_estimate_fiscal: Optional[dict] = None,
    raw_opinion_tp: Optional[dict] = None,
    raw_financial: Optional[dict] = None,
) -> FnSpaceNormalized:
    """5개 원시 응답 → 한 종목 정규화 묶음. 결측은 None."""
    return FnSpaceNormalized(
        code=_norm_code(code),
        forward=parse_forward(raw_forward),
        estimate_daily=parse_estimate_daily(raw_estimate_daily),
        fiscal=parse_estimate_fiscal(raw_estimate_fiscal),
        opinion_tp=parse_opinion_tp(raw_opinion_tp),
        financial=parse_financial(raw_financial),
    )


# ── fixture 로더(개발/테스트용) ─────────────────────────────────────────────────
def load_fixture(name: str) -> dict:
    """epsrev/adapters/fixtures/<name> JSON 로드."""
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    import pprint
    fw = parse_forward(load_fixture("mock_forward.json"))
    print("forward:", fw.code, len(fw.points), "pts")
    print("  timepoints(asof=2026-06-29):", pick_timepoints(fw.points, date(2026, 6, 29)))
    pprint.pprint(parse_estimate_fiscal(load_fixture("mock_estimate_fiscal.json")))
    pprint.pprint(parse_opinion_tp(load_fixture("mock_opinion_tp.json")))
