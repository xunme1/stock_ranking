from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT_DIR / "data" / "processed"
DEFAULT_INPUT_FILE = PROCESSED_DIR / "us_stocks_daily.parquet"
DEFAULT_ALL_FILE = PROCESSED_DIR / "stock_screen_ma5_ma10_all.csv"
DEFAULT_SELECTED_FILE = PROCESSED_DIR / "stock_screen_ma5_ma10_selected.csv"


def parse_tickers(value: str | None) -> set[str] | None:
    if not value:
        return None
    tickers = {ticker.strip().upper() for ticker in value.split(",") if ticker.strip()}
    return tickers or None


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT_DIR / path


def load_daily_data(input_file: Path, tickers: set[str] | None = None) -> pd.DataFrame:
    if not input_file.exists():
        raise FileNotFoundError(f"Parquet file not found: {input_file}")

    df = pd.read_parquet(input_file)
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["ticker", "date", "close"])

    if tickers:
        df = df[df["ticker"].isin(tickers)].copy()
    if df.empty:
        raise ValueError("No daily data available after filtering.")

    return df.sort_values(["ticker", "date"])


def calculate_one_ticker(g: pd.DataFrame) -> dict[str, object] | None:
    g = g.copy().sort_values("date")
    ticker = str(g["ticker"].iloc[0])

    if len(g) < 10:
        print(f"{ticker} skipped: fewer than 10 daily rows")
        return None

    g["ma5"] = g["close"].rolling(5).mean()
    g["ma10"] = g["close"].rolling(10).mean()
    g["return_1d"] = g["close"].pct_change(1) * 100
    g["return_5d"] = g["close"].pct_change(5) * 100
    g["return_10d"] = g["close"].pct_change(10) * 100
    g["return_20d"] = g["close"].pct_change(20) * 100
    g["volume_ma20"] = g["volume"].rolling(20).mean()
    g["volume_ratio_20d"] = g["volume"] / g["volume_ma20"]

    latest = g.iloc[-1]
    if pd.isna(latest["ma5"]) or pd.isna(latest["ma10"]):
        return None

    close = latest["close"]
    above_ma5 = bool(close > latest["ma5"])
    above_ma10 = bool(close > latest["ma10"])

    return {
        "ticker": ticker,
        "date": latest["date"].date().isoformat(),
        "close": close,
        "ma5": latest["ma5"],
        "ma10": latest["ma10"],
        "above_ma5": above_ma5,
        "above_ma10": above_ma10,
        "selected": above_ma5 and above_ma10,
        "volume": latest["volume"],
        "volume_ma20": latest["volume_ma20"],
        "volume_ratio_20d": latest["volume_ratio_20d"],
        "return_1d": latest["return_1d"],
        "return_5d": latest["return_5d"],
        "return_10d": latest["return_10d"],
        "return_20d": latest["return_20d"],
    }


def build_screen_result(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, g in df.groupby("ticker", sort=True):
        row = calculate_one_ticker(g)
        if row is not None:
            rows.append(row)

    if not rows:
        raise ValueError("No MA5/MA10 screen rows generated.")

    return pd.DataFrame(rows)


def save_screen_result(screen_df: pd.DataFrame, all_file: Path, selected_file: Path) -> pd.DataFrame:
    selected_df = screen_df[screen_df["selected"]].copy()
    selected_df = selected_df.sort_values(["return_20d", "return_5d"], ascending=[False, False])

    all_file.parent.mkdir(parents=True, exist_ok=True)
    screen_df.to_csv(all_file, index=False, encoding="utf-8-sig")
    selected_df.to_csv(selected_file, index=False, encoding="utf-8-sig")
    return selected_df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Screen stocks where latest close is above MA5 and MA10.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT_FILE), help="Input Parquet path.")
    parser.add_argument("--output-all", default=str(DEFAULT_ALL_FILE), help="All screen rows CSV path.")
    parser.add_argument("--output-selected", default=str(DEFAULT_SELECTED_FILE), help="Selected rows CSV path.")
    parser.add_argument("--tickers", default=None, help="Comma-separated ticker subset, for example MRVL,COHR.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_file = resolve_path(args.input)
    all_file = resolve_path(args.output_all)
    selected_file = resolve_path(args.output_selected)
    tickers = parse_tickers(args.tickers)

    df = load_daily_data(input_file, tickers=tickers)
    screen_df = build_screen_result(df)
    selected_df = save_screen_result(screen_df, all_file, selected_file)

    print("MA5/MA10 screen finished")
    print(f"Input tickers: {df['ticker'].nunique()}")
    print(f"Screen rows: {len(screen_df)}")
    print(f"Selected rows: {len(selected_df)}")
    print(f"All output: {all_file}")
    print(f"Selected output: {selected_file}")
    print(selected_df.head(30).to_string(index=False))


if __name__ == "__main__":
    main()
