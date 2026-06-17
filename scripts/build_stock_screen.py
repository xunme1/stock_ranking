from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT_DIR / "data" / "processed"
DEFAULT_INPUT_FILE = PROCESSED_DIR / "us_stocks_daily.parquet"
DEFAULT_ALL_FILE = PROCESSED_DIR / "stock_screen_all.csv"
DEFAULT_SELECTED_FILE = PROCESSED_DIR / "stock_screen_selected.csv"


def parse_tickers(value: str | None) -> set[str] | None:
    if not value:
        return None
    tickers = {ticker.strip().upper() for ticker in value.split(",") if ticker.strip()}
    return tickers or None


def load_tickers_file(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    if not path.exists():
        raise FileNotFoundError(f"Ticker file not found: {path}")

    tickers = {
        line.strip().upper()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
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


def calculate_daily_indicators(g: pd.DataFrame) -> pd.DataFrame:
    g = g.copy().sort_values("date")
    g["ma10_daily"] = g["close"].rolling(10).mean()
    g["return_1d"] = g["close"].pct_change(1) * 100
    g["return_5d"] = g["close"].pct_change(5) * 100
    g["return_20d"] = g["close"].pct_change(20) * 100
    g["volume_ma20"] = g["volume"].rolling(20).mean()
    g["volume_ratio_20d"] = g["volume"] / g["volume_ma20"]
    return g


def build_weekly_data(g: pd.DataFrame) -> pd.DataFrame:
    weekly = (
        g.set_index("date")
        .resample("W-FRI")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna(subset=["close"])
    )
    weekly["ma10_weekly"] = weekly["close"].rolling(10).mean()
    return weekly


def calculate_one_ticker(g: pd.DataFrame) -> dict[str, object] | None:
    g = calculate_daily_indicators(g)
    if len(g) < 60:
        print(f"{g['ticker'].iloc[0]} skipped: fewer than 60 daily rows")
        return None

    latest = g.iloc[-1]
    if pd.isna(latest["ma10_daily"]):
        return None

    weekly = build_weekly_data(g)
    if len(weekly) < 10:
        print(f"{latest['ticker']} skipped: fewer than 10 weekly rows")
        return None

    latest_weekly = weekly.iloc[-1]
    if pd.isna(latest_weekly["ma10_weekly"]):
        return None

    latest_close = latest["close"]
    ma10_daily = latest["ma10_daily"]
    ma10_weekly = latest_weekly["ma10_weekly"]
    above_ma10_daily = bool(latest_close > ma10_daily)
    above_ma10_weekly = bool(latest_close > ma10_weekly)

    return {
        "ticker": latest["ticker"],
        "date": latest["date"].date().isoformat(),
        "close": latest_close,
        "ma10_daily": ma10_daily,
        "weekly_date": latest_weekly.name.date().isoformat(),
        "weekly_close": latest_weekly["close"],
        "ma10_weekly": ma10_weekly,
        "above_ma10_daily": above_ma10_daily,
        "above_ma10_weekly": above_ma10_weekly,
        "selected": above_ma10_daily and above_ma10_weekly,
        "volume": latest["volume"],
        "volume_ma20": latest["volume_ma20"],
        "volume_ratio_20d": latest["volume_ratio_20d"],
        "return_1d": latest["return_1d"],
        "return_5d": latest["return_5d"],
        "return_20d": latest["return_20d"],
    }


def build_screen_result(df: pd.DataFrame) -> pd.DataFrame:
    results = []
    for _, g in df.groupby("ticker", sort=True):
        row = calculate_one_ticker(g)
        if row is not None:
            results.append(row)

    if not results:
        raise ValueError("No stock screen rows generated.")

    return pd.DataFrame(results)


def save_screen_result(screen_df: pd.DataFrame, all_file: Path, selected_file: Path) -> pd.DataFrame:
    selected_df = screen_df[screen_df["selected"]].copy()
    selected_df = selected_df.sort_values("return_20d", ascending=False)

    all_file.parent.mkdir(parents=True, exist_ok=True)
    screen_df.to_csv(all_file, index=False, encoding="utf-8-sig")
    selected_df.to_csv(selected_file, index=False, encoding="utf-8-sig")
    return selected_df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build daily/weekly trend screen results.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT_FILE), help="Input Parquet path.")
    parser.add_argument("--output-all", default=str(DEFAULT_ALL_FILE), help="All screen rows CSV path.")
    parser.add_argument("--output-selected", default=str(DEFAULT_SELECTED_FILE), help="Selected rows CSV path.")
    parser.add_argument("--tickers", default=None, help="Comma-separated ticker subset, for example MRVL,COHR.")
    parser.add_argument("--tickers-file", default=None, help="Ticker file filter, one ticker per line.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_file = resolve_path(args.input)
    all_file = resolve_path(args.output_all)
    selected_file = resolve_path(args.output_selected)
    tickers = parse_tickers(args.tickers)
    file_tickers = load_tickers_file(resolve_path(args.tickers_file) if args.tickers_file else None)
    if tickers and file_tickers:
        tickers = tickers & file_tickers
    elif file_tickers:
        tickers = file_tickers

    df = load_daily_data(input_file, tickers=tickers)
    screen_df = build_screen_result(df)
    selected_df = save_screen_result(screen_df, all_file, selected_file)

    print("Stock screen finished")
    print(f"Input tickers: {df['ticker'].nunique()}")
    print(f"Screen rows: {len(screen_df)}")
    print(f"Selected rows: {len(selected_df)}")
    print(f"All output: {all_file}")
    print(f"Selected output: {selected_file}")
    print(screen_df.to_string(index=False))


if __name__ == "__main__":
    main()
