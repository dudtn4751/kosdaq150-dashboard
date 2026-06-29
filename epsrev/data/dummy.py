import sys, os

from epsrev.eps_revision_score import (
    StockInput, Consensus, Diffusion, Dispersion,
    TargetPrice, ActualsYTD, Fiscal,
)

# 12섹터 × 3종목 = 36종목  (강세 / 중립 / 약세)
STOCKS_BY_SECTOR: dict[str, list[tuple[str, str]]] = {
    "반도체":    [("000660","SK하이닉스"),          ("005930","삼성전자"),           ("042700","한미반도체")],
    "전기전자":  [("066570","LG전자"),              ("009150","삼성전기"),           ("058470","리노공업")],
    "전력기기":  [("298040","효성중공업"),          ("034020","두산에너빌리티"),    ("010120","LS일렉트릭")],
    "조선방산":  [("012450","한화에어로스페이스"), ("329180","HD현대중공업"),       ("272210","한화시스템")],
    "자동차":    [("005380","현대차"),              ("000270","기아"),              ("012330","현대모비스")],
    "2차전지":   [("373220","LG에너지솔루션"),      ("247540","에코프로비엠"),      ("003670","포스코퓨처엠")],
    "바이오":    [("207940","삼성바이오로직스"),    ("128940","한미약품"),          ("000100","유한양행")],
    "소비재":    [("097950","CJ제일제당"),          ("004170","신세계"),            ("139480","이마트")],
    "인터넷SW":  [("035420","NAVER"),               ("259960","크래프톤"),          ("035720","카카오")],
    "금융":      [("105560","KB금융"),              ("138040","메리츠금융지주"),    ("032830","삼성생명")],
    "철강비철":  [("010130","고려아연"),            ("005490","POSCO홀딩스"),       ("004020","현대제철")],
    "정유화학":  [("096770","SK이노베이션"),        ("051910","LG화학"),            ("011170","롯데케미칼")],
    "건설운송":  [("028260","삼성물산"),            ("011200","HMM"),              ("006360","GS건설")],
}

# ── 섹터별 3M / 1M 리비전율  [강세, 중립, 약세] ──────────────────────────────
_REV_3M = {
    "반도체":    [ 1.00,  0.15, -0.20],
    "전기전자":  [ 0.25,  0.03, -0.12],
    "전력기기":  [ 0.55,  0.10, -0.15],
    "조선방산":  [ 0.45,  0.08, -0.12],
    "자동차":    [ 0.45,  0.05, -0.15],
    "2차전지":   [ 0.25,  0.00, -0.25],
    "바이오":    [ 0.60,  0.08, -0.18],
    "소비재":    [ 0.20,  0.02, -0.12],
    "인터넷SW":  [ 0.35,  0.05, -0.10],
    "금융":      [ 0.15, -0.03, -0.20],
    "철강비철":  [ 0.20, -0.05, -0.20],
    "정유화학":  [ 0.05, -0.08, -0.30],
    "건설운송":  [ 0.15,  0.00, -0.18],
}
_REV_1M = {
    "반도체":    [ 0.30,  0.05, -0.08],
    "전기전자":  [ 0.08,  0.01, -0.05],
    "전력기기":  [ 0.18,  0.04, -0.06],
    "조선방산":  [ 0.14,  0.03, -0.05],
    "자동차":    [ 0.12,  0.01, -0.06],
    "2차전지":   [ 0.08,  0.00, -0.10],
    "바이오":    [ 0.18,  0.02, -0.07],
    "소비재":    [ 0.07,  0.01, -0.05],
    "인터넷SW":  [ 0.12,  0.02, -0.04],
    "금융":      [ 0.04, -0.01, -0.08],
    "철강비철":  [ 0.06, -0.02, -0.08],
    "정유화학":  [ 0.02, -0.03, -0.12],
    "건설운송":  [ 0.05,  0.00, -0.07],
}

# 3 포지션: (up, down, total) / analyst_n / age_days
_DIFFUSION  = [(36, 6, 42), (14, 14, 28), (2, 13, 15)]
_ANALYST_N  = [42, 28, 15]
_AGE_DAYS   = [12.0, 25.0, 50.0]
_RUNRATE    = [0.20,  0.00, -0.12]
_TP_REV     = [0.20,  0.02, -0.10]
_NEWS       = [0.45,  0.02, -0.38]
_BEAT       = [0.10,  0.00, -0.07]
_SCALE      = [2.5,   0.8,   0.3]

_BASE_OP = {
    "반도체":    80000.0,
    "전기전자":  18000.0,
    "전력기기":   3000.0,
    "조선방산":   4000.0,
    "자동차":    18000.0,
    "2차전지":    5000.0,
    "바이오":     4000.0,
    "소비재":     8000.0,
    "인터넷SW":   6000.0,
    "금융":      25000.0,
    "철강비철":   4000.0,
    "정유화학":   8000.0,
    "건설운송":   3500.0,
}


def _build(ticker: str, sector: str, pos: int) -> StockInput:
    """pos: 0=강세, 1=중립, 2=약세"""
    op1  = _BASE_OP[sector] * _SCALE[pos]
    r3   = _REV_3M[sector][pos]
    r1   = _REV_1M[sector][pos]
    op3m = op1 / (1.0 + r3) if (1.0 + r3) > 0 else op1 * 1.5
    op1m = op1 / (1.0 + r1) if (1.0 + r1) > 0 else op1 * 1.05
    e1, e3m, e1m = op1 * 0.15, op3m * 0.15, op1m * 0.15
    up, dn, tot  = _DIFFUSION[pos]
    price  = op1 * 8.0
    tp_ago = price * 1.20
    tp_now = tp_ago * (1.0 + _TP_REV[pos])
    ytd    = (op1 / 4.0) * (1.0 + _RUNRATE[pos])
    qcons  = op1 * 0.25
    return StockInput(
        ticker=ticker, sector=sector,
        consensus=Consensus(
            op_fy1=op1,  op_fy1_1m=op1m, op_fy1_3m=op3m, op_fy2=op1 * 1.12,
            eps_fy1=e1,  eps_fy1_1m=e1m,  eps_fy1_3m=e3m,  eps_fy2=e1 * 1.12,
        ),
        diffusion=Diffusion(up_count=up, down_count=dn, total=tot),
        dispersion=Dispersion(
            std=op1 * (0.05 + pos * 0.03), mean=op1,
            analyst_n=_ANALYST_N[pos], avg_estimate_age_days=_AGE_DAYS[pos],
        ),
        target_price=TargetPrice(tp_now=tp_now, tp_3m_ago=tp_ago, price=price),
        actuals_ytd=ActualsYTD(
            ytd_cumulative_op=ytd, fy_consensus_op=op1,
            quarters_elapsed=1, prior_fy_actual_op=op1 * 0.85,
        ),
        fiscal=Fiscal(current_fy_tag="FY26", fy_roll_flag=False),
        surprise_4q=[(qcons * (1 + _BEAT[pos]), qcons)] * 4,
        news_sentiment=_NEWS[pos],
        sector_revision_autocorr=0.45,
    )


# (StockInput, 종목명, 섹터) — import 시 1회 생성
DUMMY_STOCKS: list[tuple[StockInput, str, str]] = [
    (_build(ticker, sector, pos), name, sector)
    for sector, stocks in STOCKS_BY_SECTOR.items()
    for pos, (ticker, name) in enumerate(stocks)
]
