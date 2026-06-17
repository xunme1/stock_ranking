from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
RAW_DAILY_DIR = ROOT_DIR / "data" / "raw" / "daily"
PROCESSED_DIR = ROOT_DIR / "data" / "processed"
DEFAULT_OUTPUT_FILE = PROCESSED_DIR / "us_stocks_daily.parquet"
REQUIRED_COLUMNS = ["ticker", "date", "open", "high", "low", "close", "volume"]


def parse_tickers(value: str | None) -> list[str] | None:
    if not value:
        return None
    tickers = [ticker.strip().upper() for ticker in value.split(",") if ticker.strip()]
    return tickers or None


def csv_paths(tickers: list[str] | None = None) -> list[Path]:
    if tickers:
        return [RAW_DAILY_DIR / f"{ticker}.csv" for ticker in tickers]
    return sorted(RAW_DAILY_DIR.glob("*.csv"))


def load_one_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        print(f"Missing CSV, skipped: {path.name}")
        return None
    if path.stat().st_size == 0:
        print(f"Empty CSV, skipped: {path.name}")
        return None

    try:
        df = pd.read_csv(path)
    except Exception as exc:
        print(f"Read failed, skipped {path.name}: {exc}")
        return None

    missing_columns = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_columns:
        print(f"Bad columns, skipped {path.name}: missing {missing_columns}")
        return None

    return df


def merge_all_csv(tickers: list[str] | None = None) -> pd.DataFrame:
    frames = []
    for path in csv_paths(tickers):
        df = load_one_csv(path)
        if df is not None and not df.empty:
            frames.append(df)

    if not frames:
        raise ValueError("No usable CSV files found.")

    return pd.concat(frames, ignore_index=True)


def clean_merged_data(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["ticker", "date", "close"])

    numeric_columns = ["open", "high", "low", "close", "volume", "vwap", "transactions"]
    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    return df


def save_parquet(df: pd.DataFrame, output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_file, index=False, engine="pyarrow")


def print_summary(df: pd.DataFrame, output_file: Path) -> None:
    print("Merge finished")
    print(f"Tickers: {df['ticker'].nunique()}")
    print(f"Rows: {len(df)}")
    print(f"Start date: {df['date'].min().date()}")
    print(f"End date: {df['date'].max().date()}")
    print(f"Output file: {output_file}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge per-ticker daily CSV files into one Parquet file.")
    parser.add_argument("--tickers", default=None, help="Comma-separated ticker subset, for example MRVL,COHR.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_FILE), help="Output Parquet path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tickers = parse_tickers(args.tickers)
    output_file = Path(args.output)
    if not output_file.is_absolute():
        output_file = ROOT_DIR / output_file

    merged = merge_all_csv(tickers=tickers)
    cleaned = clean_merged_data(merged)
    save_parquet(cleaned, output_file)
    print_summary(cleaned, output_file)


if __name__ == "__main__":
    main()
