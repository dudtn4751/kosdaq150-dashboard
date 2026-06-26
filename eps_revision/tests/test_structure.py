"""스캐폴딩 구조 검증 (계산 로직 전 단계).

- 패키지·모듈 임포트 정상
- 스키마(EpsRevisionInput) 샘플 구성 가능
- 각 레이어/게이트/집계/인사이트 진입점이 NotImplementedError를 던짐(아직 미구현)

sample_input()은 이후 단계의 로직 테스트가 재사용할 픽스처.
실행: python -m eps_revision.tests.test_structure  (또는 pytest)
"""

from __future__ import annotations

from eps_revision import layer1, layer2, layer3, confidence, aggregate, insight
from eps_revision.schemas import EpsRevisionInput


def sample_input() -> EpsRevisionInput:
    """완전한 형태의 샘플 입력 1건 (값은 예시 — 로직 테스트용 픽스처)."""
    tp = {"now": 100.0, "m1": 98.0, "m3": 92.0}
    return {
        "consensus": {
            "op_fy1": dict(tp), "op_fy2": {"now": 130.0, "m1": 128.0, "m3": 120.0},
            "eps_fy1": {"now": 5000.0, "m1": 4900.0, "m3": 4600.0},
            "eps_fy2": {"now": 6200.0, "m1": 6100.0, "m3": 5800.0},
        },
        "diffusion": {"up_count": 7, "down_count": 2, "total": 12},
        "surprise": [(105.0, 100.0), (98.0, 99.0), (110.0, 102.0), (120.0, 112.0)],
        "dispersion": {"std": 8.0, "mean": 100.0, "analyst_n": 12, "avg_estimate_age_days": 25.0},
        "target_price": {"tp_now": 150000.0, "tp_3m_ago": 130000.0, "price": 120000.0},
        "actuals_ytd": {"ytd_cumulative_op": 60.0, "fy_consensus_op": 100.0, "quarters_elapsed": 2},
        "news_sentiment": 0.3,
        "fiscal": {"current_fy_tag": "2026", "fy_roll_flag": False},
        "sector": "정보기술",
    }


def _raises_not_implemented(fn, *args) -> bool:
    try:
        fn(*args)
    except NotImplementedError:
        return True
    except Exception:  # noqa: BLE001  (다른 예외 = 스캐폴딩 깨짐)
        return False
    return False


def test_sample_input_shape():
    d = sample_input()
    assert set(d) == {"consensus", "diffusion", "surprise", "dispersion", "target_price",
                      "actuals_ytd", "news_sentiment", "fiscal", "sector"}
    assert set(d["consensus"]) == {"op_fy1", "op_fy2", "eps_fy1", "eps_fy2"}
    assert len(d["surprise"]) == 4


def test_implemented_entrypoints():
    """구현 완료된 진입점은 정상 동작해야 한다."""
    d = sample_input()
    assert layer1.realized_revision(d).available is True   # Layer1 구현됨


def test_entrypoints_not_yet_implemented():
    """아직 미구현인 진입점은 NotImplementedError."""
    d = sample_input()
    assert _raises_not_implemented(layer2.revision_momentum, d)
    assert _raises_not_implemented(layer3.forward_pressure, d)
    assert _raises_not_implemented(confidence.confidence_gate, d)
    assert _raises_not_implemented(aggregate.combine_layers, {}, 1.0)
    assert _raises_not_implemented(aggregate.standardize_sector_relative, 0.0, [])
    assert _raises_not_implemented(aggregate.standardize_sector_batch, {}, {})
    assert _raises_not_implemented(insight.generate_insight, 0.0, {}, 1.0, {})


if __name__ == "__main__":
    test_sample_input_shape()
    test_implemented_entrypoints()
    test_entrypoints_not_yet_implemented()
    print("OK — 구조 검증 통과 (Layer1 구현 / 나머지 6 진입점 미구현)")
