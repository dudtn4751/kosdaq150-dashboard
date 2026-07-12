"""숏 후보 스크리너 (롱숏 페어 MVP) — Long 티커 1개 → Short 후보 DataFrame.

데이터 소스 (MVP 범위):
  - CSV: data/value_chain/vc_nodes.csv, vc_edges.csv → 관계 근접성
  - pykrx/KRX: 가격, 거래대금, ADV20, 시가총액, 기관/외국인 수급
  - Stub(미연동, 추후 확장): EPS Revision, 12M Fwd PER/PBR, 대차 가능 여부,
    공매도/대차 리스크, DART 이벤트

설계 원칙 (절대 규칙):
  1) EPS 미연동은 0점이 아니라 **분모 제외**(가중치 재정규화) — coverage_ratio로 노출.
  2) 밸류(PER/PBR)는 **점수에 넣지 않는다** — 표시용 stub 컬럼만.
  3) beta 안정성은 시장 beta가 아니라 **두 종목 간 pair return beta**의
     rolling 표준편차 기준.
  4) sizing_beta / hedge_beta / market_beta_ratio는 **구현하지 않는다**.
  5) 타이밍 신호(z_score, half_life, 수급)는 **구조점수에 합산하지 않는다** —
     별도 컬럼으로만 표시.

streamlit 무의존 — 캐시는 페이지 래퍼(@st.cache_data)에서.
"""

import math
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
VC_DIR = BASE_DIR / "data" / "value_chain"

# ---------- 구조점수 가중치 ----------
# eps_gap은 stub(None) → 분모에서 제외되어 coverage_ratio = 0.80으로 표시된다.
# 타이밍(z_score/half_life/수급)과 밸류는 여기 없어야 정상 (절대 규칙 2·5).
FACTOR_WEIGHTS = {
    "proximity": 0.30,      # 관계 근접성 (밸류체인 CSV)
    "correlation": 0.20,    # 일수익률 상관 (120d)
    "beta_stability": 0.15, # pair beta rolling std (낮을수록 안정)
    "liquidity": 0.15,      # ADV20 (숏 가능 유동성)
    "eps_gap": 0.20,        # EPS Revision 갭 — stub, 분모 제외
}
COVERAGE_STAR_THRESHOLD = 0.9  # coverage_ratio 미만이면 grade에 '*' 표기

CORR_WINDOW = 120          # 상관/pair beta 산출 구간(거래일)
BETA_ROLL_WINDOW = 60      # rolling pair beta 창
ZSCORE_WINDOW = 60         # 스프레드 z-score 창
LOOKBACK_CAL_DAYS = 420    # 달력일 기준 시세 조회 구간(거래일 ~280 확보)
ENRICH_TOP_N = 12          # pykrx 조회(느림)를 수행할 근접성 상위 후보 수

# 관계 근접성 — 높을수록 페어 구조상 가까움
PROXIMITY = {
    "same_chain_step": 1.0,   # 동일 대분류·서브섹터·체인단계 (직접 경쟁)
    "same_subsector": 0.7,    # 동일 서브섹터, 다른 체인단계
    "direct_edge": 0.5,       # 공급-고객 직접 관계
    "same_category": 0.3,     # 동일 대분류만
}
RELATION_LABEL = {
    "same_chain_step": "동일 체인단계(직접 경쟁)",
    "same_subsector": "동일 서브섹터",
    "direct_edge": "공급-고객 관계",
    "same_category": "동일 대분류",
}


# ---------- Stub (추후 확장 지점 — 전부 None 반환) ----------
def stub_eps_revision_gap(long_ticker: str, short_ticker: str) -> Optional[float]:
    """EPS Revision 갭 (long 리비전 - short 리비전). 미연동 → None.
    연동 시: epsrev/data/dashboard_data.py CO[t]['sc']/['hist'] 재사용 예정.
    None이면 구조점수 분모에서 eps_gap 가중치가 제외된다 (0점 처리 금지)."""
    return None


def stub_fwd_valuation(ticker: str) -> dict:
    """12M Fwd PER/PBR. 미연동 → None. ⚠️ 연동되더라도 점수에는 넣지 않는다(표시용)."""
    return {"fwd_per": None, "fwd_pbr": None}


def stub_borrow_available(ticker: str) -> Optional[bool]:
    """실제 대차 가능 여부(증권사 API/수기 리스트). 미연동 → None."""
    return None


def stub_short_lending_risk(ticker: str) -> Optional[str]:
    """공매도 잔고/대차잔고 리스크 등급. 미연동 → None.
    연동 시: KRX 공매도 통계 or CO[t]['sb'](대차잔고) 재사용 예정."""
    return None


def stub_dart_events(ticker: str) -> Optional[str]:
    """DART 이벤트(유증·CB·소송 등). 미연동 → None."""
    return None


# ---------- 종목명 ↔ 티커 ----------
def _load_name_maps():
    """epsrev CO 맵(1차) + pykrx 전체 상장사(2차)로 이름→티커 사전 구성."""
    name_to_ticker, ticker_to_name = {}, {}
    try:
        from epsrev.data.dashboard_data import CO
        for t, info in CO.items():
            name_to_ticker[str(info["n"]).replace(" ", "")] = t
            ticker_to_name[t] = info["n"]
    except Exception:
        pass
    return name_to_ticker, ticker_to_name


def _pykrx_name_map():
    """pykrx 전체 KOSPI+KOSDAQ 이름→티커 (CO에 없는 종목 fallback)."""
    from pykrx import stock
    out = {}
    for mkt in ("KOSPI", "KOSDAQ"):
        for t in stock.get_market_ticker_list(market=mkt):
            out[stock.get_market_ticker_name(t).replace(" ", "")] = t
    return out


# ---------- 관계 근접성 (CSV) ----------
def load_value_chain():
    nodes = pd.read_csv(VC_DIR / "vc_nodes.csv", encoding="utf-8-sig").fillna("")
    edges = pd.read_csv(VC_DIR / "vc_edges.csv", encoding="utf-8-sig").fillna("")
    nodes["기업명"] = nodes["기업명"].astype(str).str.strip()
    return nodes, edges


def relation_candidates(long_name: str, nodes: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    """long 종목명 기준 밸류체인 이웃 → (기업명, relation, proximity). 근접성 최고값만 유지."""
    mine = nodes[nodes["기업명"] == long_name]
    found = {}  # name -> (relation_key, proximity)

    def _add(name, rel):
        name = str(name).strip()
        if not name or name == long_name:
            return
        if name not in found or PROXIMITY[rel] > found[name][1]:
            found[name] = (rel, PROXIMITY[rel])

    for _, row in mine.iterrows():
        cat, sub, step = row["대분류"], row["서브섹터"], row["체인단계"]
        same_step = nodes[(nodes["대분류"] == cat) & (nodes["서브섹터"] == sub) & (nodes["체인단계"] == step)]
        for n in same_step["기업명"]:
            _add(n, "same_chain_step")
        same_sub = nodes[(nodes["대분류"] == cat) & (nodes["서브섹터"] == sub)]
        for n in same_sub["기업명"]:
            _add(n, "same_subsector") if n not in found else None
        same_cat = nodes[nodes["대분류"] == cat]
        for n in same_cat["기업명"]:
            _add(n, "same_category") if n not in found else None

    e = edges[(edges["공급사"] == long_name) | (edges["고객사"] == long_name)]
    for _, row in e.iterrows():
        other = row["고객사"] if row["공급사"] == long_name else row["공급사"]
        _add(other, "direct_edge")

    if not found:
        return pd.DataFrame(columns=["name", "relation", "proximity"])
    return pd.DataFrame(
        [{"name": n, "relation": RELATION_LABEL[rel], "proximity": p} for n, (rel, p) in found.items()]
    ).sort_values("proximity", ascending=False).reset_index(drop=True)


# ---------- pykrx 시세/수급 ----------
def _date_range():
    end = pd.Timestamp.today().normalize()
    start = end - pd.Timedelta(days=LOOKBACK_CAL_DAYS)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def fetch_price(ticker: str) -> Optional[pd.DataFrame]:
    """일봉 OHLCV(+거래대금). 실패/빈값 → None."""
    from pykrx import stock
    s, e = _date_range()
    try:
        df = stock.get_market_ohlcv_by_date(s, e, ticker)
        return df if df is not None and not df.empty else None
    except Exception:
        return None


def fetch_mktcap(ticker: str) -> Optional[float]:
    """시가총액(원). KRX cap 엔드포인트 미가용 환경(빈 DF) → None (표시용)."""
    from pykrx import stock
    s, e = _date_range()
    try:
        cap = stock.get_market_cap_by_date(s, e, ticker)
        if cap is None or cap.empty:
            return None
        return float(cap["시가총액"].iloc[-1])
    except Exception:
        return None


def adv20_from_px(px: pd.DataFrame) -> Optional[float]:
    """ADV20(원). 거래대금 컬럼이 있으면 그대로, 없으면 종가×거래량 근사 —
    pykrx 버전/KRX 엔드포인트 차이에도 유동성 팩터가 살아있게 유지."""
    try:
        if "거래대금" in px.columns and px["거래대금"].tail(20).sum() > 0:
            return float(px["거래대금"].tail(20).mean())
        approx = (px["종가"] * px["거래량"]).tail(20)
        return float(approx.mean()) if approx.notna().any() else None
    except Exception:
        return None


def fetch_flows_20d(ticker: str) -> dict:
    """최근 20거래일 기관/외국인 순매수 금액(원). 실패 → None (표시용 — 점수 미반영)."""
    from pykrx import stock
    s, e = _date_range()
    try:
        tv = stock.get_market_trading_value_by_date(s, e, ticker)
        if tv is None or tv.empty:
            return {"inst_net_20d": None, "forgn_net_20d": None}
        tail = tv.tail(20)
        inst = float(tail["기관합계"].sum()) if "기관합계" in tail.columns else None
        forg = float(tail["외국인합계"].sum()) if "외국인합계" in tail.columns else None
        return {"inst_net_20d": inst, "forgn_net_20d": forg}
    except Exception:
        return {"inst_net_20d": None, "forgn_net_20d": None}


# ---------- 페어 통계 ----------
def pair_stats(long_close: pd.Series, cand_close: pd.Series) -> dict:
    """corr / pair beta / beta 안정성 / 스프레드 z-score / half-life.
    ⚠️ pair_beta는 cand 수익률 ~ long 수익률 회귀 — 시장(KOSPI) beta가 아니다."""
    df = pd.concat([long_close.rename("l"), cand_close.rename("c")], axis=1).dropna()
    if len(df) < BETA_ROLL_WINDOW + 20:
        return {"corr": None, "pair_beta": None, "beta_stability": None, "z_score": None, "half_life": None}

    rl = df["l"].pct_change().dropna()
    rc = df["c"].pct_change().dropna()
    both = pd.concat([rl.rename("l"), rc.rename("c")], axis=1).dropna().tail(CORR_WINDOW)

    corr = float(both["l"].corr(both["c"]))
    var_l = float(both["l"].var())
    pair_beta = float(both["l"].cov(both["c"]) / var_l) if var_l > 0 else None

    # pair beta 안정성: rolling 60d pair beta의 표준편차 (낮을수록 안정)
    roll = pd.concat([rl.rename("l"), rc.rename("c")], axis=1).dropna()
    betas = []
    for i in range(BETA_ROLL_WINDOW, len(roll) + 1):
        w = roll.iloc[i - BETA_ROLL_WINDOW : i]
        v = float(w["l"].var())
        if v > 0:
            betas.append(float(w["l"].cov(w["c"]) / v))
    beta_stability = float(np.std(betas)) if len(betas) >= 5 else None

    # 스프레드(로그가격비) — z_score·half_life는 타이밍 지표: 구조점수 합산 금지
    spread = np.log(df["l"]) - np.log(df["c"])
    tail = spread.tail(ZSCORE_WINDOW)
    z = float((spread.iloc[-1] - tail.mean()) / tail.std()) if tail.std() > 0 else None

    ds = spread.diff().dropna()
    lag = spread.shift(1).dropna().loc[ds.index]
    var_lag = float(lag.var())
    half_life = None
    if var_lag > 0:
        b = float(lag.cov(ds) / var_lag)
        if b < 0:
            half_life = float(-math.log(2) / b)

    return {"corr": corr, "pair_beta": pair_beta, "beta_stability": beta_stability,
            "z_score": z, "half_life": half_life}


# ---------- 팩터 정규화 (0~100 고정 매핑 — 후보 수 1개여도 안정) ----------
def _score_proximity(p) -> Optional[float]:
    return None if p is None else float(p) * 100.0


def _score_correlation(c) -> Optional[float]:
    return None if c is None else max(0.0, min(1.0, float(c))) * 100.0


def _score_beta_stability(std) -> Optional[float]:
    # std 0 → 100, 0.2 → 50, 0.6 이상 → ~14 (연속 감쇠)
    return None if std is None else 100.0 / (1.0 + 5.0 * float(std))


def _score_liquidity(adv20_won) -> Optional[float]:
    if adv20_won is None:
        return None
    eok = adv20_won / 1e8
    for th, sc in ((100, 100.0), (50, 80.0), (20, 60.0), (10, 40.0)):
        if eok >= th:
            return sc
    return 20.0


def structure_score(factors: dict) -> tuple:
    """가용 팩터만으로 가중평균. None 팩터는 **분모 제외** (0점 처리 금지).
    반환: (score 0~100 or None, coverage_ratio)."""
    total_w = sum(FACTOR_WEIGHTS.values())
    used_w, acc = 0.0, 0.0
    for k, w in FACTOR_WEIGHTS.items():
        v = factors.get(k)
        if v is not None:
            used_w += w
            acc += w * v
    coverage = used_w / total_w if total_w else 0.0
    score = (acc / used_w) if used_w > 0 else None
    return score, coverage


def grade_of(score, coverage) -> str:
    """A/B/C/D + coverage 미달 시 '*' (부분 커버리지 경고 — MVP는 EPS stub이라 항상 *)."""
    if score is None:
        return "N/A"
    g = "A" if score >= 75 else "B" if score >= 60 else "C" if score >= 45 else "D"
    return g + ("*" if coverage < COVERAGE_STAR_THRESHOLD else "")


# ---------- 메인 ----------
def find_short_candidates(long_ticker: str, top_n: int = 10) -> pd.DataFrame:
    """Long 티커 → Short 후보 DataFrame (구조점수 내림차순).

    컬럼: ticker, name, relation, proximity, corr_120d, pair_beta, beta_stability,
          adv20_eok, mktcap_eok, structure_score, coverage_ratio, grade,
          [타이밍·표시용] z_score, half_life_d, inst_net_20d_eok, forgn_net_20d_eok,
          [stub] eps_gap, fwd_per, fwd_pbr, borrowable, short_risk, dart_event
    """
    long_ticker = str(long_ticker).zfill(6)
    name_to_ticker, ticker_to_name = _load_name_maps()

    long_name = ticker_to_name.get(long_ticker)
    if long_name is None:
        try:
            from pykrx import stock
            long_name = stock.get_market_ticker_name(long_ticker)
        except Exception:
            long_name = None
    if not long_name:
        return pd.DataFrame()

    nodes, edges = load_value_chain()
    rel = relation_candidates(str(long_name).strip(), nodes, edges)
    if rel.empty:
        return pd.DataFrame()

    # 이름→티커 매핑 (CO 우선, pykrx fallback은 필요할 때 1회만 빌드)
    pykrx_map = None
    rows = []
    for _, r in rel.iterrows():
        key = r["name"].replace(" ", "")
        t = name_to_ticker.get(key)
        if t is None:
            if pykrx_map is None:
                try:
                    pykrx_map = _pykrx_name_map()
                except Exception:
                    pykrx_map = {}
            t = pykrx_map.get(key)
        if t and t != long_ticker:
            rows.append({"ticker": t, "name": r["name"], "relation": r["relation"], "proximity": r["proximity"]})
    if not rows:
        return pd.DataFrame()

    cand = pd.DataFrame(rows).drop_duplicates("ticker")
    cand = cand.sort_values("proximity", ascending=False).head(ENRICH_TOP_N)

    long_px = fetch_price(long_ticker)
    if long_px is None:
        return pd.DataFrame()
    long_close = long_px["종가"]

    out = []
    for _, r in cand.iterrows():
        t = r["ticker"]
        px = fetch_price(t)
        if px is None:
            continue
        st_ = pair_stats(long_close, px["종가"])
        adv20 = adv20_from_px(px)
        mktcap = fetch_mktcap(t)
        flows = fetch_flows_20d(t)
        val = stub_fwd_valuation(t)

        factors = {
            "proximity": _score_proximity(r["proximity"]),
            "correlation": _score_correlation(st_["corr"]),
            "beta_stability": _score_beta_stability(st_["beta_stability"]),
            "liquidity": _score_liquidity(adv20),
            "eps_gap": stub_eps_revision_gap(long_ticker, t),  # None → 분모 제외
        }
        score, coverage = structure_score(factors)

        out.append({
            "ticker": t, "name": r["name"], "relation": r["relation"], "proximity": r["proximity"],
            "corr_120d": st_["corr"], "pair_beta": st_["pair_beta"], "beta_stability": st_["beta_stability"],
            "adv20_eok": (adv20 / 1e8) if adv20 is not None else None,
            "mktcap_eok": (mktcap / 1e8) if mktcap is not None else None,
            "structure_score": score, "coverage_ratio": coverage, "grade": grade_of(score, coverage),
            # ---- 타이밍/수급 (구조점수 미반영 — 표시 전용) ----
            "z_score": st_["z_score"], "half_life_d": st_["half_life"],
            "inst_net_20d_eok": (flows["inst_net_20d"] / 1e8) if flows["inst_net_20d"] is not None else None,
            "forgn_net_20d_eok": (flows["forgn_net_20d"] / 1e8) if flows["forgn_net_20d"] is not None else None,
            # ---- stub (미연동 — None) ----
            "eps_gap": None, "fwd_per": val["fwd_per"], "fwd_pbr": val["fwd_pbr"],
            "borrowable": stub_borrow_available(t), "short_risk": stub_short_lending_risk(t),
            "dart_event": stub_dart_events(t),
        })

    if not out:
        return pd.DataFrame()
    df = pd.DataFrame(out).sort_values("structure_score", ascending=False, na_position="last")
    return df.head(top_n).reset_index(drop=True)
