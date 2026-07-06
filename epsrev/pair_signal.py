"""롱숏 페어 실행 신호 + 헤지 사이징 — 순수 함수.

pair_signal(stats): 진입/청산/손절 판정(방향은 롱=저평가 레그로 이미 고정).
hedge_sizing(beta, capital): 달러/베타 중립 비율·제안 수량.
"""
from __future__ import annotations

ENTRY_Z = 2.0
EXIT_Z = 0.5
STOP_Z = 3.0
HL_MAX = 60.0        # 반감기 과대(평균회귀 붕괴) 기준(일)
CORR_MIN = 0.3       # 상관 급락 손절 기준


def pair_signal(stats: dict) -> dict:
    """stats(compute_pair_stats) → {state, reason, z, entry_z}.
    state: 진입가능 | 대기 | 청산 | 손절. z 없으면 대기(데이터 부족)."""
    z = stats.get("zscore")
    corr = stats.get("corr")
    hl = stats.get("half_life")
    out = {"state": "대기", "reason": "", "z": z, "entry_z": ENTRY_Z}

    if z is None:
        out["reason"] = "z 계산 불가(데이터 부족)"
        return out
    az = abs(float(z))

    # 손절: 평균회귀 붕괴 신호 우선
    stop = []
    if az >= STOP_Z:
        stop.append(f"|z|={az:.1f}≥{STOP_Z:g} 추세 이탈")
    if hl is None:
        stop.append("반감기 정의 안 됨(평균회귀 붕괴)")
    elif float(hl) > HL_MAX:
        stop.append(f"반감기 {float(hl):.0f}일 과대")
    if corr is not None and float(corr) < CORR_MIN:
        stop.append(f"상관 {float(corr):.2f} 급락")
    if stop:
        out["state"] = "손절"
        out["reason"] = " · ".join(stop)
        return out

    if az <= EXIT_Z:
        out["state"] = "청산"
        out["reason"] = f"|z|={az:.1f}≤{EXIT_Z:g} (z→0 수렴)"
        return out

    if az >= ENTRY_Z:
        drift = "롱 레그 저평가" if z < 0 else "롱 레그 고평가(역방향 주의)"
        out["state"] = "진입가능"
        out["reason"] = f"|z|={az:.1f}≥{ENTRY_Z:g} 스프레드 벌어짐 · {drift}"
        return out

    out["state"] = "대기"
    out["reason"] = f"|z|={az:.1f} (진입 {ENTRY_Z:g} 대기)"
    return out


def hedge_sizing(beta, capital: float = 10_000_000) -> dict:
    """달러/베타 중립 헤지 비율·제안 금액.
    long_w=1, short_w=|beta|. 자본을 비율대로 배분. beta 결측 시 1(달러 중립)."""
    try:
        b = abs(float(beta))
        if b != b or b <= 0:
            b = 1.0
    except (TypeError, ValueError):
        b = 1.0
    long_w, short_w = 1.0, round(b, 3)
    total = long_w + short_w
    cap = float(capital) if capital else 0.0
    return {
        "long_w": long_w,
        "short_w": short_w,
        "long_amt": round(cap * long_w / total),
        "short_amt": round(cap * short_w / total),
    }
