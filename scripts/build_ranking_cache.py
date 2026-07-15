from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import CN_DEFAULT_BENCHMARK, DEFAULT_BENCHMARK, HK_DEFAULT_BENCHMARK  # noqa: E402
from app.services.data_loader import (  # noqa: E402
    load_daily_data,
    load_optionable_status,
    load_stock_profiles_for_market,
    load_ticker_file_for_market,
    normalize_market,
    normalize_ticker_for_market,
)
from app.services.ranking_service import (  # noqa: E402
    build_and_cache_ranking_frame,
    ranking_cache_path,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build CSV caches for daily Nasdaq-100 ranking results.")
    parser.add_argument("--windows", default="10,20", help="Comma-separated ranking windows, for example 10,20.")
    parser.add_argument("--days", type=int, default=10, help="Number of recent benchmark trading days to cache.")
    parser.add_argument("--end-date", default=None, help="Latest cache date in YYYY-MM-DD. Defaults to latest benchmark date.")
    parser.add_argument("--benchmark", default=None, help="Benchmark ticker. Defaults to QQQ for US, 000905 for CN.")
    parser.add_argument("--market", choices=["us", "cn", "hk"], default="us", help="Market to build: us, cn, or hk.")
    return parser.parse_args()


def recent_trading_dates(benchmark: str, market: str, days: int, end_date: date | None) -> list[date]:
    df = load_daily_data(benchmark, market)
    if end_date is not None:
        df = df[df["date"].dt.date <= end_date]
    dates = [item.date() for item in df["date"].dropna().tail(days)]
    if not dates:
        raise ValueError(f"No trading dates found for {benchmark}")
    return dates


def prune_cache_dates(window: int, market: str, benchmark: str, dates: list[date]) -> None:
    path = ranking_cache_path(window, market)
    if not path.exists() or path.stat().st_size == 0:
        return
    keep_dates = {item.isoformat() for item in dates}
    df = pd.read_csv(path, dtype={"ticker": str, "benchmark": str})
    df = df[
        (df["benchmark"].astype(str) == benchmark)
        & (df["as_of_date"].astype(str).isin(keep_dates))
    ].copy()
    df.to_csv(path, index=False, encoding="utf-8-sig")


def main() -> None:
    args = parse_args()
    windows = [int(item.strip()) for item in args.windows.split(",") if item.strip()]
    market = normalize_market(args.market)
    default_benchmark = CN_DEFAULT_BENCHMARK if market == "cn" else HK_DEFAULT_BENCHMARK if market == "hk" else DEFAULT_BENCHMARK
    benchmark = normalize_ticker_for_market(args.benchmark or default_benchmark, market)
    end_date = date.fromisoformat(args.end_date) if args.end_date else None
    dates = recent_trading_dates(benchmark, market, args.days, end_date)

    tickers = load_ticker_file_for_market(market)
    universe = list(tickers)
    if benchmark not in universe:
        universe.append(benchmark)

    optionable_status = {} if market in {"cn", "hk"} else load_optionable_status()
    stock_profiles = load_stock_profiles_for_market(market)

    print(f"Market: {market}")
    print(f"Benchmark: {benchmark}")
    print(f"Universe: {len(universe)} tickers")
    print(f"Dates: {dates[0].isoformat()} to {dates[-1].isoformat()} ({len(dates)})")
    print(f"Windows: {windows}")

    for window in windows:
        print(f"\nBuilding window {window}: {ranking_cache_path(window, market)}")
        for as_of_date in dates:
            try:
                df, skipped, benchmark_score = build_and_cache_ranking_frame(
                    universe=universe,
                    window=window,
                    benchmark=benchmark,
                    market=market,
                    as_of_date=as_of_date,
                    optionable_status=optionable_status,
                    stock_profiles=stock_profiles,
                )
            except ValueError as exc:
                print(f"{as_of_date.isoformat()} skipped: {exc}")
                continue
            print(
                f"{as_of_date.isoformat()} rows={len(df)} skipped={len(skipped)} "
                f"benchmark_score={benchmark_score:.3f}"
            )
        prune_cache_dates(window, market, benchmark, dates)

    print("\nRanking cache build finished.")


if __name__ == "__main__":
    main()
