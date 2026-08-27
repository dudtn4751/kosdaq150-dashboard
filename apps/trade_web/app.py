"""수출입 대시보드 (Flask + Chart.js) — M1: 골격 + JSON API + 품목 상세 1페이지.

Streamlit 앱과 **같은 데이터**(data/trade_dashboard/*.csv)와 **같은 계산 모듈**
(trade_metrics)을 쓴다. 지표는 전부 서버에서 선계산해 배열로 내려주고(레퍼런스 계약),
클라이언트는 Chart.js로 그리기만 한다 — 뷰 토글 시 서버 왕복이 없다.

실행: python3 apps/trade_web/app.py   (또는 scripts/run_trade_web.sh — waitress)
"""

import sys
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
            "spark": [_f(v) for v in g["export_amount"].tail(12)],
            "has_company": name in comp_items,
        })
    items.sort(key=lambda r: (r["decade_yoy"] is None, -(r["decade_yoy"] or 0)))
    payload = {
        "count": len(items),
        "categories": sorted({i["category"] for i in items if i["category"]}),
        "decade_latest": latest_date.strftime("%Y-%m-%d"),
        "month_latest": mon_csv["date"].max().strftime("%Y-%m"),
        "company_item_count": len(comp_items),
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
            "price": _f(last_snap["unit_price"]),
        },
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
        # 한 페이지에 두 층위가 통합돼 있음을 명시하기 위한 기준 배지
        "layer": {
            "decade_latest": last_snap["date"].strftime("%Y-%m-%d"),
            "month_latest": labels[-1] if labels else None,
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


@app.get("/")
def index():
    hs = request.args.get("hs")           # 기존 딥링크: /?hs=8507602000 → 해당 품목 상세로
    if hs:
        name = _item_by_hs(hs)
        if name and name in {i["item"] for i in items_payload()["items"]}:
            return redirect(f"/item/{name}", code=302)
    return render_template("home.html", nav="home")


@app.get("/item/<path:name>")
def item_page(name: str):
    names = [i["item"] for i in items_payload()["items"]]
    if name not in set(names):
        abort(404, description=f"품목 없음: {name}")
    i = names.index(name)
    return render_template(
        "item.html", item=name, nav="home",
        prev_item=names[i - 1] if i > 0 else None,
        next_item=names[i + 1] if i < len(names) - 1 else None,
    )



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


@app.get("/api/signal")
def api_signal():
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
    return jsonify({"count": len(rows), "kpis": kpis, "items": rows})


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


@app.get("/signal")
def signal_page():
    return render_template("signal.html", nav="signal")


@app.get("/watchlist")
def watchlist_page():
    return render_template("watchlist.html", nav="watchlist")


@app.get("/companies")
def companies_page():
    return render_template("companies.html", nav="companies")


def create_app():
    """waitress --call 용 팩토리."""
    return app


if __name__ == "__main__":
    import os

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5100)), debug=False)
