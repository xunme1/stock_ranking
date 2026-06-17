from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv
from requests import Response
from tqdm import tqdm


sys.dont_write_bytecode = True

ROOT_DIR = Path(__file__).resolve().parents[1]
TICKERS_FILE = ROOT_DIR / "config" / "tickers.txt"
RAW_DAILY_DIR = ROOT_DIR / "data" / "raw" / "daily"
LOG_DIR = ROOT_DIR / "logs"
DOWNLOAD_LOG_FILE = LOG_DIR / "download_log.csv"
FAILED_TICKERS_FILE = LOG_DIR / "failed_tickers.csv"

API_URL = "https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"
CSV_COLUMNS = [
    "ticker",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vwap",
    "transactions",
]
API_KEY_PATTERN = re.compile(r"(apiKey=)[^&\s,)\"]+", re.IGNORECASE)


def sanitize_reason(reason: object) -> str:
    text = str(reason)
    return API_KEY_PATTERN.sub(r"\1***", text)


def ensure_directories() -> None:
    RAW_DAILY_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def load_api_keys() -> list[str]:
    load_dotenv(ROOT_DIR / ".env")
    api_keys: list[str] = []

    numbered_index = 1
    while True:
        api_key = os.getenv(f"POLYGON_API_KEY_{numbered_index}")
        if not api_key:
            break
        api_keys.append(api_key)
        numbered_index += 1

    legacy_api_key = os.getenv("POLYGON_API_KEY")
    if legacy_api_key and legacy_api_key not in api_keys:
        api_keys.insert(0, legacy_api_key)

    if not api_keys:
        raise ValueError("No Polygon API keys found. Set POLYGON_API_KEY_1, POLYGON_API_KEY_2, ... in .env.")
    return api_keys


def load_api_key() -> str:
    return load_api_keys()[0]


@dataclass
class ApiKeyPool:
    api_keys: list[str]
    cooldown_seconds: int

    def __post_init__(self) -> None:
        self.next_available_at = [0.0 for _ in self.api_keys]
        self.next_index = 0

    def acquire(self) -> tuple[int, str]:
        if not self.api_keys:
            raise ValueError("API key pool is empty.")

        now = time.monotonic()
        best_index = min(range(len(self.api_keys)), key=lambda index: self.next_available_at[index])
        wait_seconds = self.next_available_at[best_index] - now
        if wait_seconds > 0:
            time.sleep(wait_seconds)

        key_index = best_index
        self.next_available_at[key_index] = time.monotonic() + max(self.cooldown_seconds, 0)
        self.next_index = (key_index + 1) % len(self.api_keys)
        return key_index + 1, self.api_keys[key_index]

    def delay_key(self, key_number: int, seconds: int) -> None:
        if seconds <= 0:
            return
        index = key_number - 1
        if 0 <= index < len(self.next_available_at):
            self.next_available_at[index] = max(self.next_available_at[index], time.monotonic() + seconds)


def load_tickers(path: Path = TICKERS_FILE, limit: int | None = None) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Ticker file not found: {path}")

    tickers: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        ticker = line.strip().upper()
        if not ticker or ticker.startswith("#") or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)

    if not tickers:
        raise ValueError(f"Ticker file is empty: {path}")
    return tickers[:limit] if limit else tickers


def get_date_range(years: int = 2) -> tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=365 * years + 7)
    return start.isoformat(), end.isoformat()


def ticker_csv_path(ticker: str) -> Path:
    return RAW_DAILY_DIR / f"{ticker}.csv"


def already_downloaded(ticker: str) -> bool:
    path = ticker_csv_path(ticker)
    return path.exists() and path.stat().st_size > 0


def append_csv_row(path: Path, fieldnames: list[str], row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def append_download_log(ticker: str, status: str, reason: str = "", rows: int = 0) -> None:
    safe_reason = sanitize_reason(reason)
    append_csv_row(
        DOWNLOAD_LOG_FILE,
        ["time", "ticker", "status", "reason", "rows"],
        {
            "time": datetime.now().isoformat(timespec="seconds"),
            "ticker": ticker,
            "status": status,
            "reason": safe_reason,
            "rows": rows,
        },
    )


def append_failed_ticker(ticker: str, reason: str) -> None:
    safe_reason = sanitize_reason(reason)
    append_csv_row(
        FAILED_TICKERS_FILE,
        ["time", "ticker", "reason"],
        {
            "time": datetime.now().isoformat(timespec="seconds"),
            "ticker": ticker,
            "reason": safe_reason,
        },
    )


def request_polygon_daily(
    ticker: str,
    start: str,
    end: str,
    api_key: str,
    timeout: int = 30,
) -> Response:
    url = API_URL.format(ticker=ticker, start=start, end=end)
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 50000,
        "apiKey": api_key,
    }
    return requests.get(url, params=params, timeout=timeout)


def parse_polygon_results(ticker: str, payload: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for item in payload.get("results") or []:
        timestamp_ms = item.get("t")
        trade_date = ""
        if timestamp_ms is not None:
            trade_date = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).date().isoformat()

        rows.append(
            {
                "ticker": ticker,
                "date": trade_date,
                "open": item.get("o"),
                "high": item.get("h"),
                "low": item.get("l"),
                "close": item.get("c"),
                "volume": item.get("v"),
                "vwap": item.get("vw"),
                "transactions": item.get("n"),
            }
        )

    df = pd.DataFrame(rows, columns=CSV_COLUMNS)
    if not df.empty:
        df = df.dropna(subset=["date"]).drop_duplicates(subset=["ticker", "date"])
        df = df.sort_values(["ticker", "date"])
    return df


def save_ticker_csv(ticker: str, df: pd.DataFrame) -> Path:
    path = ticker_csv_path(ticker)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def download_one_ticker(
    ticker: str,
    start: str,
    end: str,
    api_key: str | None = None,
    api_key_pool: ApiKeyPool | None = None,
    max_retries: int = 3,
    retry_wait_seconds: int = 60,
    force: bool = False,
) -> str:
    if not force and already_downloaded(ticker):
        append_download_log(ticker, "skipped", "csv already exists", 0)
        return "skipped"

    last_reason = ""
    for attempt in range(1, max_retries + 1):
        key_number = 1
        selected_api_key = api_key
        if api_key_pool is not None:
            key_number, selected_api_key = api_key_pool.acquire()
        if not selected_api_key:
            raise ValueError("No API key available for request.")

        try:
            response = request_polygon_daily(ticker, start, end, selected_api_key)
            if response.status_code == 429:
                last_reason = f"429 rate limited on attempt {attempt} with key #{key_number}"
                print(f"{ticker}: {sanitize_reason(last_reason)}; waiting {retry_wait_seconds}s")
                if api_key_pool is not None:
                    api_key_pool.delay_key(key_number, retry_wait_seconds)
                else:
                    time.sleep(retry_wait_seconds)
                continue

            if response.status_code != 200:
                last_reason = f"HTTP {response.status_code} with key #{key_number}: {response.text[:300]}"
                print(f"{ticker}: {sanitize_reason(last_reason)}")
                time.sleep(min(5 * attempt, 30))
                continue

            payload = response.json()
            df = parse_polygon_results(ticker, payload)
            if df.empty:
                reason = payload.get("message") or "no results returned"
                append_download_log(ticker, "empty", reason, 0)
                return "empty"

            save_ticker_csv(ticker, df)
            append_download_log(ticker, "success", "", len(df))
            return "success"

        except requests.RequestException as exc:
            last_reason = f"request error on attempt {attempt}: {exc}"
            print(f"{ticker}: {sanitize_reason(last_reason)}")
            time.sleep(min(5 * attempt, 30))
        except ValueError as exc:
            last_reason = f"invalid response on attempt {attempt}: {exc}"
            print(f"{ticker}: {sanitize_reason(last_reason)}")
            time.sleep(min(5 * attempt, 30))

    append_download_log(ticker, "failed", last_reason, 0)
    append_failed_ticker(ticker, last_reason)
    return "failed"


def sleep_after_request(seconds: int, status: str) -> None:
    if seconds <= 0 or status == "skipped":
        return
    time.sleep(seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download daily US stock OHLCV data from Polygon.io.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N tickers.")
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
    tickers = load_tickers(limit=args.limit)
    start, end = get_date_range(years=args.years)

    print(f"Project root: {ROOT_DIR}")
    print(f"Tickers: {len(tickers)}")
    print(f"Date range: {start} to {end}")
    print(f"API keys: {len(api_keys)}")
    print(f"Per-key cooldown seconds: {args.key_cooldown_seconds}")
    print(f"Extra global sleep seconds: {args.sleep_seconds}")

    counts = {"success": 0, "failed": 0, "empty": 0, "skipped": 0}
    for ticker in tqdm(tickers, desc="Downloading", unit="ticker"):
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

    print("Download finished")
    print(f"success={counts.get('success', 0)} skipped={counts.get('skipped', 0)} empty={counts.get('empty', 0)} failed={counts.get('failed', 0)}")
    print(f"Raw data dir: {RAW_DAILY_DIR}")
    print(f"Download log: {DOWNLOAD_LOG_FILE}")
    print(f"Failed tickers: {FAILED_TICKERS_FILE}")


if __name__ == "__main__":
    main()
