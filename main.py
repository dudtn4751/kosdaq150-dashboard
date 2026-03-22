"""
코스닥 150 편입/편출 예측 시스템 - 메인 실행 스크립트

사용법:
    python main.py                  # 빠른 실행 (당일 스냅샷 기준)
    python main.py --full           # 정밀 실행 (6개월 일평균 데이터 사용)
    python main.py --date 2026-03-20  # 특정 기준일로 실행
"""

import argparse
import sys
from datetime import datetime

import pandas as pd

from data_collector import collect_all
from selection_engine import predict_changes


def print_header(title: str):
    width = 60
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)


def print_stock_table(stocks: list, label: str):
    if not stocks:
        print(f"\n  {label}: 없음")
        return

    print(f"\n  {label} ({len(stocks)}종목)")
    print(f"  {'순번':>4}  {'종목코드':<8} {'종목명':<16} {'섹터':<14} {'시가총액':>12}")
    print(f"  {'----':>4}  {'--------':<8} {'----------------':<16} {'--------------':<14} {'------------':>12}")

    for i, s in enumerate(stocks, 1):
        marcap = s["marcap"]
        if marcap >= 1e12:
            marcap_str = f"{marcap/1e12:.2f}조"
        else:
            marcap_str = f"{marcap/1e8:.0f}억"
        print(f"  {i:>4}  {s['code']:<8} {s['name']:<16} {s['sector']:<14} {marcap_str:>12}")


def main():
    parser = argparse.ArgumentParser(description="코스닥 150 편입/편출 예측 시스템")
    parser.add_argument("--full", action="store_true",
                        help="6개월 일평균 데이터 사용 (정밀 모드, 시간 소요)")
    parser.add_argument("--date", type=str, default=None,
                        help="심사 기준일 (YYYY-MM-DD)")
    args = parser.parse_args()

    print_header("코스닥 150 편입/편출 예측 시스템")
    print(f"  실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  모드: {'정밀 (6개월 일평균)' if args.full else '빠른 (당일 스냅샷)'}")
    if args.date:
        print(f"  기준일: {args.date}")

    # 1. 데이터 수집
    print_header("데이터 수집")
    skip_daily = not args.full
    data = collect_all(end_date=args.date, skip_daily=skip_daily)

    kosdaq = data["kosdaq_listing"]
    gics_map = data["gics_map"]
    current_150 = data["current_150"]
    avg_data = data.get("avg_data")

    if len(current_150) == 0:
        print("\n  [오류] 현재 코스닥 150 구성종목을 가져오지 못했습니다.")
        sys.exit(1)

    # 2. 편입/편출 예측
    print_header("편입/편출 예측 실행")
    result = predict_changes(kosdaq, gics_map, current_150, avg_data)

    # 3. 결과 출력
    print_header("예측 결과")
    print(f"\n  현재 구성종목: {len(current_150)}종목")
    print(f"  예측 구성종목: {len(result['new_selected'])}종목")
    print(f"  유지: {result['retained']}종목")
    print(f"  신규 편입 예상: {len(result['additions'])}종목")
    print(f"  편출 예상: {len(result['removals'])}종목")

    print_stock_table(result["additions"], "신규 편입 예상")
    print_stock_table(result["removals"], "편출 예상")

    # 4. 섹터별 요약
    print_header("섹터별 구성 요약")
    summary = result["sector_summary"]
    print(f"\n  {'섹터':<16} {'종목수':>6} {'시가총액':>14}")
    print(f"  {'----------------':<16} {'------':>6} {'--------------':>14}")
    for sector, row in summary.iterrows():
        marcap = row["total_marcap"]
        if marcap >= 1e12:
            marcap_str = f"{marcap/1e12:.1f}조"
        else:
            marcap_str = f"{marcap/1e8:.0f}억"
        print(f"  {sector:<16} {int(row['count']):>6} {marcap_str:>14}")

    print("\n" + "=" * 60)
    print("  완료")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
