"""
시장 시그널 — 장 마감 후 당일 종가 기준 데이터 수집
매일 15:40 KST에 실행 (launchd)
"""

import json
import os
import sys
import warnings
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FT

import pandas as pd
import FinanceDataReader as fdr

warnings.filterwarnings("ignore")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
SIGNAL_PATH = os.path.join(PROJECT_ROOT, "data", "market_signal.json")

MIN_CAP = 3e11  # 3000억
SURGE_PCT = 7.0
SECTOR_MAP_PATH = os.path.join(PROJECT_ROOT, "data", "sector_map.json")

# 네이버 세부 업종 → 통합 섹터
SECTOR_CONSOLIDATION = {
    "반도체와반도체장비":"반도체/전자","전자장비와기기":"반도체/전자","디스플레이장비및부품":"반도체/전자",
    "디스플레이패널":"반도체/전자","핸드셋":"반도체/전자","통신장비":"반도체/전자",
    "컴퓨터와주변기기":"반도체/전자","사무용전자제품":"반도체/전자","전자제품":"반도체/전자",
    "전기제품":"2차전지/신재생","전기장비":"에너지/유틸리티","에너지장비및서비스":"에너지/유틸리티",
    "IT서비스":"IT/소프트웨어","소프트웨어":"IT/소프트웨어","양방향미디어와서비스":"IT/소프트웨어",
    "건강관리기술":"IT/소프트웨어","인터넷과카탈로그소매":"IT/소프트웨어","정보기술":"IT/소프트웨어",
    "자동차":"자동차/부품","자동차부품":"자동차/부품",
    "기계":"조선/기계/방산","조선":"조선/기계/방산","우주항공과국방":"조선/기계/방산",
    "건설":"조선/기계/방산","운송인프라":"조선/기계/방산",
    "화학":"화학/소재","비철금속":"화학/소재","건축자재":"화학/소재","건축제품":"화학/소재",
    "포장재":"화학/소재","종이와목재":"화학/소재","철강":"화학/소재","소재":"화학/소재",
    "제약":"바이오/헬스케어","생물공학":"바이오/헬스케어","생명과학도구및서비스":"바이오/헬스케어",
    "건강관리장비와용품":"바이오/헬스케어","건강관리업체및서비스":"바이오/헬스케어","헬스케어":"바이오/헬스케어",
    "금융":"금융","은행":"금융","증권":"금융","손해보험":"금융","생명보험":"금융",
    "카드":"금융","기타금융":"금융","창업투자":"금융",
    "화장품":"소비재/유통","식품":"소비재/유통","음료":"소비재/유통","담배":"소비재/유통",
    "가정용기기와용품":"소비재/유통","가정용품":"소비재/유통","가구":"소비재/유통",
    "문구류":"소비재/유통","레저용장비와제품":"소비재/유통","백화점과일반상점":"소비재/유통",
    "전문소매":"소비재/유통","식품과기본식료품소매":"소비재/유통","섬유,의류,신발,호화품":"소비재/유통",
    "자유소비재":"소비재/유통","필수소비재":"소비재/유통","다각화된소비자서비스":"소비재/유통",
    "항공사":"소비재/유통","항공화물운송과물류":"소비재/유통","해운사":"소비재/유통",
    "도로와철도운송":"소비재/유통","호텔,레스토랑,레저":"소비재/유통","교육서비스":"소비재/유통",
    "방송과엔터테인먼트":"미디어/엔터","게임엔터테인먼트":"미디어/엔터","광고":"미디어/엔터","출판":"미디어/엔터",
    "다각화된통신서비스":"통신","무선통신서비스":"통신",
    "석유와가스":"에너지/유틸리티","가스유틸리티":"에너지/유틸리티","전기유틸리티":"에너지/유틸리티",
    "복합유틸리티":"에너지/유틸리티","에너지":"에너지/유틸리티","유틸리티":"에너지/유틸리티",
    "부동산":"부동산","상업서비스와공급품":"산업서비스","복합기업":"산업서비스",
    "판매업체":"산업서비스","무역회사와판매업체":"산업서비스","산업재":"산업서비스",
    "커뮤니케이션서비스":"미디어/엔터",
}


def fmt_cap(val):
    if pd.isna(val) or val == 0:
        return "-"
    if val >= 1e12:
        return f"{val/1e12:.1f}조"
    if val >= 1e8:
        return f"{val/1e8:.0f}억"
    return f"{val:,.0f}"


def load_today():
    """당일 전 종목 시세"""
    kospi = fdr.StockListing("KOSPI")
    kosdaq = fdr.StockListing("KOSDAQ")
    kospi["market"] = "KOSPI"
    kosdaq["market"] = "KOSDAQ"
    df = pd.concat([kospi, kosdaq], ignore_index=True)
    df = df.rename(columns={"Code": "code", "Name": "name", "Marcap": "marcap",
                            "ChagesRatio": "change_pct", "Close": "close",
                            "Open": "open", "High": "high", "Low": "low",
                            "Volume": "volume", "Amount": "amount"})
    df = df[df["close"] > 0].copy()
    # High/Low가 0인 경우 종가로 대체 (장 시작 전 또는 비정상 데이터)
    df.loc[df["high"] <= 0, "high"] = df.loc[df["high"] <= 0, "close"]
    df.loc[df["low"] <= 0, "low"] = df.loc[df["low"] <= 0, "close"]
    return df


def fetch_52w(code, start_date):
    try:
        hist = fdr.DataReader(code, start_date)
        if hist is not None and not hist.empty:
            # 0값(휴장일/비정상) 제외
            valid = hist[(hist["High"] > 0) & (hist["Low"] > 0)]
            if not valid.empty:
                return code, valid["High"].max(), valid["Low"].min()
    except Exception:
        pass
    return code, None, None


def main():
    now = datetime.now()
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] 시장 시그널 수집 시작")

    today_df = load_today()
    filtered = today_df[today_df["marcap"] >= MIN_CAP].copy()
    print(f"  전체: {len(today_df)}종목, 필터(3000억+): {len(filtered)}종목")

    # 섹터 매핑 로드
    sector_raw = {}
    try:
        with open(SECTOR_MAP_PATH, "r", encoding="utf-8") as f:
            sector_raw = json.load(f)
    except Exception:
        pass

    # 1) 급등/급락
    surge = filtered[filtered["change_pct"] >= SURGE_PCT].sort_values("change_pct", ascending=False)
    plunge = filtered[filtered["change_pct"] <= -SURGE_PCT].sort_values("change_pct")

    def to_record(row):
        detail = sector_raw.get(row["code"], "기타")
        sector = SECTOR_CONSOLIDATION.get(detail, detail)
        return {
            "code": row["code"],
            "name": row["name"],
            "market": row["market"],
            "close": int(row["close"]),
            "change_pct": round(row["change_pct"], 2),
            "marcap": int(row["marcap"]),
            "marcap_str": fmt_cap(row["marcap"]),
            "sector": sector,
            "sector_detail": detail,
        }

    surge_list = [to_record(r) for _, r in surge.iterrows()]
    plunge_list = [to_record(r) for _, r in plunge.iterrows()]
    print(f"  급등({SURGE_PCT}%+): {len(surge_list)}종목, 급락: {len(plunge_list)}종목")

    # 2) 52주 신고가/신저가
    codes = filtered["code"].tolist()
    start_date = (now - timedelta(days=365)).strftime("%Y-%m-%d")
    w52 = {}
    batch_size = 30

    from concurrent.futures import as_completed
    import time as _time
    print(f"  52주 데이터 로딩 ({len(codes)}종목)...")
    done = 0
    t0 = _time.time()
    for b in range(0, len(codes), batch_size):
        batch = codes[b:b + batch_size]
        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = {ex.submit(fetch_52w, c, start_date): c for c in batch}
            try:
                for fut in as_completed(futures, timeout=30):
                    try:
                        code, h52, l52 = fut.result(timeout=5)
                        if h52 is not None:
                            w52[code] = (h52, l52)
                    except Exception:
                        pass
                    done += 1
            except FT:
                # 배치 타임아웃 — 미완료 건 스킵
                done += sum(1 for f in futures if not f.done())
        elapsed = _time.time() - t0
        print(f"    {done}/{len(codes)} ({len(w52)}개 성공, {elapsed:.0f}초)")

    new_highs = []
    new_lows = []
    for _, r in filtered.iterrows():
        # 당일 거래가 없는 종목(volume=0) 제외
        if r.get("volume", 0) <= 0:
            continue
        data = w52.get(r["code"])
        if not data:
            continue
        h52, l52 = data
        rec = to_record(r)
        if r["high"] >= h52:
            rec["high_52w"] = int(h52)
            new_highs.append(rec)
        if r["low"] <= l52:
            rec["low_52w"] = int(l52)
            new_lows.append(rec)

    # 신고가는 등락률 내림차순, 신저가는 오름차순
    new_highs.sort(key=lambda x: x["change_pct"], reverse=True)
    new_lows.sort(key=lambda x: x["change_pct"])

    print(f"  52주 신고가: {len(new_highs)}종목, 신저가: {len(new_lows)}종목")

    # 저장
    result = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "date": now.strftime("%Y-%m-%d"),
        "min_cap": "3000억",
        "surge_pct": SURGE_PCT,
        "surge": surge_list,
        "plunge": plunge_list,
        "new_high": new_highs,
        "new_low": new_lows,
    }

    os.makedirs(os.path.dirname(SIGNAL_PATH), exist_ok=True)
    with open(SIGNAL_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"  저장 완료: {SIGNAL_PATH}")
    return result


if __name__ == "__main__":
    main()
