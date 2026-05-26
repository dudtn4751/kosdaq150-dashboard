"""
미국 이벤트 수집 + 테마별 Claude 해석
매일 미장 마감 후 (07:00 KST 권장) 실행

흐름:
1. data/themes.json에서 정의된 테마 + 미국 티커 로드
2. yfinance에서 각 티커의 어제~오늘 가격/어닝/뉴스 수집
3. 테마별로 묶어서 Claude API에 분석 요청 — 핵심 이슈 3-5개, 영향 KR 종목
4. data/us_events.json에 raw_events + themes로 저장

사용:
    python3 scripts/update_us_events.py            # 기본
    python3 scripts/update_us_events.py --dry-run  # 수집만 (LLM 없음)
    python3 scripts/update_us_events.py --themes semi_logic_ai,power_grid  # 일부 테마만
"""

import argparse
import json
import os
import sys
import time
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

# stdout/stderr UTF-8 강제
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import yfinance as yf

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

warnings.filterwarnings("ignore")

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
THEMES_PATH = PROJECT_ROOT / "data" / "themes.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "us_events.json"


def load_themes():
    with open(THEMES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["themes"]


# ── 이벤트 수집 ────────────────────────────────────
def fetch_recent_events(ticker, lookback_hours=36):
    """티커의 최근 36시간 내 가격/어닝/뉴스 수집"""
    events = []
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=lookback_hours)

    try:
        t = yf.Ticker(ticker)
    except Exception:
        return events

    # 1) 전일 가격 변동
    try:
        h = t.history(period="5d")
        if len(h) >= 2:
            last = h["Close"].iloc[-1]
            prev = h["Close"].iloc[-2]
            ret = (last - prev) / prev * 100 if prev else 0
            events.append({
                "ticker": ticker,
                "type": "price_move",
                "close": round(last, 2),
                "ret_pct": round(ret, 2),
                "volume": int(h["Volume"].iloc[-1]) if "Volume" in h.columns else None,
                "as_of": h.index[-1].strftime("%Y-%m-%d"),
            })
    except Exception:
        pass

    # 2) 어닝
    try:
        ed = t.earnings_dates
        if ed is not None and not ed.empty:
            ed = ed.copy()
            ed.index = ed.index.tz_convert("UTC") if ed.index.tz else ed.index.tz_localize("UTC")
            recent = ed[(ed.index >= cutoff) & (ed.index <= now_utc)]
            if not recent.empty:
                row = recent.iloc[0]
                eps_est = row.get("EPS Estimate")
                eps_act = row.get("Reported EPS")
                surprise_pct = row.get("Surprise(%)")
                events.append({
                    "ticker": ticker,
                    "type": "earnings",
                    "eps_estimate": float(eps_est) if eps_est == eps_est else None,
                    "eps_actual": float(eps_act) if eps_act == eps_act else None,
                    "surprise_pct": float(surprise_pct) if surprise_pct == surprise_pct else None,
                    "report_dt": recent.index[0].strftime("%Y-%m-%d %H:%M UTC"),
                })
    except Exception:
        pass

    # 3) 뉴스 헤드라인
    try:
        news = t.news or []
        kept = []
        for n in news[:5]:
            content = n.get("content", {}) if isinstance(n, dict) else {}
            if not isinstance(content, dict):
                continue
            title = content.get("title") or n.get("title", "")
            if not title:
                continue
            summary = (content.get("summary") or "")[:400]
            pub_date = content.get("pubDate") or n.get("providerPublishTime")
            kept.append({"title": title, "summary": summary, "pub": str(pub_date) if pub_date else ""})
            if len(kept) >= 3:
                break
        if kept:
            events.append({"ticker": ticker, "type": "news", "headlines": kept})
    except Exception:
        pass

    return events


def collect_for_tickers(tickers):
    """티커 리스트의 이벤트 수집 (중복 호출 방지)"""
    seen = set()
    all_events = []
    unique_tickers = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            unique_tickers.append(t)

    for i, t in enumerate(unique_tickers):
        evs = fetch_recent_events(t)
        all_events.extend(evs)
        if (i + 1) % 10 == 0:
            print(f"  수집 진행: {i+1}/{len(unique_tickers)} ({len(all_events)} events)")
        time.sleep(0.2)
    return all_events


# ── 테마별 Claude 분석 ──────────────────────────────
THEME_SYSTEM = """당신은 한국 주식 투자자를 위한 미국 시장 분석가입니다.
주어진 산업 테마에 속한 미국 종목들의 어제 이벤트(가격, 어닝, 뉴스 헤드라인)를 종합 분석하세요.

다음 JSON 스키마로만 응답합니다. 다른 텍스트 금지.

{
  "summary": "이 테마의 어제 핵심 흐름 2-3 문장.",
  "key_issues": [
    {
      "text": "구체적 이슈. 단순 가격 변동보다는 CEO 코멘트, 가이던스, 정책, 어닝 서프라이즈, 신제품 발표 등 의미있는 정보를 우선.",
      "source_tickers": ["관련 미국 티커"]
    }
  ],
  "sentiment": "positive 또는 negative 또는 mixed 또는 neutral",
  "impact_strength": "high 또는 medium 또는 low",
  "affected_kr_sectors": ["네이버 업종명 또는 일반 업종명, 최대 5개"],
  "kr_tickers": [
    {"code": "6자리 종목코드", "name": "한국 종목명", "direction": "positive 또는 negative 또는 neutral"}
  ]
}

규칙:
- key_issues는 3-5개. 가치 있는 이슈만. 정보가 없으면 적게.
- kr_tickers는 5-8개. anchor_tickers를 우선 활용하고 추가 종목도 자유롭게 제안.
- 뉴스가 단순 잡음(가격 움직임 분석 등)이면 key_issues에 포함하지 말 것.
- 정책/관세/가이던스/CEO 발언 등은 우선순위 높게.

**문체(매우 중요)**:
- summary와 key_issues.text는 "~다"로 끝나는 평서문 금지.
- 명사형(~함, ~임, ~중, ~예정, ~확대, ~상승) 또는 단어로 끝나는 보고서식 짧은 문장 사용.
- 예시 OK:
  · "AI 데이터센터 수요로 매출 전망 상향."
  · "NVDA 실적 발표 대기 심리로 섹터 전반 약세."
  · "트럼프, 대만 반도체 산업 비난 발언. 관세 압박 시사함."
- 예시 NG:
  · "매출 전망을 상향했다." → "매출 전망 상향"
  · "약세를 보였다." → "약세"
  · "긍정적이다." → "긍정적"
- 간결하고 단정적인 톤. 불필요한 설명 없이 핵심만."""


def interpret_theme(theme, events_by_ticker, api_key, model="claude-sonnet-4-6"):
    """단일 테마에 대해 Claude 분석 요청"""
    from anthropic import Anthropic

    # 이 테마 티커의 이벤트만 추출
    theme_events = {}
    for tk in theme["us_tickers"]:
        evs = events_by_ticker.get(tk, [])
        if evs:
            theme_events[tk] = evs

    if not theme_events:
        return None

    input_blob = {
        "theme": theme["name"],
        "theme_desc": theme.get("desc", ""),
        "kr_anchor_tickers": theme.get("kr_anchor_tickers", []),
        "us_events": theme_events,
    }

    client = Anthropic(api_key=api_key)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            system=THEME_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"테마: {theme['name']}\n"
                    f"설명: {theme.get('desc', '')}\n\n"
                    f"미국 종목들의 어제 이벤트:\n"
                    f"```json\n{json.dumps(input_blob, ensure_ascii=False, indent=2)}\n```"
                ),
            }],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = "\n".join(l for l in text.split("\n") if not l.startswith("```"))
        parsed = json.loads(text)
        return parsed
    except json.JSONDecodeError as e:
        print(f"  [경고] '{theme['name']}' JSON 파싱 실패: {e}")
        return None
    except Exception as e:
        print(f"  [경고] '{theme['name']}' 해석 실패: {type(e).__name__}: {str(e)[:200]}")
        return None


# ── 메인 ────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="LLM 호출 없이 수집만")
    parser.add_argument("--themes", type=str, default="", help="처리할 테마 ID 쉼표구분 (생략시 전체)")
    args = parser.parse_args()

    now = datetime.now()
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] 미국 이벤트 수집 시작")

    # 1. 테마 로드
    themes = load_themes()
    if args.themes:
        wanted = set(args.themes.split(","))
        themes = [t for t in themes if t["id"] in wanted]
    print(f"  테마: {len(themes)}개")

    # 2. 모든 티커 수집
    all_us_tickers = []
    for t in themes:
        all_us_tickers.extend(t["us_tickers"])
    raw_events = collect_for_tickers(all_us_tickers)
    print(f"  수집 완료: {len(raw_events)} events")

    # 티커별 그룹화
    events_by_ticker = {}
    for e in raw_events:
        events_by_ticker.setdefault(e["ticker"], []).append(e)

    # 3. 테마별 LLM 분석
    theme_results = []
    if not args.dry_run:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("  [경고] ANTHROPIC_API_KEY 없음. 테마 해석 건너뜀.")
        else:
            model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
            print(f"  Claude 테마 분석 (model={model})...")
            for i, theme in enumerate(themes):
                print(f"    [{i+1}/{len(themes)}] {theme['name']}")
                analysis = interpret_theme(theme, events_by_ticker, api_key, model=model)
                if analysis:
                    analysis["id"] = theme["id"]
                    analysis["name"] = theme["name"]
                    analysis["desc"] = theme.get("desc", "")
                    analysis["us_tickers"] = theme["us_tickers"]
                    analysis["events_count"] = sum(
                        len(events_by_ticker.get(tk, [])) for tk in theme["us_tickers"]
                    )
                    theme_results.append(analysis)
                time.sleep(0.3)
            print(f"  테마 분석 완료: {len(theme_results)}/{len(themes)}")

    # 4. 안전장치: 결과가 비어있으면 기존 파일 덮어쓰지 않음 (네트워크/LLM 실패 시 데이터 파괴 방지)
    if not raw_events and not theme_results:
        print("  [경고] 수집/해석 결과 모두 비어있음 — 기존 us_events.json 유지 (덮어쓰기 안 함).")
        print("  → 네트워크 또는 API 키 문제일 가능성. 종료 코드 2.")
        sys.exit(2)
    if not theme_results and not args.dry_run:
        print(f"  [경고] 테마 분석 결과 0건 — LLM 호출 모두 실패한 것으로 보임. 기존 파일 유지.")
        print(f"  (수집된 raw events: {len(raw_events)}건)")
        sys.exit(2)

    # 5. 저장
    output = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "date": now.strftime("%Y-%m-%d"),
        "ticker_count": len(events_by_ticker),
        "event_count": len(raw_events),
        "raw_events": raw_events,
        "themes": theme_results,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"  저장 완료: {OUTPUT_PATH} (테마 {len(theme_results)}/{len(themes)}, 이벤트 {len(raw_events)})")


if __name__ == "__main__":
    main()
