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
CONFIG_DIR = ROOT_DIR / "config"
PROCESSED_DIR = ROOT_DIR / "data" / "processed"
DEFAULT_UNIVERSE_FILE = CONFIG_DIR / "nasdaq100_tickers.txt"
DEFAULT_OUTPUT_CSV = PROCESSED_DIR / "nasdaq100_atr_relative_strength.csv"
DEFAULT_OUTPUT_MD = PROCESSED_DIR / "nasdaq100_atr_relative_strength.md"
BENCHMARK_TICKER = "QQQ"

ANNOUNCED_2026_06_22_ADDS = ["ALAB", "CRWV", "NBIS", "RKLB", "TER"]
ANNOUNCED_2026_06_22_REMOVES = ["CHTR", "CTSH", "INSM", "VRSK", "ZS"]


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT_DIR / path


def load_universe(path: Path, apply_announced_rebalance: bool) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Universe file not found: {path}")

    tickers = []
    seen = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        ticker = line.strip().upper()
        if not ticker or ticker.startswith("#") or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)

    if apply_announced_rebalance:
        remove_set = set(ANNOUNCED_2026_06_22_REMOVES)
        tickers = [ticker for ticker in tickers if ticker not in remove_set]
        for ticker in ANNOUNCED_2026_06_22_ADDS:
            if ticker not in tickers:
                tickers.append(ticker)

    return tickers


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


def ensure_all_data(tickers: list[str], key_cooldown_seconds: int) -> None:
    for ticker in tickers:
        ensure_ticker_data(ticker, key_cooldown_seconds)


def calculate_one_ticker(ticker: str, benchmark_ticker: str) -> dict[str, object] | None:
    path = ticker_csv_path(ticker)
    if not path.exists() or path.stat().st_size == 0:
        print(f"{ticker} skipped: missing local CSV")
        return None

    df = pd.read_csv(path)
    required_columns = {"date", "high", "low", "close"}
    if df.empty or not required_columns.issubset(df.columns):
        print(f"{ticker} skipped: missing required OHLC columns")
        return None

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for column in ["high", "low", "close"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["date", "high", "low", "close"]).sort_values("date")

    if len(df) < 19:
        print(f"{ticker} skipped: fewer than 19 rows")
        return None

    previous_close = df["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - previous_close).abs(),
            (df["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    df["ma10"] = df["close"].rolling(10).mean()
    df["atr10"] = true_range.rolling(10).mean()
    ma10_center_10d = df["ma10"].dropna().tail(10).mean()
    latest = df.iloc[-1]

    if pd.isna(ma10_center_10d) or pd.isna(latest["atr10"]) or latest["atr10"] == 0:
        print(f"{ticker} skipped: invalid MA10 center or ATR10")
        return None

    atr_score = (latest["close"] - ma10_center_10d) / latest["atr10"]
    return {
        "ticker": ticker,
        "type": "Nasdaq-100 ETF" if ticker == benchmark_ticker else "Nasdaq-100 Stock",
        "date": latest["date"].date().isoformat(),
        "close": latest["close"],
        "latest_ma10": latest["ma10"],
        "ma10_center_10d": ma10_center_10d,
        "atr10": latest["atr10"],
        "atr_score": atr_score,
        "price_vs_center_pct": (latest["close"] / ma10_center_10d - 1) * 100,
    }


def build_report(tickers: list[str], benchmark_ticker: str) -> pd.DataFrame:
    full_tickers = list(tickers)
    if benchmark_ticker not in full_tickers:
        full_tickers.append(benchmark_ticker)

    rows = []
    for ticker in full_tickers:
        row = calculate_one_ticker(ticker, benchmark_ticker)
        if row is not None:
            rows.append(row)

    if not rows:
        raise ValueError("No ATR relative strength rows generated.")

    report_df = pd.DataFrame(rows)
    benchmark_row = report_df[report_df["ticker"] == benchmark_ticker]
    if benchmark_row.empty:
        raise ValueError(f"Benchmark ticker missing from report: {benchmark_ticker}")

    benchmark_score = float(benchmark_row.iloc[0]["atr_score"])
    report_df["excess_atr_vs_benchmark"] = report_df["atr_score"] - benchmark_score
    report_df = report_df.sort_values("atr_score", ascending=False).reset_index(drop=True)
    report_df.insert(0, "rank", range(1, len(report_df) + 1))
    return report_df


def write_markdown(df: pd.DataFrame, output_file: Path, benchmark_ticker: str) -> None:
    display_df = df.copy()
    display_df["ticker"] = display_df["ticker"].apply(
        lambda ticker: f"**{ticker}**" if ticker == benchmark_ticker else ticker
    )
    for column in [
        "close",
        "latest_ma10",
        "ma10_center_10d",
        "atr10",
        "atr_score",
        "price_vs_center_pct",
        "excess_atr_vs_benchmark",
    ]:
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
    parser = argparse.ArgumentParser(description="Build Nasdaq-100 ATR relative strength report versus QQQ.")
    parser.add_argument("--universe-file", default=str(DEFAULT_UNIVERSE_FILE), help="Nasdaq-100 ticker file.")
    parser.add_argument("--benchmark", default=BENCHMARK_TICKER, help="Benchmark ETF ticker.")
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV), help="Output CSV path.")
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD), help="Output Markdown path.")
    parser.add_argument("--key-cooldown-seconds", type=int, default=13, help="Cooldown per API key for missing data downloads.")
    parser.add_argument(
        "--apply-announced-2026-06-22-rebalance",
        action="store_true",
        help="Apply announced Nasdaq-100 changes effective 2026-06-22.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    universe_file = resolve_path(args.universe_file)
    output_csv = resolve_path(args.output_csv)
    output_md = resolve_path(args.output_md)
    benchmark = args.benchmark.strip().upper()

    tickers = load_universe(universe_file, args.apply_announced_2026_06_22_rebalance)
    ensure_all_data(tickers + [benchmark], args.key_cooldown_seconds)
    report_df = build_report(tickers, benchmark)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    report_df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    write_markdown(report_df, output_md, benchmark)

    benchmark_rank = int(report_df.loc[report_df["ticker"] == benchmark, "rank"].iloc[0])
    benchmark_score = float(report_df.loc[report_df["ticker"] == benchmark, "atr_score"].iloc[0])

    print("ATR relative strength report finished")
    print(f"Universe tickers: {len(tickers)}")
    print(f"Rows including benchmark: {len(report_df)}")
    print(f"Benchmark: {benchmark}")
    print(f"Benchmark rank: {benchmark_rank}")
    print(f"Benchmark ATR score: {benchmark_score:.4f}")
    print(f"Applied announced 2026-06-22 rebalance: {args.apply_announced_2026_06_22_rebalance}")
    print(f"CSV output: {output_csv}")
    print(f"Markdown output: {output_md}")
    print(report_df.head(30).to_string(index=False))


if __name__ == "__main__":
    main()
