from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import pandas as pd

from app.core.config import DEFAULT_BENCHMARK
from app.services.data_loader import load_daily_data, load_ticker_file, normalize_ticker


ANNOUNCED_2026_06_22_ADDS = ["ALAB", "CRWV", "NBIS", "RKLB", "TER"]
ANNOUNCED_2026_06_22_REMOVES = ["CHTR", "CTSH", "INSM", "VRSK", "ZS"]


@dataclass
class RankingConfig:
    window: int = 10
    benchmark: str = DEFAULT_BENCHMARK
    apply_announced_rebalance: bool = False
    as_of_date: date | None = None


def apply_rebalance(tickers: list[str]) -> list[str]:
    remove_set = set(ANNOUNCED_2026_06_22_REMOVES)
    result = [ticker for ticker in tickers if ticker not in remove_set]
    for ticker in ANNOUNCED_2026_06_22_ADDS:
        if ticker not in result:
            result.append(ticker)
    return result


def true_range(df: pd.DataFrame) -> pd.Series:
    previous_close = df["close"].shift(1)
    return pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - previous_close).abs(),
            (df["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def clean_number(value: object) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def trim_to_as_of_date(df: pd.DataFrame, as_of_date: date | None) -> pd.DataFrame:
    if as_of_date is None:
        return df
    return df[df["date"].dt.date <= as_of_date]


def latest_available_date(ticker: str) -> date:
    df = load_daily_data(ticker)
    if df.empty:
        raise ValueError(f"No daily data for {ticker}")
    return df.iloc[-1]["date"].date()


def available_dates(ticker: str, limit: int = 260) -> list[str]:
    df = load_daily_data(ticker).tail(limit)
    return [row.date.date().isoformat() for row in df.itertuples(index=False)]


def calculate_ticker_score(
    ticker: str,
    window: int,
    benchmark: str,
    as_of_date: date | None,
) -> dict[str, object] | None:
    df = load_daily_data(ticker)
    df = trim_to_as_of_date(df, as_of_date)
    if len(df) < window * 2 - 1:
        return None

    df = df.copy()
    df["ma"] = df["close"].rolling(window).mean()
    df["atr"] = true_range(df).rolling(window).mean()

    center = df["ma"].dropna().tail(window).mean()
    latest = df.iloc[-1]
    atr = clean_number(latest["atr"])
    close = clean_number(latest["close"])

    if close is None or atr is None or atr == 0 or not math.isfinite(center):
        return None

    atr_score = (close - float(center)) / atr
    price_vs_center_pct = (close / float(center) - 1) * 100
    ticker = normalize_ticker(ticker)

    return {
        "ticker": ticker,
        "type": "Nasdaq-100 ETF" if ticker == benchmark else "Nasdaq-100 Stock",
        "date": latest["date"].date().isoformat(),
        "close": close,
        "latest_ma": clean_number(latest["ma"]),
        "ma_center": clean_number(center),
        "atr": atr,
        "atr_score": atr_score,
        "price_vs_center_pct": price_vs_center_pct,
    }


def build_ranking(config: RankingConfig) -> dict[str, object]:
    benchmark = normalize_ticker(config.benchmark)
    effective_as_of_date = config.as_of_date or latest_available_date(benchmark)
    tickers = load_ticker_file()
    if config.apply_announced_rebalance:
        tickers = apply_rebalance(tickers)

    universe = list(tickers)
    if benchmark not in universe:
        universe.append(benchmark)

    rows = []
    skipped: list[str] = []
    for ticker in universe:
        try:
            row = calculate_ticker_score(ticker, config.window, benchmark, effective_as_of_date)
        except FileNotFoundError:
            row = None
        if row is None:
            skipped.append(ticker)
        else:
            rows.append(row)

    if not rows:
        raise ValueError("No ranking rows generated")

    df = pd.DataFrame(rows)
    benchmark_rows = df[df["ticker"] == benchmark]
    if benchmark_rows.empty:
        raise ValueError(f"Benchmark {benchmark} is missing from ranking")

    benchmark_score = float(benchmark_rows.iloc[0]["atr_score"])
    df["excess_atr_vs_benchmark"] = df["atr_score"] - benchmark_score
    df = df.sort_values("atr_score", ascending=False).reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))

    return {
        "window": config.window,
        "as_of_date": effective_as_of_date.isoformat(),
        "benchmark": benchmark,
        "benchmark_rank": int(df.loc[df["ticker"] == benchmark, "rank"].iloc[0]),
        "benchmark_score": benchmark_score,
        "count": len(df),
        "skipped": skipped,
        "data": df.to_dict(orient="records"),
    }
