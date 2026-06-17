from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from tqdm import tqdm

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from download_polygon_daily import (  # noqa: E402
    ApiKeyPool,
    FAILED_TICKERS_FILE,
    download_one_ticker,
    ensure_directories,
    get_date_range,
    load_api_keys,
    sleep_after_request,
)


def load_failed_tickers(limit: int | None = None) -> list[str]:
    if not FAILED_TICKERS_FILE.exists() or FAILED_TICKERS_FILE.stat().st_size == 0:
        return []

    df = pd.read_csv(FAILED_TICKERS_FILE)
    if "ticker" not in df.columns:
        return []

    tickers = []
    seen = set()
    for ticker in df["ticker"].dropna().astype(str):
        normalized = ticker.strip().upper()
        if normalized and normalized not in seen:
            seen.add(normalized)
            tickers.append(normalized)

    return tickers[:limit] if limit else tickers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Retry failed Polygon.io daily data downloads.")
    parser.add_argument("--limit", type=int, default=None, help="Only retry the first N failed tickers.")
    parser.add_argument("--years", type=int, default=2, help="Number of recent years to download.")
    parser.add_argument("--key-cooldown-seconds", type=int, default=13, help="Cooldown per API key after each ticker request.")
    parser.add_argument("--sleep-seconds", type=int, default=0, help="Extra global sleep after each ticker request.")
    parser.add_argument("--retry-wait-seconds", type=int, default=60, help="Wait time after HTTP 429.")
    parser.add_argument("--max-retries", type=int, default=3, help="Max attempts per ticker.")
    parser.add_argument("--force", action="store_true", help="Redownload even when CSV already exists.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_directories()
    api_keys = load_api_keys()
    api_key_pool = ApiKeyPool(api_keys=api_keys, cooldown_seconds=args.key_cooldown_seconds)
    tickers = load_failed_tickers(limit=args.limit)

    if not tickers:
        print("No failed tickers to retry.")
        return

    start, end = get_date_range(years=args.years)
    counts = {"success": 0, "failed": 0, "empty": 0, "skipped": 0}

    print(f"Retry tickers: {len(tickers)}")
    print(f"Date range: {start} to {end}")
    print(f"API keys: {len(api_keys)}")
    print(f"Per-key cooldown seconds: {args.key_cooldown_seconds}")

    for ticker in tqdm(tickers, desc="Retrying", unit="ticker"):
        status = download_one_ticker(
            ticker=ticker,
            start=start,
            end=end,
            api_key_pool=api_key_pool,
            max_retries=args.max_retries,
            retry_wait_seconds=args.retry_wait_seconds,
            force=args.force,
        )
        counts[status] = counts.get(status, 0) + 1
        sleep_after_request(args.sleep_seconds, status)

    print("Retry finished")
    print(f"success={counts.get('success', 0)} skipped={counts.get('skipped', 0)} empty={counts.get('empty', 0)} failed={counts.get('failed', 0)}")


if __name__ == "__main__":
    main()
