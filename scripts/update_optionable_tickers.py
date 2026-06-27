from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from tqdm import tqdm


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT_DIR / "scripts"
BACKEND_DIR = ROOT_DIR / "backend"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from download_polygon_daily import ApiKeyPool, load_api_keys, load_tickers  # noqa: E402
from app.core.config import (  # noqa: E402
    DEFAULT_BENCHMARK,
    NASDAQ100_FILE,
    OPTIONABLE_TICKERS_FILE,
)
from app.services.data_loader import normalize_ticker  # noqa: E402
from app.services.ranking_service import apply_rebalance  # noqa: E402


API_URL = "https://api.polygon.io/v3/reference/options/contracts"
CSV_COLUMNS = ["ticker", "has_options", "checked_at", "source", "reason"]


def load_existing_status(path: Path = OPTIONABLE_TICKERS_FILE) -> dict[str, dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    df = pd.read_csv(path)
    existing: dict[str, dict[str, str]] = {}
    for row in df.fillna("").itertuples(index=False):
        ticker = normalize_ticker(str(getattr(row, "ticker", "")))
        if not ticker:
            continue
        existing[ticker] = {
            "ticker": ticker,
            "has_options": str(getattr(row, "has_options", "")).strip().upper(),
            "checked_at": str(getattr(row, "checked_at", "")).strip(),
            "source": str(getattr(row, "source", "")).strip(),
            "reason": str(getattr(row, "reason", "")).strip(),
        }
    return existing


def save_status(rows: list[dict[str, str]], path: Path = OPTIONABLE_TICKERS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda row: row["ticker"])
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def is_confirmed_previous_status(row: dict[str, str]) -> bool:
    reason = row.get("reason", "").lower()
    if "check failed" in reason or "kept previous value" in reason:
        return False
    return row.get("has_options") in {"Y", "N"}


def load_universe(
    tickers_arg: str | None,
    limit: int | None,
    apply_announced_rebalance: bool,
    benchmark: str,
) -> list[str]:
    if tickers_arg:
        tickers = [normalize_ticker(item) for item in tickers_arg.split(",") if item.strip()]
    else:
        tickers = load_tickers(path=NASDAQ100_FILE, limit=limit)
        if apply_announced_rebalance:
            tickers = apply_rebalance(tickers)

    benchmark = normalize_ticker(benchmark)
    if benchmark not in tickers:
        tickers.append(benchmark)

    seen: set[str] = set()
    result: list[str] = []
    for ticker in tickers:
        ticker = normalize_ticker(ticker)
        if ticker and ticker not in seen:
            seen.add(ticker)
            result.append(ticker)
    return result


def query_optionable(ticker: str, api_key: str, timeout: int = 30) -> tuple[str | None, str]:
    response = requests.get(
        API_URL,
        params={
            "underlying_ticker": ticker,
            "expired": "false",
            "limit": 1,
            "apiKey": api_key,
        },
        timeout=timeout,
    )
    if response.status_code == 429:
        return None, "429 rate limited"
    if response.status_code != 200:
        return None, f"HTTP {response.status_code}: {response.text[:240]}"

    payload: dict[str, Any] = response.json()
    results = payload.get("results") or []
    if results:
        return "Y", "active option contract found"
    return "N", payload.get("message") or "no active option contract found"


def update_one_ticker(
    ticker: str,
    api_key_pool: ApiKeyPool,
    existing: dict[str, dict[str, str]],
    max_retries: int,
    retry_wait_seconds: int,
) -> dict[str, str]:
    checked_at = datetime.now().isoformat(timespec="seconds")
    last_reason = ""
    for attempt in range(1, max_retries + 1):
        key_number, api_key = api_key_pool.acquire()
        try:
            has_options, reason = query_optionable(ticker, api_key)
        except requests.RequestException as exc:
            has_options, reason = None, f"request error: {exc}"

        if has_options is not None:
            return {
                "ticker": ticker,
                "has_options": has_options,
                "checked_at": checked_at,
                "source": "polygon_options_contracts",
                "reason": reason,
            }

        last_reason = f"{reason} on attempt {attempt} with key #{key_number}"
        if "429" in reason:
            api_key_pool.delay_key(key_number, retry_wait_seconds)
        else:
            time.sleep(min(5 * attempt, 30))

    previous = existing.get(ticker)
    if previous and is_confirmed_previous_status(previous):
        return {
            "ticker": ticker,
            "has_options": previous["has_options"],
            "checked_at": previous.get("checked_at", ""),
            "source": previous.get("source", ""),
            "reason": f"kept previous value; latest check failed: {last_reason}",
        }

    return {
        "ticker": ticker,
        "has_options": "U",
        "checked_at": checked_at,
        "source": "polygon_options_contracts",
        "reason": f"check failed; status unknown: {last_reason}",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update stock option availability from Polygon options contracts.")
    parser.add_argument("--tickers", default=None, help="Comma-separated ticker subset. Defaults to config/nasdaq100_tickers.txt.")
    parser.add_argument("--limit", type=int, default=None, help="Only process first N tickers from the default ticker file.")
    parser.add_argument("--benchmark", default=DEFAULT_BENCHMARK, help="Benchmark ticker to include. Defaults to QQQ.")
    parser.add_argument("--no-rebalance", action="store_true", help="Do not apply the announced 2026-06-22 Nasdaq-100 rebalance.")
    parser.add_argument("--key-cooldown-seconds", type=int, default=13, help="Cooldown per API key after each request.")
    parser.add_argument("--retry-wait-seconds", type=int, default=60, help="Wait time after HTTP 429.")
    parser.add_argument("--max-retries", type=int, default=2, help="Max attempts per ticker.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_keys = load_api_keys()
    api_key_pool = ApiKeyPool(api_keys=api_keys, cooldown_seconds=args.key_cooldown_seconds)
    tickers = load_universe(
        tickers_arg=args.tickers,
        limit=args.limit,
        apply_announced_rebalance=not args.no_rebalance,
        benchmark=args.benchmark,
    )
    existing = load_existing_status()

    print(f"Tickers: {len(tickers)}")
    print(f"API keys: {len(api_keys)}")
    print(f"Output: {OPTIONABLE_TICKERS_FILE}")

    status_by_ticker = dict(existing)
    for ticker in tqdm(tickers, desc="Checking options", unit="ticker"):
        row = update_one_ticker(
            ticker=ticker,
            api_key_pool=api_key_pool,
            existing=existing,
            max_retries=args.max_retries,
            retry_wait_seconds=args.retry_wait_seconds,
        )
        status_by_ticker[ticker] = row
        save_status(list(status_by_ticker.values()))

    checked_rows = [status_by_ticker[ticker] for ticker in tickers]
    counts = {
        "Y": sum(1 for row in checked_rows if row["has_options"] == "Y"),
        "N": sum(1 for row in checked_rows if row["has_options"] == "N"),
        "U": sum(1 for row in checked_rows if row["has_options"] == "U"),
    }
    print(f"Option availability updated: Y={counts.get('Y', 0)} N={counts.get('N', 0)} U={counts.get('U', 0)}")


if __name__ == "__main__":
    main()
