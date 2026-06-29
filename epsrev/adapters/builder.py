"""
adapters/builder.py
===================
backend.py get_company() 반환값을 eps_revision_score.StockInput으로 변환하는 어댑터.
FnSpace 미연결 구간은 더미값(주석 TODO)으로 채우고, fnspace_extra 인자로 실제값 주입 가능.
"""
from __future__ import annotations

import datetime
import sys
import os

from typing import Optional

from epsrev.eps_revision_score import (
    ActualsYTD,
    Consensus,
    Diffusion,
    Dispersion,
    Fiscal,
    StockInput,
    TargetPrice,
)

# ── 섹터별 리비전 자기상관계수 ────────────────────────────────────────────────
SECTOR_AUTOCORR: dict[str, float] = {
    "반도체·IT하드웨어":        0.58,
    "전력기기·전력인프라·원전": 0.52,
    "조선·방산·우주항공":       0.50,
    "자동차·모빌리티":          0.48,
    "2차전지·배터리소재":       0.35,
    "바이오·의료기기":          0.30,
    "K소비재·유통":             0.42,
    "인터넷·SW·게임·콘텐츠":   0.45,
    "금융·지주":                0.38,
    "철강·비철금속":            0.40,
    "정유·화학·석유화학":       0.38,
    "건설·운송·상사":           0.35,
}
_DEFAULT_AUTOCORR = 0.40

_POS_WORDS = frozenset({"상향", "호실적", "서프라이즈", "수주", "증가", "개선", "확대", "성장"})
_NEG_WORDS = frozenset({"하향", "실망", "우려", "감소", "부진", "축소", "둔화", "적자"})


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _parse_quarter(q_tag: str) -> Optional[tuple[int, int]]:
    """'25Q2' → (2025, 6)  실패 시 None."""
    try:
        yr2  = int(q_tag[:2])
        qnum = int(q_tag[3])
        return (2000 + yr2, qnum * 3)
    except (ValueError, IndexError):
        return None


def _parse_cons_month(m_str: str) -> Optional[tuple[int, int]]:
    """'25.07' → (2025, 7)  실패 시 None."""
    try:
        yr2, mo = m_str.split(".")
        return (2000 + int(yr2), int(mo))
    except (ValueError, AttributeError):
        return None


def _months_diff(d1: tuple[int, int], d2: tuple[int, int]) -> int:
    return abs((d1[0] - d2[0]) * 12 + (d1[1] - d2[1]))


def _news_sentiment(news: list[dict]) -> float:
    """제목 키워드 기반 감성 점수 (-1 ~ +1). TODO: KR-FinBERT 연결 후 교체."""
    if not news:
        return 0.0
    pos = sum(
        1 for item in news for w in _POS_WORDS if w in item.get("t", "")
    )
    neg = sum(
        1 for item in news for w in _NEG_WORDS if w in item.get("t", "")
    )
    return max(-1.0, min(1.0, (pos - neg) / max(len(news), 1)))


def _surprise_4q(fin: list[dict], cons: list[dict]) -> list[tuple[float, float]]:
    """
    fin 최근 4분기 × (actual_op, consensus_op).
    consensus_op: 해당 분기 종료월과 가장 가까운 cons 항목의 fy1 사용(6개월 이내).
    매칭 불가 시 actual_op * 0.95 더미.
    TODO: FnSpace 연결 후 분기별 실제 컨센서스로 교체.
    """
    result: list[tuple[float, float]] = []
    for entry in fin[-4:]:
        actual = float(entry.get("op", 0))
        q_date = _parse_quarter(entry.get("q", ""))

        if q_date and cons:
            best = min(
                cons,
                key=lambda c: _months_diff(
                    q_date,
                    _parse_cons_month(c.get("m", "")) or (0, 0),
                ),
            )
            best_date = _parse_cons_month(best.get("m", ""))
            if best_date and _months_diff(q_date, best_date) <= 6:
                consensus_op = float(best.get("fy1", actual * 0.95))
            else:
                consensus_op = actual * 0.95  # 더미: 매칭 거리 초과
        else:
            consensus_op = actual * 0.95  # 더미: 날짜 파싱 불가

        result.append((actual, consensus_op))
    return result


# ── 퍼블릭 API ────────────────────────────────────────────────────────────────

def build_stock_input(
    ticker: str,
    sector: str,
    fin: list[dict],
    cons: list[dict],
    rpt: Optional[dict],
    news: list[dict],
    price_data: dict,
    fnspace_extra: Optional[dict] = None,
    # fnspace_extra 예시:
    # {
    #   "eps_fy1": 44459, "eps_fy1_1m": 40000, "eps_fy1_3m": 30000, "eps_fy2": 50000,
    #   "diffusion": {"up_count": 20, "down_count": 3, "total": 25},
    #   "dispersion": {"std": 4.0, "mean": 85.5, "analyst_n": 25, "avg_estimate_age_days": 20},
    #   "tp_3m_ago": 380000,
    # }
) -> Optional[StockInput]:
    """
    fin 또는 cons가 비어있으면 None 반환.
    fnspace_extra가 있으면 해당 필드를 더미값 대신 실제값으로 채움.
    """
    if not fin or not cons:
        return None

    fx = fnspace_extra or {}
    today     = datetime.date.today()
    cur_yr2   = today.year % 100   # e.g. 26
    cur_month = today.month

    # ── Consensus ─────────────────────────────────────────────────────────────
    op_fy1    = float(cons[-1]["fy1"])
    op_fy1_1m = float(cons[-2]["fy1"]) if len(cons) >= 2 else None
    op_fy1_3m = float(cons[-4]["fy1"]) if len(cons) >= 4 else None
    op_fy2    = float(cons[-1]["fy2"])

    # FnSpace 연결 전 None, fnspace_extra로 덮어쓰기 가능
    # TODO: FnSpace 연결 후 실제 EPS 컨센서스로 교체
    eps_fy1    = fx.get("eps_fy1")
    eps_fy1_1m = fx.get("eps_fy1_1m")
    eps_fy1_3m = fx.get("eps_fy1_3m")
    eps_fy2    = fx.get("eps_fy2")

    consensus = Consensus(
        op_fy1=op_fy1, op_fy1_1m=op_fy1_1m, op_fy1_3m=op_fy1_3m, op_fy2=op_fy2,
        eps_fy1=eps_fy1, eps_fy1_1m=eps_fy1_1m, eps_fy1_3m=eps_fy1_3m, eps_fy2=eps_fy2,
    )

    # ── Diffusion ─────────────────────────────────────────────────────────────
    # TODO: FnSpace 연결 후 실제 상향수/하향수/전체 애널리스트 수로 교체
    if "diffusion" in fx:
        d = fx["diffusion"]
        diffusion = Diffusion(
            up_count=d["up_count"], down_count=d["down_count"], total=d["total"]
        )
    else:
        diffusion = Diffusion(up_count=0, down_count=0, total=1)

    # ── Dispersion ────────────────────────────────────────────────────────────
    # TODO: FnSpace 연결 후 실제 표준편차/평균/애널리스트 수/추정 경과일로 교체
    if "dispersion" in fx:
        d = fx["dispersion"]
        dispersion = Dispersion(
            std=d["std"],
            mean=d["mean"],
            analyst_n=d["analyst_n"],
            avg_estimate_age_days=d["avg_estimate_age_days"],
        )
    else:
        dispersion = Dispersion(std=0.0, mean=op_fy1, analyst_n=5, avg_estimate_age_days=30)

    # ── TargetPrice ───────────────────────────────────────────────────────────
    tp_now    = float(rpt["tp"]) if rpt else None
    tp_3m_ago = float(fx["tp_3m_ago"]) if "tp_3m_ago" in fx else None
    # TODO: FnSpace 연결 후 tp_3m_ago 실제값으로 교체
    target_price = TargetPrice(
        tp_now=tp_now, tp_3m_ago=tp_3m_ago, price=float(price_data["price"])
    )

    # ── ActualsYTD ────────────────────────────────────────────────────────────
    cur_yr_pfx   = f"{cur_yr2:02d}Q"
    prior_yr_pfx = f"{(cur_yr2 - 1) % 100:02d}Q"

    cur_qs   = [e for e in fin if e.get("q", "").startswith(cur_yr_pfx)]
    prior_qs = [e for e in fin if e.get("q", "").startswith(prior_yr_pfx)]

    ytd_cumulative_op = float(sum(e["op"] for e in cur_qs)) if cur_qs else 0.0
    quarters_elapsed  = len(cur_qs)

    if prior_qs:
        prior_fy_actual_op = float(sum(e["op"] for e in prior_qs))
    else:
        # TODO: FnSpace 연결 후 실제 직전연도 실적으로 교체
        prior_fy_actual_op = op_fy1 * 0.8  # 더미: 직전연도 분기 없음

    actuals_ytd = ActualsYTD(
        ytd_cumulative_op=ytd_cumulative_op,
        fy_consensus_op=op_fy1,
        quarters_elapsed=max(quarters_elapsed, 1),  # 0 나눔 방지
        prior_fy_actual_op=prior_fy_actual_op,
    )

    # ── Fiscal ────────────────────────────────────────────────────────────────
    fiscal = Fiscal(
        current_fy_tag=f"FY{cur_yr2:02d}",
        fy_roll_flag=(cur_month >= 10),
    )

    # ── surprise_4q ───────────────────────────────────────────────────────────
    surprise_4q = _surprise_4q(fin, cons)

    # ── news_sentiment ────────────────────────────────────────────────────────
    # TODO: KR-FinBERT 연결 후 교체
    news_sent = _news_sentiment(news)

    # ── sector_revision_autocorr ──────────────────────────────────────────────
    autocorr = SECTOR_AUTOCORR.get(sector, _DEFAULT_AUTOCORR)

    return StockInput(
        ticker=ticker,
        sector=sector,
        consensus=consensus,
        diffusion=diffusion,
        dispersion=dispersion,
        target_price=target_price,
        actuals_ytd=actuals_ytd,
        fiscal=fiscal,
        surprise_4q=surprise_4q,
        news_sentiment=news_sent,
        sector_revision_autocorr=autocorr,
    )


def eps_score_to_bucket(eps_score: float) -> float:
    """
    compute_eps_revision_score()의 eps_score (-100~+100)를
    종합 스코어 체계의 실적 버킷 (0~40)으로 변환.
    (-100 → 0점, 0 → 20점, +100 → 40점)
    """
    return (eps_score + 100) / 200 * 40


# ── 단위 테스트 ───────────────────────────────────────────────────────────────

def _make_fin(n: int = 8) -> list[dict]:
    """더미 fin: 최근 n분기. 현재(2026)년 1분기부터 역산해 채움."""
    quarters = [
        "24Q1", "24Q2", "24Q3", "24Q4",
        "25Q1", "25Q2", "25Q3", "25Q4",
        "26Q1", "26Q2",
    ]
    base = quarters[-n:]
    return [
        {"q": q, "rev": 10000 + i * 1000, "op": 2000 + i * 200, "opm": 20}
        for i, q in enumerate(base)
    ]


def _make_cons(n: int = 12) -> list[dict]:
    """더미 cons: 최근 n개월."""
    months = [
        "24.07", "24.08", "24.09", "24.10", "24.11", "24.12",
        "25.01", "25.02", "25.03", "25.04", "25.05", "25.06",
        "25.07", "25.08",
    ]
    base = months[-n:]
    return [
        {"m": m, "fy1": 14000 + i * 200, "fy2": 17000 + i * 100}
        for i, m in enumerate(base)
    ]


def test_build_normal():
    fin  = _make_fin(8)
    cons = _make_cons(12)
    result = build_stock_input(
        ticker="005930", sector="반도체·IT하드웨어",
        fin=fin, cons=cons,
        rpt={"tp": 260000, "r": "BUY", "an": "홍길동", "d": "26.06.01"},
        news=[{"t": "삼성 수주 증가", "d": "06.25"}],
        price_data={"price": 198500},
    )
    assert result is not None, "정상 입력 → StockInput 반환해야 함"
    assert result.consensus.op_fy1_3m == float(cons[-4]["fy1"]), "op_fy1_3m == cons[-4]['fy1']"
    print("PASS test_build_normal")


def test_build_missing_cons():
    fin  = _make_fin(8)
    cons = _make_cons(12)[:2]   # 길이 2
    result = build_stock_input(
        ticker="005930", sector="반도체·IT하드웨어",
        fin=fin, cons=cons,
        rpt=None, news=[], price_data={"price": 198500},
    )
    assert result is not None
    assert result.consensus.op_fy1_3m is None, "cons 길이 2 → op_fy1_3m==None"
    print("PASS test_build_missing_cons")


def test_build_no_rpt():
    fin  = _make_fin(8)
    cons = _make_cons(12)
    result = build_stock_input(
        ticker="005930", sector="반도체·IT하드웨어",
        fin=fin, cons=cons,
        rpt=None, news=[], price_data={"price": 198500},
    )
    assert result is not None
    assert result.target_price.tp_now is None, "rpt=None → tp_now==None"
    print("PASS test_build_no_rpt")


def test_build_fnspace_extra():
    fin  = _make_fin(8)
    cons = _make_cons(12)
    fx = {
        "eps_fy1": 44459,
        "eps_fy1_1m": 40000,
        "eps_fy1_3m": 30000,
        "eps_fy2": 50000,
        "diffusion": {"up_count": 20, "down_count": 3, "total": 25},
        "dispersion": {"std": 4.0, "mean": 85.5, "analyst_n": 25, "avg_estimate_age_days": 20},
        "tp_3m_ago": 380000,
    }
    result = build_stock_input(
        ticker="005930", sector="반도체·IT하드웨어",
        fin=fin, cons=cons,
        rpt={"tp": 260000, "r": "BUY", "an": "홍길동", "d": "26.06.01"},
        news=[], price_data={"price": 198500},
        fnspace_extra=fx,
    )
    assert result is not None
    assert result.consensus.eps_fy1 == 44459,      "eps_fy1 실제값 반영"
    assert result.diffusion.up_count == 20,        "diffusion 실제값 반영"
    assert result.dispersion.analyst_n == 25,      "dispersion 실제값 반영"
    assert result.target_price.tp_3m_ago == 380000,"tp_3m_ago 실제값 반영"
    print("PASS test_build_fnspace_extra")


def test_rescale():
    assert eps_score_to_bucket(100)  == 40.0
    assert eps_score_to_bucket(-100) == 0.0
    assert eps_score_to_bucket(0)    == 20.0
    assert abs(eps_score_to_bucket(60) - 32.0) < 1e-9
    print("PASS test_rescale")


# ── __main__ ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import pprint
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    # 단위 테스트 실행
    test_build_normal()
    test_build_missing_cons()
    test_build_no_rpt()
    test_build_fnspace_extra()
    test_rescale()
    print()

    # 더미 StockInput 출력
    fin  = _make_fin(8)
    cons = _make_cons(12)
    result = build_stock_input(
        ticker="005930",
        sector="반도체·IT하드웨어",
        fin=fin,
        cons=cons,
        rpt={"tp": 260000, "r": "BUY", "an": "홍길동", "d": "26.06.01"},
        news=[
            {"t": "삼성전자, 수주 증가로 호실적 기대", "d": "06.25"},
            {"t": "반도체 업황 우려 지속", "d": "06.24"},
        ],
        price_data={"price": 198500},
    )
    print("=== StockInput ===")
    pprint.pprint(result)
