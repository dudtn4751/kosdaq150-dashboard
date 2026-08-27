"""수출입 대시보드 (Flask + Chart.js) — M1: 골격 + JSON API + 품목 상세 1페이지.

Streamlit 앱과 **같은 데이터**(data/trade_dashboard/*.csv)와 **같은 계산 모듈**
(trade_metrics)을 쓴다. 지표는 전부 서버에서 선계산해 배열로 내려주고(레퍼런스 계약),
클라이언트는 Chart.js로 그리기만 한다 — 뷰 토글 시 서버 왕복이 없다.

실행: python3 apps/trade_web/app.py   (또는 scripts/run_trade_web.sh — waitress)
"""

import sys
import threading
from pathlib import Path

import pandas as pd
from flask import Flask, abort, jsonify, redirect, render_template, request

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

import trade_metrics as tm  # noqa: E402  (경로 설정 후 import)
import trade_utils_data as tud  # noqa: E402  (시그널·즐겨찾기 계산 재사용)

DATA_DIR = BASE_DIR / "data" / "trade_dashboard"
DECADE_CSV = DATA_DIR / "trade_history_decade_long.csv"
MONTH_CSV = DATA_DIR / "trade_history_long.csv"
MAPPING_CSV = DATA_DIR / "config" / "item_mapping.csv"
COMPANY_CSV = DATA_DIR / "company_trade_history_long.csv"

COLS = {"품목명": "item_name", "대분류": "category", "기준일": "date",
        "수출금액": "export_amount", "단가": "unit_price", "기업명": "company_name"}

app = Flask(__name__)


# ── Basic Auth (TRADE_WEB_USER/PASS 설정 시에만 활성 — 로컬 개발은 무인증) ──────
import hmac
import os as _os

from flask import Response


def _auth_required() -> bool:
    return bool(_os.environ.get("TRADE_WEB_USER") and _os.environ.get("TRADE_WEB_PASS"))


@app.before_request
def _check_auth():
    if not _auth_required():
        return None
    if request.path == "/healthz":          # 헬스체크는 인증 제외(Render 상태 확인)
        return None
    a = request.authorization
    ok = (a and hmac.compare_digest(a.username or "", _os.environ["TRADE_WEB_USER"])
          and hmac.compare_digest(a.password or "", _os.environ["TRADE_WEB_PASS"]))
    if not ok:
        return Response("인증이 필요합니다.", 401,
                        {"WWW-Authenticate": 'Basic realm="trade-web"'})
    return None


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "decade_csv": DECADE_CSV.exists(),
                    "month_csv": MONTH_CSV.exists(), "company_csv": COMPANY_CSV.exists()})


# ── 파일 mtime 기준 캐시 (CSV가 갱신되면 자동 무효화) ────────────────────────
_cache: dict = {}


def _load(path: Path) -> pd.DataFrame:
    key, mtime = str(path), path.stat().st_mtime
    hit = _cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    df = pd.read_csv(path).rename(columns=COLS)
    df["date"] = pd.to_datetime(df["date"])
    _cache[key] = (mtime, df)
    return df


def decade_df() -> pd.DataFrame:
    key = "decade_prepared"
    mtime = DECADE_CSV.stat().st_mtime
    hit = _cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    d = tm.prepare_decade(_load(DECADE_CSV))
    _cache[key] = (mtime, d)
    return d


def _f(v):
    """JSON 직렬화용 — NaN/NaT는 None."""
    if v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v):
        return None
    return float(v)


# ── API ───────────────────────────────────────────────────────────────────────
@app.get("/api/items")
def api_items():
    return jsonify(items_payload())


def _company_items() -> set:
    return set(_load(COMPANY_CSV)["item_name"].unique())


def items_payload() -> dict:
    """홈 카드 그리드용 — 순별(최신 누계·동순YoY) + 월간(최신월·YoY) + 스파크라인 배열."""
    key = "items_payload"
    mtime = (DECADE_CSV.stat().st_mtime, MONTH_CSV.stat().st_mtime, COMPANY_CSV.stat().st_mtime)
    hit = _cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]

    dec = decade_df()
    mon_csv = _load(MONTH_CSV).sort_values("date")
    comp_items = _company_items()

    # 순별: 최신 스냅샷 = 같은 (m, decade) 버킷의 전년과 비교(★동순)
    latest_date = dec["date"].max()
    cy, cm = int(latest_date.year), int(latest_date.month)
    cbkt = tm.decade_bucket(int(latest_date.day))
    cur = dec[(dec.y == cy) & (dec.m == cm) & (dec.decade == cbkt)].groupby("item_name").last()
    prv = dec[(dec.y == cy - 1) & (dec.m == cm) & (dec.decade == cbkt)].groupby("item_name")["export_amount"].last()

    items = []
    for name, g in mon_csv.groupby("item_name"):
        g = g.sort_values("date")
        last = g.iloc[-1]
        prev_y = g[g["date"] == last["date"] - pd.DateOffset(years=1)]
        m_yoy = None
        if not prev_y.empty and prev_y["export_amount"].iloc[0]:
            m_yoy = (last["export_amount"] / prev_y["export_amount"].iloc[0] - 1) * 100

        d_cum = d_yoy = None
        if name in cur.index:
            d_cum = float(cur.loc[name, "export_amount"])
            pv = prv.get(name)
            if pv:
                d_yoy = (d_cum / pv - 1) * 100

        items.append({
            "item": name,
            "category": str(last.get("category") or ""),
            "decade_label": f"{cm}/{int(latest_date.day)}",
            "decade_cum": _f(d_cum), "decade_yoy": _f(d_yoy),
            "month_period": last["date"].strftime("%Y-%m"),
            "month_amount": _f(last["export_amount"]), "month_yoy": _f(m_yoy),
            "spark": [_f(v) for v in g["export_amount"].tail(12)],          # 월간(완료월)
            "spark_decade": [_f(v) for v in
                             dec[dec.item_name == name].sort_values("date")["export_amount"].tail(12)],
            "has_company": name in comp_items,
        })
    items.sort(key=lambda r: (r["decade_yoy"] is None, -(r["decade_yoy"] or 0)))
    payload = {
        "count": len(items),
        "categories": sorted({i["category"] for i in items if i["category"]}),
        "decade_latest": latest_date.strftime("%Y-%m-%d"),
        "month_latest": mon_csv["date"].max().strftime("%Y-%m"),
        "company_item_count": len(comp_items),
        "company_latest": _load(COMPANY_CSV)["date"].max().strftime("%Y-%m"),
        "items": items,
    }
    _cache[key] = (mtime, payload)
    return payload


def companies_payload(name: str) -> list:
    """[월간 전용] 기업별 월 시계열 + 최신월·YoY·비중."""
    c = _load(COMPANY_CSV)
    c = c[c["item_name"] == name].sort_values("date")
    if c.empty:
        return []
    latest = c["date"].max()
    total_latest = c[c["date"] == latest]["export_amount"].sum()
    out = []
    for comp, g in c.groupby("company_name"):
        g = g.sort_values("date")
        last = g.iloc[-1]
        prev = g[g["date"] == last["date"] - pd.DateOffset(years=1)]
        yoy = None
        if not prev.empty and prev["export_amount"].iloc[0]:
            yoy = (last["export_amount"] / prev["export_amount"].iloc[0] - 1) * 100
        share = (last["export_amount"] / total_latest * 100) if total_latest else None
        out.append({
            "name": str(comp),
            "labels": [d.strftime("%Y-%m") for d in g["date"]],
            "values": [_f(v) for v in g["export_amount"]],
            "latest": _f(last["export_amount"]), "latest_period": last["date"].strftime("%Y-%m"),
            "yoy": _f(yoy), "share": _f(share),
        })
    out.sort(key=lambda r: -(r["latest"] or 0))
    return out


@app.get("/api/item/<path:name>")
def api_item(name: str):
    """한 품목의 전체 선계산 배열 — 클라이언트는 그리기만 한다."""
    dec = decade_df()
    if name not in set(dec["item_name"]):
        abort(404, description=f"품목 없음: {name}")

    mon = tm.decade_monthly(dec, name)          # 순별 층위(구간 증분·진행월 포함)
    snaps = tm.decade_same_bucket_yoy(dec, name)

    # ── 월간 층위는 trade_history_long.csv(완료월·확정치)가 정본 ─────────────
    # decade 파생은 진행월(부분 누계)이 섞여 월간 계열을 오염시키므로 분리한다.
    mdf = _load(MONTH_CSV)
    mdf = mdf[mdf["item_name"] == name].sort_values("date").copy()
    mdf["ym"] = mdf["date"].dt.to_period("M")
    inc_by_ym = {r.ym: (r.inc1, r.inc2, r.inc3) for r in mon.itertuples()}

    labels = [str(p_) for p_ in mdf["ym"]]
    total = [float(v) for v in mdf["export_amount"]]
    price_m = [_f(v) for v in mdf["unit_price"]]
    by_ym_total = dict(zip(mdf["ym"], mdf["export_amount"]))
    yoy, mom, d10, d20, dend, mismatch = [], [], [], [], [], []
    for i, r in enumerate(mdf.itertuples()):
        prev_y = by_ym_total.get(r.ym - 12)
        yoy.append(_f((r.export_amount / prev_y - 1) * 100) if prev_y else None)
        mom.append(_f((r.export_amount / total[i - 1] - 1) * 100) if i and total[i - 1] else None)
        a, b_, c_ = inc_by_ym.get(r.ym, (None, None, None))
        d10.append(_f(a)); d20.append(_f(b_)); dend.append(_f(c_))
        # 구간 증분 합과 월간 확정치가 다른 달 — 잔차를 하순에 얹지 않고 그대로 두고 표기만.
        parts = [x for x in (a, b_, c_) if x is not None and pd.notna(x)]
        gap = (r.export_amount - sum(parts)) if len(parts) == 3 else None
        mismatch.append(_f(gap) if (gap is not None and abs(gap) > 1) else None)

    # 분기(QoQ) — 월간 확정치 합산
    q = mdf.copy()
    q["qtr"] = q["ym"].dt.asfreq("Q")
    qs = q.groupby("qtr")["export_amount"].sum().reset_index()
    qs["qoq"] = qs["export_amount"].pct_change() * 100

    # 10일 단위(순별 누계 + 동순 YoY)
    dec_labels = [d.strftime("%Y-%m-%d") for d in snaps["date"]]

    # 영업일 일평균(월별 누적 / 10일 구간별)
    m_starts = [pd.Timestamp(p_.year, p_.month, 1) for p_ in mdf["ym"]]
    biz_month = [tm.bizdays(st_, st_ + pd.offsets.MonthEnd(0)) for st_ in m_starts]
    seg_x, seg_avg, seg_biz = [], [], []
    for r in mon.itertuples():
        for key, dcol, bcol in (("inc1", "d1", "biz1"), ("inc2", "d2", "biz2"), ("inc3", "d3", "biz3")):
            inc, dd, bz = getattr(r, key), getattr(r, dcol), getattr(r, bcol)
            if inc is not None and pd.notna(inc) and dd is not None and bz:
                seg_x.append(dd.strftime("%Y-%m-%d")); seg_avg.append(_f(inc / bz)); seg_biz.append(int(bz))

    # KPI (최신 스냅샷 기준 — Streamlit 상세와 동일 정의)
    cur = mon.iloc[-1]
    bkt_key = {"상순": ("inc1", "biz1"), "중순": ("inc2", "biz2"), "월말": ("inc3", "biz3")}[cur["last_bkt"]]
    seg_inc, seg_bd = cur[bkt_key[0]], cur[bkt_key[1]]
    day_avg = (seg_inc / seg_bd) if (pd.notna(seg_inc) and seg_bd) else None
    prev_mon = mon.iloc[-2] if len(mon) >= 2 else None
    davg_mom = None
    if day_avg is not None and prev_mon is not None:
        p_inc, p_bd = prev_mon[bkt_key[0]], prev_mon[bkt_key[1]]
        if pd.notna(p_inc) and p_bd:
            davg_mom = (day_avg / (p_inc / p_bd) - 1) * 100
    last_snap = snaps.iloc[-1]
    # 직전 스냅샷 대비 가속 Δ(%p) — 순별 층위 전용 지표
    accel = None
    if len(snaps) >= 2:
        a0, a1 = last_snap["same_bucket_yoy"], snaps.iloc[-2]["same_bucket_yoy"]
        if a0 is not None and a1 is not None:
            accel = a0 - a1
    mom_kpi = None
    if prev_mon is not None:
        ps = dec[(dec["item_name"] == name) & (dec["y"] == prev_mon["y"])
                 & (dec["m"] == prev_mon["m"]) & (dec["decade"] == cur["last_bkt"])]
        if not ps.empty:
            mom_kpi = (last_snap["export_amount"] / ps["export_amount"].iloc[-1] - 1) * 100

    # 원데이터 5개년
    raw = snaps[snaps["date"] > (snaps["date"].max() - pd.DateOffset(years=5))].sort_values(
        "date", ascending=False)

    return jsonify({
        "item": name,
        "category": str(dec[dec["item_name"] == name]["category"].iloc[-1]),
        "kpi": {
            "latest_date": last_snap["date"].strftime("%Y-%m-%d"),
            "latest_label": f"{int(last_snap['date'].month)}/{int(last_snap['date'].day)}",
            "latest_amount": _f(last_snap["export_amount"]),
            "day_avg": _f(day_avg), "day_avg_biz": int(seg_bd) if seg_bd else None,
            "day_avg_mom": _f(davg_mom),
            "mom": _f(mom_kpi), "yoy": _f(last_snap["same_bucket_yoy"]),
            "price": _f(last_snap["unit_price"]), "accel": _f(accel),
        },
        # 월간 층위 KPI — 정본은 월간 CSV(완료월). 순별 KPI와 섞지 않는다.
        "kpi_monthly": ({
            "period": labels[-1],
            "amount": _f(total[-1]),
            "day_avg": _f(total[-1] / biz_month[-1]) if biz_month and biz_month[-1] else None,
            "day_avg_biz": int(biz_month[-1]) if biz_month else None,
            "day_avg_mom": _f((total[-1] / biz_month[-1]) / (total[-2] / biz_month[-2]) * 100 - 100)
                           if len(total) >= 2 and biz_month[-1] and biz_month[-2] else None,
            "mom": mom[-1], "yoy": yoy[-1], "price": price_m[-1],
        } if labels else None),
        "monthly": {                      # 정본: trade_history_long.csv(완료월·확정치)
            "labels": labels,
            "d10": d10, "d20": d20, "dend": dend,   # 구간 분해는 순별에만 존재
            "total": [_f(v) for v in total],
            "price": price_m,
            "yoy": yoy, "mom": mom,
            "mismatch": mismatch,          # 증분 합 − 월간 확정치(있으면 잠정/확정 차이)
        },
        "quarterly": {
            "labels": [str(p_) for p_ in qs["qtr"]],
            "total": [_f(v) for v in qs["export_amount"]],
            "qoq": [_f(v) for v in qs["qoq"]],
        },
        "decade": {
            "labels": dec_labels,
            "cum": [_f(v) for v in snaps["export_amount"]],
            "same_bucket_yoy": [_f(v) for v in snaps["same_bucket_yoy"]],
            "bucket": list(snaps["decade"]),
        },
        "biz_day_avg": {
            "month_labels": labels,
            "month_avg": [_f(c / b) if b else None for c, b in zip(total, biz_month)],
            "month_biz": biz_month,
            "seg_labels": seg_x, "seg_avg": seg_avg, "seg_biz": seg_biz,
        },
        "raw": [{
            "date": d.strftime("%Y-%m-%d"), "cum": _f(a),
            "yoy": _f(y), "price": _f(pr),
        } for d, a, y, pr in zip(raw["date"], raw["export_amount"],
                                 raw["same_bucket_yoy"], raw["unit_price"])],
        "raw_monthly": [{
            "period": l, "total": _f(t), "yoy": y, "mom": mm, "price": pr,
        } for l, t, y, mm, pr in list(zip(labels, total, yoy, mom, price_m))[-60:][::-1]],
        # 한 페이지에 두 층위가 통합돼 있음을 명시하기 위한 기준 배지
        # 3층위 기준 — 잠정(순별)/월간/확정(기업별). 확정치에만 국내 지역 정보가 있어
        # 기업 특정이 가능하고, 그래서 매월 1~15일 구간에는 기업별이 한 달 뒤처져 보인다.
        "layer": {
            "decade_latest": last_snap["date"].strftime("%Y-%m-%d"),
            "month_latest": labels[-1] if labels else None,
            "company_latest": (_load(COMPANY_CSV)["date"].max().strftime("%Y-%m")
                               if COMPANY_CSV.exists() else None),
        },
        "companies": companies_payload(name),
    })


# ── 페이지 ────────────────────────────────────────────────────────────────────
def _item_by_hs(code: str):
    """HS코드 → 품목명. epsrev 종목상세/페어파인더의 기존 `?hs=` 딥링크 호환용."""
    if not MAPPING_CSV.exists():
        return None
    m = pd.read_csv(MAPPING_CSV)
    code = str(code).strip()
    for _, r in m.iterrows():
        codes = [c.strip() for c in str(r.get("hs_code") or "").split(";") if c.strip()]
        if code in codes:
            return str(r["item_name"])
    return None



# ── 월간 품목·기업 통합 테이블 (레퍼런스: '잠정 수출 품목 지역별 리스트' 스타일) ────
@app.get("/api/monthly_table")
def api_monthly_table():
    """품목 행 + 하위 기업 행. 컬럼은 [수출 금액]·[수출 단가] 두 그룹 × (최신월·전년동월·
    YoY·전월·전전월). 품목=월간 CSV(확정), 기업=company CSV(확정치에만 존재)."""
    key = "monthly_table"
    mtime = (MONTH_CSV.stat().st_mtime, COMPANY_CSV.stat().st_mtime)
    hit = _cache.get(key)
    if hit and hit[0] == mtime:
        return jsonify(hit[1])

    mon = _load(MONTH_CSV).copy()
    mon["ym"] = mon["date"].dt.to_period("M")
    latest = mon["ym"].max()
    cols = {"cur": latest, "prev_y": latest - 12, "m1": latest - 1, "m2": latest - 2}

    def _label(pr):
        d = mon[mon["ym"] == pr]["date"]
        return (d.max() if not d.empty else pr.to_timestamp("M")).strftime("%Y.%m.%d")

    def _cells(g, amt_col="export_amount", price_col="unit_price"):
        """기간별 금액/단가 + YoY."""
        by = {r.ym: r for r in g.itertuples()}
        out = {}
        for k, pr in cols.items():
            r = by.get(pr)
            out[f"amt_{k}"] = _f(getattr(r, amt_col)) if r is not None else None
            out[f"price_{k}"] = _f(getattr(r, price_col)) if r is not None else None
        for kind in ("amt", "price"):
            c, p_ = out[f"{kind}_cur"], out[f"{kind}_prev_y"]
            out[f"{kind}_yoy"] = _f((c / p_ - 1) * 100) if (c and p_) else None
        return out

    comp = _load(COMPANY_CSV).copy()
    comp["ym"] = comp["date"].dt.to_period("M")

    rows = []
    for name, g in mon.groupby("item_name"):
        g = g.sort_values("date")
        item_row = {"item": name, "category": str(g.iloc[-1].get("category") or ""),
                    **_cells(g)}
        kids = []
        cg = comp[comp["item_name"] == name]
        for cname, gg in cg.groupby("company_name"):
            kids.append({"company": str(cname), **_cells(gg.sort_values("date"))})
        kids.sort(key=lambda r: -(r["amt_cur"] or 0))
        item_row["companies"] = kids
        rows.append(item_row)
    rows.sort(key=lambda r: (r["amt_yoy"] is None, -(r["amt_yoy"] or 0)))

    payload = {
        "count": len(rows),
        "categories": sorted({r["category"] for r in rows if r["category"]}),
        "labels": {"cur": _label(cols["cur"]), "prev_y": _label(cols["prev_y"]),
                   "m1": _label(cols["m1"]), "m2": _label(cols["m2"])},
        "company_item_count": int(comp["item_name"].nunique()),
        "rows": rows,
    }
    _cache[key] = (mtime, payload)
    return jsonify(payload)



# ── 기업 카드/상세 (월간 확정 기준) ──────────────────────────────────────────
def _company_frame():
    c = _load(COMPANY_CSV).copy()
    c["ym"] = c["date"].dt.to_period("M")
    return c


def _yoy_mom(g, latest):
    """기업 합계 시계열 g(ym→amount)에서 최신월 기준 YoY·MoM."""
    cur = g.get(latest)
    py, pm = g.get(latest - 12), g.get(latest - 1)
    return (_f((cur / py - 1) * 100) if (cur and py) else None,
            _f((cur / pm - 1) * 100) if (cur and pm) else None)


@app.get("/api/company_cards")
def api_company_cards():
    """월간 홈용 — 기업 1장 = 카드 1개. 소속 품목 병기·최신 확정월 합계·YoY·스파크라인."""
    key = "company_cards"
    mtime = COMPANY_CSV.stat().st_mtime
    hit = _cache.get(key)
    if hit and hit[0] == mtime:
        return jsonify(hit[1])

    c = _company_frame()
    latest = c["ym"].max()
    cats = _load(MONTH_CSV).groupby("item_name")["category"].last().to_dict()

    cards = []
    for name, g in c.groupby("company_name"):
        tot = g.groupby("ym")["export_amount"].sum().sort_index()
        yoy, mom = _yoy_mom(tot.to_dict(), latest)
        items = sorted(g["item_name"].unique())
        cards.append({
            "company": str(name),
            "items": items,
            "items_short": [i.split("_")[-1] for i in items],
            "categories": sorted({str(cats.get(i) or "") for i in items} - {""}),
            "latest_period": str(latest),
            "latest_amount": _f(tot.get(latest)),
            "yoy": yoy, "mom": mom,
            "spark": [_f(v) for v in tot.tail(12)],
        })
    cards.sort(key=lambda r: (r["yoy"] is None, -(r["yoy"] or 0)))
    payload = {"count": len(cards), "latest": str(latest),
               "categories": sorted({x for r in cards for x in r["categories"]}),
               "items": sorted({i for r in cards for i in r["items"]}),
               "cards": cards}
    _cache[key] = (mtime, payload)
    return jsonify(payload)


@app.get("/api/company/<path:name>")
def api_company(name: str):
    """기업 상세 — 계열(합산 + 품목별)을 모두 선계산해 내려준다.
    각 계열: labels·amount·price·yoy·mom·biz·day_avg + kpi. 클라이언트는 토글만 하면 된다.
    합산 단가는 **가중평균**(Σ금액 ÷ Σ추정물량, 물량=금액÷단가)."""
    c = _company_frame()
    g0 = c[c["company_name"] == name]
    if g0.empty:
        abort(404, description=f"기업 없음: {name}")
    latest = c["ym"].max()

    def _series(df: pd.DataFrame, weighted_price: bool) -> dict:
        """월별 계열 하나를 만든다. weighted_price=True면 여러 품목을 합산."""
        if weighted_price:
            g = df.copy()
            g["vol"] = g["export_amount"] / g["unit_price"].replace(0, pd.NA)
            agg = g.groupby("ym").agg(amount=("export_amount", "sum"), vol=("vol", "sum"))
            agg["price"] = agg["amount"] / agg["vol"]
        else:
            agg = df.groupby("ym").agg(amount=("export_amount", "sum"),
                                       price=("unit_price", "last"))
        agg = agg.sort_index()
        yms = list(agg.index)
        amt = {p_: float(v) for p_, v in agg["amount"].items()}
        labels = [str(p_) for p_ in yms]
        amount = [_f(amt[p_]) for p_ in yms]
        price = [_f(v) for v in agg["price"]]
        yoy = [_f((amt[p_] / amt[p_ - 12] - 1) * 100) if (p_ - 12) in amt and amt[p_ - 12] else None
               for p_ in yms]
        mom = [_f((amt[p_] / amt[p_ - 1] - 1) * 100) if (p_ - 1) in amt and amt[p_ - 1] else None
               for p_ in yms]
        biz = [tm.bizdays(pd.Timestamp(p_.year, p_.month, 1),
                          pd.Timestamp(p_.year, p_.month, 1) + pd.offsets.MonthEnd(0)) for p_ in yms]
        day_avg = [_f(a / b) if (a and b) else None for a, b in zip(amount, biz)]
        i = labels.index(str(latest)) if str(latest) in labels else len(labels) - 1
        return {
            "labels": labels, "amount": amount, "price": price,
            "yoy": yoy, "mom": mom, "biz": biz, "day_avg": day_avg,
            "kpi": {"period": labels[i], "total": amount[i], "yoy": yoy[i], "mom": mom[i],
                    "price": price[i], "day_avg": day_avg[i], "day_avg_biz": biz[i]},
        }

    items = sorted(g0["item_name"].unique())
    series = {"합산": _series(g0, weighted_price=True)} if len(items) > 1 else {}
    for it in items:
        series[it] = _series(g0[g0["item_name"] == it], weighted_price=False)
    default_key = "합산" if len(items) > 1 else items[0]

    # 품목별 요약 테이블(최신 확정월)
    tot_latest = series[default_key]["kpi"]["total"]
    table = []
    for it in items:
        k = series[it]["kpi"]
        table.append({"item": it, "latest": k["total"], "yoy": k["yoy"], "price": k["price"],
                      "share": _f(k["total"] / tot_latest * 100) if (k["total"] and tot_latest) else None})
    table.sort(key=lambda r: -(r["latest"] or 0))

    raw = g0[g0["ym"] >= latest - 59].sort_values(["date", "item_name"], ascending=[False, True])
    return jsonify({
        "company": name, "latest_period": str(latest),
        "items": items, "default_key": default_key, "multi": len(items) > 1,
        "series": series, "table": table,
        "raw": [{"period": str(r.ym), "item": r.item_name, "amount": _f(r.export_amount),
                 "price": _f(r.unit_price)} for r in raw.itertuples()],
    })


# ── 투자 시그널 보드 ──────────────────────────────────────────────────────────
def _signal_df() -> pd.DataFrame:
    """Streamlit 페이지와 동일 경로: compute_item_metrics → enrich_signal_board →
    trade_score 엔진 점수로 signal_score 덮어쓰기(엔진 미가용 시 기존 가중식 폴백)."""
    key = "signal_df"
    mtime = DECADE_CSV.stat().st_mtime
    hit = _cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]

    hist = tud.load_history_from_decade()
    metrics = tud.compute_item_metrics(hist)
    latest = metrics.sort_values("date").groupby("item_name", as_index=False).tail(1)
    df = tud.enrich_signal_board(latest)
    try:
        from epsrev.trade_score.item_score import item_scores

        eng = item_scores(metrics).rename(columns={"signal_score": "_engine"})
        df = df.merge(eng, on="item_name", how="left")
        df["signal_score"] = df["_engine"].fillna(df["signal_score"])
        df = df.drop(columns=["_engine"])
    except Exception:
        pass
    df = df.sort_values("signal_score", ascending=False).reset_index(drop=True)
    _cache[key] = (mtime, df)
    return df


def _fav_mtime() -> float:
    try:
        return Path(tud.FAVORITES_PATH).stat().st_mtime
    except Exception:
        return 0.0


@app.get("/api/signal")
def api_signal():
    """DF뿐 아니라 직렬화된 페이로드까지 캐시 — 같은 CSV·즐겨찾기면 재계산 없음."""
    key = "signal_payload"
    mtime = (DECADE_CSV.stat().st_mtime, _fav_mtime())
    hit = _cache.get(key)
    if hit and hit[0] == mtime:
        return jsonify(hit[1])

    df = _signal_df()
    favs = tud.load_favorites()
    rows = [{
        "rank": i + 1, "item": r["item_name"], "category": r.get("category"),
        "score": _f(r["signal_score"]), "tag": r.get("tag"),
        "period": str(r.get("period")), "amount": _f(r.get("export_amount")),
        "yoy": _f(r.get("yoy")), "mom": _f(r.get("mom")), "ma3_yoy": _f(r.get("ma3_yoy")),
        "price_yoy": _f(r.get("price_yoy")), "volume_yoy": _f(r.get("volume_yoy")),
        "fav": r["item_name"] in favs,
    } for i, r in df.iterrows()]
    strong = tud.STRONG_YOY_PCT
    kpis = {
        "surge": int(sum(1 for x in rows if (x["yoy"] or 0) >= strong)),
        "price_up": int(sum(1 for x in rows if (x["price_yoy"] or 0) > 0)),
        "volume_up": int(sum(1 for x in rows if (x["volume_yoy"] or 0) > 0)),
        "negative_turn": int(sum(1 for x in rows if x["tag"] == tud.TAG_NEGATIVE_TURN)),
        "watchlist": len(favs),
    }
    payload = {"count": len(rows), "kpis": kpis, "items": rows}
    _cache[key] = (mtime, payload)
    return jsonify(payload)


# ── Watchlist(즐겨찾기) ───────────────────────────────────────────────────────
@app.get("/api/favorites")
def api_favorites_get():
    return jsonify({"favorites": sorted(tud.load_favorites())})


@app.post("/api/favorites")
def api_favorites_post():
    """{"item": "...", "action": "toggle|add|remove"} — favorites.json에 즉시 반영."""
    body = request.get_json(silent=True) or {}
    item = body.get("item")
    if not item:
        abort(400, description="item 필요")
    favs = tud.load_favorites()
    action = body.get("action", "toggle")
    if action == "add" or (action == "toggle" and item not in favs):
        favs.add(item)
    else:
        favs.discard(item)
    tud.save_favorites(favs)
    return jsonify({"item": item, "fav": item in favs, "favorites": sorted(favs)})


# ── 기업 검색 ─────────────────────────────────────────────────────────────────
@app.get("/api/companies")
def api_companies():
    """company CSV 전 기업 인덱스 — 기업×품목별 최신월·YoY·비중 + 미니차트용 시계열."""
    key = "companies_index"
    mtime = COMPANY_CSV.stat().st_mtime
    hit = _cache.get(key)
    if hit and hit[0] == mtime:
        return jsonify(hit[1])

    c = _load(COMPANY_CSV).sort_values("date")
    latest_by_item = c.groupby("item_name")["date"].max().to_dict()
    tot_by_item = {it: c[(c.item_name == it) & (c.date == d)]["export_amount"].sum()
                   for it, d in latest_by_item.items()}
    out = {}
    for (comp, item), g in c.groupby(["company_name", "item_name"]):
        g = g.sort_values("date")
        last = g.iloc[-1]
        prev = g[g["date"] == last["date"] - pd.DateOffset(years=1)]
        yoy = None
        if not prev.empty and prev["export_amount"].iloc[0]:
            yoy = (last["export_amount"] / prev["export_amount"].iloc[0] - 1) * 100
        tot = tot_by_item.get(item) or 0
        out.setdefault(str(comp), []).append({
            "item": item, "period": last["date"].strftime("%Y-%m"),
            "latest": _f(last["export_amount"]), "yoy": _f(yoy),
            "share": _f(last["export_amount"] / tot * 100) if tot else None,
            "labels": [d.strftime("%Y-%m") for d in g["date"].tail(36)],
            "values": [_f(v) for v in g["export_amount"].tail(36)],
        })
    payload = {"count": len(out),
               "companies": [{"name": k, "items": v} for k, v in sorted(out.items())]}
    _cache[key] = (mtime, payload)
    return jsonify(payload)


# ── 랜딩용 경량 요약 ──────────────────────────────────────────────────────────
def _signal_cached():
    """이미 계산된 시그널 DF가 있으면 반환, 없으면 None(계산을 유발하지 않는다).
    랜딩이 시그널 전체 계산(콜드 ~0.7s)을 기다리지 않게 하는 게 핵심."""
    hit = _cache.get("signal_df")
    if hit and hit[0] == DECADE_CSV.stat().st_mtime:
        return hit[1]
    return None


def _s(v):
    """NaN/None → None, 그 외 문자열."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return str(v)


def summary_payload() -> dict:
    """랜딩 섹션 카드의 동적 숫자만 — 기준일 3개·건수·Watchlist·시그널 Top1.
    스파크라인/전체 랭킹 같은 무거운 배열은 담지 않는다(수 ms, 수백 바이트)."""
    key = "summary_meta"
    mtime = (DECADE_CSV.stat().st_mtime, MONTH_CSV.stat().st_mtime, COMPANY_CSV.stat().st_mtime)
    hit = _cache.get(key)
    base = hit[1] if (hit and hit[0] == mtime) else None
    if base is None:
        dec, mon, comp = _load(DECADE_CSV), _load(MONTH_CSV), _load(COMPANY_CSV)
        base = {
            "decade_latest": dec["date"].max().strftime("%Y-%m-%d"),
            "decade_item_count": int(dec["item_name"].nunique()),
            "month_latest": mon["date"].max().strftime("%Y-%m"),
            "item_count": int(mon["item_name"].nunique()),
            "company_latest": comp["date"].max().strftime("%Y-%m"),
            "company_count": int(comp["company_name"].nunique()),
            "company_item_count": int(comp["item_name"].nunique()),
        }
        _cache[key] = (mtime, base)

    out = dict(base)
    out["watchlist_count"] = len(tud.load_favorites())
    sig = _signal_cached()
    if sig is not None and len(sig):
        r = sig.iloc[0]
        out["signal_ready"] = True
        out["signal_count"] = int(len(sig))
        out["signal_top1"] = {"item": _s(r["item_name"]), "score": _f(r["signal_score"]),
                              "tag": _s(r.get("tag"))}
    else:
        # 워밍 중 — 클라이언트가 잠시 뒤 한 번 더 물어본다(카드는 이미 떠 있다).
        out["signal_ready"] = False
        out["signal_count"] = None
        out["signal_top1"] = None
    return out


@app.get("/api/summary")
def api_summary():
    return jsonify(summary_payload())


@app.get("/")
def index():
    """랜딩(허브) — 섹션 선택 + 통합 검색. `?hs=` 딥링크는 종전대로 품목 상세로 보낸다."""
    hs = request.args.get("hs")
    if hs:
        name = _item_by_hs(hs)
        if name and name in {i["item"] for i in items_payload()["items"]}:
            return redirect(f"/monthly/item/{name}", code=302)
    return render_template("landing.html", nav="home")


@app.get("/decade")
def decade_home():
    return render_template("home.html", nav="decade", layer="decade")


@app.get("/monthly")
def monthly_home():
    """월간 홈 = 기업 카드 그리드(기본). 품목 뷰는 /monthly/items."""
    return render_template("company_cards.html", nav="monthly", layer="monthly")


@app.get("/monthly/items")
def monthly_items():
    """품목 보기 — 품목·기업 통합 테이블."""
    return render_template("monthly_table.html", nav="monthly", layer="monthly")


@app.get("/monthly/company/<path:name>")
def monthly_company(name: str):
    return render_template("company_item.html", company=name, nav="monthly", layer="monthly")


def _nav_items(name: str):
    names = [i["item"] for i in items_payload()["items"]]
    if name not in set(names):
        abort(404, description=f"품목 없음: {name}")
    i = names.index(name)
    return (names[i - 1] if i > 0 else None), (names[i + 1] if i < len(names) - 1 else None)


@app.get("/decade/item/<path:name>")
def decade_item(name: str):
    prev_i, next_i = _nav_items(name)
    return render_template("decade_item.html", item=name, nav="decade", layer="decade",
                           prev_item=prev_i, next_item=next_i)


@app.get("/monthly/item/<path:name>")
def monthly_item(name: str):
    prev_i, next_i = _nav_items(name)
    return render_template("monthly_item.html", item=name, nav="monthly", layer="monthly",
                           prev_item=prev_i, next_item=next_i)


@app.get("/item/<path:name>")
def item_page_legacy(name: str):
    """하위호환 — 기존 /item/<name> 링크는 월간 상세로."""
    return redirect(f"/monthly/item/{name}", code=301)


@app.get("/signal")
def signal_page():
    return render_template("signal.html", nav="signal")


@app.get("/watchlist")
def watchlist_page():
    return render_template("watchlist.html", nav="watchlist")


@app.get("/companies")
def companies_page():
    """구 기업 검색 페이지 — 월간 홈(기업 카드)로 통합됨."""
    return redirect("/monthly", code=301)


# ── 기동 시 캐시 워밍 ─────────────────────────────────────────────────────────
# waitress가 첫 요청을 받기 전에 CSV 로드·요약·시그널을 미리 계산해 둔다.
# 데몬 스레드라 실패해도 앱 기동을 막지 않는다(요청 시 지연 로드로 폴백).
def _warm_cache() -> None:
    import time as _time
    t0 = _time.time()
    for label, fn in (("csv+요약", lambda: (_load(MONTH_CSV), _load(COMPANY_CSV),
                                            decade_df(), summary_payload())),
                      ("품목 카드", items_payload),
                      ("시그널", _signal_df)):
        try:
            fn()
            print(f"[warm] {label} 완료 ({_time.time() - t0:.1f}s)", flush=True)
        except Exception as e:  # noqa: BLE001 — 워밍 실패는 치명적이지 않다
            print(f"[warm] {label} 실패(요청 시 지연 로드): {e}", flush=True)


if _os.environ.get("TRADE_WEB_NO_WARM") != "1":
    threading.Thread(target=_warm_cache, name="cache-warm", daemon=True).start()


def create_app():
    """waitress --call 용 팩토리."""
    return app


if __name__ == "__main__":
    import os

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5100)), debug=False)
