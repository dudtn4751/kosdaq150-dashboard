"""epsrev/data/financials.py — FnGuide Company Guide 스타일 실적 추이 데이터 provider.

seam: get_fin_timeseries(ticker) 하나가 콘텐츠를 책임진다.
- OPENDART_API_KEY 없으면 '빈 스키마'(모든 값 None/[]) 반환 → 양식만 렌더(graceful).
- 있으면 OpenDartReader(재무) + pykrx(PER/PBR/주가)로 실데이터.

단위: OpenDART 원 → 백만원(1e6). 손익·현금흐름은 DART 누적보고 → 분기 개별값으로 환산
     (당분기누적 - 직전분기누적). 재무상태표는 기말잔액 그대로.
"""
from __future__ import annotations

import os
from datetime import datetime

try:
    import streamlit as st
    def _cache(func):
        return st.cache_data(ttl=86400, show_spinner=False)(func)
except Exception:
    def _cache(func):
        return func

# 고정 스키마 키
_QKEYS = ["period", "rev", "op", "opm", "ni", "ni_ctrl", "assets", "liab",
          "equity", "cf_op", "cf_inv", "cf_fin", "per", "pbr"]

# DART 분기 보고서 코드
_RC = {"1Q": "11013", "2Q": "11012", "3Q": "11014", "A": "11011"}  # 2Q/3Q=반기/3분기 누적, A=사업보고서


def _get_key():
    """OPENDART_API_KEY 조회 — 로컬 .env(os.environ) + Streamlit Cloud Secrets 둘 다 지원.
    앱 본체는 load_dotenv를 안 부르므로 여기서 best-effort로 .env를 끌어온다."""
    key = os.environ.get("OPENDART_API_KEY")
    if not key:
        try:
            from dotenv import load_dotenv  # 로컬 .env → os.environ
            load_dotenv(override=False)
            key = os.environ.get("OPENDART_API_KEY")
        except Exception:
            pass
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("OPENDART_API_KEY")
        except Exception:
            key = None
    return (str(key).strip() or None) if key else None


def _empty(note=None):
    return {"quarterly": [], "annual": [], "price": [], "note": note}


def _num(v):
    """DART 문자열 금액 → float(원). 빈값/NaN/'-' → None."""
    try:
        if v is None or v == "" or str(v).strip() in ("-", "—", "nan", "NaN"):
            return None
        f = float(str(v).replace(",", "").strip())
        return None if f != f else f   # NaN 제거
    except (ValueError, TypeError):
        return None


def _mn(v):
    """원 → 백만원."""
    return None if v is None else round(v / 1e6, 1)


def _acct(df, sj_divs, keywords, cols=("thstrm_amount",)):
    """finstate_all df에서 sj_div ∈ sj_divs, account_nm이 keyword 포함하는 첫 값(원).
    cols 순서대로 시도(누적 컬럼 우선 등). 실패 시 None."""
    if df is None or len(df) == 0:
        return None
    try:
        sub = df[df["sj_div"].isin(sj_divs)]
        names = sub["account_nm"].astype(str).str.replace(" ", "")
        for kw in keywords:
            k = kw.replace(" ", "")
            hit = sub[names.str.contains(k, na=False, regex=False)]
            if len(hit):
                row = hit.iloc[0]
                for c in cols:
                    if c in row.index:
                        v = _num(row[c])
                        if v is not None:
                            return v
                return None
    except Exception:
        return None
    return None


# 계정 추출 규칙 (sj_div 후보, 이름 키워드)
def _extract_flows(df, cum=False):
    """손익+현금흐름 추출 → dict(원).
    cum=True(반기·3분기 보고서): 누적 컬럼(thstrm_add_amount) 우선 → 일관된 '누적'값.
    cum=False(1분기·사업보고서): thstrm_amount(각각 3M·12M).
    """
    # 손익(IS/CIS): 반기·3분기 thstrm=3M이므로 누적은 add_amount 우선.
    # 현금흐름(CF): thstrm 자체가 연초부터 누적 → thstrm 우선.
    is_cols = ("thstrm_add_amount", "thstrm_amount") if cum else ("thstrm_amount",)
    cf_cols = ("thstrm_amount", "thstrm_add_amount")
    return {
        "rev":     _acct(df, ["IS", "CIS"], ["매출액", "수익(매출액)", "영업수익", "매출및지분법손익"], is_cols),
        "op":      _acct(df, ["IS", "CIS"], ["영업이익"], is_cols),
        "ni":      _acct(df, ["IS", "CIS"], ["당기순이익", "분기순이익", "반기순이익", "연결당기순이익"], is_cols),
        "ni_ctrl": _acct(df, ["IS", "CIS"], ["지배기업의소유주에게귀속되는당기순이익",
                                             "지배기업소유주지분", "지배주주순이익", "지배기업의소유주"], is_cols),
        "cf_op":   _acct(df, ["CF"], ["영업활동현금흐름", "영업활동으로인한현금흐름"], cf_cols),
        "cf_inv":  _acct(df, ["CF"], ["투자활동현금흐름", "투자활동으로인한현금흐름"], cf_cols),
        "cf_fin":  _acct(df, ["CF"], ["재무활동현금흐름", "재무활동으로인한현금흐름"], cf_cols),
    }


def _extract_bs(df):
    """재무상태표(기말잔액) 추출 → dict(원)."""
    return {
        "assets": _acct(df, ["BS"], ["자산총계"]),
        "liab":   _acct(df, ["BS"], ["부채총계"]),
        "equity": _acct(df, ["BS"], ["자본총계"]),
    }


def _sub(a, b):
    return None if (a is None or b is None) else a - b


def _opm(op, rev):
    if op is None or rev in (None, 0):
        return None
    return round(op / rev * 100, 1)


def _finstate(dart, corp, year, rc):
    """finstate_all 연결(CFS) 우선, 없으면 별도(OFS). 실패 시 None."""
    for fs in ("CFS", "OFS"):
        try:
            df = dart.finstate_all(corp, year, reprt_code=rc, fs_div=fs)
            if df is not None and len(df) > 0:
                return df
        except Exception:
            continue
    return None


def _pykrx_fund(ticker, date_yyyymmdd):
    """해당 일자(가장 가까운 영업일) PER/PBR. 실패 시 (None, None)."""
    try:
        from pykrx import stock
        # 해당 월 구간 조회 후 마지막 값
        d = date_yyyymmdd
        frm = d[:6] + "01"
        df = stock.get_market_fundamental_by_date(frm, d, ticker)
        if df is not None and len(df):
            row = df.iloc[-1]
            per = float(row.get("PER")) if row.get("PER") not in (None, 0) else None
            pbr = float(row.get("PBR")) if row.get("PBR") not in (None, 0) else None
            return per, pbr
    except Exception:
        pass
    return None, None


def _pykrx_price(ticker, years=5):
    """일별 종가 [{date, close}]. 실패 시 []."""
    try:
        from pykrx import stock
        end = datetime.now()
        frm = end.replace(year=end.year - years)
        df = stock.get_market_ohlcv_by_date(frm.strftime("%Y%m%d"), end.strftime("%Y%m%d"), ticker)
        if df is None or len(df) == 0:
            return []
        out = []
        for idx, row in df.iterrows():
            try:
                dt = idx.strftime("%Y-%m-%d")
                out.append({"date": dt, "close": float(row["종가"])})
            except Exception:
                continue
        return out
    except Exception:
        return []


def _period_end(year, q):
    """분기 말일 YYYYMMDD. q: 1~4, None=연말."""
    ends = {1: "0331", 2: "0630", 3: "0930", 4: "1231", None: "1231"}
    return f"{year}{ends[q]}"


@_cache
def get_fin_timeseries(ticker: str) -> dict:
    """FnGuide 스타일 실적 추이 데이터. 스키마 고정.
    키/데이터 없으면 빈 스키마(양식만). 예외는 전부 graceful → 빈 스키마.
    """
    key = _get_key()
    if not key:
        return _empty("OPENDART_API_KEY 미설정 — 로컬 .env 또는 Streamlit Secrets에 키를 넣어주세요.")

    try:
        import OpenDartReader
    except Exception:
        return _empty("OpenDartReader 미설치 — requirements.txt의 OpenDartReader 설치 필요.")
    try:
        dart = OpenDartReader(key)   # 생성 시 CORPCODE 다운로드(키 유효성·네트워크 검증)
    except Exception as e:
        return _empty(f"OpenDart 초기화 실패({type(e).__name__}) — 키 유효성/네트워크 확인. {str(e)[:80]}")

    ticker = str(ticker).zfill(6)
    now_year = datetime.now().year

    # corp 확인(미발견 → 빈 스키마)
    try:
        corp_code = dart.find_corp_code(ticker)
    except Exception:
        corp_code = None
    corp = ticker  # OpenDartReader는 종목코드도 허용

    quarterly, annual = [], []
    try:
        # ── 연도별(최근 5년): 사업보고서(11011) ──
        for year in range(now_year - 1, now_year - 6, -1):
            df_a = _finstate(dart, corp, year, _RC["A"])
            if df_a is None:
                continue
            fl = _extract_flows(df_a)      # 연간 누적 = 연간값
            bs = _extract_bs(df_a)
            per, pbr = _pykrx_fund(ticker, _period_end(year, None))
            annual.append({
                "period": str(year),
                "rev": _mn(fl["rev"]), "op": _mn(fl["op"]), "opm": _opm(fl["op"], fl["rev"]),
                "ni": _mn(fl["ni"]), "ni_ctrl": _mn(fl["ni_ctrl"]),
                "assets": _mn(bs["assets"]), "liab": _mn(bs["liab"]), "equity": _mn(bs["equity"]),
                "cf_op": _mn(fl["cf_op"]), "cf_inv": _mn(fl["cf_inv"]), "cf_fin": _mn(fl["cf_fin"]),
                "per": per, "pbr": pbr,
            })
        annual.reverse()  # 오래된→최신

        # ── 분기별(최근 2년 → 8분기): 누적 → 개별 환산 ──
        for year in range(now_year - 1, now_year - 3, -1):
            dfs = {q: _finstate(dart, corp, year, rc) for q, rc in _RC.items()}
            # 일관된 '누적' 손익/현금흐름: 1Q=3M, 반기=6M누적, 3분기=9M누적, 사업=12M
            cum = {
                "1Q": _extract_flows(dfs["1Q"]) if dfs["1Q"] is not None else None,
                "2Q": _extract_flows(dfs["2Q"], cum=True) if dfs["2Q"] is not None else None,
                "3Q": _extract_flows(dfs["3Q"], cum=True) if dfs["3Q"] is not None else None,
                "A":  _extract_flows(dfs["A"]) if dfs["A"] is not None else None,
            }
            # 개별값 = 당분기누적 - 직전분기누적
            def indiv(q):
                if q == 1:
                    return cum["1Q"]
                prev = {2: "1Q", 3: "2Q", 4: "3Q"}[q]
                curk = {2: "2Q", 3: "3Q", 4: "A"}[q]
                c, p = cum[curk], cum[prev]
                if c is None:
                    return None
                if p is None:
                    return c  # 직전 없으면 누적 그대로(부정확하나 graceful)
                return {k: _sub(c[k], p[k]) for k in c}
            for q in (1, 2, 3, 4):
                fl = indiv(q)
                if fl is None:
                    continue
                bs_df = dfs[{1: "1Q", 2: "2Q", 3: "3Q", 4: "A"}[q]]
                bs = _extract_bs(bs_df) if bs_df is not None else {"assets": None, "liab": None, "equity": None}
                per, pbr = _pykrx_fund(ticker, _period_end(year, q))
                quarterly.append({
                    "period": f"{year} {q}Q",
                    "rev": _mn(fl["rev"]), "op": _mn(fl["op"]), "opm": _opm(fl["op"], fl["rev"]),
                    "ni": _mn(fl["ni"]), "ni_ctrl": _mn(fl["ni_ctrl"]),
                    "assets": _mn(bs["assets"]), "liab": _mn(bs["liab"]), "equity": _mn(bs["equity"]),
                    "cf_op": _mn(fl["cf_op"]), "cf_inv": _mn(fl["cf_inv"]), "cf_fin": _mn(fl["cf_fin"]),
                    "per": per, "pbr": pbr,
                })
        quarterly.sort(key=lambda x: x["period"])  # 오래된→최신
    except Exception as e:
        note = f"DART 조회 오류: {type(e).__name__}"
    else:
        note = None

    price = _pykrx_price(ticker, years=5)
    if not quarterly and not annual:
        note = note or "DART 재무 응답 없음 — API 키 유효성/종목코드/네트워크를 확인하세요."
    return {"quarterly": quarterly, "annual": annual, "price": price, "note": note}
