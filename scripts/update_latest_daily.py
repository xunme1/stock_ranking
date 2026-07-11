from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from tqdm import tqdm

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from download_polygon_daily import (  # noqa: E402
    CSV_COLUMNS,
    ApiKeyPool,
    append_download_log,
    append_failed_ticker,
    ensure_directories,
    load_api_keys,
    load_tickers,
    parse_polygon_results,
    request_polygon_daily,
    save_ticker_csv,
    sleep_after_request,
    ticker_csv_path,
)
from ths_ifind_daily import (  # noqa: E402
    fetch_ifind_history,
    ifind_session,
    load_us_exchange_suffixes,
    merge_daily_csv,
    normalize_project_ticker,
)


def get_last_local_date(ticker: str) -> date | None:
    path = ticker_csv_path(ticker)
    if not path.exists() or path.stat().st_size == 0:
        return None

    try:
        df = pd.read_csv(path, usecols=["date"])
    except Exception as exc:
        append_download_log(ticker, "failed", f"could not read local csv dates: {exc}", 0)
        append_failed_ticker(ticker, f"could not read local csv dates: {exc}")
        return None

    if df.empty:
        return None

    dates = pd.to_datetime(df["date"], errors="coerce").dropna()
    if dates.empty:
        return None
    return dates.max().date()


def previous_weekday(value: date) -> date:
    current = value - timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def merge_old_new_data(ticker: str, new_df: pd.DataFrame) -> int:
    path = ticker_csv_path(ticker)
    old_df = pd.read_csv(path) if path.exists() and path.stat().st_size > 0 else pd.DataFrame(columns=CSV_COLUMNS)
    merged = pd.concat([old_df, new_df], ignore_index=True)
    merged["date"] = pd.to_datetime(merged["date"], errors="coerce")
    merged = merged.dropna(subset=["date"])
    merged["date"] = merged["date"].dt.date.astype(str)
    merged = merged.drop_duplicates(subset=["ticker", "date"], keep="last")
    merged = merged.sort_values(["ticker", "date"])
    save_ticker_csv(ticker, merged.reindex(columns=CSV_COLUMNS))
    return len(merged) - len(old_df)


def update_one_ticker(
    ticker: str,
    end: date,
    api_key_pool: ApiKeyPool,
    max_retries: int,
    retry_wait_seconds: int,
    download_missing: bool = False,
) -> str:
    last_date = get_last_local_date(ticker)
    if last_date is None:
        if not download_missing:
            append_download_log(ticker, "skipped", "missing local csv", 0)
            return "skipped"
        start = end - timedelta(days=365 * 2 + 7)
    else:
        start = last_date + timedelta(days=1)

    if start > end:
        append_download_log(ticker, "skipped", "already up to date", 0)
        return "skipped"

    last_reason = ""
    for attempt in range(1, max_retries + 1):
        key_number, api_key = api_key_pool.acquire()
        try:
            response = request_polygon_daily(ticker, start.isoformat(), end.isoformat(), api_key)
            if response.status_code == 429:
                last_reason = f"429 rate limited on attempt {attempt} with key #{key_number}"
                api_key_pool.delay_key(key_number, retry_wait_seconds)
                continue

            if response.status_code != 200:
                last_reason = f"HTTP {response.status_code} with key #{key_number}: {response.text[:300]}"
                if response.status_code == 403:
                    append_download_log(ticker, "failed", last_reason, 0)
                    append_failed_ticker(ticker, last_reason)
                    return "failed"
                time.sleep(min(5 * attempt, 30))
                continue

            df = parse_polygon_results(ticker, response.json())
            if df.empty:
                append_download_log(ticker, "skipped", f"no new rows from {start} to {end}", 0)
                return "skipped"

            added_rows = merge_old_new_data(ticker, df)
            append_download_log(ticker, "success", f"updated from {start} to {end}", added_rows)
            return "success"
        except Exception as exc:
            last_reason = f"update error on attempt {attempt}: {exc}"
            time.sleep(min(5 * attempt, 30))

    append_download_log(ticker, "failed", last_reason, 0)
    append_failed_ticker(ticker, last_reason)
    return "failed"


def update_one_ticker_ths(
    ticker: str,
    end: date,
    us_exchange_suffixes: dict[str, str],
    download_missing: bool = False,
) -> str:
    ticker = normalize_project_ticker(ticker, "us")
    last_date = get_last_local_date(ticker)
    if last_date is None:
        if not download_missing:
            append_download_log(ticker, "skipped", "missing local csv", 0)
            return "skipped"
        start = end - timedelta(days=365 * 2 + 7)
    else:
        start = last_date + timedelta(days=1)

    if start > end:
        append_download_log(ticker, "skipped", "already up to date", 0)
        return "skipped"

    try:
        result = fetch_ifind_history(ticker, "us", start, end, us_exchange_suffixes)
        added_rows = merge_daily_csv(ticker_csv_path(ticker), ticker, result.frame, CSV_COLUMNS)
        append_download_log(ticker, "success", f"iFinD {result.code} updated from {start} to {end}", added_rows)
        return "success"
    except Exception as exc:  # noqa: BLE001 - vendor SDK errors include plain dicts/strings.
        reason = f"iFinD update error: {exc}"
        append_download_log(ticker, "failed", reason, 0)
        append_failed_ticker(ticker, reason)
        return "failed"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Append latest daily bars to existing local ticker CSV files.")
    parser.add_argument("--source", choices=["ths", "polygon"], default="ths", help="Daily data source. Defaults to ths.")
    parser.add_argument("--limit", type=int, default=None, help="Only update the first N tickers.")
    parser.add_argument("--tickers", default=None, help="Comma-separated ticker subset.")
    parser.add_argument("--end-date", default=None, help="End date in YYYY-MM-DD. Defaults to the previous weekday.")
    parser.add_argument("--key-cooldown-seconds", type=int, default=13, help="Cooldown per API key.")
    parser.add_argument("--sleep-seconds", type=int, default=0, help="Extra global sleep after each ticker.")
    parser.add_argument("--retry-wait-seconds", type=int, default=60, help="Wait time after HTTP 429.")
    parser.add_argument("--max-retries", type=int, default=3, help="Max attempts per ticker.")
    parser.add_argument("--download-missing", action="store_true", help="Download a two-year history if local CSV is missing.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_directories()

    if args.tickers:
        tickers = [ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()]
    else:
        tickers = load_tickers(limit=args.limit)

    end = date.fromisoformat(args.end_date) if args.end_date else previous_weekday(date.today())
    api_key_pool: ApiKeyPool | None = None
    api_keys: list[str] = []
    if args.source == "polygon":
        api_keys = load_api_keys()
        api_key_pool = ApiKeyPool(api_keys=api_keys, cooldown_seconds=args.key_cooldown_seconds)

    print(f"Tickers: {len(tickers)}")
    print(f"End date: {end}")
    print(f"Source: {args.source}")
    if args.source == "polygon":
        print(f"API keys: {len(api_keys)}")
        print(f"Per-key cooldown seconds: {args.key_cooldown_seconds}")

    counts = {"success": 0, "failed": 0, "skipped": 0}
    if args.source == "ths":
        us_exchange_suffixes = load_us_exchange_suffixes()
        with ifind_session():
            for ticker in tqdm(tickers, desc="Updating", unit="ticker"):
                status = update_one_ticker_ths(
                    ticker=ticker,
                    end=end,
                    us_exchange_suffixes=us_exchange_suffixes,
                    download_missing=args.download_missing,
                )
                counts[status] = counts.get(status, 0) + 1
                sleep_after_request(args.sleep_seconds, status)
    else:
        if api_key_pool is None:
            raise RuntimeError("Polygon API key pool was not initialized.")
        for ticker in tqdm(tickers, desc="Updating", unit="ticker"):
            status = update_one_ticker(
                ticker=ticker,
                end=end,
                api_key_pool=api_key_pool,
                max_retries=args.max_retries,
                retry_wait_seconds=args.retry_wait_seconds,
                download_missing=args.download_missing,
            )
            counts[status] = counts.get(status, 0) + 1
            sleep_after_request(args.sleep_seconds, status)

    print("Update finished")
    print(f"success={counts.get('success', 0)} skipped={counts.get('skipped', 0)} failed={counts.get('failed', 0)}")


if __name__ == "__main__":
    main()
