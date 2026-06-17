from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from download_polygon_daily import (  # noqa: E402
    ApiKeyPool,
    download_one_ticker,
    ensure_directories,
    get_date_range,
    load_api_keys,
    ticker_csv_path,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT_DIR / "data" / "processed"
DEFAULT_SELECTED_FILE = PROCESSED_DIR / "stock_screen_nasdaq100_optionable_selected.csv"
DEFAULT_OUTPUT_CSV = PROCESSED_DIR / "relative_strength_nasdaq100_optionable.csv"
DEFAULT_OUTPUT_MD = PROCESSED_DIR / "relative_strength_nasdaq100_optionable.md"
BENCHMARK_TICKER = "QQQ"


def ensure_ticker_data(ticker: str, key_cooldown_seconds: int) -> None:
    path = ticker_csv_path(ticker)
    if path.exists() and path.stat().st_size > 0:
        return

    ensure_directories()
    start, end = get_date_range()
    api_key_pool = ApiKeyPool(api_keys=load_api_keys(), cooldown_seconds=key_cooldown_seconds)
    status = download_one_ticker(
        ticker=ticker,
        start=start,
        end=end,
        api_key_pool=api_key_pool,
        max_retries=3,
        retry_wait_seconds=60,
    )
    if status not in {"success", "skipped"}:
        raise RuntimeError(f"Could not download {ticker}: {status}")


def load_selected_tickers(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Selected file not found: {path}")

    df = pd.read_csv(path)
    if "ticker" not in df.columns:
        raise ValueError(f"Selected file has no ticker column: {path}")

    tickers = []
    seen = set()
    for value in df["ticker"].dropna().astype(str):
        ticker = value.strip().upper()
        if ticker and ticker not in seen:
            seen.add(ticker)
            tickers.append(ticker)
    return tickers


def calculate_relative_strength(ticker: str, benchmark_ticker: str) -> dict[str, object] | None:
    path = ticker_csv_path(ticker)
    if not path.exists() or path.stat().st_size == 0:
        print(f"{ticker} skipped: missing local CSV")
        return None

    df = pd.read_csv(path)
    if df.empty:
        print(f"{ticker} skipped: empty CSV")
        return None

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["date", "close"]).sort_values("date")

    if len(df) < 19:
        print(f"{ticker} skipped: fewer than 19 rows for MA10 center")
        return None

    df["ma10"] = df["close"].rolling(10).mean()
    ma10_window = df["ma10"].dropna().tail(10)
    if len(ma10_window) < 10:
        print(f"{ticker} skipped: fewer than 10 MA10 points")
        return None

    latest = df.iloc[-1]
    ma10_center = ma10_window.mean()
    relative_strength_pct = (latest["close"] / ma10_center - 1) * 100

    return {
        "ticker": ticker,
        "type": "Benchmark ETF" if ticker == benchmark_ticker else "Stock",
        "date": latest["date"].date().isoformat(),
        "close": latest["close"],
        "latest_ma10": df["ma10"].iloc[-1],
        "ma10_center_10d": ma10_center,
        "relative_strength_pct": relative_strength_pct,
    }


def build_report_rows(selected_tickers: list[str], benchmark_ticker: str) -> pd.DataFrame:
    tickers = list(selected_tickers)
    if benchmark_ticker not in tickers:
        tickers.append(benchmark_ticker)

    rows = []
    for ticker in tickers:
        row = calculate_relative_strength(ticker, benchmark_ticker)
        if row is not None:
            rows.append(row)

    if not rows:
        raise ValueError("No relative strength rows generated.")

    df = pd.DataFrame(rows)
    benchmark_rows = df[df["ticker"] == benchmark_ticker]
    if benchmark_rows.empty:
        raise ValueError(f"Benchmark ticker missing from report: {benchmark_ticker}")

    benchmark_strength = benchmark_rows.iloc[0]["relative_strength_pct"]
    df["excess_vs_benchmark_pct"] = df["relative_strength_pct"] - benchmark_strength
    df = df.sort_values("relative_strength_pct", ascending=False).reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))
    return df


def write_markdown(df: pd.DataFrame, output_file: Path, benchmark_ticker: str) -> None:
    display_df = df.copy()
    display_df["ticker"] = display_df["ticker"].apply(
        lambda ticker: f"**{ticker}**" if ticker == benchmark_ticker else ticker
    )
    numeric_columns = [
        "close",
        "latest_ma10",
        "ma10_center_10d",
        "relative_strength_pct",
        "excess_vs_benchmark_pct",
    ]
    for column in numeric_columns:
        display_df[column] = display_df[column].map(lambda value: round(float(value), 4))

    headers = list(display_df.columns)
    rows = display_df.astype(str).values.tolist()
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build relative strength report for selected stocks versus QQQ.")
    parser.add_argument("--selected-file", default=str(DEFAULT_SELECTED_FILE), help="Selected ticker CSV path.")
    parser.add_argument("--benchmark", default=BENCHMARK_TICKER, help="Benchmark ETF ticker.")
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV), help="Output CSV path.")
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD), help="Output Markdown path.")
    parser.add_argument("--key-cooldown-seconds", type=int, default=13, help="Cooldown per API key for missing benchmark download.")
    return parser.parse_args()


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT_DIR / path


def main() -> None:
    args = parse_args()
    selected_file = resolve_path(args.selected_file)
    output_csv = resolve_path(args.output_csv)
    output_md = resolve_path(args.output_md)
    benchmark = args.benchmark.strip().upper()

    ensure_ticker_data(benchmark, args.key_cooldown_seconds)
    selected_tickers = load_selected_tickers(selected_file)
    report_df = build_report_rows(selected_tickers, benchmark)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    report_df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    write_markdown(report_df, output_md, benchmark)

    benchmark_rank = int(report_df.loc[report_df["ticker"] == benchmark, "rank"].iloc[0])
    benchmark_strength = float(report_df.loc[report_df["ticker"] == benchmark, "relative_strength_pct"].iloc[0])

    print("Relative strength report finished")
    print(f"Selected stocks: {len(selected_tickers)}")
    print(f"Rows including benchmark: {len(report_df)}")
    print(f"Benchmark: {benchmark}")
    print(f"Benchmark rank: {benchmark_rank}")
    print(f"Benchmark relative strength pct: {benchmark_strength:.4f}")
    print(f"CSV output: {output_csv}")
    print(f"Markdown output: {output_md}")
    print(report_df.head(30).to_string(index=False))


if __name__ == "__main__":
    main()
