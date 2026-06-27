from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import DEFAULT_BENCHMARK  # noqa: E402
from app.services.data_loader import (  # noqa: E402
    load_daily_data,
    load_optionable_status,
    load_stock_profiles,
    load_ticker_file,
    normalize_ticker,
)
from app.services.ranking_service import (  # noqa: E402
    apply_rebalance,
    build_and_cache_ranking_frame,
    ranking_cache_path,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build CSV caches for daily Nasdaq-100 ranking results.")
    parser.add_argument("--windows", default="10,20", help="Comma-separated ranking windows, for example 10,20.")
    parser.add_argument("--days", type=int, default=20, help="Number of recent benchmark trading days to cache.")
    parser.add_argument("--end-date", default=None, help="Latest cache date in YYYY-MM-DD. Defaults to latest benchmark date.")
    parser.add_argument("--benchmark", default=DEFAULT_BENCHMARK, help="Benchmark ticker. Defaults to QQQ.")
    parser.add_argument(
        "--no-rebalance",
        action="store_true",
        help="Use config/nasdaq100_tickers.txt as-is instead of applying the announced 2026-06-22 rebalance.",
    )
    return parser.parse_args()


def recent_trading_dates(benchmark: str, days: int, end_date: date | None) -> list[date]:
    df = load_daily_data(benchmark)
    if end_date is not None:
        df = df[df["date"].dt.date <= end_date]
    dates = [item.date() for item in df["date"].dropna().tail(days)]
    if not dates:
        raise ValueError(f"No trading dates found for {benchmark}")
    return dates


def main() -> None:
    args = parse_args()
    windows = [int(item.strip()) for item in args.windows.split(",") if item.strip()]
    benchmark = normalize_ticker(args.benchmark)
    end_date = date.fromisoformat(args.end_date) if args.end_date else None
    dates = recent_trading_dates(benchmark, args.days, end_date)

    tickers = load_ticker_file()
    if not args.no_rebalance:
        tickers = apply_rebalance(tickers)
    universe = list(tickers)
    if benchmark not in universe:
        universe.append(benchmark)

    optionable_status = load_optionable_status()
    stock_profiles = load_stock_profiles()

    print(f"Benchmark: {benchmark}")
    print(f"Universe: {len(universe)} tickers")
    print(f"Dates: {dates[0].isoformat()} to {dates[-1].isoformat()} ({len(dates)})")
    print(f"Windows: {windows}")

    for window in windows:
        print(f"\nBuilding window {window}: {ranking_cache_path(window)}")
        for as_of_date in dates:
            df, skipped, benchmark_score = build_and_cache_ranking_frame(
                universe=universe,
                window=window,
                benchmark=benchmark,
                as_of_date=as_of_date,
                optionable_status=optionable_status,
                stock_profiles=stock_profiles,
            )
            print(
                f"{as_of_date.isoformat()} rows={len(df)} skipped={len(skipped)} "
                f"benchmark_score={benchmark_score:.3f}"
            )

    print("\nRanking cache build finished.")


if __name__ == "__main__":
    main()
