"""
미국 이벤트 수집 + 대주제(group)별 Claude 심층 해석
매일 미장 마감 후 (07:00 KST 권장) 실행

흐름:
1. data/themes.json에서 정의된 테마(세부) + group(대주제) + 미국 티커 로드
2. yfinance에서 각 티커의 어제~오늘 가격/어닝/뉴스 수집
3. 대주제별로 묶어서 Claude API에 분석 요청
   — 핵심 이슈 3-5개(트리거·확산성·지속성 태그 포함), 영향 KR 종목
4. data/us_events.json에 raw_events + groups로 저장

사용:
    python3 scripts/update_us_events.py              # 기본 (수집 + 분석)
    python3 scripts/update_us_events.py --dry-run    # 수집만 (LLM 없음)
    python3 scripts/update_us_events.py --reanalyze   # 재수집 없이 기존 raw_events로 LLM만 재실행 (프롬프트 반복/테스트용)
    python3 scripts/update_us_events.py --groups tech_semi,industrial  # 일부 대주제만
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


def load_themes_file():
    with open(THEMES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_groups(themes_data, wanted_group_ids=None):
    """대주제(group) 단위로 테마/티커/앵커를 집계."""
    group_defs = {g["id"]: g for g in themes_data.get("groups", [])}
    themes = themes_data["themes"]

    groups = {}
    for th in themes:
        gid = th.get("group", th["id"])  # group 미지정 시 테마 자체를 그룹으로
        if wanted_group_ids and gid not in wanted_group_ids:
            continue
        gdef = group_defs.get(gid, {"id": gid, "name": gid, "desc": "", "order": 99})
        g = groups.setdefault(gid, {
            "id": gid,
            "name": gdef.get("name", gid),
            "desc": gdef.get("desc", ""),
            "order": gdef.get("order", 99),
            "sub_themes": [],     # [{id, name}]
            "us_tickers": [],
            "kr_anchor_tickers": [],
        })
        g["sub_themes"].append({"id": th["id"], "name": th["name"]})
        for tk in th.get("us_tickers", []):
            if tk not in g["us_tickers"]:
                g["us_tickers"].append(tk)
        seen_codes = {a["code"] for a in g["kr_anchor_tickers"]}
        for a in th.get("kr_anchor_tickers", []):
            if a["code"] not in seen_codes:
                g["kr_anchor_tickers"].append(a)
                seen_codes.add(a["code"])

    return sorted(groups.values(), key=lambda g: g["order"])


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


# ── 대주제별 Claude 분석 ────────────────────────────
GROUP_SYSTEM = """당신은 한국 주식 투자자를 위한 미국 시장 분석가입니다.
주어진 '대주제'(예: 테크·반도체, 산업재·방산·전력)에 속한 미국 종목들의 어제 이벤트(가격, 어닝, 뉴스 헤드라인)를 종합 분석하세요.
한 대주제에는 여러 하위 산업이 묶여 있습니다. 산재한 개별 뉴스를 나열하지 말고, "이 대주제에서 어제 무슨 일이 있었나"를 통합된 시각으로 정리하세요.

다음 JSON 스키마로만 응답합니다. 다른 텍스트 금지.

{
  "summary": "이 대주제의 어제 핵심 흐름 2-3문장. 가장 중요한 동인 중심으로 통합.",
  "key_issues": [
    {
      "text": "구체적 이슈. 단순 가격 변동보다 CEO 코멘트·가이던스·정책·관세·어닝 서프라이즈·계약/M&A 등 의미있는 정보 우선.",
      "source_tickers": ["관련 미국 티커"],
      "trigger": "어닝 | 가이던스 | 정책·규제 | 관세 | CEO·임원발언 | 신제품·계약 | M&A | 매크로지표 | 수급·가격 | 기타",
      "spread": "종목한정 | 섹터전반 | 대주제확산",
      "persistence": "구조적 | 지속관찰 | 일회성"
    }
  ],
  "sentiment": "positive 또는 negative 또는 mixed 또는 neutral",
  "impact_strength": "high 또는 medium 또는 low",
  "affected_kr_sectors": ["네이버 업종명 또는 일반 업종명, 최대 5개"],
  "kr_tickers": [
    {"code": "6자리 종목코드", "name": "한국 종목명", "direction": "positive 또는 negative 또는 neutral"}
  ]
}

분석 깊이(필수 — 각 key_issue마다 반드시 채울 것):
- trigger: 이슈를 촉발한 근본 원인 1개를 위 분류에서 선택.
- spread(확산성): 영향이 번질 범위. "종목한정"=해당 기업만, "섹터전반"=같은 업종 전반, "대주제확산"=다른 산업/대주제까지 파급될 사안.
- persistence(지속성): "구조적"=수개월 이상 지속될 추세 전환/구조 변화, "지속관찰"=며칠~수주 영향, "일회성"=하루성 노이즈.
- 진짜 중요한 이슈(구조적 또는 대주제확산)는 key_issues 앞쪽에 배치.

규칙:
- key_issues는 3-5개. 가치 있는 이슈만. 정보가 없으면 적게.
- kr_tickers는 5-8개. anchor_tickers를 우선 활용하고 추가 종목도 자유롭게 제안. 코드(6자리)와 종목명을 정확히 일치시킬 것.
- 뉴스가 단순 잡음(가격 움직임 분석 등)이면 key_issues에 넣지 말거나 persistence를 "일회성"으로 명시.
- 정책/관세/가이던스/CEO 발언 등은 우선순위 높게.
- 매크로·지수 대주제는 개별 기업이 아니라 지수·금리·달러·변동성의 방향과 시장 위험선호(risk-on/off)를 해석하고, kr_tickers는 KODEX 200/코스닥150 같은 지수 ETF나 시장 전체 방향을 대표하는 종목으로.

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
- 간결하고 단정적인 톤. 불필요한 설명 없이 핵심만."""

# ── 오늘의 논점 (시장 전체 종합 브리핑) ──────────────
BRIEF_SYSTEM = """당신은 한국 상장주식 운용팀(펀드매니저)의 모닝미팅을 돕는 시장 전략가입니다.
8개 대주제의 어제 미국 시장 분석 결과를 종합해, 펀드매니저들이 오늘 아침 미팅에서 함께 짚을 '오늘의 논점'을 작성하세요.

다음 JSON 스키마로만 응답합니다. 다른 텍스트 금지.

{
  "market_read": "오늘 시장을 보는 한 줄 총평. 간밤 미국 흐름과 위험선호 방향, 한국 시장 시사점을 압축.",
  "risk_sentiment": "risk_on 또는 risk_off 또는 neutral 또는 mixed",
  "talking_points": [
    {
      "title": "논점 제목 (짧고 단정적으로)",
      "detail": "1-2문장. 무슨 일이고 왜 중요한지 + 한국 시장/운용 관점의 의미.",
      "groups": ["관련 대주제명, 최대 3개"],
      "watch": "오늘 장중 확인할 포인트 또는 대응 관점 한 줄"
    }
  ]
}

규칙:
- talking_points는 3-5개. 구조적이거나 여러 대주제로 확산되는 이슈, 한국 시장 영향이 큰 것을 우선.
- 매크로(금리·환율·고용·정책)와 섹터 구조 변화에 집중. 단순 하루치 가격 노이즈는 제외.
- 한국 상장주식 운용 관점에서 "오늘 무엇을 보고 무엇을 조심할지"가 드러나게.
- 서로 다른 대주제를 잇는 연결고리(예: 금리상승→성장주 부담→반도체·플랫폼 동시 압박)가 있으면 우선 부각.

문체(매우 중요):
- "~다" 평서문 금지. 명사형(~함, ~임, ~예상, ~부담, ~주목) 종결의 보고서체.
- 간결하고 단정적으로. 핵심만."""


def synthesize_brief(group_results, api_key, model="claude-sonnet-4-6"):
    """8개 대주제 결과를 종합해 '오늘의 논점' 생성."""
    from anthropic import Anthropic

    if not group_results:
        return None

    # 대주제 결과를 압축 (토큰 절약)
    compact = []
    for g in group_results:
        compact.append({
            "대주제": g.get("name"),
            "sentiment": g.get("sentiment"),
            "impact": g.get("impact_strength"),
            "summary": g.get("summary"),
            "key_issues": [
                {"text": i.get("text"), "trigger": i.get("trigger"),
                 "spread": i.get("spread"), "persistence": i.get("persistence")}
                for i in g.get("key_issues", [])
            ],
        })

    client = Anthropic(api_key=api_key, timeout=240.0, max_retries=5)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            system=BRIEF_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    "어제 미국 시장 8개 대주제 분석 결과입니다. 이를 종합해 오늘의 논점을 작성하세요.\n\n"
                    f"```json\n{json.dumps(compact, ensure_ascii=False, indent=2)}\n```"
                ),
            }],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = "\n".join(l for l in text.split("\n") if not l.startswith("```"))
        return json.loads(text)
    except Exception as e:
        print(f"  [경고] 오늘의 논점 생성 실패: {type(e).__name__}: {str(e)[:200]}")
        return None


VALID_TRIGGER = {"어닝", "가이던스", "정책·규제", "관세", "CEO·임원발언", "신제품·계약", "M&A", "매크로지표", "수급·가격", "기타"}
VALID_SPREAD = {"종목한정", "섹터전반", "대주제확산"}
VALID_PERSISTENCE = {"구조적", "지속관찰", "일회성"}


def _normalize_issue(issue):
    """LLM이 살짝 다르게 쓴 분류 라벨을 보정."""
    issue.setdefault("source_tickers", [])
    t = (issue.get("trigger") or "기타").strip()
    s = (issue.get("spread") or "섹터전반").strip()
    p = (issue.get("persistence") or "지속관찰").strip()
    issue["trigger"] = t if t in VALID_TRIGGER else "기타"
    issue["spread"] = s if s in VALID_SPREAD else "섹터전반"
    issue["persistence"] = p if p in VALID_PERSISTENCE else "지속관찰"
    return issue


def interpret_group(group, events_by_ticker, api_key, model="claude-sonnet-4-6"):
    """단일 대주제에 대해 Claude 분석 요청"""
    from anthropic import Anthropic

    # 이 대주제 티커의 이벤트만 추출
    group_events = {}
    for tk in group["us_tickers"]:
        evs = events_by_ticker.get(tk, [])
        if evs:
            group_events[tk] = evs

    if not group_events:
        return None

    input_blob = {
        "group": group["name"],
        "group_desc": group.get("desc", ""),
        "sub_themes": [s["name"] for s in group.get("sub_themes", [])],
        "kr_anchor_tickers": group.get("kr_anchor_tickers", []),
        "us_events": group_events,
    }

    client = Anthropic(api_key=api_key, timeout=240.0, max_retries=5)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=3072,
            system=GROUP_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"대주제: {group['name']}\n"
                    f"설명: {group.get('desc', '')}\n"
                    f"포함 산업: {', '.join(s['name'] for s in group.get('sub_themes', []))}\n\n"
                    f"미국 종목들의 어제 이벤트:\n"
                    f"```json\n{json.dumps(input_blob, ensure_ascii=False, indent=2)}\n```"
                ),
            }],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = "\n".join(l for l in text.split("\n") if not l.startswith("```"))
        parsed = json.loads(text)
        parsed["key_issues"] = [_normalize_issue(i) for i in parsed.get("key_issues", [])]
        return parsed
    except json.JSONDecodeError as e:
        print(f"  [경고] '{group['name']}' JSON 파싱 실패: {e}")
        return None
    except Exception as e:
        print(f"  [경고] '{group['name']}' 해석 실패: {type(e).__name__}: {str(e)[:200]}")
        return None


# ── 메인 ────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="LLM 호출 없이 수집만")
    parser.add_argument("--reanalyze", action="store_true",
                        help="yfinance 재수집 없이 기존 us_events.json의 raw_events로 LLM만 재실행")
    parser.add_argument("--groups", type=str, default="", help="처리할 대주제 group ID 쉼표구분 (생략시 전체)")
    args = parser.parse_args()

    now = datetime.now(timezone(timedelta(hours=9)))  # KST (러너 UTC여도 일관)
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] 미국 이벤트 {'재분석' if args.reanalyze else '수집'} 시작")

    # 1. 대주제 로드
    themes_data = load_themes_file()
    wanted = set(args.groups.split(",")) if args.groups else None
    groups = build_groups(themes_data, wanted)
    print(f"  대주제: {len(groups)}개")

    # 2. 이벤트 수집 (또는 캐시 재사용)
    if args.reanalyze:
        if not OUTPUT_PATH.exists():
            print("  [오류] --reanalyze 인데 기존 us_events.json 없음. 먼저 일반 실행 필요.")
            sys.exit(1)
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            prev = json.load(f)
        raw_events = prev.get("raw_events", [])
        print(f"  기존 raw_events 재사용: {len(raw_events)}건 (수집 생략)")
    else:
        all_us_tickers = []
        for g in groups:
            all_us_tickers.extend(g["us_tickers"])
        raw_events = collect_for_tickers(all_us_tickers)
        print(f"  수집 완료: {len(raw_events)} events")

    # 티커별 그룹화
    events_by_ticker = {}
    for e in raw_events:
        events_by_ticker.setdefault(e["ticker"], []).append(e)

    # 3. 대주제별 LLM 분석
    group_results = []
    if not args.dry_run:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("  [경고] ANTHROPIC_API_KEY 없음. 대주제 해석 건너뜀.")
        else:
            model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
            print(f"  Claude 대주제 분석 (model={model})...")
            for i, group in enumerate(groups):
                print(f"    [{i+1}/{len(groups)}] {group['name']}")
                analysis = interpret_group(group, events_by_ticker, api_key, model=model)
                if analysis:
                    analysis["id"] = group["id"]
                    analysis["name"] = group["name"]
                    analysis["desc"] = group.get("desc", "")
                    analysis["sub_themes"] = group.get("sub_themes", [])
                    analysis["us_tickers"] = group["us_tickers"]
                    analysis["events_count"] = sum(
                        len(events_by_ticker.get(tk, [])) for tk in group["us_tickers"]
                    )
                    group_results.append(analysis)
                time.sleep(0.3)
            print(f"  대주제 분석 완료: {len(group_results)}/{len(groups)}")

            # 중요 섹터(반도체·에너지·소프트웨어)는 특이 이슈가 없어도 항상 카드 보장
            ALWAYS_ON = {"tech_semi", "energy_materials", "software_platform"}
            analyzed_ids = {a.get("id") for a in group_results}
            for group in groups:
                if group["id"] in ALWAYS_ON and group["id"] not in analyzed_ids:
                    group_results.append({
                        "id": group["id"], "name": group["name"], "desc": group.get("desc", ""),
                        "sub_themes": group.get("sub_themes", []), "us_tickers": group["us_tickers"],
                        "summary": "어제 해당 섹터에서 특이 이슈 없음.",
                        "key_issues": [], "sentiment": "neutral", "impact_strength": "low",
                        "affected_kr_sectors": [], "kr_tickers": [],
                        "events_count": sum(len(events_by_ticker.get(tk, [])) for tk in group["us_tickers"]),
                    })
                    print(f"    [보강] 중요 섹터 카드 추가: {group['name']}")

    # 3-b. 오늘의 논점 (시장 전체 종합)
    brief = None
    if not args.dry_run and group_results:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
            print("  오늘의 논점 종합 생성...")
            brief = synthesize_brief(group_results, api_key, model=model)
            if brief:
                print(f"    논점 {len(brief.get('talking_points', []))}개 / 위험선호={brief.get('risk_sentiment')}")

    # 4. 안전장치: 결과가 비어있으면 기존 파일 덮어쓰지 않음 (네트워크/LLM 실패 시 데이터 파괴 방지)
    if not raw_events and not group_results:
        print("  [경고] 수집/해석 결과 모두 비어있음 — 기존 us_events.json 유지 (덮어쓰기 안 함).")
        print("  → 네트워크 또는 API 키 문제일 가능성. 종료 코드 2.")
        sys.exit(2)
    if not group_results and not args.dry_run:
        print(f"  [경고] 대주제 분석 결과 0건 — LLM 호출 모두 실패한 것으로 보임. 기존 파일 유지.")
        print(f"  (수집된 raw events: {len(raw_events)}건)")
        sys.exit(2)

    # 5. 저장
    output = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "date": now.strftime("%Y-%m-%d"),
        "schema": "groups_v2",
        "ticker_count": len(events_by_ticker),
        "event_count": len(raw_events),
        "raw_events": raw_events,
        "groups": group_results,
        "brief": brief,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"  저장 완료: {OUTPUT_PATH} (대주제 {len(group_results)}/{len(groups)}, 이벤트 {len(raw_events)})")


if __name__ == "__main__":
    main()
