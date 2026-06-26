"""종목별 뉴스 심리 (KR-FinBERT) — 롱숏 EPS Revision/심리 컴포넌트.

네이버 금융 종목 뉴스 제목을 수집하고 KR-FinBERT(snunlp/KR-FinBert-SC)로 금융 감성을 분류해
종목별 뉴스 심리 점수(-1~+1)를 산출한다. 키 불필요(공개 뉴스 + 공개 모델).

'추정치(EPS 상향) 심리'와 '애널리스트/시장 심리'를 텍스트에서 포착 → 알파의 EPS/심리 신호.
출력: data/news_sentiment.json
사용: python3 scripts/update_news.py [--limit N]

transformers/torch 미설치 시: 안전하게 건너뜀(기존 파일 유지, exit 0).
"""

import argparse
import html
import json
import re
import sys
import time
import urllib.request
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

warnings.filterwarnings("ignore")

KST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).parent.parent
DATA = PROJECT_ROOT / "data"
OUTPUT_PATH = DATA / "news_sentiment.json"
MODEL = "snunlp/KR-FinBert-SC"
HEADLINES_PER = 6  # 종목당 최신 제목 수


def fetch_titles(code):
    """네이버 금융 종목 뉴스 최신 제목 리스트."""
    url = (f"https://finance.naver.com/item/news_news.naver?code={code}"
           f"&page=1&sm=title_entity_id.basic")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                               "Referer": "https://finance.naver.com/"})
    try:
        raw = urllib.request.urlopen(req, timeout=12).read().decode("euc-kr", "ignore")
    except Exception:
        return []
    titles = re.findall(r'class="title">\s*<a[^>]*>(.*?)</a>', raw, re.S)
    out = []
    for t in titles:
        t = html.unescape(re.sub(r"<[^>]+>", "", t)).strip().strip("'\" ")
        if t and len(t) > 6:
            out.append(t)
    return out[:HEADLINES_PER]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    now = datetime.now(KST)
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] 종목별 뉴스 심리(KR-FinBERT) 수집")

    # 모델 (미설치 시 건너뜀)
    try:
        from transformers import pipeline
    except Exception:
        print("  [건너뜀] transformers 미설치 — 뉴스 심리 생략(기존 파일 유지).")
        return

    try:
        cons = json.loads((DATA / "consensus.json").read_text(encoding="utf-8"))
        codes = [(s["code"], s["name"]) for s in cons.get("stocks", [])]
    except Exception:
        codes = []
    if args.limit:
        codes = codes[:args.limit]
    if not codes:
        print("  [경고] 유니버스 없음(consensus.json 필요) — 중단(exit 2).")
        sys.exit(2)

    # 1) 제목 수집
    per_titles, all_titles, idx = {}, [], []
    for i, (code, name) in enumerate(codes):
        ts = fetch_titles(code)
        if ts:
            per_titles[code] = ts
            for t in ts:
                all_titles.append(t)
                idx.append(code)
        if (i + 1) % 100 == 0:
            print(f"  뉴스 수집 {i+1}/{len(codes)} (제목 {len(all_titles)})")
        time.sleep(0.1)
    print(f"  제목 총 {len(all_titles)}개 / {len(per_titles)}종목 — KR-FinBERT 분류 시작")

    if len(all_titles) < 30:
        print(f"  [경고] 제목 {len(all_titles)}개 — 수집 장애 의심. 기존 파일 유지(exit 2).")
        sys.exit(2)

    # 2) 감성 분류 (배치)
    clf = pipeline("sentiment-analysis", model=MODEL, truncation=True)
    preds = clf(all_titles, batch_size=32)

    def signed(p):
        lab = p["label"].lower()
        if "pos" in lab:
            return p["score"]
        if "neg" in lab:
            return -p["score"]
        return 0.0

    # 3) 종목별 집계
    agg = {}
    for code, p in zip(idx, preds):
        agg.setdefault(code, []).append(signed(p))
    flows = {}
    for code, vals in agg.items():
        ns = round(sum(vals) / len(vals), 3)
        pos = sum(1 for v in vals if v > 0.3)
        neg = sum(1 for v in vals if v < -0.3)
        # 대표 제목 3개 (강도순)
        pairs = sorted(zip(per_titles[code], vals), key=lambda x: abs(x[1]), reverse=True)[:3]
        recent = [{"title": t, "s": round(v, 2)} for t, v in pairs]
        flows[code] = {"sentiment": ns, "n": len(vals), "pos": pos, "neg": neg, "recent": recent}

    out = {"updated": now.strftime("%Y-%m-%d %H:%M"), "date": now.strftime("%Y-%m-%d"),
           "model": MODEL, "count": len(flows), "flows": flows}
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  저장: {OUTPUT_PATH} (뉴스 심리 {len(flows)}종목)")


if __name__ == "__main__":
    main()
