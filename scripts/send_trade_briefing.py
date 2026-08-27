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


def _rank_lines(df, amt_col="amt") -> str:
    lines = []
    for _, r in df.iterrows():
        lines.append(f"{emo(r['yoy'])} <b>{r['yoy']:+.1f}%</b>  {esc(r['item'])}  <i>{fmt_amt(r[amt_col])}</i>")
    return "\n".join(lines)


def _bucket(day: int) -> str:
    return "상순" if day <= 10 else ("중순" if day <= 20 else "월말")


# ---------- 데이터/브리핑 ----------
def _monthly_yoy():
    df = pd.read_csv(DATA_DIR / "trade_history_long.csv")
    df["기준일"] = pd.to_datetime(df["기준일"])
    df["ym"] = df["기준일"].dt.to_period("M")
    latest = df["ym"].max()
    rows = []
    for it, g in df.groupby("품목명"):
        cur = g[g["ym"] == latest]
        prev = g[g["ym"] == (latest - 12)]
        if cur.empty or prev.empty:
            continue
        cv = float(cur.sort_values("기준일")["수출금액"].iloc[-1])
        pv = float(prev.sort_values("기준일")["수출금액"].iloc[-1])
        if pv <= 0:
            continue
        rows.append((it, cv, (cv / pv - 1) * 100))
    return latest, pd.DataFrame(rows, columns=["item", "amt", "yoy"]).dropna()


def brief_monthly(kind: str):
    """kind = 표시 라벨(현재 '월별' — 월별 데이터는 매월 1일 갱신)."""
    latest, r = _monthly_yoy()
    if r.empty:
        log("월간 데이터 부족 — 브리핑 없음")
        return None
    top = r.sort_values("yoy", ascending=False).head(5)
    bot = r.sort_values("yoy").head(5)
    p = latest  # Period(월)
    head = f"📅 <b>수출입 월간 브리핑 · {p.year}년 {p.month}월 {kind}</b>\n<i>전년 동월 대비(YoY) · {len(r)}개 품목</i>"
    body = (
        f"\n\n<b>🔺 YoY 상위 5</b>\n{_rank_lines(top)}"
        f"\n\n<b>🔻 YoY 하위 5</b>\n{_rank_lines(bot)}"
    )
    return head + body


def brief_decade():
    dec = pd.read_csv(DATA_DIR / "trade_history_decade_long.csv")
    dec["기준일"] = pd.to_datetime(dec["기준일"])
    dec["y"], dec["m"] = dec["기준일"].dt.year, dec["기준일"].dt.month
    dec["bkt"] = dec["기준일"].dt.day.map(_bucket)
    latest = dec["기준일"].max()
    cy, cm, cb = int(latest.year), int(latest.month), _bucket(int(latest.day))
    dlabel = f"{cm}/{int(latest.day)}"

    cur = dec[(dec.y == cy) & (dec.m == cm) & (dec.bkt == cb)].groupby(["품목명", "대분류"])["수출금액"].last()
    prev = dec[(dec.y == cy - 1) & (dec.m == cm) & (dec.bkt == cb)].groupby("품목명")["수출금액"].last()
    cur = cur.reset_index().rename(columns={"수출금액": "amt"})
    cur["prev"] = cur["품목명"].map(prev)
    cur["yoy"] = (cur["amt"] / cur["prev"] - 1) * 100
    r = cur.dropna(subset=["yoy"]).rename(columns={"품목명": "item"})
    if r.empty:
        log("순별 동순 데이터 부족 — 브리핑 없음")
        return None

    # 직전 순 대비 가속 Δ (이번 스냅샷 동순YoY − 직전 스냅샷 동순YoY)
    lookup = dec.set_index(["품목명", "y", "m", "bkt"])["수출금액"].to_dict()

    def _dyoy(it, row):
        p = lookup.get((it, int(row.y) - 1, int(row.m), row.bkt))
        return (row["수출금액"] / p - 1) * 100 if p else None

    accel = []
    for it, g in dec.groupby("품목명"):
        g = g.sort_values("기준일")
        if len(g) < 2:
            continue
        a0, a1 = _dyoy(it, g.iloc[-1]), _dyoy(it, g.iloc[-2])
        if a0 is not None and a1 is not None:
            accel.append((it, a0 - a1, a0))
    accel_df = pd.DataFrame(accel, columns=["item", "delta", "yoy"]).sort_values("delta", ascending=False)

    top = r.sort_values("yoy", ascending=False).head(5)
    bot = r.sort_values("yoy").head(5)
    head = (
        f"🗓 <b>수출입 순별 속보 · {dlabel} 누계</b>\n"
        f"<i>전년 같은 날짜({dlabel}) 대비 동순 YoY · {cy}년 {cm}월 · {len(r)}개 품목</i>"
    )
    body = (
        f"\n\n<b>🔺 동순 YoY 상위 5</b>\n{_rank_lines(top)}"
        f"\n\n<b>🔻 동순 YoY 하위 5</b>\n{_rank_lines(bot)}"
    )
    if not accel_df.empty:
        acc_lines = "\n".join(
            f"⚡ <b>{r2['delta']:+.1f}%p</b>  {esc(r2['item'])}  (YoY {r2['yoy']:+.1f}%)"
            for _, r2 in accel_df.head(3).iterrows()
        )
        body += f"\n\n<b>⚡ 직전 순 대비 가속 상위 3</b>\n{acc_lines}"
    return head + body



def brief_company_new(top_n: int = 5) -> str:
    """[1일 전용] 기업별 신규 갱신 — 월별·기업(품목·지역) 데이터는 매월 1일에 함께
    갱신된다. 최신월 기업×품목 중 YoY 상하위."""
    path = DATA_DIR / "company_trade_history_long.csv"
    if not path.exists():
        return ""
    c = pd.read_csv(path)
    c["기준일"] = pd.to_datetime(c["기준일"])
    latest = c["기준일"].max()
    cur = c[c["기준일"] == latest]
    prev = c[c["기준일"] == latest - pd.DateOffset(years=1)]
    pmap = {(r["품목명"], r["기업명"]): r["수출금액"] for _, r in prev.iterrows()}
    rows = []
    for _, r in cur.iterrows():
        pv = pmap.get((r["품목명"], r["기업명"]))
        if pv:
            # _rank_lines가 esc()를 적용하므로 여기서 태그·이스케이프를 넣지 않는다(이중 처리 방지).
            rows.append({"item": f"{r['기업명']} ({r['품목명']})",
                         "amt": float(r["수출금액"]), "yoy": (r["수출금액"] / pv - 1) * 100})
    if not rows:
        log("기업별 전년 대비 데이터 부족 — 섹션 생략")
        return ""
    df = pd.DataFrame(rows)
    up = df.sort_values("yoy", ascending=False).head(top_n)
    dn = df.sort_values("yoy").head(top_n)
    head = (f"\n\n<b>🏢 기업별 신규 갱신 · {latest:%Y-%m}</b>\n"
            f"<i>품목·지역 데이터 기준(매월 1일 갱신) · {cur['기업명'].nunique()}개 기업 "
            f"/ {cur['품목명'].nunique()}품목</i>")
    return (head
            + f"\n\n<b>🔺 기업 YoY 상위 {top_n}</b>\n" + _rank_lines(up)
            + f"\n\n<b>🔻 기업 YoY 하위 {top_n}</b>\n" + _rank_lines(dn))


def build(day: int):
    if day == 1:
        # 1일 = 월별 갱신일 → 월별 + 기업별 신규 갱신을 함께
        base = brief_monthly("월별")
        return (base + brief_company_new()) if base else base
    if day in (11, 21):
        return brief_decade()
    log(f"day={day} 는 발표일 아님 — 브리핑 없음")
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
