"""앱 섹터 → 빅파이낸스 산업지표/신용카드 선택 매핑 (PHASE: config만, 스크레이프는 다음).

근거 데이터:
  - data/bf_industry_subcodes.json  : 산업지표 트리(카테고리 code → subCode, 갱신일·주기)
  - data/bf_industry_catalog.json   : 무역(trade) 산업 트리(industryCode → productCode)
  - data/bf_creditcard_catalog.json : searchable-companies(163, A코드·companyId)
  - /api/launch-data/credit-card/sectors : 신용카드 소비 섹터(lCode/mCode) 60개

각 지표 필드:
  code, sub : 산업지표(src="industry") 카테고리 code + subCode  또는
              무역(src="trade")  industryCode + productCode
  label     : 축약 표시명
  freq      : 원 시계열 주기(월/분기/반기/주/일) — 엔진이 계산 전 '월간 리샘플'로 통일
  series_type : "growth" | "level"  ← 스코어 엔진 처리 분기(아래)
  src       : "industry"(기본, /api/industry/chart/codes/{code}/subCodes/{sub})
              "trade"(/api/launch-data/trade/industries/{code}/{sub}/{kind}/export/chart)

series_type 의미(핸드오프 STEP 1~2와 일치):
  - growth : 수출/판매/생산/매출/수주(신규)/소매판매/트래픽 등 '양(volume·value)'.
             4축(모멘텀=ma3_yoy, 가속=Δma3_yoy+저점반등, 품질=물량 vs 단가, 사이클=runrate_gap) 그대로.
  - level  : 금리/유가/스프레드/정제마진·가동률/신조선가/BDI·SCFI/가격지수/단가/점유율/
             증감률(rate)/잔액·재고 등 '가격·수준·비율'.
             모멘텀=레벨 z 또는 Δ, 가속=레벨 2차 차분, 품질축 제외(재정규화), 사이클=24M추세 대비.
             ⚠️ level형엔 YoY-성장률 로직 금지(레벨의 YoY%는 왜곡).

⚠️ 이 파일은 '선택'만 담는다. 실제 시계열 호출/파싱은 다음 PHASE.
"""
from __future__ import annotations

# 표기 단축: (code, sub, label, freq, series_type[, src])
def _ind(code, sub, label, freq, stype, src="industry"):
    return {"code": code, "sub": sub, "label": label, "freq": freq,
            "series_type": stype, "src": src}


# ---------- 산업지표 선택: 섹터 → [지표…] ----------
SECTOR_INDUSTRY: dict[str, list[dict]] = {
    "반도체": [
        _ind(15, 2,   "한국 반도체 수출 금액", "월", "growth"),
        _ind(15, 181, "반도체 생산·출하·재고지수", "월", "level"),   # 지수(레벨)
        _ind(15, 54,  "TSMC 월매출", "월", "growth"),
        _ind(15, 40,  "대만 메모리반도체 업체별 매출", "월", "growth"),
        _ind(15, 38,  "대만 파운드리 업체별 매출", "월", "growth"),
        _ind(15, 42,  "대만 패키징·테스트 업체별 매출", "월", "growth"),
        _ind(15, 178, "Micron 기술별 매출", "분기", "growth"),
        # ⚠️ DRAM/NAND 고정거래가격(DRAMeXchange류): 산업지표 트리에 없음 → 미포함.
        #    (필요 시 외부 소스 별도 연동. 트리 검색결과 메모리 '가격' 시리즈 부재 확인.)
    ],
    "전기전자": [
        _ind(15, 25,  "한국 MLCC 수출 금액", "월", "growth"),
        _ind(15, 5,   "한국 PCB 수출 금액", "월", "growth"),
        _ind(15, 21,  "한국 카메라모듈 수출 금액", "월", "growth"),
        _ind(15, 1,   "한국 휴대폰 수출 금액", "월", "growth"),
        _ind(15, 3,   "한국 디스플레이패널 수출 금액", "월", "growth"),
        _ind(15, 137, "Yageo(MLCC) 월매출", "월", "growth"),
        _ind(15, 46,  "대만 서버 업체별 매출", "월", "growth"),
    ],
    "2차전지·배터리소재": [
        # 무역(trade) 에너지(9): 배터리·소재 품목별 수출 (src="trade")
        _ind(9, 3,  "리튬이온 배터리 수출", "월", "growth", src="trade"),
        _ind(9, 8,  "양극활물질 수출", "월", "growth", src="trade"),
        _ind(9, 9,  "음극활물질 수출", "월", "growth", src="trade"),
        _ind(9, 10, "분리막 수출", "월", "growth", src="trade"),
        # 산업지표(19) 2차전지 소재 총괄
        _ind(19, 70, "한국 2차전지 소재 수출 금액", "월", "growth"),
        _ind(19, 72, "한국 2차전지 소재 수출 단가", "월", "level"),   # 단가=가격(레벨)
        # 수요 드라이버
        _ind(0, 84, "글로벌 브랜드별 전기차 판매", "월", "growth"),
        # ⚠️ 리튬·니켈 '메탈가격' 시리즈: 트리에 없음(연간 '생산량' 19/73·74만, 2025-08 stale) → 미포함.
    ],
    "자동차·모빌리티": [
        _ind(0, 2,  "한국 자동차 판매: 회사별", "월", "growth"),
        _ind(0, 14, "현대차 내수 판매: 모델별", "월", "growth"),
        _ind(0, 15, "현대차 수출 판매: 모델별", "월", "growth"),
        _ind(0, 17, "기아차 내수 판매: 모델별", "월", "growth"),
        _ind(0, 84, "글로벌 브랜드별 전기차 판매", "월", "growth"),
        _ind(0, 22, "한국 자동차 수출", "월", "growth"),
        _ind(0, 27, "한국 자동차 수출 단가", "월", "level"),   # 단가=가격(레벨)
    ],
    "철강·비철금속": [
        _ind(1, 10, "한국 철강 수출 금액", "월", "growth"),
        _ind(1, 11, "한국 철강 수출 단가", "월", "level"),
        _ind(1, 13, "한국 비철금속 수출 금액", "월", "growth"),
        _ind(1, 17, "China Steel: Exports", "월", "growth"),
        _ind(1, 31, "China Crude Steel: Output", "월", "growth"),
        _ind(1, 35, "China Iron Ore: Imports", "월", "growth"),
    ],
    "정유·화학·석유화학": [
        _ind(19, 100, "원유수입가·두바이유", "월", "level"),
        _ind(19, 21,  "한국 화학제품 스프레드(제품별)", "월", "level"),
        _ind(19, 69,  "국가별 정제 처리량", "월", "growth"),
        _ind(19, 68,  "국가별 정제설비 가동률", "월", "level"),
        _ind(19, 15,  "한국 화학제품 수출 금액(제품별)", "월", "growth"),
        _ind(19, 17,  "한국 화학제품 수출 단가(제품별)", "월", "level"),
    ],
    "조선·방산·우주항공": [
        _ind(17, 1,  "HD현대중공업 신규 수주", "월", "growth"),
        _ind(17, 2,  "HD현대중공업 수주 잔량", "월", "level"),   # 잔고(스톡)=레벨
        _ind(17, 9,  "삼성중공업 신규 수주", "월", "growth"),
        _ind(17, 18, "탱커 신조선가", "주", "level"),           # 주→월 리샘플
        _ind(17, 24, "한국 선박 수출 금액", "월", "growth"),
        _ind(5,  11, "한국 항공부품 수출액", "월", "growth"),
        _ind(5,  13, "Boeing Orders", "월", "growth"),
    ],
    "건설·운송·상사": [
        _ind(4, 1,  "건설 수주: 발주자·공종별", "월", "growth"),
        _ind(4, 60, "해외건설 수주: 업체별", "월", "growth"),
        _ind(4, 20, "부동산 매매가격지수: 아파트", "월", "level"),   # 가격지수=레벨
        _ind(4, 14, "미분양 주택 현황: 규모별", "월", "level"),      # 재고=레벨
        _ind(7, 14, "Freight Index: BDI", "일", "level"),        # 일→월 리샘플
        _ind(7, 18, "Freight Index: SCFI", "주", "level"),       # 주→월 리샘플
        _ind(7, 9,  "해운항만: 컨테이너 처리실적", "월", "growth"),
    ],
    "금융·지주": [
        _ind(20, 1,  "한국은행 기준금리", "월", "level"),
        _ind(20, 16, "예대금리차(신규취급액)", "월", "level"),
        _ind(20, 13, "예금취급기관 가계대출 현황", "월", "level"),   # 잔액=레벨
        _ind(20, 20, "국내 주식시장 거래대금", "월", "growth"),
        _ind(20, 21, "투자자예탁금·신용공여 추이", "월", "level"),   # 잔액=레벨
        _ind(20, 32, "손해보험사 원수손해율", "월", "level"),        # 비율=레벨
    ],
    "K소비재·유통": [
        _ind(2, 5,  "유통매출 증감률: 백화점", "월", "level"),   # 증감률(rate)=레벨
        _ind(2, 6,  "유통매출 증감률: 편의점", "월", "level"),
        _ind(2, 46, "유통매출 증감률: 온라인", "월", "level"),
        _ind(2, 1,  "소비자심리지수(CSI)", "월", "level"),       # 심리지수=레벨
        _ind(11, 8, "음식료 수출: 직접소비재", "월", "growth"),
        _ind(11, 10, "음식료 수출: 라면", "월", "growth"),
    ],
    "화장품": [
        _ind(8, 1,  "화장품 수출: 글로벌 총계", "월", "growth"),
        _ind(8, 3,  "화장품 수출: 주요 국가별", "월", "growth"),
        _ind(8, 4,  "화장품 수출: 중국 상세", "월", "growth"),
        _ind(8, 9,  "화장품 수출: 미국 상세", "월", "growth"),
        _ind(8, 2,  "화장품 수출단가: 글로벌", "월", "level"),
        _ind(8, 20, "중국 화장품 소매판매액", "월", "growth"),
    ],
    "바이오·의료기기": [
        _ind(16, 20,  "한국 바이오의약품 수출 금액", "월", "growth"),
        _ind(16, 7,   "한국 보톡스 수출·입 금액", "월", "growth"),
        _ind(16, 5,   "한국 임플란트 수출·입 금액", "월", "growth"),
        _ind(16, 90,  "한국 미용레이저기기 수출 금액", "월", "growth"),
        _ind(16, 110, "카드결제 추정: 피부과", "월", "growth"),
        _ind(16, 111, "카드결제 추정: 성형외과", "월", "growth"),
    ],
    "인터넷·소프트웨어·게임·콘텐츠": [
        # 앨범/통신 프록시 비중↓ → K-콘텐츠 수출·매출 중심 + 카드소비(SECTOR_CREDITCARD) 병행.
        _ind(3, 10, "한국 콘텐츠 산업: 분야별 수출액", "반기", "growth"),   # 반기→월 리샘플
        _ind(3, 9,  "한국 콘텐츠 산업: 분야별 매출액", "반기", "growth"),
        _ind(3, 69, "콘텐츠 업체별 VFX 매출액", "분기", "growth"),
        _ind(3, 86, "앨범 판매량 Top400", "월", "growth"),   # 엔터(음악)만 커버 — 보조
        # ⚠️ 순수 게임주(넷마블·펄어비스 등)는 산업지표 직접 커버 약함.
        #    → COMPANY_CREDITCARD의 게임/콘텐츠 종목 + SECTOR_CREDITCARD 온라인/레저 카드소비로 보완.
        #    (통신 IPTV/무선트래픽 프록시는 상관 낮아 제외)
    ],
}

# ---------- 신용카드 소비 섹터: 앱 섹터 → [{lCode, mCode, label}] ----------
SECTOR_CREDITCARD: dict[str, list[dict]] = {
    "K소비재·유통": [
        {"lCode": "B002", "mCode": "M0201", "label": "유통: 백화점"},
        {"lCode": "B002", "mCode": "M0202", "label": "유통: 할인점/슈퍼"},
        {"lCode": "B002", "mCode": "M0203", "label": "유통: 편의점"},
        {"lCode": "B002", "mCode": "M0205", "label": "유통: 면세점"},
        {"lCode": "B014", "mCode": "M1401", "label": "온라인"},
        {"lCode": "B003", "mCode": "M0301", "label": "음/식료품"},
    ],
    "화장품": [
        {"lCode": "B007", "mCode": "M0703", "label": "미용: 화장품"},
        {"lCode": "B007", "mCode": "M0701", "label": "미용서비스"},
    ],
    "인터넷·소프트웨어·게임·콘텐츠": [  # 온라인·콘텐츠·레저 카드소비(게임주 약커버 보완)
        {"lCode": "B014", "mCode": "M1401", "label": "온라인"},
        {"lCode": "B005", "mCode": "M0501", "label": "스포츠/문화/레저"},
        {"lCode": "B005", "mCode": "M0502", "label": "스포츠/문화/레저용품"},
        {"lCode": "B006", "mCode": "M0603", "label": "여행"},
        {"lCode": "B006", "mCode": "M0602", "label": "숙박"},
    ],
    "음식료": [
        {"lCode": "B001", "mCode": "M0101", "label": "요식: 한식"},
        {"lCode": "B001", "mCode": "M0103", "label": "요식: 제과/커피/패스트푸드"},
        {"lCode": "B003", "mCode": "M0301", "label": "음/식료품"},
    ],
    "바이오·의료기기": [
        {"lCode": "B010", "mCode": "M1013", "label": "의료: 성형외과"},
        {"lCode": "B010", "mCode": "M1023", "label": "의료: 피부과의원"},
        {"lCode": "B007", "mCode": "M0702", "label": "회원제 스파/마사지"},
    ],
    "자동차·모빌리티": [
        {"lCode": "B012", "mCode": "M1201", "label": "자동차 판매"},
        {"lCode": "B012", "mCode": "M1202", "label": "자동차 서비스/용품"},
        {"lCode": "B013", "mCode": "M1301", "label": "주유"},
    ],
}

# ---------- 기업 직접 신용카드 매핑: {ticker: companyId} ----------
# searchable-companies(163개, A코드) ∩ 앱 유니버스(CO 6자리) = 61종목.
# 기업 상세 화면의 'I렌즈(카드소비)' 탭에서 companies/{id}/trends 호출용.
# 전체 61종목은 build_company_creditcard()로 재생성(A코드 stripping → CO 조인).
COMPANY_CREDITCARD: dict[str, int] = {
    "000100": 100144, "000640": 100147, "000880": 100002, "001040": 100003,
    "001740": 100005, "002790": 100006, "003380": 100113, "003490": 100119,
    "003920": 100007, "004170": 100008, "004990": 100009, "005930": 100011,
    # ⚠️ 검수용 일부. 전체는 build_company_creditcard()로 채운다(이 PHASE는 매핑 로직만 확정).
}


def build_company_creditcard(searchable: list, universe_tickers: set) -> dict:
    """searchable-companies(A코드) ∩ 유니버스 → {ticker: companyId}."""
    out = {}
    for it in searchable or []:
        code = str(it.get("companyCode", ""))
        tk = code[1:] if code.startswith("A") else code
        if tk in universe_tickers and it.get("companyId") is not None:
            out[tk] = it["companyId"]
    return out


# ---------- 엔드포인트 템플릿(다음 PHASE) ----------
INDUSTRY_CHART_PATH = "/api/industry/chart/codes/{code}/subCodes/{sub}"
TRADE_EXPORT_CHART_PATH = "/api/launch-data/trade/industries/{code}/{sub}/{kind}/export/chart"  # kind: confirm|provisional
CREDITCARD_SECTOR_TREND_PATH = "/api/launch-data/credit-card/sectors/{lCode}/{mCode}/trends"
CREDITCARD_COMPANY_TREND_PATH = "/api/launch-data/credit-card/companies/{id}/trends"
