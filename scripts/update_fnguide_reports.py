"""FnGuide 리서치 리포트 자동수집 — 개별 종목 리포트(요약 + EPS).

흐름: 로그인 → GetReports → 종목 리포트(CATEGORY.TYP==1) → 메타 매핑
      → PDF 본문 → Claude 요약 + EPS(캐시) → research_reports.json 병합(종목당 3개).

⚠️ 실행 위치: 사용자 Mac(평소 IP)에서 하루 1회. 클라우드/GitHub Actions 금지
   (FnGuide IP·PC 제한 + 비정상 이용 시 영구 정지 위험). 스크립트 로그인 시 브라우저 세션 로그아웃됨.

자격증명: .env FNGUIDE_ID/FNGUIDE_PW (+ 요약용 ANTHROPIC_API_KEY). 사용: python3 scripts/update_fnguide_reports.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=str(PROJECT_ROOT / ".env"), override=True)
except Exception:
    pass

import fnguide_session as fg
from update_research import merge_and_cap
from report_summarizer import _load_cache, _save_cache

KST = timezone(timedelta(hours=9))
OUTPUT_PATH = PROJECT_ROOT / "data" / "research_reports.json"

EPS_SYSTEM = """당신은 한국 상장주식 운용팀을 돕는 애널리스트입니다.
증권사 종목 리포트 '본문'을 받아 펀드매니저용 핵심 요약과 EPS 추정치를 추출하세요.

JSON으로만 응답:
{
  "tldr": "한 줄 핵심",
  "thesis": ["투자포인트 3~5개 bullet"],
  "catalysts": ["주가 촉매 1줄들"],
  "risks": ["리스크 1줄들"],
  "tp_logic": "목표주가 산정 근거",
  "earnings": "실적/추정치 변화 요약",
  "eps_fy1": 당기연도 EPS 추정(원, 숫자만; 본문에 없으면 null),
  "eps_fy2": 차기연도 EPS 추정(원, 숫자만; 없으면 null)
}
문체: '~다' 금지, 명사형 종결. 본문에 근거 없는 값은 null. EPS는 반드시 본문 표/추정치에서만."""

MAX_TEXT = 30000


def _num(v):
    try:
        return int(str(v).replace(",", "").strip())
    except (ValueError, TypeError, AttributeError):
        return None


def _anl_date(s: str) -> str:
    """'26.07.03' → '2026-07-03'."""
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{2})", s or "")
    return f"20{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else (s or "")


def _summarize(text: str, api_key: str, model: str) -> dict | None:
    try:
        from anthropic import Anthropic
        c = Anthropic(api_key=api_key, timeout=240.0, max_retries=5)
        resp = c.messages.create(
            model=model, max_tokens=1600, system=EPS_SYSTEM,
            messages=[{"role": "user", "content": f"```\n{text[:MAX_TEXT]}\n```"}])
        out = resp.content[0].text.strip()
        if out.startswith("```"):
            out = "\n".join(l for l in out.split("\n") if not l.startswith("```"))
        m = re.search(r"\{.*\}", out, re.S)   # JSON 블록만 추출(뒤 텍스트 방지)
        if m:
            out = m.group(0)
        return json.loads(out)
    except Exception as e:
        print(f"    [경고] 요약 실패: {type(e).__name__}: {str(e)[:100]}")
        return None


def main(limit: int | None = None):
    now = datetime.now(KST)
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] FnGuide 리포트 수집 시작")

    s = fg.login()
    if s is None:
        print("  [경고] FnGuide 로그인 실패 — .env FNGUIDE_ID/PW 확인. exit 2")
        sys.exit(2)

    # 워치리스트 로드 (data/fnguide_watchlist.txt — 종목코드 한 줄에 하나)
    wl_path = PROJECT_ROOT / "data" / "fnguide_watchlist.txt"
    codes = []
    if wl_path.exists():
        for line in wl_path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*(\d{6})\s*$", line)
            if m:
                codes.append(m.group(1))
    # 중복 제거(순서 유지)
    codes = list(dict.fromkeys(codes))
    if limit:
        codes = codes[:limit]
    print(f"  워치리스트: {len(codes)}개 종목 → 종목별 최신 3개")
    if not codes:
        print("  [경고] 워치리스트 비어있음(data/fnguide_watchlist.txt) — 기존 파일 유지. exit 2")
        sys.exit(2)

    prev = {}
    if OUTPUT_PATH.exists():
        try:
            prev = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        except Exception:
            prev = {}

    cache = _load_cache()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    new_records = []
    n_sum = 0
    for ci, code in enumerate(codes, 1):
        for r in fg.fetch_stock_reports(s, code, per_page=3):   # 종목별 최신 3개
            cat = r.get("CATEGORY") or {}
            rid = str(r.get("RPT_ID") or "")
            rec = {
                "date": _anl_date(r.get("ANL_DT")),
                "code": code, "name": cat.get("NAME") or "",
                "title": re.sub(r"\s+", " ", r.get("RPT_TITLE") or "")[:120],
                "tp": _num(r.get("TARGET_PRICE")),
                "opinion": r.get("RECOMM") or "",
                "broker": (r.get("BROKERAGE") or {}).get("NAME", ""),
                "analyst": ",".join(a.get("NAME", "") for a in (r.get("ANALYSTS") or [])),
                "report_id": rid, "source": "fnguide",
            }
            # 요약 + EPS: 신규(미캐시)만 → report_summaries.json (클릭 시 캐시 히트로 즉시 표시)
            if api_key and rid and rid not in cache:
                txt = fg.get_report_pdf_text(s, rid)
                if txt:
                    summ = _summarize(txt, api_key, model)
                    if summ:
                        summ["report_id"] = rid
                        summ["summarized_at"] = now.strftime("%Y-%m-%d %H:%M")
                        cache[rid] = summ
                        _save_cache(cache)
                        n_sum += 1
            new_records.append(rec)
        if ci % 10 == 0:
            print(f"    ... {ci}/{len(codes)}종목 (수집 {len(new_records)}건, 신규요약 {n_sum})")
        time.sleep(0.6)   # 조회 간 딜레이(버스트 회피 — 계정 리스크↓)

    print(f"  종목 리포트 {len(new_records)}건 수집 · 신규 요약 {n_sum}건")

    stored = merge_and_cap(prev.get("reports", []), new_records)

    # 한경 리포트도 사전 요약(원문 링크 있음, 미캐시) → 배포 앱이 Claude 없이 캐시로 표시.
    # (요약은 Claude 키 있는 여기서 미리 계산 → report_summaries.json 커밋)
    if api_key:
        from report_summarizer import get_report_summary
        cache = _load_cache()  # fnguide 요약 반영분 다시 로드
        n_pre = 0
        for rec in stored:
            rid = str(rec.get("report_id") or "")
            if rid and rid not in cache and rec.get("pdf_url") and rec.get("source") != "fnguide":
                if get_report_summary(rid, rec["pdf_url"]):
                    n_pre += 1
        if n_pre:
            print(f"  한경 리포트 사전요약: {n_pre}건 추가")

    _dates = [x.get("date") for x in stored if x.get("date")]
    out = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "date": max(_dates) if _dates else now.strftime("%Y-%m-%d"),
        "count": len(stored),
        "reports": stored,
        "brief": prev.get("brief"),
        "tp_history": prev.get("tp_history", {}),
    }
    OUTPUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    n_codes = len({x.get("code") for x in stored})
    print(f"  저장: {OUTPUT_PATH} (스토어 {len(stored)}건 · 종목 {n_codes}개 · 신규 {len(new_records)}건)")


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(limit=lim)
