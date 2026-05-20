"""
매크로 경제 이벤트 영문→한글 매핑 (단일 진실 소스)
investing.com 등 영문 이벤트명을 한국어로 번역
"""

import re

EVENT_KR = {
    # 고용
    "Nonfarm Payrolls": "비농업 고용",
    "ADP Nonfarm Employment": "ADP 민간고용",
    "ADP Employment Change Weekly": "ADP 주간고용변동",
    "Unemployment Rate": "실업률",
    "Initial Jobless Claims": "신규 실업수당 청구건수",
    "Continuing Jobless Claims": "계속 실업수당 청구건수",
    "JOLTS Job Openings": "JOLTS 구인건수",
    # 물가
    "CPI": "소비자물가지수(CPI)",
    "Core CPI": "근원 소비자물가지수",
    "PPI": "생산자물가지수(PPI)",
    "Core PPI": "근원 생산자물가지수",
    "Core PCE Price Index": "근원 PCE 물가지수",
    "PCE Price index": "PCE 물가지수",
    "PCE Price Index": "PCE 물가지수",
    "PCE price index": "PCE 물가지수",
    "Core PCE Prices": "근원 PCE 물가",
    "Michigan Consumer Sentiment": "미시간 소비자심리지수",
    # GDP/생산
    "GDP": "GDP",
    "GDP Price Index": "GDP 물가지수",
    "Industrial Production": "산업생산",
    "Capacity Utilization Rate": "설비가동률",
    # ISM/PMI
    "ISM Manufacturing PMI": "ISM 제조업 PMI",
    "ISM Services PMI": "ISM 서비스업 PMI",
    "ISM Manufacturing Prices": "ISM 제조업 가격지수",
    "ISM Manufacturing Employment": "ISM 제조업 고용지수",
    "ISM Non-Manufacturing PMI": "ISM 비제조업 PMI",
    "ISM Non-Manufacturing Employment": "ISM 비제조업 고용지수",
    "ISM Non-Manufacturing Prices": "ISM 비제조업 가격지수",
    "S&P Global Manufacturing PMI": "S&P 제조업 PMI",
    "S&P Global Services PMI": "S&P 서비스업 PMI",
    "S&P Global Composite PMI": "S&P 종합 PMI",
    "Chicago PMI": "시카고 PMI",
    # 소비/소매
    "Retail Sales": "소매판매",
    "Core Retail Sales": "근원 소매판매",
    "Personal Income": "개인소득",
    "Personal Spending": "개인소비지출",
    "Consumer Confidence": "소비자 신뢰지수(CB)",
    "CB Consumer Confidence": "소비자 신뢰지수(CB)",
    # 주택
    "New Home Sales": "신규주택판매",
    "Existing Home Sales": "기존주택판매",
    "Building Permits": "건축허가건수",
    "Housing Starts": "주택착공건수",
    "S&P/CS Composite-20 HPI": "S&P/CS 주택가격지수",
    "Pending Home Sales": "잠정주택판매",
    # 무역/기타
    "Trade Balance": "무역수지",
    "Durable Goods Orders": "내구재 주문",
    "Core Durable Goods Orders": "근원 내구재 주문",
    "Factory Orders": "공장주문",
    "Construction Spending": "건설지출",
    # 연준
    "Fed Interest Rate Decision": "FOMC 금리결정",
    "FOMC Statement": "FOMC 성명서",
    "FOMC Minutes": "FOMC 의사록",
    "FOMC Meeting Minutes": "FOMC 의사록",
    "FOMC Press Conference": "FOMC 기자회견",
    "Fed Chair Powell Speaks": "파월 의장 발언",
    "U.S. President Trump Speaks": "트럼프 대통령 발언",
    "Atlanta Fed GDPNow": "애틀랜타 연은 GDPNow",
    # 연준 인사 발언 (정적 매핑 — 동적 패턴은 translate_event의 정규식이 보완)
    "FOMC Member Daly Speaks": "FOMC 위원 데일리 발언",
    "FOMC Member Bowman Speaks": "FOMC 위원 보우만 발언",
    "FOMC Member Williams Speaks": "FOMC 위원 윌리엄스 발언",
    "FOMC Member Waller Speaks": "FOMC 위원 월러 발언",
    "Fed Waller Speaks": "연준 월러 발언",
    "Fed Vice Chair for Supervision Barr Speaks": "연준 부의장 바 발언",
    "Fed's Balance Sheet": "연준 대차대조표",
    # 유가/에너지
    "Crude Oil Inventories": "원유 재고",
    "Cushing Crude Oil Inventories": "쿠싱 원유 재고",
    "API Weekly Crude Oil Stock": "API 주간 원유 재고",
    "EIA Short-Term Energy Outlook": "EIA 단기 에너지 전망",
    "OPEC Monthly Report": "OPEC 월간 보고서",
    "IEA Monthly Report": "IEA 월간 보고서",
    "WASDE Report": "WASDE 보고서",
    # 지역 제조업
    "NY Empire State Manufacturing Index": "NY 엠파이어 제조업지수",
    "Philadelphia Fed Manufacturing Index": "필라델피아 연은 제조업지수",
    "Philly Fed Employment": "필라델피아 연은 고용지수",
    # 물가/수출입
    "Export Price Index": "수출물가지수",
    "Import Price Index": "수입물가지수",
    # 소비/재고
    "Retail Control": "소매 통제그룹",
    "Business Inventories": "기업 재고",
    "Retail Inventories Ex Auto": "소매 재고(자동차 제외)",
    # 국채 입찰
    "3-Year Note Auction": "3년물 국채 입찰",
    "10-Year Note Auction": "10년물 국채 입찰",
    "30-Year Bond Auction": "30년물 국채 입찰",
    # 기타
    "Consumer Credit": "소비자 신용",
    "Beige Book": "베이지북",
    "TIC Net Long-Term Transactions": "TIC 장기 자본 순유입",
    "Michigan 1-Year Inflation Expectations": "미시간 1년 기대인플레이션",
    "Michigan 5-Year Inflation Expectations": "미시간 5년 기대인플레이션",
    "Michigan Consumer Expectations": "미시간 소비자기대지수",
    "NY Fed 1-Year Consumer Inflation Expectations": "NY 연은 1년 기대인플레이션",
}


def translate_event(name: str) -> str:
    """영문 이벤트명 → 한글 (기간/Final/Preliminary 보존, FOMC 위원 패턴 대응)"""
    if not name:
        return name
    clean = name.strip()

    # 동적 패턴 1: FOMC Member <Name> Speaks
    m = re.match(r'FOMC Member (\w+) Speaks', clean)
    if m:
        return f"FOMC 위원 {m.group(1)} 발언"

    # 동적 패턴 2: Fed <Name> Speaks
    m = re.match(r'Fed (\w+) Speaks', clean)
    if m:
        return f"연준 {m.group(1)} 발언"

    # 정적 사전 매칭 (긴 키부터 매칭하면 부분일치 오류 줄일 수 있음)
    for eng in sorted(EVENT_KR.keys(), key=len, reverse=True):
        if eng in clean:
            kor = EVENT_KR[eng]
            periods = re.findall(r'\(([^)]+)\)', clean)
            period_str = " ".join(f"({p})" for p in periods) if periods else ""
            result = f"{kor} {period_str}".strip() if period_str else kor
            if "Final" in clean:
                result += " 확정치"
            elif "Preliminary" in clean or "Flash" in clean:
                result += " 잠정치"
            return result.strip()
    return clean
