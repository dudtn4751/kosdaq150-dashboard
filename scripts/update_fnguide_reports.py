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

    reports = fg.fetch_reports(s)
    company = [r for r in reports if (r.get("CATEGORY") or {}).get("TYP") == 1]
    if limit:
        company = company[:limit]
    print(f"  수집: 전체 {len(reports)}건 중 종목 리포트 {len(company)}건")
    if not company:
        print("  [경고] 종목 리포트 0건 — 기존 파일 유지. exit 2")
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
    for r in company:
        cat = r["CATEGORY"]
        rid = str(r["RPT_ID"])
        code = str(cat.get("VALUE") or "").zfill(6)
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
        # 요약 + EPS (report_id 캐시 → Claude 재호출 금지)
        if api_key and rid not in cache:
            txt = fg.get_report_pdf_text(s, rid)
            print(f"    {code} {rec['name']:<10} PDF {len(txt)}자", end="")
            if txt:
                summ = _summarize(txt, api_key, model)
                if summ:
                    summ["report_id"] = rid
                    summ["summarized_at"] = now.strftime("%Y-%m-%d %H:%M")
                    cache[rid] = summ
                    _save_cache(cache)
                    print(" → 요약+EPS 완료" + (f" (EPS FY1={summ.get('eps_fy1')})" if summ.get("eps_fy1") else ""))
                else:
                    print(" → 요약 실패")
            else:
                print(" → 본문 추출 불가")
        new_records.append(rec)

    stored = merge_and_cap(prev.get("reports", []), new_records)
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
