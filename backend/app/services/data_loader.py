from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

from app.core.config import NASDAQ100_FILE, RAW_DAILY_DIR


def normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def ticker_csv_path(ticker: str) -> Path:
    return RAW_DAILY_DIR / f"{normalize_ticker(ticker)}.csv"


@lru_cache(maxsize=512)
def load_daily_csv_cached(ticker: str, mtime_ns: int) -> pd.DataFrame:
    path = ticker_csv_path(ticker)
    df = pd.read_csv(path)
    df["ticker"] = normalize_ticker(ticker)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for column in ["open", "high", "low", "close", "volume", "vwap", "transactions"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close"])
    return df.sort_values("date").reset_index(drop=True)


def load_daily_data(ticker: str) -> pd.DataFrame:
    path = ticker_csv_path(ticker)
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(f"Daily CSV not found for {normalize_ticker(ticker)}")
    return load_daily_csv_cached(normalize_ticker(ticker), path.stat().st_mtime_ns).copy()


def load_ticker_file(path: Path = NASDAQ100_FILE) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Ticker file not found: {path}")

    tickers: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        ticker = normalize_ticker(line)
        if not ticker or ticker.startswith("#") or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)
    return tickers
