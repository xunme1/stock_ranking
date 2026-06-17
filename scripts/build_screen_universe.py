from __future__ import annotations

import argparse
import sys
import time
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from tqdm import tqdm

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from download_polygon_daily import ApiKeyPool, ROOT_DIR, load_api_keys  # noqa: E402


CONFIG_DIR = ROOT_DIR / "config"
NASDAQ100_FILE = CONFIG_DIR / "nasdaq100_tickers.txt"
OPTIONABLE_FILE = CONFIG_DIR / "optionable_tickers.txt"
NASDAQ100_OPTIONABLE_FILE = CONFIG_DIR / "nasdaq100_optionable_tickers.txt"
NASDAQ100_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
OPTIONS_CONTRACTS_URL = "https://api.polygon.io/v3/reference/options/contracts"


def normalize_ticker(ticker: object) -> str:
    return str(ticker).strip().upper().replace(".", "-")


def save_tickers(tickers: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(tickers) + "\n", encoding="utf-8")


def load_tickers(path: Path) -> list[str]:
    if not path.exists():
        return []
    tickers = []
    seen = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        ticker = normalize_ticker(line)
        if ticker and ticker not in seen:
            seen.add(ticker)
            tickers.append(ticker)
    return tickers


def fetch_nasdaq100_tickers() -> list[str]:
    response = requests.get(
        NASDAQ100_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; stock-data-project/1.0)"},
        timeout=30,
    )
    response.raise_for_status()
    tables = pd.read_html(StringIO(response.text))
    candidates: list[str] = []

    for table in tables:
        symbol_col = None
        for col in table.columns:
            col_name = str(col).lower()
            if "ticker" in col_name or "symbol" in col_name:
                symbol_col = col
                break

        if symbol_col is None or len(table) < 90:
            continue

        candidates = [normalize_ticker(value) for value in table[symbol_col].tolist()]
        candidates = [ticker for ticker in candidates if ticker and ticker != "NAN"]
        if len(candidates) >= 90:
            break

    if len(candidates) < 90:
        raise RuntimeError(f"Nasdaq-100 ticker list looks too short: {len(candidates)}")

    seen = set()
    tickers = []
    for ticker in candidates:
        if ticker not in seen:
            seen.add(ticker)
            tickers.append(ticker)
    return tickers


def request_options_contracts(
    session: requests.Session,
    api_key_pool: ApiKeyPool,
    ticker: str,
    max_retries: int,
    retry_wait_seconds: int,
) -> dict[str, Any]:
    last_reason = ""
    for attempt in range(1, max_retries + 1):
        key_number, api_key = api_key_pool.acquire()
        params = {
            "underlying_ticker": ticker,
            "expired": "false",
            "limit": 1,
            "apiKey": api_key,
        }
        try:
            response = session.get(OPTIONS_CONTRACTS_URL, params=params, timeout=30)
            if response.status_code == 429:
                api_key_pool.delay_key(key_number, retry_wait_seconds)
                last_reason = f"429 rate limited with key #{key_number}"
                continue
            if response.status_code != 200:
                last_reason = f"HTTP {response.status_code}: {response.text[:200]}"
                time.sleep(min(5 * attempt, 30))
                continue
            return response.json()
        except requests.RequestException as exc:
            last_reason = f"request error: {exc}"
            time.sleep(min(5 * attempt, 30))

    raise RuntimeError(last_reason or "options request failed")


def ticker_has_options(
    session: requests.Session,
    api_key_pool: ApiKeyPool,
    ticker: str,
    max_retries: int,
    retry_wait_seconds: int,
) -> bool:
    payload = request_options_contracts(
        session=session,
        api_key_pool=api_key_pool,
        ticker=ticker,
        max_retries=max_retries,
        retry_wait_seconds=retry_wait_seconds,
    )
    return bool(payload.get("results"))


def build_optionable_tickers(
    tickers: list[str],
    key_cooldown_seconds: int,
    max_retries: int,
    retry_wait_seconds: int,
) -> list[str]:
    api_key_pool = ApiKeyPool(api_keys=load_api_keys(), cooldown_seconds=key_cooldown_seconds)
    session = requests.Session()
    optionable = []

    for ticker in tqdm(tickers, desc="Checking options", unit="ticker"):
        try:
            if ticker_has_options(
                session=session,
                api_key_pool=api_key_pool,
                ticker=ticker,
                max_retries=max_retries,
                retry_wait_seconds=retry_wait_seconds,
            ):
                optionable.append(ticker)
        except Exception as exc:
            print(f"{ticker} option check skipped: {exc}")

    return optionable


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Nasdaq-100 and optionable ticker universe files.")
    parser.add_argument("--key-cooldown-seconds", type=int, default=13, help="Cooldown per API key.")
    parser.add_argument("--retry-wait-seconds", type=int, default=60, help="Wait time after HTTP 429.")
    parser.add_argument("--max-retries", type=int, default=3, help="Max attempts per ticker.")
    parser.add_argument("--use-cache", action="store_true", help="Use existing config files when available.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.use_cache and NASDAQ100_FILE.exists():
        nasdaq100 = load_tickers(NASDAQ100_FILE)
    else:
        nasdaq100 = fetch_nasdaq100_tickers()
        save_tickers(nasdaq100, NASDAQ100_FILE)

    if args.use_cache and OPTIONABLE_FILE.exists():
        optionable = load_tickers(OPTIONABLE_FILE)
    else:
        optionable = build_optionable_tickers(
            tickers=nasdaq100,
            key_cooldown_seconds=args.key_cooldown_seconds,
            max_retries=args.max_retries,
            retry_wait_seconds=args.retry_wait_seconds,
        )
        save_tickers(optionable, OPTIONABLE_FILE)

    optionable_set = set(optionable)
    selected = [ticker for ticker in nasdaq100 if ticker in optionable_set]
    save_tickers(selected, NASDAQ100_OPTIONABLE_FILE)

    print(f"Nasdaq-100 tickers: {len(nasdaq100)}")
    print(f"Optionable tickers: {len(optionable)}")
    print(f"Intersection tickers: {len(selected)}")
    print(f"Nasdaq-100 file: {NASDAQ100_FILE}")
    print(f"Optionable file: {OPTIONABLE_FILE}")
    print(f"Output file: {NASDAQ100_OPTIONABLE_FILE}")
    print(f"First 20: {','.join(selected[:20])}")


if __name__ == "__main__":
    main()
