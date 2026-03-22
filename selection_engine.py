"""
코스닥 150 구성종목 선정 엔진

KRX 방법론 기반 선정 알고리즘:
1. 심사대상종목 필터링 (관리종목, SPAC, 유동주식비율 등 제외)
2. 11개 GICS 산업군 분류
3. 1차 선정: 산업군별 누적시가총액 60% + 유동성 기준
4. 2차 선정: 기존 종목 버퍼(120%), 신규 편입 기준(80%)
5. 3차 선정: 150종목 맞추기
6. 대형주 특례 / 소형주 제외
"""

import pandas as pd


# GICS 산업군 매핑 (WISE Index API 기준 -> KRX 방법론 기준)
GICS_SECTOR_MAP = {
    "정보기술": "정보기술",
    "IT": "정보기술",
    "헬스케어": "헬스케어",
    "건강관리": "헬스케어",
    "커뮤니케이션서비스": "커뮤니케이션서비스",
    "소재": "소재",
    "산업재": "산업재",
    "필수소비재": "필수소비재",
    "자유소비재": "자유소비재",
    "경기관련소비재": "자유소비재",
    "금융": "금융",
    "에너지": "에너지",
    "유틸리티": "유틸리티",
    "부동산": "부동산",
}

VALID_SECTORS = [
    "정보기술", "헬스케어", "커뮤니케이션서비스", "소재", "산업재",
    "필수소비재", "자유소비재", "금융", "에너지", "유틸리티", "부동산",
]


def build_eligible_stocks(
    kosdaq_df: pd.DataFrame,
    gics_map: dict,
    avg_data: pd.DataFrame = None,
) -> pd.DataFrame:
    """심사대상종목 구성: GICS 섹터 분류 + 시가총액/거래대금 데이터 병합

    Args:
        kosdaq_df: 코스닥 전체 종목 (data_collector.get_kosdaq_listing 결과)
        gics_map: {종목코드: GICS 섹터명}
        avg_data: 6개월 일평균 데이터 (None이면 당일 스냅샷 사용)

    Returns:
        심사대상 종목 DataFrame
    """
    df = kosdaq_df.copy()

    # GICS 섹터 매핑
    df["sector_raw"] = df["code"].map(gics_map)
    df["sector"] = df["sector_raw"].map(GICS_SECTOR_MAP)

    # 섹터 미분류 종목 제외
    df = df[df["sector"].notna()].copy()

    # 6개월 평균 데이터가 있으면 병합
    if avg_data is not None and not avg_data.empty:
        avg = avg_data[["code", "avg_marcap", "avg_amount"]].copy()
        df = df.merge(avg, on="code", how="left")
        df["avg_marcap"] = df["avg_marcap"].fillna(df["marcap"])
        df["avg_amount"] = df["avg_amount"].fillna(df["amount"])
    else:
        # 당일 스냅샷을 일평균 대용으로 사용
        df["avg_marcap"] = df["marcap"]
        df["avg_amount"] = df["amount"]

    # 시가총액 0 이하 제외
    df = df[df["avg_marcap"] > 0].copy()

    return df.reset_index(drop=True)


def _filter_small_sectors(df: pd.DataFrame) -> list:
    """산업군 시가총액이 전체의 1% 미만인 섹터 제외 (방법론 6.2)"""
    total_marcap = df["avg_marcap"].sum()
    sector_marcap = df.groupby("sector")["avg_marcap"].sum()
    excluded = sector_marcap[sector_marcap / total_marcap < 0.01].index.tolist()
    return excluded


def _check_liquidity(sector_df: pd.DataFrame, stock_row: pd.Series) -> bool:
    """유동성 기준: 거래대금 순위가 산업군 전체 종목수의 80% 이내 (방법론 6.4.1)"""
    sector_df_sorted = sector_df.sort_values("avg_amount", ascending=False)
    total_count = len(sector_df_sorted)
    threshold = int(total_count * 0.8)
    if threshold < 1:
        threshold = 1

    rank = (sector_df_sorted["code"] == stock_row["code"]).values
    amount_rank = rank.argmax() + 1 if rank.any() else total_count + 1
    return amount_rank <= threshold


def select_kosdaq150(
    kosdaq_df: pd.DataFrame,
    gics_map: dict,
    current_150: list = None,
    avg_data: pd.DataFrame = None,
) -> dict:
    """코스닥 150 구성종목 선정 시뮬레이션

    Args:
        kosdaq_df: 코스닥 전체 종목 DataFrame
        gics_map: {종목코드: GICS 섹터명}
        current_150: 현재 구성종목 코드 리스트 (2차 선정에 사용, None이면 생략)
        avg_data: 6개월 일평균 데이터 (None이면 당일 데이터 사용)

    Returns:
        dict:
            selected: 선정된 종목 코드 리스트
            details: 상세 DataFrame (종목코드, 이름, 섹터, 시총, 선정단계 등)
            sector_summary: 섹터별 요약
    """
    # 1. 심사대상 종목 구성
    eligible = build_eligible_stocks(kosdaq_df, gics_map, avg_data)

    # 시가총액이 코스닥 전체 상위 300위 초과 기준 (소형주 제외용)
    all_kosdaq_by_marcap = kosdaq_df.sort_values("marcap", ascending=False)
    if len(all_kosdaq_by_marcap) > 300:
        marcap_300th = all_kosdaq_by_marcap.iloc[299]["marcap"]
    else:
        marcap_300th = 0

    # 2. 소규모 섹터 제외
    excluded_sectors = _filter_small_sectors(eligible)
    eligible = eligible[~eligible["sector"].isin(excluded_sectors)].copy()

    # 3. 섹터별 유동성 기준 사전 계산
    liquidity_ok = set()
    for sector in eligible["sector"].unique():
        sector_df = eligible[eligible["sector"] == sector].copy()
        sector_df = sector_df.sort_values("avg_amount", ascending=False)
        total = len(sector_df)
        threshold = max(int(total * 0.8), 1)
        ok_codes = sector_df.head(threshold)["code"].tolist()
        liquidity_ok.update(ok_codes)

    # === 1차 선정: 산업군별 누적시가총액 60% (방법론 6.4.1) ===
    first_selected = set()
    sector_details = {}

    for sector in eligible["sector"].unique():
        sector_df = eligible[eligible["sector"] == sector].copy()
        sector_df = sector_df.sort_values("avg_marcap", ascending=False)
        total_marcap = sector_df["avg_marcap"].sum()
        target_marcap = total_marcap * 0.60

        cumsum = 0
        sector_selected = []
        for _, row in sector_df.iterrows():
            if row["code"] not in liquidity_ok:
                continue
            cumsum += row["avg_marcap"]
            sector_selected.append(row["code"])
            if cumsum >= target_marcap:
                break

        first_selected.update(sector_selected)
        sector_details[sector] = {
            "total_stocks": len(sector_df),
            "total_marcap": total_marcap,
            "selected_count": len(sector_selected),
        }

    # === 2차 선정: 기존 종목 버퍼 / 신규 편입 기준 (방법론 6.4.2) ===
    second_selected = set(first_selected)

    if current_150 is not None:
        current_set = set(current_150)

        for sector in eligible["sector"].unique():
            sector_df = eligible[eligible["sector"] == sector].copy()
            sector_df = sector_df.sort_values("avg_marcap", ascending=False)

            # 해당 섹터의 기존 구성종목 수
            sector_current = [c for c in current_set
                              if c in sector_df["code"].values]
            n_current = len(sector_current)
            if n_current == 0:
                continue

            # 기존 종목 유지 기준: 시총순위 <= 기존종목수 * 120%
            keep_threshold = max(int(n_current * 1.2), 1)
            sector_df = sector_df.reset_index(drop=True)
            sector_df["rank"] = range(1, len(sector_df) + 1)

            for code in sector_current:
                row = sector_df[sector_df["code"] == code]
                if row.empty:
                    continue
                rank = row.iloc[0]["rank"]
                if rank <= keep_threshold and code in liquidity_ok:
                    second_selected.add(code)

            # 신규 편입 기준: 시총순위 <= 기존종목수 * 80%
            new_threshold = max(int(n_current * 0.8), 1)
            if n_current < 3:
                new_threshold = keep_threshold  # 3개 미만이면 예외

            for _, row in sector_df.iterrows():
                if row["code"] in current_set:
                    continue
                if row["code"] in liquidity_ok and row["rank"] <= new_threshold:
                    second_selected.add(row["code"])

    # === 3차 선정: 150종목 맞추기 (방법론 6.4.3) ===
    final_selected = set(second_selected)

    if len(final_selected) < 150:
        # 미선정 종목 중 시총 높은 순 추가 (유동성 충족 필요)
        remaining = eligible[
            (~eligible["code"].isin(final_selected))
            & (eligible["code"].isin(liquidity_ok))
        ].sort_values("avg_marcap", ascending=False)

        for _, row in remaining.iterrows():
            if len(final_selected) >= 150:
                break
            final_selected.add(row["code"])

    elif len(final_selected) > 150:
        # 시총 낮은 순으로 제외
        selected_df = eligible[eligible["code"].isin(final_selected)].copy()
        selected_df = selected_df.sort_values("avg_marcap", ascending=True)
        excess = len(final_selected) - 150
        to_remove = selected_df.head(excess)["code"].tolist()
        final_selected -= set(to_remove)

    # === 대형주 특례 (방법론 6.4.4) ===
    # 시가총액 상위 50위 이내 종목은 산업군 무관 편입 가능
    top50 = eligible.sort_values("avg_marcap", ascending=False).head(50)
    for _, row in top50.iterrows():
        if row["code"] not in final_selected:
            final_selected.add(row["code"])
            # 기존 선정 종목 중 시총 최소 종목 제외
            if len(final_selected) > 150:
                sel_df = eligible[eligible["code"].isin(final_selected)]
                min_code = sel_df.sort_values("avg_marcap").iloc[0]["code"]
                if min_code != row["code"]:
                    final_selected.discard(min_code)

    # === 소형주 제외 (방법론 6.4.5) ===
    if marcap_300th > 0:
        to_remove = []
        for code in list(final_selected):
            stock = eligible[eligible["code"] == code]
            if not stock.empty and stock.iloc[0]["avg_marcap"] < marcap_300th:
                to_remove.append(code)
        for code in to_remove:
            final_selected.discard(code)
            # 대체 종목: 유동성 충족 잔여종목 중 시총 최대
            remaining = eligible[
                (~eligible["code"].isin(final_selected))
                & (eligible["code"].isin(liquidity_ok))
            ].sort_values("avg_marcap", ascending=False)
            if not remaining.empty:
                final_selected.add(remaining.iloc[0]["code"])

    # === 결과 정리 ===
    details = eligible[eligible["code"].isin(final_selected)].copy()
    details = details.sort_values("avg_marcap", ascending=False)
    details["selection_rank"] = range(1, len(details) + 1)

    sector_summary = (
        details.groupby("sector")
        .agg(
            count=("code", "count"),
            total_marcap=("avg_marcap", "sum"),
        )
        .sort_values("total_marcap", ascending=False)
    )

    return {
        "selected": list(details["code"]),
        "details": details,
        "sector_summary": sector_summary,
        "excluded_sectors": excluded_sectors,
    }


def predict_changes(
    kosdaq_df: pd.DataFrame,
    gics_map: dict,
    current_150: list,
    avg_data: pd.DataFrame = None,
) -> dict:
    """현재 구성종목과 시뮬레이션 결과를 비교하여 편입/편출 예상

    Returns:
        dict:
            new_selected: 시뮬레이션 결과 선정 종목
            additions: 신규 편입 예상 종목 리스트 [{code, name, sector, marcap}]
            removals: 편출 예상 종목 리스트 [{code, name, sector, marcap}]
            retained: 유지 종목 수
    """
    result = select_kosdaq150(kosdaq_df, gics_map, current_150, avg_data)
    new_selected = set(result["selected"])
    current_set = set(current_150)

    additions = new_selected - current_set
    removals = current_set - new_selected
    retained = current_set & new_selected

    eligible = build_eligible_stocks(kosdaq_df, gics_map, avg_data)

    def stock_info(code):
        row = eligible[eligible["code"] == code]
        if row.empty:
            row = kosdaq_df[kosdaq_df["code"] == code]
        if row.empty:
            return {"code": code, "name": "?", "sector": "?", "marcap": 0}
        r = row.iloc[0]
        return {
            "code": code,
            "name": r.get("name", "?"),
            "sector": r.get("sector", gics_map.get(code, "?")),
            "marcap": r.get("avg_marcap", r.get("marcap", 0)),
        }

    additions_list = sorted(
        [stock_info(c) for c in additions],
        key=lambda x: x["marcap"],
        reverse=True,
    )
    removals_list = sorted(
        [stock_info(c) for c in removals],
        key=lambda x: x["marcap"],
        reverse=True,
    )

    return {
        "new_selected": result["selected"],
        "additions": additions_list,
        "removals": removals_list,
        "retained": len(retained),
        "sector_summary": result["sector_summary"],
    }
