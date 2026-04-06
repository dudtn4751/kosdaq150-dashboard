"""
롱숏 페어 파인더 - KOSPI/KOSDAQ 전 종목 상관분석
"""

import time
import json
import pickle
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

import numpy as np
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import FinanceDataReader as fdr

from style import COLORS, PLOTLY_LAYOUT, styled_plotly, now_kst

warnings.filterwarnings("ignore")

# ── 설정 ──────────────────────────────────────────────
CACHE_DIR = Path(__file__).parent.parent / "cache_pair"
CACHE_DIR.mkdir(exist_ok=True)

PERIOD_MAP = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365, "3Y": 1095, "10Y": 3650}
PERIOD_LABELS = {"1M": "1개월", "3M": "3개월", "6M": "6개월", "1Y": "1년", "3Y": "3년", "10Y": "10년"}
MIN_TRADING_DAYS = {"1M": 10, "3M": 30, "6M": 60, "1Y": 120, "3Y": 360, "10Y": 1200}

# ── 섹터 분류 (WICS/GICS 기반) ────────────────────────
GICS_CODES = {
    "G10": "에너지",
    "G15": "소재",
    "G20": "산업재",
    "G25": "자유소비재",
    "G30": "필수소비재",
    "G35": "헬스케어",
    "G40": "금융",
    "G45": "정보기술",
    "G50": "커뮤니케이션서비스",
    "G55": "유틸리티",
    "G60": "부동산",
}


def _fetch_wics_sectors():
    """WISE Index API에서 GICS 섹터 분류 조회 → {종목코드: 섹터명}"""
    # 최근 거래일 자동 탐색
    from datetime import date
    d = date.today()
    for _ in range(10):
        if d.weekday() < 5:
            break
        d -= timedelta(days=1)
    dt = d.strftime("%Y%m%d")

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    sector_map = {}
    for code, name in GICS_CODES.items():
        try:
            url = f"https://www.wiseindex.com/Index/GetIndexComponets?ceil_yn=0&dt={dt}&sec_cd={code}"
            r = requests.get(url, headers=headers, timeout=15)
            for item in r.json().get("list", []):
                sector_map[item["CMP_CD"]] = name
        except Exception:
            pass

    # 캐시 파일 폴백
    cache_path = CACHE_DIR / "wics_sectors.json"
    if len(sector_map) < 100:
        if cache_path.exists():
            with open(cache_path, "r", encoding="utf-8") as f:
                sector_map = json.load(f)
    else:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(sector_map, f, ensure_ascii=False)

    return sector_map


def fmt_cap(val):
    if pd.isna(val) or val == 0:
        return "-"
    if val >= 1e12:
        return f"{val/1e12:.1f}조"
    if val >= 1e8:
        return f"{val/1e8:.0f}억"
    return f"{val:,.0f}"


# ── 데이터 로딩 ───────────────────────────────────────
_SECTOR_VERSION = 8  # WICS/GICS 전면 전환

@st.cache_data(ttl=3600 * 12, show_spinner=False)
def load_stock_list(_sector_version=_SECTOR_VERSION):
    cache_file = CACHE_DIR / f"stock_list_v{_sector_version}.pkl"
    if cache_file.exists():
        mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
        if (datetime.now() - mtime).days < 1:
            with open(cache_file, "rb") as f:
                return pickle.load(f)

    kospi = fdr.StockListing("KOSPI")
    kosdaq = fdr.StockListing("KOSDAQ")
    kospi["_market"] = "KOSPI"
    kosdaq["_market"] = "KOSDAQ"
    price_df = pd.concat([kospi, kosdaq], ignore_index=True)
    price_df = price_df[["Code", "Name", "_market", "Marcap", "Close", "Volume"]].copy()
    price_df.columns = ["ticker", "name", "market", "market_cap", "close", "volume"]

    df = price_df.copy()
    df = df[(df["close"] > 0) & (df["volume"] > 0)].reset_index(drop=True)

    # WICS/GICS 섹터 분류 (WISE Index API)
    wics = _fetch_wics_sectors()
    df["sector"] = df["ticker"].map(wics).fillna("미분류")

    with open(cache_file, "wb") as f:
        pickle.dump(df, f)
    return df


def _fetch_raw(ticker, start_date):
    """단일 종목 종가 fetch"""
    try:
        df = fdr.DataReader(ticker, start_date)
        if df is not None and not df.empty and "Close" in df.columns:
            return ticker, df["Close"]
    except Exception:
        pass
    return ticker, None


def load_prices(tickers, days, progress_bar=None):
    """병렬 fetch + 최장 기간 캐시 재활용"""
    cache_file = CACHE_DIR / f"prices_{days}d.pkl"

    # 1) 당일 캐시 히트
    if cache_file.exists():
        mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
        if mtime.date() == datetime.now().date():
            with open(cache_file, "rb") as f:
                cached = pickle.load(f)
                available = [t for t in tickers if t in cached.columns]
                if len(available) > len(tickers) * 0.8:
                    return cached[available]

    # 2) 더 긴 기간 캐시가 있으면 슬라이싱으로 재활용
    cutoff = datetime.now() - timedelta(days=days + 30)
    for longer_days in sorted(PERIOD_MAP.values(), reverse=True):
        if longer_days <= days:
            continue
        longer_cache = CACHE_DIR / f"prices_{longer_days}d.pkl"
        if longer_cache.exists():
            lmtime = datetime.fromtimestamp(longer_cache.stat().st_mtime)
            if lmtime.date() == datetime.now().date():
                with open(longer_cache, "rb") as f:
                    longer_df = pickle.load(f)
                available = [t for t in tickers if t in longer_df.columns]
                if len(available) > len(tickers) * 0.7:
                    sliced = longer_df.loc[longer_df.index >= cutoff, available]
                    if len(sliced) > 0:
                        with open(cache_file, "wb") as f:
                            pickle.dump(sliced, f)
                        return sliced

    # 3) 병렬 fetch (배치 + 타임아웃)
    start_date = cutoff.strftime("%Y-%m-%d")
    total = len(tickers)
    results = {}
    done = 0
    batch_size = 30
    workers = 10

    for b_start in range(0, total, batch_size):
        batch = tickers[b_start:b_start + batch_size]
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_fetch_raw, t, start_date): t for t in batch}
            for fut in futures:
                try:
                    tk, series = fut.result(timeout=15)
                    if series is not None:
                        results[tk] = series
                except (FuturesTimeout, Exception):
                    pass
                done += 1
        if progress_bar:
            progress_bar.progress(
                done / total,
                text=f"가격 로딩 {done}/{total} ({len(results)}개 완료)",
            )

    pdf = pd.DataFrame(results).sort_index()
    with open(cache_file, "wb") as f:
        pickle.dump(pdf, f)
    return pdf


def calc_correlations(target, price_df, min_days=20):
    if target not in price_df.columns:
        return pd.Series(dtype=float)
    rets = price_df.pct_change().dropna(how="all")
    if target not in rets.columns:
        return pd.Series(dtype=float)
    tgt = rets[target].dropna()
    if len(tgt) < min_days:
        return pd.Series(dtype=float)
    corr = rets.corrwith(tgt)
    return corr.drop(target, errors="ignore").dropna()


# ── 차트 ──────────────────────────────────────────────
def chart_sector_bar(sector_data):
    """섹터별 최저 상관계수 수평 바 차트"""
    fig = go.Figure(data=go.Bar(
        x=sector_data["corr"],
        y=sector_data["label"],
        orientation="h",
        marker=dict(
            color=sector_data["corr"],
            colorscale=[[0, COLORS["accent_red"]], [0.5, COLORS["accent_yellow"]], [1, COLORS["accent_green"]]],
            cmin=-1, cmax=1,
        ),
        text=sector_data["corr"].apply(lambda x: f"{x:+.3f}"),
        textposition="outside",
        textfont=dict(color=COLORS["text"], size=11),
        hovertemplate="%{y}<br>상관계수: %{x:.4f}<extra></extra>",
    ))
    fig.update_layout(
        height=max(300, len(sector_data) * 32),
        xaxis=dict(title="상관계수", range=[min(-0.5, sector_data["corr"].min() - 0.1), 1]),
        yaxis=dict(tickfont=dict(size=11)),
    )
    return styled_plotly(fig)


def chart_heatmap(corr_df, periods):
    """기간별 상관계수 히트맵"""
    fig = go.Figure(data=go.Heatmap(
        z=corr_df.values,
        x=[PERIOD_LABELS.get(p, p) for p in corr_df.columns],
        y=corr_df.index,
        colorscale=[[0, COLORS["accent_red"]], [0.3, "#ff8866"], [0.5, COLORS["accent_yellow"]],
                     [0.7, "#88cc88"], [1, COLORS["accent_green"]]],
        zmin=-1, zmax=1,
        text=np.round(corr_df.values, 3),
        texttemplate="%{text}",
        textfont={"size": 11, "color": COLORS["text"]},
        hovertemplate="종목: %{y}<br>기간: %{x}<br>상관계수: %{z:.4f}<extra></extra>",
        colorbar=dict(
            title=dict(text="상관계수", font=dict(color=COLORS["text"])),
            tickfont=dict(color=COLORS["text"]),
        ),
    ))
    fig.update_layout(height=max(350, len(corr_df) * 28))
    return styled_plotly(fig)


def chart_price_compare(t_prices, p_prices, t_name, p_name):
    """두 종목 정규화 가격 비교"""
    idx = t_prices.dropna().index.intersection(p_prices.dropna().index)
    if len(idx) < 5:
        return None
    t_n = t_prices[idx] / t_prices[idx].iloc[0] * 100
    p_n = p_prices[idx] / p_prices[idx].iloc[0] * 100

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=idx, y=t_n, name=t_name,
                             line=dict(color=COLORS["accent"], width=2.5)))
    fig.add_trace(go.Scatter(x=idx, y=p_n, name=p_name,
                             line=dict(color=COLORS["accent_red"], width=2.5)))
    fig.update_layout(
        height=350,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis=dict(title="정규화 (기준=100)"),
        hovermode="x unified",
    )
    return styled_plotly(fig)


def chart_scatter(rets_df, t_name, p_name):
    """일간 수익률 산점도"""
    fig = px.scatter(rets_df, x=t_name, y=p_name)
    fig.update_traces(marker=dict(color=COLORS["accent"], size=6, opacity=0.7))
    fig.update_layout(
        height=350,
        xaxis=dict(title=f"{t_name} 수익률", tickformat=".1%"),
        yaxis=dict(title=f"{p_name} 수익률", tickformat=".1%"),
    )
    return styled_plotly(fig)


# ── 결과 테이블 ───────────────────────────────────────
def build_result_df(corr_series, stock_df, top_n=30):
    sorted_corr = corr_series.sort_values()
    rows = []
    for ticker, cv in sorted_corr.head(top_n).items():
        info = stock_df[stock_df["ticker"] == ticker]
        if info.empty:
            continue
        r = info.iloc[0]
        rows.append({
            "순위": len(rows) + 1,
            "코드": ticker,
            "종목명": r["name"],
            "시장": r["market"],
            "섹터": r.get("sector", "기타"),
            "업종": r.get("industry", ""),
            "시가총액": fmt_cap(r.get("market_cap", 0)),
            "시가총액(원)": r.get("market_cap", 0),
            "상관계수": round(cv, 4),
        })
    return pd.DataFrame(rows)


# ── 메인 페이지 ───────────────────────────────────────
# 히어로 헤더
st.markdown(f"""
<div class="ark-hero" style="padding: 32px 40px; margin-bottom: 24px;">
    <h1 style="font-size: 2rem; margin-bottom: 4px;">📊 롱숏 페어 파인더</h1>
    <div class="subtitle">KOSPI / KOSDAQ 전 종목 상관 분석 기반 페어 트레이딩 탐색</div>
</div>
""", unsafe_allow_html=True)

# 종목 리스트 로딩
with st.spinner("종목 리스트 로딩 중..."):
    stock_df = load_stock_list()

# ── 컨트롤 패널 ───────────────────────────────────────
st.markdown(f'<div class="section-header">분석 설정</div>', unsafe_allow_html=True)

ctrl_c1, ctrl_c2, ctrl_c3, ctrl_c4 = st.columns([2, 3, 1, 1])

with ctrl_c1:
    search_input = st.text_input("종목코드 / 종목명", placeholder="005930 또는 삼성전자")

with ctrl_c2:
    period_options = list(PERIOD_MAP.keys())
    selected_periods = st.multiselect(
        "분석 기간",
        period_options,
        default=["1M", "3M", "6M", "1Y"],
        format_func=lambda x: PERIOD_LABELS[x],
    )

with ctrl_c3:
    cap_options = {"전체": 0, "100억+": 1e10, "500억+": 5e10, "1000억+": 1e11, "5000억+": 5e11, "1조+": 1e12, "5조+": 5e12}
    cap_filter = st.selectbox("최소 시총", list(cap_options.keys()), index=4)
    min_cap = cap_options[cap_filter]

with ctrl_c4:
    top_n = st.selectbox("표시 수", [10, 15, 20, 30, 50], index=2)

# 종목 매칭
target_ticker = target_name = None
if search_input:
    search_input = search_input.strip()
    match = stock_df[stock_df["ticker"] == search_input]
    if match.empty:
        match = stock_df[stock_df["name"].str.contains(search_input, na=False)]
    if len(match) == 1:
        target_ticker = match.iloc[0]["ticker"]
        target_name = match.iloc[0]["name"]
    elif len(match) > 1:
        selected = st.selectbox(
            "검색 결과에서 선택",
            match.index.tolist(),
            format_func=lambda i: f"{match.loc[i, 'ticker']}  {match.loc[i, 'name']}  ({match.loc[i, 'market']})  {fmt_cap(match.loc[i, 'market_cap'])}",
        )
        target_ticker = match.loc[selected, "ticker"]
        target_name = match.loc[selected, "name"]
    elif search_input:
        st.warning("종목을 찾을 수 없습니다")

# 섹터 필터
all_sectors = sorted(stock_df["sector"].unique())
with st.expander("섹터 필터 (선택 시 해당 섹터만 분석)", expanded=False):
    sector_filter = st.multiselect("섹터", all_sectors)

# 실행
run_btn = st.button("🔍 분석 실행", type="primary", use_container_width=True,
                     disabled=(target_ticker is None or len(selected_periods) == 0))

st.markdown("---")

# ── 분석 실행 ─────────────────────────────────────────
if run_btn and target_ticker:
    target_info = stock_df[stock_df["ticker"] == target_ticker].iloc[0]
    target_sector = target_info.get("sector", "기타")

    # 타겟 정보 카드
    t_cols = st.columns(5)
    t_cols[0].metric("종목", f"{target_name}")
    t_cols[1].metric("코드", target_ticker)
    t_cols[2].metric("시장", target_info["market"])
    t_cols[3].metric("섹터", target_sector)
    t_cols[4].metric("시가총액", fmt_cap(target_info.get("market_cap", 0)))

    # 유니버스
    universe = stock_df.copy()
    if min_cap > 0:
        universe = universe[universe["market_cap"] >= min_cap]
    if sector_filter:
        universe = universe[(universe["sector"].isin(sector_filter)) | (universe["ticker"] == target_ticker)]

    all_tickers = universe["ticker"].tolist()
    if target_ticker not in all_tickers:
        all_tickers.append(target_ticker)

    st.caption(f"분석 대상: {len(all_tickers):,}종목 | 기간: {len(selected_periods)}개 | 기준: {now_kst()}")

    # 기간별 분석 (긴 기간 먼저 → 짧은 기간은 캐시 슬라이싱)
    results = {}
    price_cache = {}
    progress = st.progress(0, text="분석 준비 중...")

    sorted_periods = sorted(selected_periods, key=lambda p: PERIOD_MAP[p], reverse=True)
    total_periods = len(sorted_periods)

    for pi, period in enumerate(sorted_periods):
        days = PERIOD_MAP[period]
        min_days = MIN_TRADING_DAYS[period]
        progress.progress(pi / total_periods, text=f"[{PERIOD_LABELS[period]}] 가격 데이터 로딩...")

        pdf = load_prices(all_tickers, days, progress_bar=progress)
        price_cache[period] = pdf

        progress.progress((pi + 0.95) / total_periods, text=f"[{PERIOD_LABELS[period]}] 상관계수 계산...")
        corr = calc_correlations(target_ticker, pdf, min_days=min_days)
        results[period] = corr

    # 사용자가 선택한 순서로 복원
    results = {p: results[p] for p in selected_periods}
    price_cache = {p: price_cache[p] for p in selected_periods}

    progress.progress(1.0, text="분석 완료!")
    time.sleep(0.3)
    progress.empty()

    # ── 요약 메트릭 ──
    st.markdown(f'<div class="section-header">기간별 요약</div>', unsafe_allow_html=True)
    sum_cols = st.columns(len(selected_periods))
    for i, p in enumerate(selected_periods):
        c = results[p]
        if c.empty:
            sum_cols[i].metric(PERIOD_LABELS[p], "데이터 부족")
        else:
            neg = (c < 0).sum()
            sum_cols[i].metric(
                PERIOD_LABELS[p],
                f"{c.min():+.4f}",
                delta=f"음의상관 {neg}종목" if neg > 0 else "음의상관 없음",
                delta_color="normal" if neg > 0 else "off",
            )

    # ── 탭 ──
    tab_labels = [f"📋 {PERIOD_LABELS[p]}" for p in selected_periods]
    if len(selected_periods) > 1:
        tab_labels.append("📊 멀티기간 종합")
    tab_labels.append("📈 가격 비교")
    tabs = st.tabs(tab_labels)

    # 기간별 탭
    for ti, period in enumerate(selected_periods):
        with tabs[ti]:
            corr = results[period]
            if corr.empty:
                st.warning(f"{PERIOD_LABELS[period]}: 데이터 부족")
                continue

            rdf = build_result_df(corr, stock_df, top_n=top_n)
            left, right = st.columns([3, 2])

            with left:
                st.markdown(f'<div class="section-header">음의 상관 / 저상관 TOP {top_n}</div>',
                            unsafe_allow_html=True)
                display = rdf[["순위", "코드", "종목명", "시장", "섹터", "시가총액", "상관계수"]].copy()
                st.dataframe(
                    display.style.applymap(
                        lambda v: f"color: {COLORS['accent_red']}; font-weight: 700"
                        if isinstance(v, (int, float)) and v < 0
                        else (f"color: {COLORS['accent_yellow']}"
                              if isinstance(v, (int, float)) and v < 0.2 else ""),
                        subset=["상관계수"],
                    ),
                    use_container_width=True,
                    height=min(700, 35 * len(display) + 38),
                    hide_index=True,
                )

            with right:
                # 섹터별 바 차트
                st.markdown(f'<div class="section-header">섹터별 최저 상관</div>', unsafe_allow_html=True)
                sec_min = rdf.loc[rdf.groupby("섹터")["상관계수"].idxmin()].copy()
                sec_min = sec_min.sort_values("상관계수")
                sec_min["label"] = sec_min["섹터"] + " / " + sec_min["종목명"]
                sd = sec_min[["label", "상관계수"]].rename(columns={"상관계수": "corr"})
                st.plotly_chart(chart_sector_bar(sd), use_container_width=True)

                # 동일 섹터
                if target_sector != "기타":
                    same = rdf[rdf["섹터"] == target_sector].head(5)
                    if not same.empty:
                        st.markdown(f'<div class="section-header">동일 섹터 [{target_sector}]</div>',
                                    unsafe_allow_html=True)
                        st.dataframe(same[["코드", "종목명", "시가총액", "상관계수"]],
                                     use_container_width=True, hide_index=True)

    # 멀티기간 탭
    if len(selected_periods) > 1:
        with tabs[len(selected_periods)]:
            st.markdown(f'<div class="section-header">멀티기간 종합 분석</div>', unsafe_allow_html=True)

            all_corr = pd.DataFrame({p: results[p] for p in selected_periods})
            avg_corr = all_corr.mean(axis=1).dropna().sort_values()
            top_tickers = avg_corr.head(top_n).index.tolist()

            mrows = []
            for rank, tk in enumerate(top_tickers, 1):
                info = stock_df[stock_df["ticker"] == tk]
                if info.empty:
                    continue
                r = info.iloc[0]
                row = {"순위": rank, "코드": tk, "종목명": r["name"], "시장": r["market"],
                       "섹터": r.get("sector", "기타"), "시총": fmt_cap(r.get("market_cap", 0))}
                for p in selected_periods:
                    v = all_corr.loc[tk, p] if tk in all_corr.index else np.nan
                    row[PERIOD_LABELS[p]] = round(v, 4) if pd.notna(v) else None
                row["평균"] = round(avg_corr[tk], 4)
                mrows.append(row)

            mdf = pd.DataFrame(mrows)
            corr_cols = [PERIOD_LABELS[p] for p in selected_periods] + ["평균"]
            st.dataframe(
                mdf.style.applymap(
                    lambda v: f"color: {COLORS['accent_red']}; font-weight: 700"
                    if isinstance(v, (int, float)) and v is not None and v < 0
                    else (f"color: {COLORS['accent_yellow']}"
                          if isinstance(v, (int, float)) and v is not None and v < 0.2
                          else f"color: {COLORS['text']}"),
                    subset=corr_cols,
                ),
                use_container_width=True,
                height=min(700, 35 * len(mdf) + 38),
                hide_index=True,
            )

            # 히트맵
            st.markdown(f'<div class="section-header">상관계수 히트맵</div>', unsafe_allow_html=True)
            hm = all_corr.loc[top_tickers, selected_periods].copy()
            name_map = stock_df.set_index("ticker")["name"].to_dict()
            hm.index = [f"{name_map.get(t, t)} ({t})" for t in hm.index]
            st.plotly_chart(chart_heatmap(hm, selected_periods), use_container_width=True)

    # 가격 비교 탭
    ptab = len(selected_periods) + (1 if len(selected_periods) > 1 else 0)
    with tabs[ptab]:
        st.markdown(f'<div class="section-header">가격 추이 비교</div>', unsafe_allow_html=True)

        if len(selected_periods) > 1:
            adf = pd.DataFrame({p: results[p] for p in selected_periods})
            avg = adf.mean(axis=1).dropna().sort_values()
        else:
            avg = results[selected_periods[0]].sort_values()

        top_pairs = avg.head(10).index.tolist()
        pair_labels = []
        for t in top_pairs:
            info = stock_df[stock_df["ticker"] == t]
            pair_labels.append(f"{info.iloc[0]['name']} ({t})" if not info.empty else t)

        cc1, cc2 = st.columns(2)
        with cc1:
            sel_label = st.selectbox("비교 종목", pair_labels, index=0)
            sel_ticker = top_pairs[pair_labels.index(sel_label)]
        with cc2:
            comp_period = st.selectbox("비교 기간", selected_periods,
                                        format_func=lambda x: PERIOD_LABELS[x])

        if comp_period in price_cache and sel_ticker:
            pdf = price_cache[comp_period]
            p_info = stock_df[stock_df["ticker"] == sel_ticker]
            p_name = p_info.iloc[0]["name"] if not p_info.empty else sel_ticker

            if target_ticker in pdf.columns and sel_ticker in pdf.columns:
                fig = chart_price_compare(pdf[target_ticker], pdf[sel_ticker], target_name, p_name)
                if fig:
                    st.plotly_chart(fig, use_container_width=True)

                rets = pdf[[target_ticker, sel_ticker]].pct_change().dropna()
                sc = st.columns(4)
                cv = rets[target_ticker].corr(rets[sel_ticker])
                sc[0].metric("상관계수", f"{cv:+.4f}")

                tr = (pdf[target_ticker].dropna().iloc[-1] / pdf[target_ticker].dropna().iloc[0] - 1) * 100
                pr = (pdf[sel_ticker].dropna().iloc[-1] / pdf[sel_ticker].dropna().iloc[0] - 1) * 100
                sc[1].metric(f"{target_name} 수익률", f"{tr:+.1f}%")
                sc[2].metric(f"{p_name} 수익률", f"{pr:+.1f}%")
                sc[3].metric("스프레드", f"{abs(tr - pr):.1f}%p")

                st.markdown(f'<div class="section-header">일간 수익률 산점도</div>',
                            unsafe_allow_html=True)
                sdf = rets.rename(columns={target_ticker: target_name, sel_ticker: p_name})
                st.plotly_chart(chart_scatter(sdf, target_name, p_name), use_container_width=True)

# ── 분석 방법론 ──
st.markdown("---")
with st.expander("분석 방법론 및 기준", expanded=False):
    st.markdown(f"""
<div style="color: {COLORS['text']}; line-height: 1.9; font-size: 0.92rem;">

#### 상관계수 산출 방식

본 분석은 **피어슨 상관계수(Pearson Correlation Coefficient)**를 사용하여
두 종목 간 일간 수익률의 선형 관계를 측정합니다.

$$
\\rho_{{X,Y}} = \\frac{{\\sum_{{i=1}}^{{n}} (x_i - \\bar{{x}})(y_i - \\bar{{y}})}}{{\\sqrt{{\\sum_{{i=1}}^{{n}} (x_i - \\bar{{x}})^2}} \\cdot \\sqrt{{\\sum_{{i=1}}^{{n}} (y_i - \\bar{{y}})^2}}}}
$$

- $x_i$, $y_i$ : 각 종목의 $i$번째 거래일 일간 수익률
- $\\bar{{x}}$, $\\bar{{y}}$ : 분석 기간 내 평균 일간 수익률
- 결과 범위 : **-1** (완전 역상관) ~ **+1** (완전 양상관)

---

#### 수익률 계산

일간 **단순 수익률**을 사용합니다.

$$
r_t = \\frac{{P_t - P_{{t-1}}}}{{P_{{t-1}}}}
$$

- $P_t$ : $t$일의 종가 (수정주가 기준)

---

#### 분석 기간별 최소 거래일 기준

상관계수의 통계적 유의성을 확보하기 위해 기간별 최소 거래일 수를 적용합니다.

| 분석 기간 | 캘린더 일수 | 최소 거래일 | 비고 |
|:---:|:---:|:---:|:---|
| 1개월 | 30일 | 10일 | 단기 모멘텀 |
| 3개월 | 90일 | 30일 | 분기 추세 |
| 6개월 | 180일 | 60일 | 중기 추세 |
| 1년 | 365일 | 120일 | 연간 사이클 |
| 3년 | 1,095일 | 360일 | 장기 구조적 관계 |
| 10년 | 3,650일 | 1,200일 | 초장기 구조적 관계 |

최소 거래일 미달 종목은 해당 기간 분석에서 자동 제외됩니다.

---

#### 섹터 분류 기준

**WICS(WISE Industry Classification Standard)** 기반 **GICS 11개 섹터**로 분류합니다.
WISE Index API에서 실시간으로 종목별 섹터를 조회하며, 실질 산업 기준으로 분류됩니다.

> 에너지 · 소재 · 산업재 · 자유소비재 · 필수소비재 · 헬스케어 · 금융 ·
> 정보기술 · 커뮤니케이션서비스 · 유틸리티 · 부동산

---

#### 데이터 소스

| 항목 | 출처 |
|:---|:---|
| 종목 리스트 · 시가총액 | FinanceDataReader (`StockListing`) |
| 섹터 분류 | WISE Index API (WICS/GICS 11개 섹터) |
| 일별 종가 | FinanceDataReader (`DataReader`) |

- 가격 데이터는 **수정주가** 기준이며, 당일 캐시를 사용합니다.
- 거래정지 · 상장폐지 종목은 종가 또는 거래량이 0인 경우 자동 제외됩니다.

---

#### 해석 시 유의사항

- 피어슨 상관계수는 **선형 관계**만 측정하며, 비선형 역상관 관계는 포착하지 못합니다.
- 과거 상관관계가 미래에도 유지된다는 보장이 없으며, 시장 국면 전환 시 상관 구조가 급변할 수 있습니다.
- 극단적 시장 이벤트(급등/급락)가 포함된 기간은 상관계수가 왜곡될 수 있습니다.
- 멀티기간 종합 분석의 평균값은 **단순 산술 평균**이며, 기간별 가중치를 적용하지 않습니다.

</div>
""", unsafe_allow_html=True)

# ── 푸터 ──
st.markdown(f"""
<div class="ark-footer">
    ARK IMPACT 분석 대시보드 · 롱숏 페어 파인더 · 데이터: FinanceDataReader + KRX · {now_kst()}
</div>
""", unsafe_allow_html=True)
