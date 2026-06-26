"""롱숏 알파 스코어 (1단계: EPS Revision + 상대강도 + 이벤트).

문서 프레임워크 기반 멀티팩터 L-S 점수:
  - EPS Revision (30%): 영업이익 컨센서스 3개월 리비전(consensus) + 리포트 TP 방향(research)
  - 상대강도   (15%): RS = 종목 20일 수익률 - 업종(섹터) 20일 평균 (5/60일 확인)
  - 이벤트     (10%): 코스닥150 편입/편출 예측(rebal) + ETF 매수압력/신규 편입(etf_flow)
  (대체데이터 25% · 퀄리티 20%는 소스 확보 후 — 현재 가용 알파끼리 비중 재정규화)

종합 점수(-100~+100) → 롱(고점수)/숏(저점수) 후보 + 섹터 내 페어.
출력: data/alpha.json
사용: python3 scripts/update_alpha.py [--limit N]
"""

import argparse
import json
import socket
import sys
import time
import warnings

socket.setdefaulttimeout(20)  # fdr/네트워크 행 방지 — 응답 없으면 20초 후 실패(해당 종목 스킵)
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd
import FinanceDataReader as fdr

warnings.filterwarnings("ignore")

KST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).parent.parent
DATA = PROJECT_ROOT / "data"
OUTPUT_PATH = DATA / "alpha.json"
CRITERIA_PATH = PROJECT_ROOT / "sector_criteria.json"

# 가용 알파 비중 (문서: EPS30/대체25/퀄리티20/RS15/이벤트10) — EPS·RS·이벤트·퀄리티 활성 → 재정규화
WEIGHTS = {"eps": 30, "rs": 15, "event": 10, "quality": 20}
PENDING = {"대체데이터": 25}
DEFAULT_AUTOCORR = 0.5   # 섹터 리비전 자기상관 기본값(미산출 → 잠정 주입)

# EPS Revision 3레이어 모듈(섹터상대) — 가용 시 EPS 팩터로 사용, 실패/미가용 시 레거시 폴백
try:
    sys.path.insert(0, str(PROJECT_ROOT))
    from eps_revision.score import extract_components
    from eps_revision.confidence import confidence_gate as _eps_conf
    from eps_revision.aggregate import aggregate_batch as _eps_aggregate
    from eps_revision.guards import yoy_consistency as _eps_yoy, unit_consistency as _eps_unit
    from eps_revision.insight import generate_insight as _eps_insight
    EPS_REV_OK = True
except Exception:
    EPS_REV_OK = False


def build_eps_input(s, price, news_sent, fy_tag, q_elapsed):
    """consensus.json 종목 + 가격/뉴스 → EpsRevisionInput. 무료 데이터로 채울 수 있는 것만,
    나머지는 None(모듈이 재정규화). rev_3m/eps_chg/tp_chg(%)로 과거 추정치 역산."""
    rev3 = s.get("rev_3m")
    op_now, eps_now, tp_now = s.get("op_est"), s.get("eps"), s.get("tp")
    eps_chg, tp_chg = s.get("eps_chg"), s.get("tp_chg")
    bt = s.get("broker_tp") or {}
    op_m3 = op_now / (1 + rev3 / 100.0) if (op_now is not None and rev3 is not None and rev3 != -100) else None
    eps_m1 = eps_now / (1 + eps_chg / 100.0) if (eps_now is not None and eps_chg is not None and eps_chg != -100) else None
    tp_3m = None
    if tp_now is not None and tp_chg is not None and tp_chg != -100:
        tp_3m = tp_now / (1 + tp_chg / 100.0)
    elif tp_now is not None and bt.get("avg_chg") is not None and bt["avg_chg"] != -100:
        tp_3m = tp_now / (1 + bt["avg_chg"] / 100.0)
    return {
        "consensus": {
            "op_fy1": {"now": op_now, "m1": None, "m3": op_m3},
            "op_fy2": {"now": None, "m1": None, "m3": None},
            "eps_fy1": {"now": eps_now, "m1": eps_m1, "m3": None},
            "eps_fy2": {"now": None, "m1": None, "m3": None},
        },
        "diffusion": {"up_count": bt.get("up"), "down_count": bt.get("down"), "total": bt.get("n")},
        "surprise": [],
        "dispersion": {"std": None, "mean": None, "analyst_n": s.get("n_est"), "avg_estimate_age_days": None},
        "target_price": {"tp_now": tp_now, "tp_3m_ago": tp_3m, "price": price},
        "actuals_ytd": {"ytd_cumulative_op": None, "fy_consensus_op": op_now, "quarters_elapsed": q_elapsed},
        "news_sentiment": news_sent,
        "fiscal": {"current_fy_tag": fy_tag, "fy_roll_flag": False},
        "sector": s.get("sector", "기타"),
    }


def _load(name):
    p = DATA / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_criteria():
    """섹터별 기준(팩터 비중·판정 컷). 없으면 공통 기본값만."""
    default = {"weights": dict(WEIGHTS), "long_cut": 20, "short_cut": -20}
    try:
        c = json.loads(CRITERIA_PATH.read_text(encoding="utf-8"))
        if "_default" in c:
            default = {**default, **c["_default"]}
        return c, default
    except Exception:
        return {"_default": default}, default


def zscore_clip(series, lo=-2.0, hi=2.0):
    s = pd.to_numeric(series, errors="coerce")
    mu, sd = s.mean(), s.std()
    if not sd or sd != sd:
        return pd.Series(0.0, index=s.index)
    return ((s - mu) / sd).clip(lo, hi).fillna(0.0)


def fetch_prices(codes, verbose=False):
    """종목별 가격: 5/20/60일 수익률 + 60일 종가/거래대금 스파크 + 베타/변동성(퀄리티) + 일별수익률(상관용).
    반환: (info dict, 일별수익률 DataFrame[date×code])."""
    start = (datetime.now(KST) - timedelta(days=120)).strftime("%Y-%m-%d")
    # 시장(KOSPI) 일별수익률 — 베타 산출용
    try:
        mkt = fdr.DataReader("KS11", start)["Close"].dropna()
        mret = mkt.pct_change().dropna()
        mvar = float(mret.tail(60).var())
    except Exception:
        mret, mvar = None, 0.0
    info, close_series = {}, {}
    for i, code in enumerate(codes):
        try:
            df = fdr.DataReader(code, start)
            c = df["Close"].dropna()
            if len(c) < 21:
                continue
            def ret(n):
                return (c.iloc[-1] / c.iloc[-n - 1] - 1) * 100 if len(c) > n else np.nan
            # ── OHLC + 거래대금 (실제 증권 차트용, 최근 60거래일) ──
            cols = [x for x in ("Open", "High", "Low", "Close", "Volume") if x in df.columns]
            od = df[cols].reindex(c.index).tail(60).dropna(subset=["Close"])
            has_v = "Volume" in od.columns
            ohlc = {
                "d": [d.strftime("%y/%m/%d") for d in od.index],
                "o": [round(float(x), 1) for x in od.get("Open", od["Close"])],
                "h": [round(float(x), 1) for x in od.get("High", od["Close"])],
                "l": [round(float(x), 1) for x in od.get("Low", od["Close"])],
                "c": [round(float(x), 1) for x in od["Close"]],
                "amt": ([round(float(od["Close"].iloc[j] * od["Volume"].iloc[j]) / 1e8, 1) for j in range(len(od))]
                        if has_v else []),
            }
            # 베타·변동성 (최근 60거래일)
            sret = c.pct_change().dropna()
            vol = round(float(sret.tail(60).std() * np.sqrt(252) * 100), 1) if len(sret) >= 20 else None
            beta = None
            if mret is not None and mvar > 0 and len(sret) >= 20:
                al = pd.concat([sret, mret], axis=1, join="inner").dropna().tail(60)
                if len(al) >= 20:
                    beta = round(float(al.iloc[:, 0].cov(al.iloc[:, 1]) / mvar), 2)
            info[code] = {"ret_5": ret(5), "ret_20": ret(20), "ret_60": ret(60),
                          "ohlc": ohlc, "beta": beta, "vol": vol, "price": float(c.iloc[-1])}
            close_series[code] = c
        except Exception:
            pass
        if verbose and (i + 1) % 50 == 0:
            print(f"  가격 {i+1}/{len(codes)} (성공 {len(info)})")
        time.sleep(0.1)
    corr = pd.DataFrame()
    if len(close_series) >= 2:
        px = pd.DataFrame(close_series)
        corr = px.pct_change().dropna(how="all").tail(45).corr()
    return info, corr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    now = datetime.now(KST)
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] 롱숏 알파 스코어 산출")

    consensus = _load("consensus.json")
    research = _load("research_reports.json")
    rebal = _load("rebal.json")
    etf_flow = _load("etf_flow.json")
    investor = _load("investor_flow.json").get("flows", {})
    news = _load("news_sentiment.json").get("flows", {})
    criteria, crit_default = load_criteria()

    def sec_crit(sector):
        return criteria.get(sector, crit_default)

    stocks = consensus.get("stocks") or []
    if args.limit:
        stocks = stocks[:args.limit]
    stock_by_code = {s["code"]: s for s in stocks}
    if len(stocks) < 20:
        print("  [경고] 유니버스 부족(consensus.json 필요) — 중단(exit 2)")
        sys.exit(2)
    df = pd.DataFrame([{"code": s["code"], "name": s["name"], "sector": s.get("sector", "기타"),
                        "marcap": s.get("marcap", 0), "rev_3m": s.get("rev_3m"),
                        "yoy": s.get("yoy"), "op_est": s.get("op_est"),
                        "tp": s.get("tp"), "eps_est": s.get("eps"), "opinion": s.get("opinion"),
                        "n_est": s.get("n_est"), "tp_chg": s.get("tp_chg"),
                        "eps_chg": s.get("eps_chg"), "opinion_chg": s.get("opinion_chg"),
                        "broker_chg": (s.get("broker_tp") or {}).get("avg_chg"),
                        "broker_net": ((s.get("broker_tp") or {}).get("up", 0) - (s.get("broker_tp") or {}).get("down", 0))}
                       for s in stocks])
    df = df.drop_duplicates(subset="code", keep="first").reset_index(drop=True)  # 중복 코드 방지
    print(f"  유니버스: {len(df)}종목")

    # ── 이벤트/리포트/수급 맵 ──
    tp_dir = {}
    for r in research.get("reports", []):
        if r.get("code") and r.get("direction") in ("up", "down"):
            tp_dir[r["code"]] = r["direction"]
    add_codes = {x["code"] for x in (rebal.get("kosdaq150") or {}).get("additions", [])}
    rem_codes = {x["code"] for x in (rebal.get("kosdaq150") or {}).get("removals", [])}
    pressure = {p["code"]: p["pressure_eok"] for p in etf_flow.get("pressure", [])}
    active_new = set()
    for a in etf_flow.get("active_changes", []):
        for x in a.get("new_in", []):
            pass  # new_in has name only; skip code-level for now

    # ── 상대강도: 가격 수익률 + 상관(페어용) ──
    pinfo, corr = fetch_prices(df["code"].tolist(), verbose=True)
    df["ret_5"] = df["code"].map(lambda c: pinfo.get(c, {}).get("ret_5"))
    df["ret_20"] = df["code"].map(lambda c: pinfo.get(c, {}).get("ret_20"))
    df["ret_60"] = df["code"].map(lambda c: pinfo.get(c, {}).get("ret_60"))
    sector_ret20 = df.groupby("sector")["ret_20"].transform("mean")
    df["rs_20"] = df["ret_20"] - sector_ret20  # 업종 대비 상대강도
    print(f"  가격 수집: {len(pinfo)}/{len(df)} · 상관행렬 {corr.shape[0]}종목")

    # ── 서브스코어 (-100~+100) ──
    # EPS Revision = FnGuide 실제 컨센서스: 영업이익 3M 리비전 + 목표주가 변화·상승여력 + EPS 컨센 변화
    #                + 투자의견(레벨·상하향) + 한경 리포트 방향 + 뉴스 심리(KR-FinBERT, 보조 확인)
    df["price"] = df["code"].map(lambda c: pinfo.get(c, {}).get("price"))
    df["tp_upside"] = (pd.to_numeric(df["tp"], errors="coerce") / df["price"] - 1) * 100  # 목표주가 상승여력
    df["news_sent"] = df["code"].map(lambda c: news.get(c, {}).get("sentiment"))
    df["score_eps"] = (zscore_clip(df["rev_3m"]) * 30).round(1)                       # 영업이익 3M 리비전(주)
    df["score_eps"] += (zscore_clip(df["broker_chg"]) * 16).round(1)                  # 증권사 목표주가 변동률(TP 리비전, 즉시)
    df["score_eps"] += (pd.to_numeric(df["broker_net"], errors="coerce").fillna(0) * 2.5).clip(-12, 12).round(1)  # TP 상향-하향 브로커 수
    df["score_eps"] += (zscore_clip(df["tp_chg"]) * 8).round(1)                       # 목표주가 변화(자체 히스토리, 누적)
    df["score_eps"] += (zscore_clip(df["tp_upside"]) * 13).round(1)                   # 목표주가 상승여력
    df["score_eps"] += (zscore_clip(df["eps_chg"]) * 12).round(1)                     # EPS 컨센 변화
    df["score_eps"] += (zscore_clip(df["opinion"]) * 6).round(1)                      # 투자의견 레벨
    df["score_eps"] += (pd.to_numeric(df["opinion_chg"], errors="coerce").fillna(0) * 10).clip(-10, 10).round(1)  # 의견 상/하향
    df["score_eps"] += df["code"].map(lambda c: 8 if tp_dir.get(c) == "up" else (-8 if tp_dir.get(c) == "down" else 0))  # 한경 방향
    df["score_eps"] += (df["news_sent"].fillna(0) * 10).round(1)                      # 뉴스 심리(보조)
    df["score_eps"] = df["score_eps"].clip(-100, 100)

    # ── EPS Revision 3레이어 모듈(섹터상대 -100~100) → EPS 팩터 교체(가용 시), 미가용 시 레거시 ──
    eps_rev_detail = {}
    if EPS_REV_OK:
        try:
            yr, q = str(now.year), (now.month - 1) // 3 + 1
            comp_rows, conf_map, sec_map, inputs = {}, {}, {}, {}
            for code in df["code"]:
                s = stock_by_code.get(code, {})
                inp = build_eps_input(s, pinfo.get(code, {}).get("price"),
                                      (news.get(code, {}) or {}).get("sentiment"), yr, q)
                inputs[code] = inp
                comp_rows[code] = extract_components(inp, sector_revision_autocorr=DEFAULT_AUTOCORR)
                conf_map[code] = _eps_conf(inp)
                sec_map[code] = inp["sector"]
            comp_df = pd.DataFrame.from_dict(comp_rows, orient="index")
            res = _eps_aggregate(comp_df, confidence=conf_map, sector=sec_map)
            for code in df["code"]:
                if code not in res.index:
                    continue
                row = res.loc[code]
                sc = row.get("score")
                layers = {k: (None if pd.isna(row.get(k)) else round(float(row[k]), 2))
                          for k in ("realized", "momentum", "forward")}
                conf = float(conf_map.get(code, 1.0))
                s = stock_by_code.get(code, {})
                prev = ((s.get("fin") or {}).get("op") or [None])[-1]
                ry = s.get("yoy") / 100.0 if isinstance(s.get("yoy"), (int, float)) else None
                flags = _eps_yoy(s.get("op_est"), prev, ry) + _eps_unit(inputs[code])
                ins = _eps_insight(0.0 if pd.isna(sc) else float(sc), layers, conf, comp_rows[code], flags)
                eps_rev_detail[code] = {"score": None if pd.isna(sc) else round(float(sc), 1),
                                        "layers": layers, "confidence": round(conf, 3),
                                        "insight": ins, "flags": flags}
            df["eps_rev_score"] = df["code"].map(lambda c: eps_rev_detail.get(c, {}).get("score"))
            # EPS 팩터: 모듈 점수 가용 시 모듈로 교체, 아니면 레거시 score_eps 유지
            df["score_eps"] = [er if (er is not None) else leg
                               for er, leg in zip(df["eps_rev_score"], df["score_eps"])]
            print(f"  EPS Revision 모듈 적용: {sum(1 for v in eps_rev_detail.values() if v['score'] is not None)}종목")
        except Exception as e:
            print(f"  [경고] EPS Revision 모듈 실패 — 레거시 score_eps 사용: {str(e)[:100]}")

    # 외국인+기관 20일 누적 순매수(억) — 수급 유입/유출
    df["net_flow_20"] = df["code"].map(
        lambda c: (investor.get(c, {}).get("frgn_20") or 0) + (investor.get(c, {}).get("inst_20") or 0))
    df["score_rs"] = (zscore_clip(df["rs_20"]) * 38).round(1)
    df["score_rs"] += (zscore_clip(df["ret_60"]) * 10).round(1)   # 중기 확인
    df["score_rs"] += (zscore_clip(df["net_flow_20"]) * 12).round(1)  # 외국인/기관 수급
    df["score_rs"] = df["score_rs"].clip(-100, 100)

    ev = pd.Series(0.0, index=df.index)
    ev += df["code"].map(lambda c: 60 if c in add_codes else (-60 if c in rem_codes else 0))
    ev += (zscore_clip(df["code"].map(lambda c: pressure.get(c, 0))) * 25)
    df["score_event"] = ev.clip(-100, 100).round(1)

    # ── 퀄리티/저베타: 고마진(이익수익률) + 저베타 + 저변동 (키 불필요, 가격·컨센서스) ──
    df["beta"] = df["code"].map(lambda c: pinfo.get(c, {}).get("beta"))
    df["vol"] = df["code"].map(lambda c: pinfo.get(c, {}).get("vol"))
    marcap_eok = pd.to_numeric(df["marcap"], errors="coerce") / 1e8
    df["margin"] = pd.to_numeric(df["op_est"], errors="coerce") / marcap_eok.replace(0, np.nan)  # 영업이익/시총(이익수익률)
    df["score_quality"] = (zscore_clip(df["margin"]) * 35).round(1)          # 고마진/저멀티플
    df["score_quality"] += (zscore_clip(-pd.to_numeric(df["beta"], errors="coerce")) * 30).round(1)  # 저베타
    df["score_quality"] += (zscore_clip(-pd.to_numeric(df["vol"], errors="coerce")) * 25).round(1)   # 저변동
    df["score_quality"] = df["score_quality"].clip(-100, 100)

    # ── 종합 (섹터별 팩터 비중, 가용 팩터끼리 재정규화) ──
    # EPS는 컨센서스/리포트 커버 종목만, 퀄리티는 베타 산출(가격) 종목만 유효 → 가용 팩터끼리 재정규화.
    df["has_eps"] = (df["rev_3m"].notna() | df["tp"].notna() | df["code"].map(lambda c: c in tp_dir)
                     | (df["news_sent"].abs() >= 0.15))
    df["has_quality"] = df["beta"].notna() | df["margin"].notna()

    def composite(r):
        w = sec_crit(r["sector"])["weights"]
        parts = [(r["score_rs"], w.get("rs", 0)), (r["score_event"], w.get("event", 0))]
        if r["has_eps"]:
            parts.append((r["score_eps"], w.get("eps", 0)))
        if r["has_quality"]:
            parts.append((r["score_quality"], w.get("quality", 0)))
        tot = sum(wt for _, wt in parts) or 1
        return round(sum(s * wt for s, wt in parts) / tot, 1)

    df["score"] = df.apply(composite, axis=1)
    # 커버리지: 활성 팩터(EPS+RS+이벤트) / 전체 프레임(+대체데이터+퀄리티)
    coverage = round(sum(WEIGHTS.values()) / (sum(WEIGHTS.values()) + sum(PENDING.values())) * 100)

    # 섹터별 판정 컷
    df["long_cut"] = df["sector"].map(lambda s: sec_crit(s)["long_cut"])
    df["short_cut"] = df["sector"].map(lambda s: sec_crit(s)["short_cut"])

    df = df.sort_values("score", ascending=False).reset_index(drop=True)

    # ── 펀더멘탈 프로파일 (비즈니스 모델·규모 유사도용) ──
    # 규모(log 시총) · 수익성(영업이익/시총, 위에서 margin 산출) · 성장성(전년대비) 3축을 z정규화 → 거리로 유사도.
    df["logcap"] = np.log(pd.to_numeric(df["marcap"], errors="coerce").clip(lower=1.0))
    zf = pd.DataFrame({"logcap": zscore_clip(df["logcap"], -3, 3),
                       "margin": zscore_clip(df["margin"], -3, 3),
                       "yoy": zscore_clip(df["yoy"], -3, 3)}, index=df.index)
    feat = {df.at[i, "code"]: zf.loc[i].to_numpy(dtype=float) for i in df.index}

    def fund_sim(a, b):
        """펀더멘탈 프로파일 유사도 0~1 (1=동일 규모·수익성·성장 프로파일)."""
        va, vb = feat.get(a), feat.get(b)
        if va is None or vb is None:
            return 0.5
        d = float(np.linalg.norm(va - vb))
        return round(1.0 / (1.0 + d), 2)

    name_map = dict(zip(df["code"], df["name"]))
    score_map = dict(zip(df["code"], df["score"]))
    sector_map = dict(zip(df["code"], df["sector"]))
    cap_map = dict(zip(df["code"], pd.to_numeric(df["marcap"], errors="coerce").fillna(0)))
    has_corr = corr.shape[0] >= 2

    def fund_note(a, b):
        """페어 펀더멘탈 한줄 근거 (규모 비교)."""
        ca, cb = cap_map.get(a, 0), cap_map.get(b, 0)
        if ca and cb:
            r = ca / cb
            if r >= 2:
                return "롱이 2배+ 대형주"
            if r <= 0.5:
                return "숏이 2배+ 대형주"
            return "유사 규모"
        return ""

    def best_counterpart(code):
        """동일 섹터(비즈니스 모델) 내에서 상관·펀더멘탈 유사도·점수 스프레드 종합 최적 반대편.
        품질 = 스프레드 × 상관 × (0.5 + 0.5×펀더멘탈유사도). 동일섹터 우선, 없으면 교차섹터 폴백."""
        if not has_corr or code not in corr.columns:
            return None
        s = score_map.get(code, 0)
        my_sec = sector_map.get(code)
        best, bq, best_cross, bqc = None, 0, None, 0
        for other in corr.columns:
            if other == code or other not in score_map:
                continue
            cv = corr.at[code, other]
            if cv != cv or cv < 0.3:   # 헤지 가능한 상관만
                continue
            o = score_map[other]
            spread = s - o
            if (s >= 0 and spread <= 5) or (s < 0 and spread >= -5):  # 반대 극단만
                continue
            fs = fund_sim(code, other)
            q = cv * abs(spread) * (0.5 + 0.5 * fs)
            cand = {"code": other, "name": name_map[other], "score": float(o),
                    "corr": round(float(cv), 2), "spread": round(abs(spread), 0),
                    "fund_sim": fs, "fund_note": fund_note(code, other) if s >= 0 else fund_note(other, code),
                    "same_sector": sector_map.get(other) == my_sec}
            if cand["same_sector"]:
                if q > bq:
                    bq, best = q, cand
            elif q > bqc:
                bqc, best_cross = q, cand
        return best or best_cross  # 동일섹터 우선

    pair_map = {c: best_counterpart(c) for c in df["code"]}

    # ── 섹터별 매수 강도 랭킹 (평균 종합점수 = 강도, 섹터 판정 컷 적용) ──
    sector_rows = []
    for sec, grp in df.groupby("sector"):
        g = grp.sort_values("score", ascending=False)
        cr = sec_crit(sec)
        lc, scut = cr["long_cut"], cr["short_cut"]
        tl, ts = g.iloc[0], g.iloc[-1]
        sector_rows.append({
            "sector": sec, "n": int(len(g)),
            "avg_score": round(float(g["score"].mean()), 1),
            "avg_eps": round(float(g["score_eps"].mean()), 1),
            "avg_rs": round(float(g["score_rs"].mean()), 1),
            "avg_event": round(float(g["score_event"].mean()), 1),
            "avg_quality": round(float(g["score_quality"].mean()), 1),
            "long_n": int((g["score"] >= lc).sum()),
            "short_n": int((g["score"] <= scut).sum()),
            "long_cut": lc, "short_cut": scut,
            "weights": cr["weights"], "note": cr.get("note", ""),
            "drivers": cr.get("drivers", ""), "valuation": cr.get("valuation", ""),
            "net_flow": round(float(pd.to_numeric(g["net_flow_20"], errors="coerce").fillna(0).sum()), 0),
            "top_long": {"code": tl["code"], "name": tl["name"], "score": float(tl["score"])},
            "top_short": {"code": ts["code"], "name": ts["name"], "score": float(ts["score"])},
        })
    sector_rows.sort(key=lambda x: x["avg_score"], reverse=True)

    def rec(r):
        code = r["code"]
        cr = sec_crit(r["sector"])
        return {"code": code, "name": r["name"], "sector": r["sector"],
                "marcap": float(r["marcap"]) if r["marcap"] == r["marcap"] else 0,
                "score": float(r["score"]),
                "eps": float(r["score_eps"]), "rs": float(r["score_rs"]), "event": float(r["score_event"]),
                "eps_rev": eps_rev_detail.get(code),
                "quality": float(r["score_quality"]), "has_eps": bool(r["has_eps"]), "has_quality": bool(r["has_quality"]),
                "beta": None if pd.isna(r.get("beta")) else round(float(r["beta"]), 2),
                "vol": None if pd.isna(r.get("vol")) else round(float(r["vol"]), 1),
                "margin": None if pd.isna(r.get("margin")) else round(float(r["margin"]) * 100, 2),
                "long_cut": cr["long_cut"], "short_cut": cr["short_cut"], "weights": cr["weights"],
                "rev_3m": None if pd.isna(r["rev_3m"]) else float(r["rev_3m"]),
                "tp": None if pd.isna(r.get("tp")) else float(r["tp"]),
                "eps_est": None if pd.isna(r.get("eps_est")) else float(r["eps_est"]),
                "opinion": None if pd.isna(r.get("opinion")) else round(float(r["opinion"]), 2),
                "n_est": None if pd.isna(r.get("n_est")) else int(r["n_est"]),
                "tp_chg": None if pd.isna(r.get("tp_chg")) else round(float(r["tp_chg"]), 1),
                "eps_chg": None if pd.isna(r.get("eps_chg")) else round(float(r["eps_chg"]), 1),
                "opinion_chg": None if pd.isna(r.get("opinion_chg")) else round(float(r["opinion_chg"]), 2),
                "tp_upside": None if pd.isna(r.get("tp_upside")) else round(float(r["tp_upside"]), 1),
                "news_sent": news.get(code, {}).get("sentiment"),
                "news_recent": news.get(code, {}).get("recent", []),
                "yoy": None if pd.isna(r.get("yoy")) else round(float(r["yoy"]), 1),
                "ret_5": None if pd.isna(r["ret_5"]) else round(float(r["ret_5"]), 1),
                "ret_20": None if pd.isna(r["ret_20"]) else round(float(r["ret_20"]), 1),
                "ret_60": None if pd.isna(r["ret_60"]) else round(float(r["ret_60"]), 1),
                "rs_20": None if pd.isna(r["rs_20"]) else round(float(r["rs_20"]), 1),
                "pressure_eok": pressure.get(code),
                "frgn_5": investor.get(code, {}).get("frgn_5"),
                "frgn_20": investor.get(code, {}).get("frgn_20"),
                "inst_5": investor.get(code, {}).get("inst_5"),
                "inst_20": investor.get(code, {}).get("inst_20"),
                "frgn_hold": investor.get(code, {}).get("frgn_hold"),
                "tp_dir": tp_dir.get(code),
                "index_event": ("add" if code in add_codes else ("remove" if code in rem_codes else None)),
                "ohlc": pinfo.get(code, {}).get("ohlc", {}),
                "pair": pair_map.get(code)}

    ranked = [rec(r) for _, r in df.iterrows()]
    longs = ranked[:25]
    shorts = ranked[::-1][:25]

    # ── 정밀 페어 (동일섹터·펀더멘탈 유사 우선, 상관 헤지 × 점수 스프레드, 종목 중복 제거) ──
    pairs, used = [], set()
    for r in ranked:                          # 점수 높은 순(롱 후보)부터
        if r["score"] < 10 or r["code"] in used:
            continue
        cp = r.get("pair")
        if not cp or cp["code"] in used or cp["score"] > -5 or cp["corr"] < 0.4:
            continue
        used.add(r["code"]); used.add(cp["code"])
        pairs.append({"long": {"code": r["code"], "name": r["name"], "score": r["score"]},
                      "short": {"code": cp["code"], "name": cp["name"], "score": cp["score"]},
                      "corr": cp["corr"], "spread": cp["spread"],
                      "fund_sim": cp.get("fund_sim"), "fund_note": cp.get("fund_note", ""),
                      "same_sector": cp["same_sector"], "sector": r["sector"],
                      "quality": round(cp["corr"] * cp["spread"] * (0.5 + 0.5 * (cp.get("fund_sim") or 0.5)), 0)})
    pairs.sort(key=lambda x: x["quality"], reverse=True)

    out = {
        "updated": now.strftime("%Y-%m-%d %H:%M"), "date": now.strftime("%Y-%m-%d"),
        "universe": len(df), "coverage_pct": coverage,
        "weights": WEIGHTS, "pending": PENDING,
        "criteria": criteria,
        "sectors": sector_rows,
        "longs": longs, "shorts": shorts, "pairs": pairs[:20],
        "ranked": ranked,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  저장: {OUTPUT_PATH} (롱{len(longs)}/숏{len(shorts)}/페어{len(pairs)}, 커버리지 {coverage}%)")


if __name__ == "__main__":
    main()
