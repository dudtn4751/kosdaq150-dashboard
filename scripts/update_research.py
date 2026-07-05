"""국내 증권사 리포트 요약 + 목표주가(TP) 상/하향 정리 (프로젝트 2).

소스: 한경 컨센서스(consensus.hankyung.com) 기업 리포트 목록 — 종목·증권사·적정가격(TP)·투자의견.
매일 스냅샷을 쌓아 종목별 직전 TP 대비 상향/하향을 판정하고, Claude로 아침 브리핑을 생성.

출력: data/research_reports.json
사용: python3 scripts/update_research.py
"""

import json
import os
import re
import sys
import time
import urllib.request
import warnings
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
from bs4 import BeautifulSoup

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

warnings.filterwarnings("ignore")

KST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_PATH = PROJECT_ROOT / "data" / "research_reports.json"
BASE = "https://consensus.hankyung.com/analysis/list"
HOST = "https://consensus.hankyung.com"          # PDF 원문: {HOST}/analysis/downpdf?report_idx=ID
MAX_PAGES = 12          # 실제 사이트 페이지네이션 (샌드박스는 1쪽만 반환)
PER_CODE_KEEP = 3       # 종목당 유지할 최신 리포트 개수


def _get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Referer": "https://consensus.hankyung.com/"})
    return urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore")


def _num(v):
    try:
        return int(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _clean_repeat(t):
    """한경 제목의 반복 붕괴. 'A A B' / 'A A' → 'A' (read_html이 셀 중복 텍스트를 이어붙임)."""
    t = re.sub(r"\s+", " ", str(t or "")).strip()
    words = t.split(" ")
    n = len(words)
    for size in range(2, n // 2 + 1):        # 단어 2개 이상 단위의 반복
        unit = words[:size]
        reps = n // size
        if reps >= 2 and words[:size * reps] == unit * reps:
            return " ".join(unit)
    return t


def _extract_report_idxs(html):
    """리포트 목록 테이블의 각 행에서 report_idx를 '행 순서대로' 추출.
    pd.read_html이 버리는 <a href="/analysis/downpdf?report_idx=..."> 링크를 직접 파싱.
    행 수와 동일한 길이의 리스트를 반환(정렬 주입용). 실패 시 [].
    """
    soup = BeautifulSoup(html, "html.parser")
    for tb in soup.find_all("table"):
        txt = tb.get_text()
        if "제목" in txt and "작성일" in txt and "report_idx" in str(tb):
            idxs = []
            for tr in tb.find_all("tr"):
                m = re.search(r"report_idx=(\d+)", str(tr))
                if m:                       # 헤더행 등 링크 없는 tr은 제외
                    idxs.append(m.group(1))
            return idxs
    return []


def fetch_reports(skin="business"):
    """한경 컨센서스 기업 리포트 수집 → 레코드 리스트."""
    out, seen = [], set()
    for pg in range(1, MAX_PAGES + 1):
        url = f"{BASE}?skinType={skin}&now_page={pg}"
        try:
            html = _get(url)
            dfs = pd.read_html(StringIO(html))
        except Exception as e:
            print(f"  [경고] page {pg} 수집 실패: {type(e).__name__}")
            break
        cand = [t for t in dfs if "제목" in t.columns and "작성일" in t.columns]
        if not cand:
            break
        df = cand[0].reset_index(drop=True)
        # read_html이 버린 PDF 링크(report_idx)를 행 순서대로 정렬 주입
        idxs = _extract_report_idxs(html)
        if len(idxs) == len(df):
            df["__rid"] = idxs
        else:                               # 정렬 보장 안 되면 URL 생략(오결합 방지)
            df["__rid"] = [None] * len(df)
            print(f"  [경고] page {pg}: report_idx {len(idxs)}건 ≠ 행 {len(df)}건 → URL 생략")
        df = df.dropna(subset=["제목"])
        if df.empty:
            break
        added = 0
        for _, r in df.iterrows():
            title = str(r.get("제목", "")).strip()
            m = re.search(r"([가-힣A-Za-z0-9&.\s]+?)\((\d{6})\)", title)
            if not m:
                continue
            name, code = m.group(1).strip(), m.group(2)
            date = str(r.get("작성일", "")).strip()[:10]
            key = (code, date, title[:30])
            if key in seen:
                continue
            seen.add(key)
            rid = r.get("__rid")
            rid = str(rid) if (rid is not None and pd.notna(rid)) else None
            out.append({
                "date": date, "code": code, "name": name,
                "title": _clean_repeat(title)[:120],
                "tp": _num(r.get("적정가격")),
                "opinion": str(r.get("투자의견", "")).strip(),
                "broker": str(r.get("제공출처", "")).strip(),
                "analyst": str(r.get("작성자", "")).strip(),
                "report_id": rid,
                "pdf_url": f"{HOST}/analysis/downpdf?report_idx={rid}" if rid else None,
            })
            added += 1
        if added == 0:
            break
        time.sleep(0.3)
    return out


def compute_tp_changes(reports, prev):
    """직전 스냅샷의 종목별 마지막 TP와 비교해 상/하향 판정. tp_history 갱신."""
    hist = dict((prev or {}).get("tp_history", {}))  # {code: last_tp}
    # 오래된→최신 순으로 처리해 같은 종목 연속 리포트도 반영
    for rep in sorted(reports, key=lambda x: x["date"]):
        tp, code = rep.get("tp"), rep["code"]
        prev_tp = hist.get(code)
        if tp and prev_tp and tp != prev_tp:
            rep["tp_prev"] = prev_tp
            rep["tp_change_pct"] = round((tp - prev_tp) / prev_tp * 100, 1)
            rep["direction"] = "up" if tp > prev_tp else "down"
        else:
            rep["tp_prev"] = prev_tp
            rep["tp_change_pct"] = None
            rep["direction"] = "new" if (tp and not prev_tp) else "flat"
        if tp:
            hist[code] = tp
    return hist


def merge_and_cap(prev_reports, new_reports, per_code_keep=PER_CODE_KEEP):
    """prev + new 병합 → 중복제거 → 종목당 최신 per_code_keep개만 유지.

    - 중복 키: 내용(code·date·증권사·제목) 기준 — 한경/fnguide 교차소스 같은 리포트도 병합.
    - 같은 키면 new_reports가 우선(fnguide=원문/요약 접근 가능한 쪽을 남김).
    - code별 그룹 → date 내림차순 → 상위 N개. 최종은 전역 date 내림차순.
    """
    def _key(r):
        code, date = r.get("code"), r.get("date")
        broker = (r.get("broker") or "").strip()
        title = _clean_repeat(r.get("title") or "")        # 반복 붕괴(기존 3중 데이터 포함)
        title = re.sub(r"^[^()]*\(\d{6}\)\s*", "", title)   # 한경 '종목명(코드)' 접두 제거
        title = re.sub(r"\s+", "", title)[:20]
        if code and date and broker:          # 내용키(교차소스 중복 방지)
            return (code, date, broker, title)
        return r.get("report_id") or (code, date, r.get("title"))

    merged = {}
    for r in prev_reports:          # 과거 스토어 먼저
        merged[_key(r)] = r
    for r in new_reports:           # 신규가 덮어씀
        merged[_key(r)] = r

    by_code = {}
    for r in merged.values():
        by_code.setdefault(r.get("code"), []).append(r)

    stored = []
    for lst in by_code.values():
        lst.sort(key=lambda r: (r.get("date") or ""), reverse=True)
        stored.extend(lst[:per_code_keep])
    stored.sort(key=lambda r: (r.get("date") or ""), reverse=True)
    return stored


BRIEF_SYSTEM = """당신은 한국 상장주식 운용팀의 모닝미팅을 돕는 애널리스트입니다.
오늘 발표된 국내 증권사 기업 리포트 목록(종목/증권사/목표주가/투자의견/직전 대비 변화)을 받아
펀드매니저가 아침에 빠르게 훑을 '리포트 브리핑'을 작성하세요.

JSON으로만 응답:
{
  "headline": "오늘 리포트 흐름 한 줄 요약",
  "tp_up": ["목표주가 상향 종목 핵심 1줄, 최대 6개"],
  "tp_down": ["목표주가 하향 종목 핵심 1줄, 최대 6개"],
  "notable": ["그 외 주목할 리포트/논점 1줄, 최대 5개"]
}
문체: '~다' 금지, 명사형 종결(~상향, ~목표가 OOO원, ~의견 유지). 간결하게."""


def synthesize_brief(reports, api_key, model):
    from anthropic import Anthropic
    ups = [r for r in reports if r.get("direction") == "up"]
    downs = [r for r in reports if r.get("direction") == "down"]
    compact = {
        "tp_up": [{"name": r["name"], "broker": r["broker"], "tp": r["tp"],
                   "prev": r.get("tp_prev"), "chg%": r.get("tp_change_pct"), "title": r["title"]} for r in ups[:15]],
        "tp_down": [{"name": r["name"], "broker": r["broker"], "tp": r["tp"],
                     "prev": r.get("tp_prev"), "chg%": r.get("tp_change_pct"), "title": r["title"]} for r in downs[:15]],
        "all": [{"name": r["name"], "broker": r["broker"], "opinion": r["opinion"], "title": r["title"]} for r in reports[:40]],
    }
    try:
        client = Anthropic(api_key=api_key, timeout=240.0, max_retries=5)
        resp = client.messages.create(
            model=model, max_tokens=1500, system=BRIEF_SYSTEM,
            messages=[{"role": "user", "content": f"```json\n{json.dumps(compact, ensure_ascii=False)}\n```"}])
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = "\n".join(l for l in text.split("\n") if not l.startswith("```"))
        return json.loads(text)
    except Exception as e:
        print(f"  [경고] 리포트 브리핑 생성 실패: {type(e).__name__}: {str(e)[:120]}")
        return None


def main():
    now = datetime.now(KST)
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] 증권사 리포트 수집 시작")
    prev = {}
    if OUTPUT_PATH.exists():
        try:
            prev = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        except Exception:
            prev = {}

    new_reports = fetch_reports("business")     # 오늘 신규 수집분
    print(f"  수집(신규): {len(new_reports)}건")

    # 안전장치: 수집 0건이면 기존 파일 유지 (사이트 장애/차단 시 데이터 파괴 방지)
    if not new_reports:
        print("  [경고] 리포트 0건 — 기존 research_reports.json 유지(덮어쓰기 안 함). exit 2")
        sys.exit(2)

    # TP 방향(up/down)·tp_history 갱신 = 오늘 신규분 기준(직전 TP 대비). new_reports를 in-place 보강.
    tp_history = compute_tp_changes(new_reports, prev)

    # 스토어 = 과거 스토어 + 신규 병합 → 중복제거 → 종목당 최신 PER_CODE_KEEP개
    stored_reports = merge_and_cap(prev.get("reports", []), new_reports)

    # 브리핑은 '오늘 신규분'만 (스토어의 과거 리포트가 섞이지 않게). 신규 없으면 스킵.
    brief = None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key and new_reports:
        model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        print("  리포트 브리핑 생성(신규분)...")
        brief = synthesize_brief(new_reports, api_key, model)

    up_n = sum(1 for r in new_reports if r.get("direction") == "up")
    down_n = sum(1 for r in new_reports if r.get("direction") == "down")
    _dates = [r.get("date") for r in stored_reports if r.get("date")]
    latest_date = max(_dates) if _dates else now.strftime("%Y-%m-%d")
    n_codes = len({r.get("code") for r in stored_reports})
    out = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "date": latest_date,
        "count": len(stored_reports), "tp_up_count": up_n, "tp_down_count": down_n,
        "reports": stored_reports, "brief": brief, "tp_history": tp_history,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  저장: {OUTPUT_PATH} (스토어 {len(stored_reports)}건 · 종목 {n_codes}개 · "
          f"신규 {len(new_reports)}건, 오늘 TP 상향 {up_n}/하향 {down_n})")


if __name__ == "__main__":
    main()
