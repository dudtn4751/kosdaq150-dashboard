"""get_price_df 어댑터 템플릿 — 팀원 대시보드의 data/scorer.py(또는 데이터 레이어)에 추가.

비율선/기술 패널은 종목별 '일봉'이 필요합니다. 아래 계약(반환 형태)만 맞춰
여러분의 일봉 소스(DB/CSV/API/내부 함수)에 연결하면 패널이 켜집니다.
소스 연결 전에는 None을 반환 → 패널은 '비활성 캡션'으로 안전하게 표시됩니다.

계약:
  get_price_df(ticker: str) -> pandas.DataFrame | None
    필수 컬럼: date  (YYYY-MM-DD 문자열 또는 datetime),
              close (float),
              value (float, 거래대금 — 억 단위 권장; 없으면 NaN/None 가능)
    행 = 일자별(오름차순 권장). 데이터 없으면 None.
    최소 60거래일 권장(z-score/상관 윈도우). 120일이면 이동평균 배열(정/역배열)까지 산출.
"""

import pandas as pd


def get_price_df(ticker: str):
    """여러분의 일봉 소스에 연결. 아래 두 예시 중 택1로 _load_daily만 구현하면 됨."""
    df = _load_daily(ticker)
    if df is None or df.empty:
        return None
    # 컬럼 표준화(이름이 다르면 매핑) — 필수: date, close, value
    cols = {c.lower(): c for c in df.columns}
    out = pd.DataFrame({
        "date": df[cols.get("date", "date")],
        "close": pd.to_numeric(df[cols.get("close", "close")], errors="coerce"),
        "value": pd.to_numeric(df[cols["value"]], errors="coerce") if "value" in cols else None,
    })
    return out


def _load_daily(ticker: str):
    """★ 여기만 구현 ★ — 종목코드 → 일봉 DataFrame(date, close, value). 없으면 None.

    예시 A) 종목별 CSV (data/daily/005930.csv):
        from pathlib import Path
        p = Path("data/daily") / f"{ticker}.csv"
        return pd.read_csv(p) if p.exists() else None

    예시 B) 하나의 통합 CSV (컬럼: ticker,date,close,value):
        all_df = pd.read_csv("data/daily_all.csv", dtype={"ticker": str})
        sub = all_df[all_df["ticker"] == ticker]
        return sub if len(sub) else None

    예시 C) 내부 API/DB:
        return your_db.get_ohlcv(ticker)   # date,close,value 포함 DataFrame
    """
    return None   # ← 소스 연결 전까지 None (패널 비활성)
