"""pair_signal: 진입/청산/손절 케이스 + hedge_sizing 단위테스트."""
from epsrev.pair_signal import pair_signal, hedge_sizing


def _st(z=None, corr=0.8, hl=10.0):
    return {"zscore": z, "corr": corr, "half_life": hl, "coint_p": 0.02, "adf_p": 0.03, "beta": 1.0}


def test_signal_entry():
    r = pair_signal(_st(z=-2.4))
    assert r["state"] == "진입가능" and "벌어" in r["reason"]


def test_signal_exit():
    assert pair_signal(_st(z=0.3))["state"] == "청산"


def test_signal_stop_highz():
    assert pair_signal(_st(z=3.2))["state"] == "손절"


def test_signal_stop_halflife():
    assert pair_signal(_st(z=2.2, hl=None))["state"] == "손절"     # 반감기 붕괴
    assert pair_signal(_st(z=2.2, hl=90))["state"] == "손절"       # 반감기 과대


def test_signal_stop_corr():
    assert pair_signal(_st(z=2.2, corr=0.2))["state"] == "손절"    # 상관 급락


def test_signal_wait():
    assert pair_signal(_st(z=1.0))["state"] == "대기"
    assert pair_signal(_st(z=None))["state"] == "대기"             # 데이터 부족


def test_hedge_sizing():
    h = hedge_sizing(0.8, capital=10_000_000)
    assert h["long_w"] == 1.0 and h["short_w"] == 0.8
    assert h["long_amt"] + h["short_amt"] == 10_000_000
    assert h["long_amt"] > h["short_amt"]                          # long_w > short_w
    # beta 결측 → 달러중립(1:1)
    h2 = hedge_sizing(None, capital=10_000_000)
    assert h2["short_w"] == 1.0 and h2["long_amt"] == h2["short_amt"]
