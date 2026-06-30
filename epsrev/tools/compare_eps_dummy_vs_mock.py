"""
epsrev/tools/compare_eps_dummy_vs_mock.py
=========================================
'더미 vs 목업' EPS 리비전 점수 비교 (라이브 호출 없음).

목적(키 없이 검증):
    1) 동일 종목을 (a)더미 경로 (b)목업 FnSpace 번들 주입 으로 각각 빌드해 점수 비교.
    2) 결측(dispersion std/mean, 추정경과일)이 0이 아니라 '가중제외'로 반영되는지
       → evidence.disp_cv is None, confidence 가 분산 결측으로 감점되지 않음.
    3) diffusion proxy(목표주가 상향/하향/전체)가 실제로 들어가는지
       → 더미 diffusion_idx ≈ 0 vs 목업 diffusion_idx ≈ (12-2)/26.

실행: PYTHONPATH=. python epsrev/tools/compare_eps_dummy_vs_mock.py
"""
from __future__ import annotations

from datetime import date

from epsrev.adapters import fnspace as fns
from epsrev.adapters.fnspace_parser import load_fixture, parse_all
from epsrev.adapters.builder import build_stock_input
from epsrev.eps_revision_score import (
    Consensus, Diffusion, Dispersion, Fiscal, StockInput, TargetPrice, ActualsYTD,
    compute_eps_revision_score,
)

ASOF = date(2026, 6, 29)   # 목업 최신일 — 결정적


# ── 섹터 피어(표준화용 분포). 단일종목이면 eps_score=0 이므로 피어 필요 ──────────────
def _peer(ticker, op1, op1m, op3m, up, down, total) -> StockInput:
    return StockInput(
        ticker=ticker, sector="반도체·IT하드웨어",
        consensus=Consensus(op_fy1=op1, op_fy1_1m=op1m, op_fy1_3m=op3m, op_fy2=op1 * 1.1,
                            eps_fy1=op1, eps_fy1_1m=op1m, eps_fy1_3m=op3m, eps_fy2=op1 * 1.1),
        diffusion=Diffusion(up_count=up, down_count=down, total=total),
        dispersion=Dispersion(std=op1 * 0.03, mean=op1, analyst_n=20, avg_estimate_age_days=25),
        target_price=TargetPrice(tp_now=op1 * 10, tp_3m_ago=op3m * 10, price=op1 * 8),
        actuals_ytd=ActualsYTD(ytd_cumulative_op=op1 * 0.5, fy_consensus_op=op1,
                               quarters_elapsed=2, prior_fy_actual_op=op3m * 0.9),
        fiscal=Fiscal(current_fy_tag="FY26", fy_roll_flag=False),
        surprise_4q=[(op1 * 0.25, op1m * 0.25)] * 4,
        news_sentiment=0.0, sector_revision_autocorr=0.58,
    )


PEERS = [
    _peer("000001", 100, 98, 95, 5, 8, 20),     # 약한/하향 피어
    _peer("000002", 100, 100, 100, 10, 10, 22),  # 중립
    _peer("000003", 100, 102, 99, 14, 4, 24),    # 완만 상향
    _peer("000004", 100, 105, 92, 16, 3, 25),    # 강한 상향
]


def _dummy_inputs():
    """더미 경로 입력(cons/fin/rpt). fnspace_extra=None → 자동 시도→키없음→더미 폴백."""
    fin = [{"q": "26Q1", "rev": 100000, "op": 91000, "opm": 20},
           {"q": "26Q2", "rev": 110000, "op": 96000, "opm": 21}]
    cons = [{"m": "26.03", "fy1": 330000, "fy2": 360000},
            {"m": "26.05", "fy1": 345000, "fy2": 400000},
            {"m": "26.06", "fy1": 350000, "fy2": 410000}]
    rpt = {"tp": 80000}
    return fin, cons, rpt


def run_comparison() -> dict:
    fin, cons, rpt = _dummy_inputs()
    price = {"price": 62000}

    # (a) 더미
    si_dummy = build_stock_input(
        ticker="005930", sector="반도체·IT하드웨어",
        fin=fin, cons=cons, rpt=rpt, news=[], price_data=price,
        fnspace_extra=None,
    )
    # (b) 목업 번들 주입
    bundle = fns.assemble_extra(
        parse_all(
            "A005930",
            raw_forward=load_fixture("mock_forward.json"),
            raw_estimate_daily=load_fixture("mock_estimate_daily.json"),
            raw_estimate_fiscal=load_fixture("mock_estimate_fiscal.json"),
            raw_opinion_tp=load_fixture("mock_opinion_tp.json"),
            raw_financial=load_fixture("mock_financial.json"),
        ),
        asof=ASOF,
    )
    si_mock = build_stock_input(
        ticker="005930", sector="반도체·IT하드웨어",
        fin=fin, cons=cons, rpt=rpt, news=[], price_data=price,
        fnspace_extra=bundle,
    )

    res_dummy = compute_eps_revision_score(si_dummy, sector_dist=PEERS)
    res_mock  = compute_eps_revision_score(si_mock,  sector_dist=PEERS)
    return {"bundle": bundle, "dummy": res_dummy, "mock": res_mock,
            "si_dummy": si_dummy, "si_mock": si_mock}


def _fmt(x):
    return "None" if x is None else (f"{x:+.3f}" if isinstance(x, float) else str(x))


def main() -> int:
    r = run_comparison()
    d, m = r["dummy"], r["mock"]

    rows = [
        ("eps_score",      d["eps_score"],            m["eps_score"]),
        ("confidence",     d["confidence"],           m["confidence"]),
        ("layer realized", d["layers"]["realized"],   m["layers"]["realized"]),
        ("layer momentum", d["layers"]["momentum"],   m["layers"]["momentum"]),
        ("layer forward",  d["layers"]["forward"],    m["layers"]["forward"]),
        ("ev diffusion_idx", d["evidence"]["diffusion_idx"], m["evidence"]["diffusion_idx"]),
        ("ev disp_cv",     d["evidence"]["disp_cv"],  m["evidence"]["disp_cv"]),
        ("ev rev_op_3m",   d["evidence"]["rev_op_3m"], m["evidence"]["rev_op_3m"]),
        ("ev runrate_gap", d["evidence"]["runrate_gap"], m["evidence"]["runrate_gap"]),
        ("ev tp_lead",     d["evidence"]["tp_lead"],  m["evidence"]["tp_lead"]),
    ]
    print("=" * 64)
    print(f"{'항목':<18}{'더미':>14}{'목업':>16}")
    print("-" * 64)
    for name, dv, mv in rows:
        print(f"{name:<18}{_fmt(dv):>14}{_fmt(mv):>16}")
    print("-" * 64)
    print("더미 diffusion :", r['si_dummy'].diffusion)
    print("목업 diffusion :", r['si_mock'].diffusion, " (목표주가 1M 상향/하향/전체 proxy)")
    print("목업 dispersion:", r['si_mock'].dispersion, " (std/mean/age=None → 가중제외)")
    print("목업 insight   :", m["insight"])
    print("=" * 64)

    # ── 검증(가중제외 & diffusion proxy) ──
    assert m["evidence"]["disp_cv"] is None, "분산 결측은 None(가중제외)이어야 함"
    assert r["si_mock"].dispersion.std is None and r["si_mock"].dispersion.mean is None
    di_m = m["evidence"]["diffusion_idx"]
    assert di_m is not None and abs(di_m - (12 - 2) / 26) < 1e-6, "diffusion proxy 미반영"
    di_d = d["evidence"]["diffusion_idx"]
    assert di_d == 0.0, "더미 diffusion_idx 는 0 이어야"
    assert m["confidence"] > d["confidence"], "목업(커버리지26·결측 가중제외)이 더미보다 신뢰도↑"
    assert m["eps_score"] != d["eps_score"], "더미 vs 목업 점수가 달라야"
    print("✅ 검증 통과: 결측=가중제외(disp_cv None), diffusion proxy 반영, 더미≠목업")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
