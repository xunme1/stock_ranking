from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from download_polygon_daily import ApiKeyPool, ROOT_DIR, TICKERS_FILE, load_api_keys  # noqa: E402


REFERENCE_URL = "https://api.polygon.io/v3/reference/tickers"
DEFAULT_TYPES: list[str | None] = [None]


def load_existing_tickers(path: Path = TICKERS_FILE) -> list[str]:
    if not path.exists():
        return []

    tickers = []
    seen = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        ticker = line.strip().upper()
        if not ticker or ticker.startswith("#") or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)
    return tickers


def add_unique(target: list[str], seen: set[str], ticker: str) -> None:
    ticker = ticker.strip().upper()
    if not ticker or ticker in seen:
        return
    seen.add(ticker)
    target.append(ticker)


def request_reference_page(
    session: requests.Session,
    api_key_pool: ApiKeyPool,
    params: dict[str, Any] | None = None,
    next_url: str | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    for attempt in range(1, 4):
        key_number, api_key = api_key_pool.acquire()
        try:
            if next_url:
                response = session.get(next_url, params={"apiKey": api_key}, timeout=timeout)
            else:
                request_params = dict(params or {})
                request_params["apiKey"] = api_key
                response = session.get(REFERENCE_URL, params=request_params, timeout=timeout)

            if response.status_code == 429:
                wait_seconds = 60
                api_key_pool.delay_key(key_number, wait_seconds)
                print(f"Reference API rate limited on key #{key_number}; waiting before retry")
                continue
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
            return response.json()
        except requests.RequestException as exc:
            if attempt == 3:
                raise RuntimeError(f"Reference API request failed: {exc}") from exc
            time.sleep(5 * attempt)

    raise RuntimeError("Reference API request failed after retries.")


def fetch_polygon_tickers(
    target_count: int | None,
    existing_count: int,
    api_key_pool: ApiKeyPool,
    ticker_types: list[str | None],
) -> list[str]:
    fetched: list[str] = []
    session = requests.Session()

    for ticker_type in ticker_types:
        next_url: str | None = None
        params: dict[str, Any] | None = {
            "market": "stocks",
            "active": "true",
            "locale": "us",
            "limit": 1000,
            "sort": "ticker",
            "order": "asc",
        }
        if ticker_type:
            params["type"] = ticker_type

        while target_count is None or len(fetched) + existing_count < target_count:
            payload = request_reference_page(
                session=session,
                api_key_pool=api_key_pool,
                params=params,
                next_url=next_url,
            )
            results = payload.get("results") or []
            if not results:
                break

            for item in results:
                ticker = str(item.get("ticker") or "").strip().upper()
                if ticker:
                    fetched.append(ticker)

            next_url = payload.get("next_url")
            params = None
            if not next_url:
                break

        if target_count is not None and len(fetched) + existing_count >= target_count:
            break

    return fetched


def build_ticker_pool(target_count: int | None, ticker_types: list[str | None], key_cooldown_seconds: int) -> list[str]:
    existing = load_existing_tickers()
    selected: list[str] = []
    seen: set[str] = set()

    for ticker in existing:
        add_unique(selected, seen, ticker)

    api_key_pool = ApiKeyPool(api_keys=load_api_keys(), cooldown_seconds=key_cooldown_seconds)
    fetched = fetch_polygon_tickers(
        target_count=target_count,
        existing_count=len(selected),
        api_key_pool=api_key_pool,
        ticker_types=ticker_types,
    )

    for ticker in fetched:
        add_unique(selected, seen, ticker)
        if target_count is not None and len(selected) >= target_count:
            break

    if target_count is not None and len(selected) < target_count:
        raise RuntimeError(f"Only built {len(selected)} tickers, target was {target_count}.")

    return selected[:target_count] if target_count is not None else selected


def save_tickers(tickers: list[str], path: Path = TICKERS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(tickers) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a local ticker pool from Polygon reference data.")
    parser.add_argument("--target-count", type=int, default=None, help="Number of tickers to write. Omit with --all.")
    parser.add_argument("--all", action="store_true", help="Fetch every active US stock ticker Polygon returns.")
    parser.add_argument(
        "--types",
        default="ALL",
        help="Comma-separated Polygon ticker types, for example CS,ETF. Use ALL to omit the type filter.",
    )
    parser.add_argument("--key-cooldown-seconds", type=int, default=13, help="Cooldown per API key.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.all and args.target_count is None:
        args.target_count = 2000

    if args.types.strip().upper() == "ALL":
        ticker_types: list[str | None] = [None]
    else:
        ticker_types = [value.strip().upper() for value in args.types.split(",") if value.strip()]

    tickers = build_ticker_pool(
        target_count=args.target_count,
        ticker_types=ticker_types,
        key_cooldown_seconds=args.key_cooldown_seconds,
    )
    save_tickers(tickers)

    print(f"Project root: {ROOT_DIR}")
    type_label = "ALL" if ticker_types == [None] else ",".join(str(value) for value in ticker_types)
    print(f"Ticker types: {type_label}")
    print(f"Tickers written: {len(tickers)}")
    print(f"Output file: {TICKERS_FILE}")
    print(f"First 10: {','.join(tickers[:10])}")
    print(f"Last 10: {','.join(tickers[-10:])}")


if __name__ == "__main__":
    main()
