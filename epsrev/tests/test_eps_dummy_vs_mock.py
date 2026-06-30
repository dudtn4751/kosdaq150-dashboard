"""
'더미 vs 목업' EPS 리비전 비교 불변식 (라이브 호출 없음).
실행: python -m pytest epsrev/tests/test_eps_dummy_vs_mock.py
"""
from epsrev.tools.compare_eps_dummy_vs_mock import run_comparison


def test_missing_dispersion_is_weight_excluded_not_zero():
    r = run_comparison()
    # 목업: std/mean 결측 → disp_cv None(가중제외), 0 아님
    assert r["mock"]["evidence"]["disp_cv"] is None
    assert r["si_mock"].dispersion.std is None
    # momentum 레이어는 disp_cv 결측에도 (accel 등으로) 산출됨 → 0으로 채우지 않고 재정규화
    assert r["mock"]["layers"]["momentum"] is not None


def test_diffusion_proxy_applied():
    r = run_comparison()
    assert abs(r["mock"]["evidence"]["diffusion_idx"] - (12 - 2) / 26) < 1e-6
    assert r["dummy"]["evidence"]["diffusion_idx"] == 0.0
    assert r["si_mock"].diffusion.up_count == 12 and r["si_mock"].diffusion.total == 26


def test_mock_differs_and_higher_confidence():
    r = run_comparison()
    assert r["mock"]["eps_score"] != r["dummy"]["eps_score"]
    assert r["mock"]["confidence"] > r["dummy"]["confidence"]
