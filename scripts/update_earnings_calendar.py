from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
OUTPUT_FILE = ROOT_DIR / "data" / "fundamental" / "earnings_calendar.csv"
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.ranking_service import RankingConfig, build_ranking  # noqa: E402


def load_api_key() -> str:
    load_dotenv(ROOT_DIR / ".env")
    api_key = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()
    if not api_key:
        raise ValueError("No Alpha Vantage API key found. Set ALPHAVANTAGE_API_KEY in .env.")
    return api_key


def top_ranked_tickers(limit: int, window: int) -> list[str]:
    ranking = build_ranking(
        RankingConfig(window=window, benchmark="QQQ")
    )
    return [str(row["ticker"]) for row in ranking["data"][:limit]]


def fetch_earnings_calendar(api_key: str, horizon: str) -> pd.DataFrame:
    response = requests.get(
        ALPHA_VANTAGE_URL,
        params={
            "function": "EARNINGS_CALENDAR",
            "horizon": horizon,
            "apikey": api_key,
        },
        timeout=60,
    )
    response.raise_for_status()
    text = response.text.strip()
    if not text:
        raise ValueError("Alpha Vantage returned an empty earnings calendar.")
    if text.startswith("{"):
        raise ValueError(f"Alpha Vantage returned JSON instead of CSV: {text[:300]}")
    return pd.read_csv(StringIO(text))


def pick_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    lower_map = {column.lower(): column for column in df.columns}
    for candidate in candidates:
        column = lower_map.get(candidate.lower())
        if column:
            return column
    return None


def build_output_rows(calendar_df: pd.DataFrame, tickers: list[str]) -> list[dict[str, str]]:
    symbol_col = pick_column(calendar_df, ["symbol", "ticker"])
    report_date_col = pick_column(calendar_df, ["reportDate", "report_date"])
    fiscal_date_col = pick_column(calendar_df, ["fiscalDateEnding", "fiscal_date_ending"])
    estimate_col = pick_column(calendar_df, ["estimate", "epsEstimate", "eps_estimate"])
    currency_col = pick_column(calendar_df, ["currency"])
    name_col = pick_column(calendar_df, ["name"])

    if not symbol_col or not report_date_col:
        raise ValueError(f"Unexpected Alpha Vantage columns: {list(calendar_df.columns)}")

    df = calendar_df.copy()
    df[symbol_col] = df[symbol_col].astype(str).str.upper().str.strip()
    df[report_date_col] = pd.to_datetime(df[report_date_col], errors="coerce")
    df = df.dropna(subset=[report_date_col])
    df = df.sort_values(report_date_col)

    updated_at = datetime.now().isoformat(timespec="seconds")
    output_rows: list[dict[str, str]] = []
    for ticker in tickers:
        matches = df[df[symbol_col] == ticker]
        match = matches.iloc[0] if not matches.empty else None
        output_rows.append(
            {
                "ticker": ticker,
                "earnings_date": "" if match is None else match[report_date_col].date().isoformat(),
                "earnings_time": "",
                "earnings_estimate": "" if match is None or not estimate_col else str(match.get(estimate_col, "")).strip(),
                "earnings_currency": "" if match is None or not currency_col else str(match.get(currency_col, "")).strip(),
                "fiscal_date_ending": "" if match is None or not fiscal_date_col else str(match.get(fiscal_date_col, "")).strip(),
                "company_name": "" if match is None or not name_col else str(match.get(name_col, "")).strip(),
                "source": "Alpha Vantage",
                "updated_at": updated_at,
            }
        )
    return output_rows


def save_rows(rows: list[dict[str, str]], path: Path = OUTPUT_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "ticker",
        "earnings_date",
        "earnings_time",
        "earnings_estimate",
        "earnings_currency",
        "fiscal_date_ending",
        "company_name",
        "source",
        "updated_at",
    ]
    merged: dict[str, dict[str, str]] = {}
    if path.exists() and path.stat().st_size > 0:
        with path.open("r", newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                ticker = str(row.get("ticker", "")).strip().upper()
                if ticker:
                    merged[ticker] = {field: str(row.get(field, "")) for field in fieldnames}

    for row in rows:
        ticker = str(row.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        merged[ticker] = {field: str(row.get(field, "")) for field in fieldnames}

    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([merged[ticker] for ticker in sorted(merged)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update upcoming earnings dates for ranked stocks.")
    parser.add_argument("--top", type=int, default=20, help="Fetch earnings dates for top N ranked stocks.")
    parser.add_argument("--window", type=int, default=10, help="Ranking window used to select top stocks.")
    parser.add_argument("--horizon", default="3month", choices=["3month", "6month", "12month"], help="Alpha Vantage horizon.")
    parser.add_argument("--tickers", default=None, help="Optional comma-separated ticker override.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = load_api_key()
    tickers = (
        [ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()]
        if args.tickers
        else top_ranked_tickers(args.top, args.window)
    )
    calendar_df = fetch_earnings_calendar(api_key, args.horizon)
    rows = build_output_rows(calendar_df, tickers)
    save_rows(rows)

    found = sum(1 for row in rows if row["earnings_date"])
    print(f"Tickers: {len(tickers)}")
    print(f"Matched earnings dates: {found}")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
