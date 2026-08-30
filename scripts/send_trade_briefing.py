#!/usr/bin/env python3
"""수출입 텔레그램 브리핑 — 실행일(day)에 맞춰 그룹에 요약 전송. ★로컬 전용.

실행일별 (2026-08-27 일정 정정 — '15일 확정 발표' 가정 폐기):
  * 1일        : 월별 갱신일 — 품목 YoY 상위/하위 5 + **기업별 신규 갱신**
                 (월별·기업 데이터는 이날 함께 갱신된다)
  * 11·21일    : 10일 단위 — 최신 스냅샷(날짜 표기, 예 "8/10 누계") 동순 YoY 상위/하위 5
                 + 직전 순 대비 가속 상위 3

데이터: data/trade_dashboard/ CSV. 대시보드와 동일 로직(동순 원칙 = 같은 day버킷끼리).
자격증명: .env 의 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 에서만 읽음(하드코딩 금지).
안전: 토큰/chat_id 없으면 스킵, 전송 실패는 로그만(graceful) — 래퍼를 죽이지 않는다.

사용: python3 scripts/send_trade_briefing.py <day>     # day 없으면 오늘 날짜(%d)
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
DATA_DIR = BASE_DIR / "data" / "trade_dashboard"

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TG_LIMIT = 4096


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# ---------- 텔레그램 ----------
def _resolve_chat_id():
    """CHAT_ID 없으면 getUpdates로 봇이 초대된 그룹(음수 id)을 자동 감지해 .env에 저장."""
    global CHAT_ID
    if CHAT_ID:
        return CHAT_ID
    if not TOKEN:
        return None
    import requests

    try:
        data = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates", timeout=15).json()
    except Exception as e:
        log(f"getUpdates 실패: {type(e).__name__}: {str(e)[:120]}")
        return None
    if not data.get("ok"):
        log(f"getUpdates API 오류: {str(data.get('description'))[:120]}")
        return None
    gid = None
    for u in data.get("result", []):
        for k in ("message", "edited_message", "channel_post", "my_chat_member"):
            chat = (u.get(k) or {}).get("chat") or {}
            if chat.get("type") in ("group", "supergroup"):
                gid = chat["id"]  # 여러 개면 마지막(최근) 채택
    if gid is None:
        log("그룹 chat_id를 찾지 못했습니다 — 봇(@…)을 그룹에 초대하고 메시지 1개를 보낸 뒤 다시 실행하세요.")
        return None
    env_path = BASE_DIR / ".env"
    try:
        txt = env_path.read_text()
        if "TELEGRAM_CHAT_ID=" not in txt:
            with env_path.open("a") as f:
                f.write(f"\nTELEGRAM_CHAT_ID={gid}\n")
            log(f"TELEGRAM_CHAT_ID={gid} 를 .env에 추가했습니다.")
    except Exception as e:
        log(f".env 저장 실패(무시하고 진행): {e}")
    CHAT_ID = str(gid)
    return CHAT_ID


def _split(text: str, limit: int = TG_LIMIT - 96):
    """텔레그램 4096자 제한 대비 — 줄 경계로 분할."""
    out, cur = [], ""
    for ln in text.split("\n"):
        if len(cur) + len(ln) + 1 > limit and cur:
            out.append(cur)
            cur = ln
        else:
            cur = f"{cur}\n{ln}" if cur else ln
    if cur:
        out.append(cur)
    return out or [text]


def send(html: str) -> bool:
    if not TOKEN:
        log("TELEGRAM_BOT_TOKEN 없음 — 전송 스킵")
        return False
    cid = _resolve_chat_id()
    if not cid:
        log("chat_id 없음 — 전송 스킵")
        return False
    import requests

    ok_all = True
    for chunk in _split(html):
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                data={"chat_id": cid, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True},
                timeout=20,
            )
            j = r.json()
            if not j.get("ok"):
                log(f"sendMessage 실패: {str(j.get('description'))[:150]}")
                ok_all = False
        except Exception as e:
            log(f"sendMessage 예외: {type(e).__name__}: {str(e)[:120]}")
            ok_all = False
    return ok_all


# ---------- 포맷 ----------
def esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt_amt(v) -> str:
    if pd.isna(v):
        return "N/A"
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1e9:
        return f"{sign}${v / 1e9:.1f}B"
    if v >= 1e6:
        return f"{sign}${v / 1e6:.1f}M"
    if v >= 1e3:
        return f"{sign}${v / 1e3:.1f}K"
    return f"{sign}${v:.0f}"


def emo(v) -> str:
    return "🔺" if v >= 0 else "🔻"


DIVIDER = "────────────────────────────"
TOP_N = 6                  # 🔴 상승 / 🔵 하락 각각 표시 개수
BASE_EFFECT_PCT = 1000.0   # |YoY| 이 값 이상은 기저효과로 보고 본 랭킹에서 분리한다


def _na(v) -> bool:
    return v is None or pd.isna(v)


def fmt_pct(v) -> str:
    return "N/A" if _na(v) else f"{v:+.1f}%"


def fmt_mom(v) -> str:
    """MoM 결측 = 직전 순/월에 값이 없던 품목 → 'N/A'가 아니라 '신규'로 읽힌다."""
    return "신규" if _na(v) else fmt_pct(v)


def dashboard_url() -> str:
    """대시보드 링크 — .env의 TRADE_WEB_URL(Render). ngrok 링크는 쓰지 않는다."""
    return (os.environ.get("TRADE_WEB_URL") or "").rstrip("/")


def _bucket(day: int) -> str:
    return "상순" if day <= 10 else ("중순" if day <= 20 else "월말")


def _rows_block(rows: list, emoji: str) -> str:
    """[{name, amt, mom, yoy}] → 템플릿 본문 블록."""
    out = []
    for r in rows:
        out.append(f"{emoji} <b>{esc(r['name'])}</b>")
        out.append(f"   수출액: {fmt_amt(r['amt'])} | MoM: {fmt_mom(r['mom'])} | YoY: {fmt_pct(r['yoy'])}")
    return "\n".join(out)


def _split_base_effect(rows: list) -> tuple:
    """YoY 유효 행을 (실질 랭킹용, 기저효과)로 가른다.

    전년 같은 순의 수출이 0에 가까웠던 품목(신규 수출·일회성 선적)은 YoY가 수천~수십만 %로
    찍혀 🔴 상위를 통째로 차지한다. 그대로 두면 '반도체_디램 +504.8%' 같은 실질 신호가
    화면 밖으로 밀려나므로 별도 섹션으로 분리한다."""
    valid = [r for r in rows if not _na(r["yoy"])]
    normal = [r for r in valid if abs(r["yoy"]) < BASE_EFFECT_PCT]
    extreme = [r for r in valid if abs(r["yoy"]) >= BASE_EFFECT_PCT]
    normal.sort(key=lambda r: r["yoy"], reverse=True)
    extreme.sort(key=lambda r: r["yoy"], reverse=True)
    return normal, extreme


def render(layer_label: str, date_label: str, rows: list, extra_sections: list = None) -> str:
    """공통 템플릿. rows는 정렬 대상 전체 — 상위/하위 TOP_N + 기저효과 섹션으로 나눈다."""
    normal, extreme = _split_base_effect(rows)
    up, down = normal[:TOP_N], normal[-TOP_N:][::-1]

    parts = [f"📊 <b>수출 데이터 업데이트</b> [{esc(layer_label)}]",
             f"📅 기준일: {date_label}", DIVIDER, ""]
    parts.append(_rows_block(up, "🔴"))
    parts.append("")
    parts.append(_rows_block(down, "🔵"))

    if extreme:
        parts += ["", DIVIDER,
                  f"<b>⚡ 기저효과 급증</b> (YoY ≥ {int(BASE_EFFECT_PCT):,}% — 전년 기저가 0에 가까움)", ""]
        parts.append(_rows_block(extreme[:TOP_N], "⚡"))

    for title, srows in (extra_sections or []):
        snormal, _ = _split_base_effect(srows)
        parts += ["", DIVIDER, f"<b>{esc(title)}</b>", ""]
        parts.append(_rows_block(snormal[:TOP_N], "🔴"))
        parts.append("")
        parts.append(_rows_block(snormal[-TOP_N:][::-1], "🔵"))

    url = dashboard_url()
    parts += ["", DIVIDER]
    if url:
        parts.append(f'🔗 대시보드: <a href="{url}">{url}</a>')
    return "\n".join(parts)


# ---------- 데이터 → rows ----------
def rows_monthly() -> tuple:
    """월별(확정) — 기준일=최신 확정월(YYYY.MM), MoM=전월, YoY=전년."""
    df = pd.read_csv(DATA_DIR / "trade_history_long.csv")
    df["기준일"] = pd.to_datetime(df["기준일"])
    df["ym"] = df["기준일"].dt.to_period("M")
    latest = df["ym"].max()
    rows = []
    for it, g in df.groupby("품목명"):
        by = g.set_index("ym")["수출금액"].to_dict()
        cur, py, pm = by.get(latest), by.get(latest - 12), by.get(latest - 1)
        if cur is None:
            continue
        rows.append({
            "name": it, "amt": float(cur),
            "mom": (cur / pm - 1) * 100 if pm else None,
            "yoy": (cur / py - 1) * 100 if py else None,
        })
    return f"{latest.year}.{latest.month:02d}", rows


def rows_company() -> tuple:
    """기업별(월별과 함께 매월 1일 갱신) — 기업×품목 단위."""
    path = DATA_DIR / "company_trade_history_long.csv"
    if not path.exists():
        return None, []
    c = pd.read_csv(path)
    c["기준일"] = pd.to_datetime(c["기준일"])
    c["ym"] = c["기준일"].dt.to_period("M")
    latest = c["ym"].max()
    rows = []
    for (comp, it), g in c.groupby(["기업명", "품목명"]):
        by = g.set_index("ym")["수출금액"].to_dict()
        cur, py, pm = by.get(latest), by.get(latest - 12), by.get(latest - 1)
        if cur is None:
            continue
        rows.append({
            "name": f"{comp} ({it})", "amt": float(cur),
            "mom": (cur / pm - 1) * 100 if pm else None,
            "yoy": (cur / py - 1) * 100 if py else None,
        })
    return f"{latest.year}.{latest.month:02d}", rows


def rows_decade() -> tuple:
    """10일 단위 — 기준일=최신 스냅샷 날짜, YoY=동순(전년 같은 순), MoM=직전 순 대비.

    ※ MoM은 **구간 증분끼리** 비교한다. decade 값은 월누계(MTD)라 누계끼리 비교하면
    (8/20 누계 vs 8/10 누계) 항상 증가로 나와 의미가 없다."""
    dec = pd.read_csv(DATA_DIR / "trade_history_decade_long.csv")
    dec["기준일"] = pd.to_datetime(dec["기준일"])
    dec["y"], dec["m"] = dec["기준일"].dt.year, dec["기준일"].dt.month
    dec["bkt"] = dec["기준일"].dt.day.map(_bucket)
    latest = dec["기준일"].max()
    cy, cm, cb = int(latest.year), int(latest.month), _bucket(int(latest.day))
    cum = dec.set_index(["품목명", "y", "m", "bkt"])["수출금액"].to_dict()

    def _inc(it, y, m, bkt):
        """그 순의 구간 증분(상순=누계, 중순=20−10, 월말=말−20)."""
        c10 = cum.get((it, y, m, "상순"))
        c20 = cum.get((it, y, m, "중순"))
        c30 = cum.get((it, y, m, "월말"))
        if bkt == "상순":
            return c10
        if bkt == "중순":
            return (c20 - c10) if (c20 is not None and c10 is not None) else None
        return (c30 - c20) if (c30 is not None and c20 is not None) else None

    order = ["상순", "중순", "월말"]
    pi = order.index(cb) - 1
    if pi < 0:                                   # 상순이면 직전 순 = 전월 월말
        p_y, p_m, p_b = (cy, cm - 1, "월말") if cm > 1 else (cy - 1, 12, "월말")
    else:
        p_y, p_m, p_b = cy, cm, order[pi]

    rows = []
    for it in sorted(dec["품목명"].unique()):
        c = cum.get((it, cy, cm, cb))
        if c is None:
            continue
        py = cum.get((it, cy - 1, cm, cb))
        cur_inc, prev_inc = _inc(it, cy, cm, cb), _inc(it, p_y, p_m, p_b)
        rows.append({
            "name": it, "amt": float(c),
            "mom": (cur_inc / prev_inc - 1) * 100 if (cur_inc and prev_inc) else None,
            "yoy": (c / py - 1) * 100 if py else None,
        })
    span = {"상순": f"{cm}/1~10", "중순": f"{cm}/11~20", "월말": f"{cm}/21~말일"}[cb]
    return f"{latest.year}.{latest.month:02d}.{latest.day:02d} ({span} 잠정)", rows


# ---------- 브리핑 ----------
def build(day: int):
    if day == 1:
        # 1일은 월별·기업별뿐 아니라 **순별 스크래퍼도 함께** 돈다(래퍼 day-1 분기).
        # 즉 전월 월말 스냅샷(예: 8/31 = 8/21~말일)이 이날 새로 들어오므로,
        # 월별·기업별과 함께 순별 섹션도 실어야 그날 갱신분이 전부 브리핑된다.
        label, rows = rows_monthly()
        if not rows:
            log("월별 데이터 부족 — 브리핑 없음")
            return None
        extra = []
        clabel, crows = rows_company()
        if crows:
            extra.append((f"🏢 기업별 신규 갱신 · {clabel}", crows))
        dlabel, drows = rows_decade()
        if drows:
            extra.append((f"🗓 10일 단위 · {dlabel}", drows))
        layer = "월별 + 10일 단위" if drows else "월별"
        return render(layer, f"{label} (확정)", rows, extra)
    if day in (11, 21):
        label, rows = rows_decade()
        if not rows:
            log("10일 단위 데이터 부족 — 브리핑 없음")
            return None
        return render("10일 단위", label, rows)
    log(f"day={day} 는 갱신일(1·11·21) 아님 — 브리핑 없음")
    return None


def main():
    day = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else datetime.now().day
    log(f"브리핑 생성 (day={day})")
    try:
        html = build(day)
    except Exception as e:
        log(f"브리핑 생성 실패(무시): {type(e).__name__}: {str(e)[:150]}")
        return
    if not html:
        return
    if send(html):
        log("전송 완료")
    else:
        log("전송 안 됨(스킵/실패) — 래퍼는 정상 종료")


if __name__ == "__main__":
    main()
