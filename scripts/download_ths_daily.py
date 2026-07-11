from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from tqdm import tqdm

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ths_ifind_daily import (  # noqa: E402
    EXTENDED_COLUMNS,
    STANDARD_COLUMNS,
    fetch_ifind_history,
    ifind_session,
    load_us_exchange_suffixes,
    merge_daily_csv,
    normalize_cn_ticker,
    normalize_hk_ticker,
    normalize_us_ticker,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT_DIR / "config"
RAW_DAILY_DIR = ROOT_DIR / "data" / "raw" / "daily"
RAW_CN_DAILY_DIR = ROOT_DIR / "data" / "raw" / "cn_daily"
RAW_HK_DAILY_DIR = ROOT_DIR / "data" / "raw" / "hk_daily"


def ticker_file_for_market(market: str) -> Path:
    if market == "cn":
        return CONFIG_DIR / "cn_stock_pool.csv"
    if market == "hk":
        return CONFIG_DIR / "hk_stock_pool.csv"
    return CONFIG_DIR / "tickers.txt"


def raw_dir_for_market(market: str) -> Path:
    if market == "cn":
        return RAW_CN_DAILY_DIR
    if market == "hk":
        return RAW_HK_DAILY_DIR
    return RAW_DAILY_DIR


def normalize_ticker_for_market(ticker: str, market: str) -> str:
    if market == "cn":
        return normalize_cn_ticker(ticker)
    if market == "hk":
        return normalize_hk_ticker(ticker)
    return normalize_us_ticker(ticker)


def load_tickers_from_file(path: Path, market: str, limit: int | None = None) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Ticker file not found: {path}")
    if path.suffix.lower() == ".csv":
        import pandas as pd

        df = pd.read_csv(path, dtype={"ticker": str}).fillna("")
        raw_items = df["ticker"].tolist()
    else:
        raw_items = [
            line.strip()
            for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    tickers: list[str] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        ticker = normalize_ticker_for_market(str(raw_item), market)
        if ticker and ticker not in seen:
            tickers.append(ticker)
            seen.add(ticker)
    return tickers[:limit] if limit else tickers


def ticker_csv_path(ticker: str, market: str) -> Path:
    return raw_dir_for_market(market) / f"{normalize_ticker_for_market(ticker, market)}.csv"


def already_downloaded(ticker: str, market: str) -> bool:
    path = ticker_csv_path(ticker, market)
    return path.exists() and path.stat().st_size > 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download daily OHLCV data from Tonghuashun iFinD.")
    parser.add_argument("--market", choices=["us", "cn", "hk"], default="us", help="Market to download. Defaults to us.")
    parser.add_argument("--tickers", default=None, help="Comma-separated ticker subset.")
    parser.add_argument("--tickers-file", default=None, help="Ticker file override.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N tickers.")
    parser.add_argument("--years", type=int, default=2, help="Number of recent years to download.")
    parser.add_argument("--end-date", default=date.today().isoformat(), help="End date in YYYY-MM-DD.")
    parser.add_argument("--sleep-seconds", type=float, default=0.0, help="Sleep after each ticker request.")
    parser.add_argument("--force", action="store_true", help="Redownload even when CSV already exists.")
    parser.add_argument("--include-benchmark", action="store_true", help="Append the market benchmark ticker.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    market = args.market
    end = date.fromisoformat(args.end_date)
    start = end - timedelta(days=365 * args.years + 7)

    if args.tickers:
        tickers = [normalize_ticker_for_market(item, market) for item in args.tickers.split(",") if item.strip()]
    else:
        tickers_file = Path(args.tickers_file) if args.tickers_file else ticker_file_for_market(market)
        tickers = load_tickers_from_file(tickers_file, market, args.limit)

    if args.include_benchmark:
        benchmark = "QQQ" if market == "us" else "000905" if market == "cn" else "HSTECH"
        if benchmark not in tickers:
            tickers.append(benchmark)

    output_columns = STANDARD_COLUMNS if market == "us" else EXTENDED_COLUMNS
    us_exchange_suffixes = load_us_exchange_suffixes() if market == "us" else {}
    stats = {"success": 0, "skipped": 0, "failed": 0}

    print(f"Project root: {ROOT_DIR}")
    print(f"Market: {market}")
    print(f"Tickers: {len(tickers)}")
    print(f"Date range: {start.isoformat()} to {end.isoformat()}")
    print(f"Raw data dir: {raw_dir_for_market(market)}")

    with ifind_session():
        for ticker in tqdm(tickers, desc=f"{market} iFinD daily", unit="ticker"):
            if not args.force and already_downloaded(ticker, market):
                stats["skipped"] += 1
                continue
            try:
                result = fetch_ifind_history(ticker, market, start, end, us_exchange_suffixes)
                merge_daily_csv(
                    ticker_csv_path(ticker, market),
                    normalize_ticker_for_market(ticker, market),
                    result.frame,
                    output_columns,
                )
                stats["success"] += 1
            except Exception as exc:  # noqa: BLE001 - vendor SDK errors include plain dicts/strings.
                stats["failed"] += 1
                tqdm.write(f"[failed] {ticker}: {exc}")
            if args.sleep_seconds > 0:
                time.sleep(args.sleep_seconds)

    print("Download finished")
    print(f"success={stats['success']} skipped={stats['skipped']} failed={stats['failed']}")


if __name__ == "__main__":
    main()
