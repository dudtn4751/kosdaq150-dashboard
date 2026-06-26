"""Layer 2 — 리비전 모멘텀 (변화의 2차 미분: 가속/감속).

같은 +리비전이라도 '빨라지는' 종목과 '식어가는' 종목을 구분한다.
  - accel          : 1M 리비전 속도(연율) - 3M 리비전 속도(연율). 양수=상향 가속.
                     1M 연율 = rev_op_1m * 12, 3M 연율 = rev_op_3m * 4 (단순 연율화)
  - diffusion_trend: diffusion_idx 개선 여부 (이번 vs 직전, 직전 데이터 있으면)
  - disp_cv        : 추정치 변동계수 std/|mean| (축소=컨센 수렴=양호). 현재 CV 우선 반환.

원칙: 순수 함수, raw 값 반환(표준화 나중), 결측 None(0으로 안 채움), 분모 0/음수 가드.
"""

from __future__ import annotations

from typing import Optional

from .layer1 import diffusion_index, revision_ratio
from .schemas import EpsRevisionInput, LayerResult

# 단순 연율화 계수
ANNUALIZE_1M = 12.0
ANNUALIZE_3M = 4.0


def revision_accel(rev_1m: Optional[float], rev_3m: Optional[float]) -> Optional[float]:
    """리비전 가속도 = (1M 속도 연율) - (3M 속도 연율). 둘 중 하나라도 결측이면 None."""
    if rev_1m is None or rev_3m is None:
        return None
    return rev_1m * ANNUALIZE_1M - rev_3m * ANNUALIZE_3M


def diffusion_trend(curr_idx: Optional[float], prev_idx: Optional[float]) -> Optional[float]:
    """확산 추세 = 현재 diffusion_idx - 직전 diffusion_idx (양수=상향 쏠림 개선).

    둘 중 하나라도 없으면 None(직전 데이터 미보유 포함).
    """
    if curr_idx is None or prev_idx is None:
        return None
    return curr_idx - prev_idx


def dispersion_cv(std: Optional[float], mean: Optional[float]) -> Optional[float]:
    """추정치 변동계수 CV = std / |mean|. mean 0·결측 또는 std 결측이면 None."""
    if std is None or mean is None or mean == 0:
        return None
    return std / abs(mean)


def revision_momentum(data: EpsRevisionInput) -> LayerResult:
    """리비전의 가속/감속을 컴포넌트 raw로 산출 → LayerResult.

    evidence: accel, diffusion_trend, disp_cv (결측 None).
    raw     : 방향성 모멘텀(accel, diffusion_trend)의 가용 평균(잠정). disp_cv는 보조(레벨).
    available: 방향성 모멘텀 신호(accel/diffusion_trend) 1개 이상 존재.
    """
    cons = data.get("consensus") or {}
    op1 = cons.get("op_fy1") if isinstance(cons.get("op_fy1"), dict) else {}
    rev_op_1m = revision_ratio(op1.get("now"), op1.get("m1"))
    rev_op_3m = revision_ratio(op1.get("now"), op1.get("m3"))
    accel = revision_accel(rev_op_1m, rev_op_3m)

    # 직전 분기 확산도(옵션: data['diffusion_prev'], 스키마 외 선택 입력) 있으면 추세 계산
    curr_diff = diffusion_index(data.get("diffusion"))
    prev_diff = diffusion_index(data.get("diffusion_prev")) if data.get("diffusion_prev") else None
    diff_trend = diffusion_trend(curr_diff, prev_diff)

    disp = data.get("dispersion") or {}
    disp_cv = dispersion_cv(disp.get("std"), disp.get("mean"))

    evidence = {"accel": accel, "diffusion_trend": diff_trend, "disp_cv": disp_cv}
    directional = [v for v in (accel, diff_trend) if v is not None]
    raw = (sum(directional) / len(directional)) if directional else 0.0
    return LayerResult(raw=raw, evidence=evidence, available=bool(directional))
