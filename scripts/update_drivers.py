"""매크로/스프레드 드라이버 → 섹터별 매크로 환경 신호 (롱숏 상대강도 이벤트 레이어).

sector_playbook.json의 드라이버 레지스트리(yfinance 티커 + 파생 스프레드)를 매일 당겨
각 드라이버의 추세(z-score)·변화율을 계산하고, 섹터별 영향 방향(effect)으로 가중합해
섹터 매크로 환경 신호(롱/숏 우위)를 산출한다.

핵심: 매크로 드라이버는 '섹터 전체'의 롱/숏 환경을 정한다(구성원에 균일 작용).
섹터 '내부' 상대강도 차등은 기업별 익스포저(고도화율·OLED비중·수출비중 등, 2차 레이어).

출력: data/market_drivers.json
사용: python3 scripts/update_drivers.py
"""

import json
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

KST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).parent.parent
PLAYBOOK_PATH = PROJECT_ROOT / "sector_playbook.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "market_drivers.json"


def fetch_series(ticker):
    """yfinance 90일 종가 시리즈 (실패 시 None)."""
    try:
        df = yf.Ticker(ticker).history(period="90d")
        c = df["Close"].dropna()
        return c if len(c) >= 10 else None
    except Exception:
        return None


def stat(series):
    """레벨·5/20일 변화율·추세 z-score (최근값의 60일 분포 내 위치)."""
    if series is None or len(series) < 10:
        return None
    s = series.astype(float)
    last = float(s.iloc[-1])

    def chg(n):
        return round((s.iloc[-1] / s.iloc[-n - 1] - 1) * 100, 1) if len(s) > n else None
    win = s.tail(60)
    mu, sd = win.mean(), win.std()
    z = round(float((last - mu) / sd), 2) if sd and sd == sd else 0.0
    return {"last": round(last, 2), "chg_5d": chg(5), "chg_20d": chg(20),
            "trend_z": max(-3.0, min(3.0, z))}


def main():
    now = datetime.now(KST)
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] 매크로 드라이버 수집")
    pb = json.loads(PLAYBOOK_PATH.read_text(encoding="utf-8"))
    reg = pb.get("drivers", {})

    # 1) yfinance 원시 시리즈 수집
    raw = {}
    for key, d in reg.items():
        if d.get("source") == "yfinance":
            s = fetch_series(d["ticker"])
            if s is not None:
                raw[key] = s
    print(f"  yfinance 수집: {len(raw)}/{sum(1 for d in reg.values() if d.get('source')=='yfinance')}")

    # 2) 파생 스프레드 시리즈
    def align(*keys):
        cols = {k: raw[k] for k in keys if k in raw}
        if len(cols) < len(keys):
            return None
        df = pd.DataFrame(cols).dropna()
        return df if len(df) >= 10 else None

    if "rbob" in raw and "wti" in raw:
        df = align("rbob", "wti")
        if df is not None:
            raw["gasoline_crack"] = df["rbob"] * 42 - df["wti"]
    if "heating_oil" in raw and "wti" in raw:
        df = align("heating_oil", "wti")
        if df is not None:
            raw["distillate_crack"] = df["heating_oil"] * 42 - df["wti"]
    if "usdkrw" in raw and "usdjpy" in raw:
        df = align("usdkrw", "usdjpy")
        if df is not None:
            raw["krwjpy"] = df["usdkrw"] / df["usdjpy"] * 100
    grains = [k for k in ("soybean", "wheat", "corn", "sugar", "cocoa") if k in raw]
    if len(grains) >= 3:
        df = pd.DataFrame({k: raw[k] for k in grains}).dropna()
        if len(df) >= 10:
            zs = (df - df.tail(60).mean()) / df.tail(60).std()
            raw["grain_basket"] = zs.mean(axis=1)

    # 3) 드라이버 통계
    drivers = {}
    for key, d in reg.items():
        st = stat(raw.get(key))
        if st is None:
            continue
        if d.get("unit") == "z":  # z-스코어 바스켓은 변화율 표기 무의미
            st["chg_5d"] = st["chg_20d"] = None
        drivers[key] = {"name": d["name"], "unit": d.get("unit", ""),
                        "source": d.get("source"), **st,
                        "affects": d.get("affects", [])}
    print(f"  드라이버 산출: {len(drivers)}개")

    # 4) 섹터별 매크로 환경 신호 = Σ effect × trend_z (영향 드라이버 가중합)
    sector_signals = {}
    for key, dv in drivers.items():
        z = dv.get("trend_z", 0.0)
        for a in dv.get("affects", []):
            sec = a["sector"]
            contrib = a["effect"] * z
            ss = sector_signals.setdefault(sec, {"signal": 0.0, "drivers": []})
            ss["signal"] += contrib
            # 방향 텍스트: 드라이버 추세 + 섹터 영향
            updown = "↑" if z > 0.2 else ("↓" if z < -0.2 else "→")
            good = "롱" if contrib > 0.15 else ("숏" if contrib < -0.15 else "중립")
            ss["drivers"].append({"name": dv["name"], "trend_z": round(z, 2),
                                  "updown": updown, "effect": a["effect"],
                                  "contrib": round(contrib, 2), "side": good})

    out_sectors = {}
    for sec, ss in sector_signals.items():
        sig = round(ss["signal"], 2)
        label = "롱 우위" if sig >= 0.5 else ("숏 우위" if sig <= -0.5 else "중립")
        ds = sorted(ss["drivers"], key=lambda x: abs(x["contrib"]), reverse=True)
        out_sectors[sec] = {"signal": sig, "label": label, "drivers": ds}

    out = {
        "updated": now.strftime("%Y-%m-%d %H:%M"), "date": now.strftime("%Y-%m-%d"),
        "drivers": drivers, "sector_signals": out_sectors,
        "driver_count": len(drivers),
    }
    # 안전장치: 핵심 드라이버 너무 적으면 기존 파일 유지
    if len(drivers) < 8:
        print(f"  [경고] 드라이버 {len(drivers)}개 — 수집 장애 의심. 기존 파일 유지(exit 2).")
        sys.exit(2)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  저장: {OUTPUT_PATH} (드라이버 {len(drivers)}개, 섹터신호 {len(out_sectors)}개)")


if __name__ == "__main__":
    main()
