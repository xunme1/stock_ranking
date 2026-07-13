from __future__ import annotations

import argparse
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from ths_ifind_daily import EXTENDED_COLUMNS, fetch_ifind_history, ifind_session, merge_daily_csv


ROOT_DIR = Path(__file__).resolve().parents[1]
POOL_FILE = ROOT_DIR / "config" / "cn_stock_pool.csv"
RAW_CN_DAILY_DIR = ROOT_DIR / "data" / "raw" / "cn_daily"
BENCHMARK_CODE = "000905"
BENCHMARK_AK_SYMBOL = "sh000905"


def load_akshare():
    try:
        import akshare as ak  # type: ignore
    except ImportError as exc:
        raise SystemExit("AkShare is not installed. Run: .\\.venv\\Scripts\\pip.exe install akshare") from exc
    return ak


def normalize_cn_code(value: object) -> str:
    text = str(value or "").strip().upper()
    if "." in text:
        text = text.split(".", 1)[0]
    if text.startswith(("SH", "SZ", "BJ")):
        text = text[2:]
    return text.zfill(6) if text.isdigit() else text


def ticker_csv_path(ticker: str) -> Path:
    return RAW_CN_DAILY_DIR / f"{normalize_cn_code(ticker)}.csv"


def ak_market_symbol(ticker: str) -> str:
    code = normalize_cn_code(ticker)
    if code.startswith(("6", "9")):
        return f"sh{code}"
    return f"sz{code}"


def load_pool(path: Path = POOL_FILE, limit: int | None = None) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"A-share pool not found: {path}. Run scripts/build_cn_stock_pool.py first.")
    df = pd.read_csv(path, dtype={"ticker": str}).fillna("")
    tickers = [normalize_cn_code(item) for item in df["ticker"].tolist()]
    tickers = [item for item in tickers if item]
    return tickers[:limit] if limit else tickers


def get_last_local_date(ticker: str) -> date | None:
    path = ticker_csv_path(ticker)
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        df = pd.read_csv(path, usecols=["date"])
    except Exception:
        return None
    if df.empty:
        return None
    dates = pd.to_datetime(df["date"], errors="coerce").dropna()
    if dates.empty:
        return None
    return dates.max().date()


def start_date_for_ticker(ticker: str, days: int, end: date) -> date:
    last_date = get_last_local_date(ticker)
    if last_date is not None:
        return last_date + timedelta(days=1)
    return end - timedelta(days=days * 2)


def normalize_stock_hist(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    column_map = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "turnover",
    }
    result = df.rename(columns=column_map).copy()
    keep = ["date", "open", "high", "low", "close", "volume", "turnover"]
    for column in keep:
        if column not in result.columns:
            result[column] = pd.NA
    result = result[keep]
    result.insert(0, "ticker", normalize_cn_code(ticker))
    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.date.astype(str)
    for column in ["open", "high", "low", "close", "volume", "turnover"]:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["vwap"] = pd.NA
    result["transactions"] = pd.NA
    return result.dropna(subset=["date", "open", "high", "low", "close"])


def normalize_index_hist(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    column_map = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "turnover",
    }
    result = df.rename(columns=column_map).copy()
    keep = ["date", "open", "high", "low", "close", "volume", "turnover"]
    for column in keep:
        if column not in result.columns:
            result[column] = pd.NA
    result = result[keep]
    result.insert(0, "ticker", normalize_cn_code(ticker))
    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.date.astype(str)
    for column in ["open", "high", "low", "close", "volume", "turnover"]:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["vwap"] = pd.NA
    result["transactions"] = pd.NA
    return result.dropna(subset=["date", "open", "high", "low", "close"])


def merge_old_new_data(ticker: str, new_df: pd.DataFrame) -> int:
    path = ticker_csv_path(ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        old_df = pd.read_csv(path, dtype={"ticker": str})
        combined = pd.concat([old_df, new_df], ignore_index=True)
    else:
        combined = new_df.copy()
    before = 0 if not path.exists() else len(pd.read_csv(path))
    combined["ticker"] = combined["ticker"].map(normalize_cn_code)
    combined["date"] = pd.to_datetime(combined["date"], errors="coerce").dt.date.astype(str)
    combined = combined.dropna(subset=["date", "open", "high", "low", "close"])
    combined = combined.drop_duplicates(subset=["ticker", "date"], keep="last")
    combined = combined.sort_values("date")
    columns = ["ticker", "date", "open", "high", "low", "close", "volume", "vwap", "transactions", "turnover"]
    for column in columns:
        if column not in combined.columns:
            combined[column] = pd.NA
    combined[columns].to_csv(path, index=False, encoding="utf-8-sig")
    return max(len(combined) - before, 0)


def fetch_stock_daily(ak, ticker: str, start: date, end: date, timeout: float) -> pd.DataFrame:
    symbol = ak_market_symbol(ticker)
    try:
        raw = ak.stock_zh_a_hist_tx(
            symbol=symbol,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="qfq",
            timeout=timeout,
        )
    except Exception:
        raw = ak.stock_zh_a_daily(
            symbol=symbol,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="qfq",
        )
    return normalize_stock_hist(raw, ticker)


def fetch_index_daily(ak, start: date, end: date) -> pd.DataFrame:
    raw = ak.stock_zh_index_daily(symbol=BENCHMARK_AK_SYMBOL)
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw = raw[(raw["date"].dt.date >= start) & (raw["date"].dt.date <= end)].copy()
    return normalize_index_hist(raw, BENCHMARK_CODE)


def update_one_ticker(
    ak,
    ticker: str,
    start: date,
    end: date,
    sleep_seconds: float,
    retries: int,
    timeout: float,
) -> tuple[str, int]:
    if start > end:
        return "skipped", 0
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            if ticker == BENCHMARK_CODE:
                df = fetch_index_daily(ak, start, end)
            else:
                df = fetch_stock_daily(ak, ticker, start, end, timeout)
            if df.empty:
                return "empty", 0
            return "success", merge_old_new_data(ticker, df)
        except Exception as exc:  # noqa: BLE001 - external data sources are noisy.
            last_error = exc
            if attempt < retries:
                time.sleep(max(sleep_seconds, 1))
    reason = str(last_error) if last_error else "unknown error"
    print(f"[failed] {ticker}: {reason}")
    return "failed", 0


def update_one_ticker_ths(ticker: str, start: date, end: date) -> tuple[str, int]:
    ticker = normalize_cn_code(ticker)
    if start > end:
        return "skipped", 0
    try:
        result = fetch_ifind_history(ticker, "cn", start, end)
        if ticker == BENCHMARK_CODE and not result.frame.empty:
            close = pd.to_numeric(result.frame["close"], errors="coerce").dropna()
            if not close.empty and close.median() < 1000:
                raise ValueError(
                    f"unexpected CSI 500 close values from {result.code}; "
                    "expected index points, got equity-like prices"
                )
        new_rows = merge_daily_csv(ticker_csv_path(ticker), ticker, result.frame, EXTENDED_COLUMNS)
        return "success", new_rows
    except Exception as exc:  # noqa: BLE001 - vendor SDK errors include plain dicts/strings.
        print(f"[failed] {ticker}: iFinD update error: {exc}")
        return "failed", 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update A-share qfq daily bars with iFinD or AkShare.")
    parser.add_argument("--source", choices=["ths", "akshare"], default="ths", help="Daily data source. Defaults to ths.")
    parser.add_argument("--pool-file", default=str(POOL_FILE), help="Normalized A-share pool CSV.")
    parser.add_argument("--tickers", default=None, help="Comma-separated ticker override.")
    parser.add_argument("--limit", type=int, default=None, help="Only update first N pool tickers.")
    parser.add_argument("--days", type=int, default=30, help="Lookback days for missing local CSVs.")
    parser.add_argument("--end-date", default=date.today().isoformat(), help="End date in YYYY-MM-DD.")
    parser.add_argument("--sleep-seconds", type=float, default=2.0, help="Sleep after each request.")
    parser.add_argument("--retries", type=int, default=2, help="Retries per ticker.")
    parser.add_argument("--timeout", type=float, default=15.0, help="AkShare per-request timeout seconds for stock data.")
    parser.add_argument("--skip-benchmark", action="store_true", help="Do not update CSI 500 benchmark.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    end = date.fromisoformat(args.end_date)
    if args.tickers:
        tickers = [normalize_cn_code(item) for item in args.tickers.split(",") if item.strip()]
    else:
        tickers = load_pool(Path(args.pool_file), args.limit)
    if not args.skip_benchmark and BENCHMARK_CODE not in tickers:
        tickers.append(BENCHMARK_CODE)

    ak = None if args.source == "ths" else load_akshare()
    stats = {"success": 0, "skipped": 0, "empty": 0, "failed": 0}
    total_new_rows = 0
    print(f"A-share tickers: {len(tickers)}")
    print(f"End date: {end.isoformat()}")
    print(f"Source: {args.source}")
    print(f"Sleep seconds: {args.sleep_seconds}")

    progress = tqdm(tickers, desc="A-share daily", unit="ticker")
    if args.source == "ths":
        with ifind_session():
            for index, ticker in enumerate(progress, start=1):
                start = start_date_for_ticker(ticker, args.days, end)
                progress.set_postfix_str(ticker)
                status, new_rows = update_one_ticker_ths(ticker, start, end)
                stats[status] = stats.get(status, 0) + 1
                total_new_rows += new_rows
                tqdm.write(f"[{index}/{len(tickers)}] {ticker} {status} new_rows={new_rows}")
                time.sleep(args.sleep_seconds)
    else:
        for index, ticker in enumerate(progress, start=1):
            start = start_date_for_ticker(ticker, args.days, end)
            progress.set_postfix_str(ticker)
            status, new_rows = update_one_ticker(ak, ticker, start, end, args.sleep_seconds, args.retries, args.timeout)
            stats[status] = stats.get(status, 0) + 1
            total_new_rows += new_rows
            tqdm.write(f"[{index}/{len(tickers)}] {ticker} {status} new_rows={new_rows}")
            time.sleep(args.sleep_seconds)

    print(
        "A-share update finished "
        f"success={stats['success']} skipped={stats['skipped']} empty={stats['empty']} "
        f"failed={stats['failed']} new_rows={total_new_rows}"
    )


if __name__ == "__main__":
    main()
