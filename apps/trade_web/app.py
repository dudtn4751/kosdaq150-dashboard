"""수출입 대시보드 (Flask + Chart.js) — M1: 골격 + JSON API + 품목 상세 1페이지.

Streamlit 앱과 **같은 데이터**(data/trade_dashboard/*.csv)와 **같은 계산 모듈**
(trade_metrics)을 쓴다. 지표는 전부 서버에서 선계산해 배열로 내려주고(레퍼런스 계약),
클라이언트는 Chart.js로 그리기만 한다 — 뷰 토글 시 서버 왕복이 없다.

실행: python3 apps/trade_web/app.py   (또는 scripts/run_trade_web.sh — waitress)
"""

import sys
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, render_template, abort

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

import trade_metrics as tm  # noqa: E402  (경로 설정 후 import)

DATA_DIR = BASE_DIR / "data" / "trade_dashboard"
DECADE_CSV = DATA_DIR / "trade_history_decade_long.csv"
MONTH_CSV = DATA_DIR / "trade_history_long.csv"
COMPANY_CSV = DATA_DIR / "company_trade_history_long.csv"

COLS = {"품목명": "item_name", "대분류": "category", "기준일": "date",
        "수출금액": "export_amount", "단가": "unit_price", "기업명": "company_name"}

app = Flask(__name__)

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
    """품목 목록 — 대분류·최신 월 수출액·YoY·기업별 보유 여부."""
    mon = _load(MONTH_CSV)
    comp_items = set(_load(COMPANY_CSV)["item_name"].unique())
    mon = mon.sort_values("date")
    out = []
    for name, g in mon.groupby("item_name"):
        last = g.iloc[-1]
        prev = g[g["date"] == last["date"] - pd.DateOffset(years=1)]
        yoy = None
        if not prev.empty and prev["export_amount"].iloc[0]:
            yoy = (last["export_amount"] / prev["export_amount"].iloc[0] - 1) * 100
        out.append({
            "item": name, "category": last.get("category"),
            "latest_period": last["date"].strftime("%Y-%m"),
            "latest_amount": _f(last["export_amount"]),
            "yoy": _f(yoy), "has_company": name in comp_items,
        })
    out.sort(key=lambda r: (r["yoy"] is None, -(r["yoy"] or 0)))
    return jsonify({"count": len(out), "items": out})


@app.get("/api/item/<path:name>")
def api_item(name: str):
    """한 품목의 전체 선계산 배열 — 클라이언트는 그리기만 한다."""
    dec = decade_df()
    if name not in set(dec["item_name"]):
        abort(404, description=f"품목 없음: {name}")

    mon = tm.decade_monthly(dec, name)
    snaps = tm.decade_same_bucket_yoy(dec, name)

    # 월별(구간 증분 + 단가 + YoY/MoM)
    labels = [str(p) for p in mon["ym"]]
    cum = list(mon["cum"])
    yoy, mom = [], []
    by_ym = {(int(r.y), int(r.m)): r.cum for r in mon.itertuples()}
    for i, r in enumerate(mon.itertuples()):
        prev_y = by_ym.get((int(r.y) - 1, int(r.m)))
        yoy.append(_f((r.cum / prev_y - 1) * 100) if prev_y else None)
        mom.append(_f((r.cum / cum[i - 1] - 1) * 100) if i and cum[i - 1] else None)

    # 분기(QoQ)
    q = mon.copy()
    q["qtr"] = q["ym"].dt.asfreq("Q")
    qs = q.groupby("qtr")["cum"].sum().reset_index()
    qs["qoq"] = qs["cum"].pct_change() * 100

    # 10일 단위(순별 누계 + 동순 YoY)
    dec_labels = [d.strftime("%Y-%m-%d") for d in snaps["date"]]

    # 영업일 일평균(월별 누적 / 10일 구간별)
    starts = [pd.Timestamp(int(r.y), int(r.m), 1) for r in mon.itertuples()]
    biz_month = [tm.bizdays(s, ld) for s, ld in zip(starts, mon["last_date"])]
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
        "monthly": {
            "labels": labels,
            "d10": [_f(v) for v in mon["inc1"]],
            "d20": [_f(v) for v in mon["inc2"]],
            "dend": [_f(v) for v in mon["inc3"]],
            "total": [_f(v) for v in cum],
            "price": [_f(v) for v in mon["price"]],
            "yoy": yoy, "mom": mom,
        },
        "quarterly": {
            "labels": [str(p) for p in qs["qtr"]],
            "total": [_f(v) for v in qs["cum"]],
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
            "month_avg": [_f(c / b) if b else None for c, b in zip(cum, biz_month)],
            "month_biz": biz_month,
            "seg_labels": seg_x, "seg_avg": seg_avg, "seg_biz": seg_biz,
        },
        "raw": [{
            "date": d.strftime("%Y-%m-%d"), "cum": _f(a),
            "yoy": _f(y), "price": _f(pr),
        } for d, a, y, pr in zip(raw["date"], raw["export_amount"],
                                 raw["same_bucket_yoy"], raw["unit_price"])],
    })


# ── 페이지 ────────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    dec = decade_df()
    items = sorted(dec["item_name"].unique())
    return render_template("index.html", items=items)


@app.get("/item/<path:name>")
def item_page(name: str):
    dec = decade_df()
    if name not in set(dec["item_name"]):
        abort(404, description=f"품목 없음: {name}")
    return render_template("item.html", item=name)


def create_app():
    """waitress --call 용 팩토리."""
    return app


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5100, debug=False)
