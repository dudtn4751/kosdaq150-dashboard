"""앱 섹터 → 빅파이낸스 산업지표/신용카드 선택 매핑 (PHASE: config만, 스크레이프는 다음).

근거 데이터:
  - data/bf_industry_subcodes.json  : 산업지표 트리(카테고리 code → subCode, 갱신일·주기)
  - data/bf_creditcard_catalog.json : searchable-companies(163, A코드·companyId)
  - /api/launch-data/credit-card/sectors : 신용카드 소비 섹터(lCode/mCode) 60개

선택 기준(SECTOR_INDUSTRY):
  - 섹터당 3~8개, 월간(월) 우선, 최근 갱신(2026-06 이후), '(중단통계)' 제외.
  - 해당 앱 섹터 종목의 주가를 움직이는 대표 판매/가격/수급 지표 위주.
  - 산업지표 차트 엔드포인트: /api/industry/chart/codes/{code}/subCodes/{sub}

앱 섹터(secName, epsrev/data/dashboard_data.py CO 기준, 13개):
  반도체 · 전기전자 · 2차전지·배터리소재 · 자동차·모빌리티 · 철강·비철금속 ·
  정유·화학·석유화학 · 조선·방산·우주항공 · 건설·운송·상사 · 금융·지주 ·
  K소비재·유통 · 화장품(→K소비재 세분) · 바이오·의료기기 ·
  인터넷·소프트웨어·게임·콘텐츠

⚠️ 이 파일은 '선택'만 담는다. 실제 시계열 호출/파싱은 다음 PHASE.
"""
from __future__ import annotations

# ---------- 산업지표 선택: 섹터 → [{code, sub, label, freq}] ----------
# code=산업 카테고리 code, sub=subCode. label은 원 subName 축약. freq: 월/분기/주.
SECTOR_INDUSTRY: dict[str, list[dict]] = {
    "반도체": [
        {"code": 15, "sub": 2,   "label": "한국 반도체 수출 금액", "freq": "월"},
        {"code": 15, "sub": 181, "label": "반도체 생산·출하·재고지수", "freq": "월"},
        {"code": 15, "sub": 54,  "label": "TSMC 월매출", "freq": "월"},
        {"code": 15, "sub": 40,  "label": "대만 메모리반도체 업체별 매출", "freq": "월"},
        {"code": 15, "sub": 38,  "label": "대만 파운드리 업체별 매출", "freq": "월"},
        {"code": 15, "sub": 42,  "label": "대만 패키징·테스트 업체별 매출", "freq": "월"},
        {"code": 15, "sub": 178, "label": "Micron 기술별 매출", "freq": "분기"},
    ],
    "전기전자": [
        {"code": 15, "sub": 25,  "label": "한국 MLCC 수출 금액", "freq": "월"},
        {"code": 15, "sub": 5,   "label": "한국 PCB 수출 금액", "freq": "월"},
        {"code": 15, "sub": 21,  "label": "한국 카메라모듈 수출 금액", "freq": "월"},
        {"code": 15, "sub": 1,   "label": "한국 휴대폰 수출 금액", "freq": "월"},
        {"code": 15, "sub": 3,   "label": "한국 디스플레이패널 수출 금액", "freq": "월"},
        {"code": 15, "sub": 137, "label": "Yageo(MLCC) 월매출", "freq": "월"},
        {"code": 15, "sub": 46,  "label": "대만 서버 업체별 매출", "freq": "월"},
    ],
    "2차전지·배터리소재": [
        # 산업 트리에 배터리 전용 카테고리가 없음 → 관련 수출/화학 지표로 대체.
        # (다음 PHASE에서 trade/industries 에너지(9) 배터리 소재 시계열로 보강 예정)
        {"code": 19, "sub": 21,  "label": "한국 화학제품 스프레드(제품별)", "freq": "월"},
        {"code": 0,  "sub": 115, "label": "한국 전기차 구동모터 수입 금액", "freq": "월"},
        {"code": 0,  "sub": 83,  "label": "글로벌 전기차 판매량", "freq": "월"},
        {"code": 0,  "sub": 84,  "label": "글로벌 브랜드별 전기차 판매", "freq": "월"},
    ],
    "자동차·모빌리티": [
        {"code": 0, "sub": 2,  "label": "한국 자동차 판매: 회사별", "freq": "월"},
        {"code": 0, "sub": 14, "label": "현대차 내수 판매: 모델별", "freq": "월"},
        {"code": 0, "sub": 15, "label": "현대차 수출 판매: 모델별", "freq": "월"},
        {"code": 0, "sub": 17, "label": "기아차 내수 판매: 모델별", "freq": "월"},
        {"code": 0, "sub": 84, "label": "글로벌 브랜드별 전기차 판매", "freq": "월"},
        {"code": 0, "sub": 22, "label": "한국 자동차 수출", "freq": "월"},
        {"code": 0, "sub": 27, "label": "한국 자동차 수출 단가", "freq": "월"},
    ],
    "철강·비철금속": [
        {"code": 1, "sub": 10, "label": "한국 철강 수출 금액", "freq": "월"},
        {"code": 1, "sub": 11, "label": "한국 철강 수출 단가", "freq": "월"},
        {"code": 1, "sub": 13, "label": "한국 비철금속 수출 금액", "freq": "월"},
        {"code": 1, "sub": 17, "label": "China Steel: Exports", "freq": "월"},
        {"code": 1, "sub": 31, "label": "China Crude Steel: Output", "freq": "월"},
        {"code": 1, "sub": 35, "label": "China Iron Ore: Imports", "freq": "월"},
    ],
    "정유·화학·석유화학": [
        {"code": 19, "sub": 100, "label": "원유수입가·두바이유", "freq": "월"},
        {"code": 19, "sub": 21,  "label": "한국 화학제품 스프레드(제품별)", "freq": "월"},
        {"code": 19, "sub": 69,  "label": "국가별 정제 처리량", "freq": "월"},
        {"code": 19, "sub": 68,  "label": "국가별 정제설비 가동률", "freq": "월"},
        {"code": 19, "sub": 15,  "label": "한국 화학제품 수출 금액(제품별)", "freq": "월"},
        {"code": 19, "sub": 17,  "label": "한국 화학제품 수출 단가(제품별)", "freq": "월"},
    ],
    "조선·방산·우주항공": [
        {"code": 17, "sub": 1,  "label": "HD현대중공업 신규 수주", "freq": "월"},
        {"code": 17, "sub": 2,  "label": "HD현대중공업 수주 잔량", "freq": "월"},
        {"code": 17, "sub": 9,  "label": "삼성중공업 신규 수주", "freq": "월"},
        {"code": 17, "sub": 18, "label": "탱커 신조선가", "freq": "주"},
        {"code": 17, "sub": 24, "label": "한국 선박 수출 금액", "freq": "월"},
        {"code": 5,  "sub": 11, "label": "한국 항공부품 수출액", "freq": "월"},
        {"code": 5,  "sub": 13, "label": "Boeing Orders", "freq": "월"},
    ],
    "건설·운송·상사": [
        {"code": 4, "sub": 1,  "label": "건설 수주: 발주자·공종별", "freq": "월"},
        {"code": 4, "sub": 60, "label": "해외건설 수주: 업체별", "freq": "월"},
        {"code": 4, "sub": 20, "label": "부동산 매매가격지수: 아파트", "freq": "월"},
        {"code": 4, "sub": 14, "label": "미분양 주택 현황: 규모별", "freq": "월"},
        {"code": 7, "sub": 14, "label": "Freight Index: BDI", "freq": "일"},
        {"code": 7, "sub": 18, "label": "Freight Index: SCFI", "freq": "주"},
        {"code": 7, "sub": 9,  "label": "해운항만: 컨테이너 처리실적", "freq": "월"},
    ],
    "금융·지주": [
        {"code": 20, "sub": 1,  "label": "한국은행 기준금리", "freq": "월"},
        {"code": 20, "sub": 16, "label": "예대금리차(신규취급액)", "freq": "월"},
        {"code": 20, "sub": 13, "label": "예금취급기관 가계대출 현황", "freq": "월"},
        {"code": 20, "sub": 20, "label": "국내 주식시장 거래대금", "freq": "월"},
        {"code": 20, "sub": 21, "label": "투자자예탁금·신용공여 추이", "freq": "월"},
        {"code": 20, "sub": 32, "label": "손해보험사 원수손해율", "freq": "월"},
    ],
    "K소비재·유통": [
        {"code": 2, "sub": 5,  "label": "유통매출 증감률: 백화점", "freq": "월"},
        {"code": 2, "sub": 6,  "label": "유통매출 증감률: 편의점", "freq": "월"},
        {"code": 2, "sub": 46, "label": "유통매출 증감률: 온라인", "freq": "월"},
        {"code": 2, "sub": 1,  "label": "소비자심리지수(CSI)", "freq": "월"},
        {"code": 11, "sub": 8, "label": "음식료 수출: 직접소비재", "freq": "월"},
        {"code": 11, "sub": 10, "label": "음식료 수출: 라면", "freq": "월"},
    ],
    "화장품": [  # K소비재 세분 — 별도 트래킹 가치 높음(중국·미국 수출 민감)
        {"code": 8, "sub": 1,  "label": "화장품 수출: 글로벌 총계", "freq": "월"},
        {"code": 8, "sub": 3,  "label": "화장품 수출: 주요 국가별", "freq": "월"},
        {"code": 8, "sub": 4,  "label": "화장품 수출: 중국 상세", "freq": "월"},
        {"code": 8, "sub": 9,  "label": "화장품 수출: 미국 상세", "freq": "월"},
        {"code": 8, "sub": 2,  "label": "화장품 수출단가: 글로벌", "freq": "월"},
        {"code": 8, "sub": 20, "label": "중국 화장품 소매판매액", "freq": "월"},
    ],
    "바이오·의료기기": [
        {"code": 16, "sub": 20,  "label": "한국 바이오의약품 수출 금액", "freq": "월"},
        {"code": 16, "sub": 7,   "label": "한국 보톡스 수출·입 금액", "freq": "월"},
        {"code": 16, "sub": 5,   "label": "한국 임플란트 수출·입 금액", "freq": "월"},
        {"code": 16, "sub": 90,  "label": "한국 미용레이저기기 수출 금액", "freq": "월"},
        {"code": 16, "sub": 110, "label": "카드결제 추정: 피부과", "freq": "월"},
        {"code": 16, "sub": 111, "label": "카드결제 추정: 성형외과", "freq": "월"},
    ],
    "인터넷·소프트웨어·게임·콘텐츠": [
        # 산업 트리에 게임/인터넷 전용 지표는 약함 → 콘텐츠·통신 인접 지표로 대체.
        {"code": 3,  "sub": 86, "label": "앨범 판매량 Top400 추이", "freq": "월"},
        {"code": 3,  "sub": 24, "label": "CSI: 교양·오락·문화생활비 전망", "freq": "월"},
        {"code": 10, "sub": 1,  "label": "무선통신 기술방식별 트래픽", "freq": "월"},
        {"code": 10, "sub": 11, "label": "IPTV 가입자 수", "freq": "월"},
    ],
}

# ---------- 신용카드 소비 섹터: 앱 섹터 → [{lCode, mCode, label}] ----------
# 소비주 섹터만. 코드는 /api/launch-data/credit-card/sectors (lCode 대분류 / mCode 중분류).
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
    "미디어·엔터·콘텐츠": [  # 인터넷·게임·콘텐츠 섹터의 소비 프록시
        {"lCode": "B005", "mCode": "M0501", "label": "스포츠/문화/레저"},
        {"lCode": "B006", "mCode": "M0603", "label": "여행"},
        {"lCode": "B006", "mCode": "M0602", "label": "숙박"},
    ],
    "음식료": [
        {"lCode": "B001", "mCode": "M0101", "label": "요식: 한식"},
        {"lCode": "B001", "mCode": "M0103", "label": "요식: 제과/커피/패스트푸드"},
        {"lCode": "B003", "mCode": "M0301", "label": "음/식료품"},
    ],
    "바이오·의료기기": [  # 미용/의료 소비(피부과·성형외과 카드결제와 연계)
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
# (스크립트 생성물 — build_company_creditcard()가 재생성. 여기엔 결과만 인라인.)
COMPANY_CREDITCARD: dict[str, int] = {
    "000100": 100144, "000640": 100147, "000880": 100002, "001040": 100003,
    "001740": 100005, "002790": 100006, "003380": 100113, "003490": 100119,
    "003920": 100007, "004170": 100008, "004990": 100009, "005930": 100011,
    "005990": 100012, "006370": 100013,
    # ⚠️ 위는 검수용 일부. 전체 61종목은 build_company_creditcard()로 채운다
    # (searchable-companies A코드 stripping → CO 조인). 이 PHASE에선 매핑 로직만 확정.
}


def build_company_creditcard(searchable: list, universe_tickers: set) -> dict:
    """searchable-companies(A코드) ∩ 유니버스 → {ticker: companyId}.
    실행 시점에 bf_creditcard_catalog.json + CO로 전체 61종목 재생성."""
    out = {}
    for it in searchable or []:
        code = str(it.get("companyCode", ""))
        tk = code[1:] if code.startswith("A") else code
        if tk in universe_tickers and it.get("companyId") is not None:
            out[tk] = it["companyId"]
    return out


# 산업지표 차트 엔드포인트 템플릿(다음 PHASE에서 사용)
INDUSTRY_CHART_PATH = "/api/industry/chart/codes/{code}/subCodes/{sub}"
CREDITCARD_SECTOR_TREND_PATH = "/api/launch-data/credit-card/sectors/{lCode}/{mCode}/trends"
CREDITCARD_COMPANY_TREND_PATH = "/api/launch-data/credit-card/companies/{id}/trends"
