"""scorer 어댑터 — 팀원 pair_finder가 기대하는 인터페이스를 우리 alpha.json(eps_rev)에 연결.

score_all_stocks() -> DataFrame[ticker, name, eps_score, confidence, flags]
get_stock_detail(ticker) -> {eps_score, confidence, insight, flags}
"""

import json
from pathlib import Path

import pandas as pd

_ALPHA = Path(__file__).resolve().parent / "alpha.json"


def _load():
    try:
        return json.loads(_ALPHA.read_text(encoding="utf-8"))
    except Exception:
        return {"ranked": []}


def score_all_stocks() -> pd.DataFrame:
    rows = []
    for s in _load().get("ranked", []):
        er = s.get("eps_rev") or {}
        score = er.get("score")
        if score is None:
            score = s.get("eps")            # 모듈 미가용 종목은 종합 EPS 팩터로 폴백
        rows.append({
            "ticker": s["code"], "name": s["name"],
            "eps_score": score,
            "confidence": er.get("confidence", 1.0),
            "flags": "; ".join(er.get("flags") or []),
        })
    return pd.DataFrame(rows, columns=["ticker", "name", "eps_score", "confidence", "flags"])


def get_stock_detail(ticker: str) -> dict:
    for s in _load().get("ranked", []):
        if s["code"] == ticker:
            er = s.get("eps_rev") or {}
            return {
                "eps_score": er.get("score", s.get("eps")),
                "confidence": er.get("confidence", 1.0),
                "insight": er.get("insight", ""),
                "flags": er.get("flags") or [],
            }
    return {}
