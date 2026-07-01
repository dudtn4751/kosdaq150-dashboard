"""증권사 리포트 PDF 요약기 (프로젝트 2 보조).

get_report_summary(report_id, pdf_url) -> dict | None
    - data/report_summaries.json 캐시에 report_id 있으면 그대로 반환(Claude 재호출 금지).
    - 없으면: pdf_url 다운로드(한경과 동일 UA/Referer) → pdfplumber 본문 추출.
      스캔 이미지 PDF(텍스트 비어있음)면 'OCR 필요'로 graceful 처리(예외 X).
    - 본문을 Claude로 요약(.env ANTHROPIC_API_KEY/ANTHROPIC_MODEL 재사용).
    - 결과를 캐시에 저장 후 반환. 다운로드/요약 실패 시 None.

사용: from scripts.report_summarizer import get_report_summary
"""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

KST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).parent.parent
CACHE_PATH = PROJECT_ROOT / "data" / "report_summaries.json"

# 한경 컨센서스와 동일 헤더 (update_research.py._get 참고)
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://consensus.hankyung.com/"}
PDF_TIMEOUT = 25
MAX_TEXT_CHARS = 30000          # Claude 입력 본문 상한 (리포트는 보통 수 페이지)

SUMMARY_SYSTEM = """당신은 한국 상장주식 운용팀을 돕는 애널리스트입니다.
국내 증권사 기업 리포트 '본문'을 받아 펀드매니저용 핵심 요약을 작성하세요.

JSON으로만 응답:
{
  "tldr": "한 줄 핵심",
  "thesis": ["투자포인트 3~5개 bullet"],
  "catalysts": ["주가 촉매 1줄들"],
  "risks": ["리스크 1줄들"],
  "tp_logic": "목표주가 산정 근거",
  "earnings": "실적/추정치 변화 요약"
}
문체: '~다' 금지, 명사형 종결(~확대, ~전망, ~목표가 OOO원). 간결하게. 본문에 근거 없는 추측 금지."""


# ── 캐시 ──────────────────────────────────────────────────────────────────────
def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


# ── PDF 다운로드 + 텍스트 추출 ───────────────────────────────────────────────────
def _download_pdf(pdf_url: str) -> bytes | None:
    try:
        req = urllib.request.Request(pdf_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=PDF_TIMEOUT) as resp:
            data = resp.read()
        if not data or data[:4] != b"%PDF":
            print(f"  [경고] PDF 아님(매직바이트 {data[:4]!r}) → None")
            return None
        return data
    except Exception as e:
        print(f"  [경고] PDF 다운로드 실패: {type(e).__name__}: {str(e)[:100]}")
        return None


def _extract_text(pdf_bytes: bytes) -> str:
    """pdfplumber로 전 페이지 텍스트 추출. 스캔 PDF면 빈 문자열."""
    import pdfplumber
    parts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            if t.strip():
                parts.append(t)
    return "\n".join(parts).strip()


def _ocr_needed_summary(report_id: str) -> dict:
    """스캔 이미지 PDF — 텍스트 추출 불가 시 graceful 결과(스키마 유지)."""
    return {
        "report_id": report_id,
        "tldr": "본문 텍스트 추출 불가(스캔 이미지 PDF) — OCR 필요",
        "thesis": [], "catalysts": [], "risks": [],
        "tp_logic": "", "earnings": "",
        "status": "ocr_needed",
        "summarized_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
    }


# ── Claude 요약 (update_research.synthesize_brief 패턴) ──────────────────────────
def _summarize_with_claude(text: str) -> dict | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  [경고] ANTHROPIC_API_KEY 없음 → 요약 불가(None)")
        return None
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key, timeout=240.0, max_retries=5)
        resp = client.messages.create(
            model=model, max_tokens=1500, system=SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": f"```\n{text[:MAX_TEXT_CHARS]}\n```"}],
        )
        out = resp.content[0].text.strip()
        if out.startswith("```"):
            out = "\n".join(l for l in out.split("\n") if not l.startswith("```"))
        return json.loads(out)
    except Exception as e:
        print(f"  [경고] Claude 요약 실패: {type(e).__name__}: {str(e)[:120]}")
        return None


# ── 퍼블릭 API ────────────────────────────────────────────────────────────────
def get_report_summary(report_id, pdf_url) -> dict | None:
    """report_id 캐시 우선. 없으면 PDF 다운로드→추출→Claude 요약→캐시 저장. 실패 시 None."""
    if not report_id or not pdf_url:
        return None
    rid = str(report_id)

    cache = _load_cache()
    if rid in cache:
        return cache[rid]                       # 캐시 히트 — Claude 재호출 금지

    pdf_bytes = _download_pdf(pdf_url)
    if pdf_bytes is None:
        return None

    try:
        text = _extract_text(pdf_bytes)
    except Exception as e:
        print(f"  [경고] 텍스트 추출 실패: {type(e).__name__}: {str(e)[:100]}")
        return None

    if not text:                                # 스캔 이미지 PDF → graceful
        result = _ocr_needed_summary(rid)
        cache[rid] = result
        _save_cache(cache)
        return result

    summary = _summarize_with_claude(text)
    if summary is None:
        return None                             # 요약 실패는 캐시하지 않음(재시도 여지)

    summary["report_id"] = rid
    summary.setdefault("status", "ok")
    summary["summarized_at"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    cache[rid] = summary
    _save_cache(cache)
    return summary


if __name__ == "__main__":
    # 단독 테스트: 인자로 report_id pdf_url, 없으면 한경 목록 첫 리포트 사용
    if len(sys.argv) >= 3:
        rid, url = sys.argv[1], sys.argv[2]
    else:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        import update_research as ur
        ur.MAX_PAGES = 1
        recs = [r for r in ur.fetch_reports() if r.get("pdf_url")]
        if not recs:
            print("샘플 리포트를 찾지 못함"); raise SystemExit(1)
        rid, url = recs[0]["report_id"], recs[0]["pdf_url"]
        print(f"샘플: {recs[0]['name']} ({recs[0]['code']})  id={rid}")
    import pprint
    pprint.pprint(get_report_summary(rid, url))
