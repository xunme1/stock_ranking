from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from app.core.config import INDUSTRY_FUND_FLOW_DB  # noqa: E402
from app.services.data_loader import normalize_market  # noqa: E402
from ths_ifind_daily import ifind_session, normalize_cn_ticker, normalize_hk_ticker, normalize_us_ticker  # noqa: E402


RAW_DIR = ROOT_DIR / "data" / "raw" / "industry_fund_flow"
FLOW_COLUMN_RE = re.compile(r"资金流向\[(\d{8})\]")
MARKET_SCOPE = {"us": "US_stock", "cn": "stock", "hk": "HK_stock"}


@dataclass(frozen=True)
class ParsedFundFlow:
    stock_rows: pd.DataFrame
    industry_rows: pd.DataFrame


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def chinese_query_date(value: date) -> str:
    return f"{value.month}月{value.day}日"


def build_ifind_query(start: date, end: date) -> str:
    return f"{chinese_query_date(start)}-{chinese_query_date(end)}行业资金流向，同花顺三级行业"


def raw_csv_path(market: str, start: date, end: date) -> Path:
    return RAW_DIR / f"industry_fund_flow_raw_{market}_{start.isoformat()}_{end.isoformat()}.csv"


def normalize_ticker_for_flow(value: object, market: str) -> str:
    text = str(value or "").strip().upper()
    if market == "cn":
        return normalize_cn_ticker(text)
    if market == "hk":
        return normalize_hk_ticker(text)
    for suffix in [".O", ".N", ".A", ".B", ".P", ".PK"]:
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return normalize_us_ticker(text)


def select_column(columns: list[str], keywords: list[str]) -> str | None:
    for keyword in keywords:
        for column in columns:
            if keyword in column:
                return column
    return None


def industry_column_for_market(df: pd.DataFrame, market: str) -> str:
    columns = [str(column) for column in df.columns]
    if market == "cn":
        selected = select_column(columns, ["所属同花顺三级行业", "同花顺三级行业", "所属同花顺行业"])
    elif market == "hk":
        selected = select_column(columns, ["所属恒生行业", "同花顺三级行业", "行业"])
    else:
        selected = select_column(columns, ["全球行业三级分类", "同花顺三级行业", "行业"])
    if not selected:
        raise ValueError(f"Cannot find industry column for market {market}: {columns}")
    return selected


def parse_raw_frame(df: pd.DataFrame, market: str) -> ParsedFundFlow:
    market = normalize_market(market)
    code_col = select_column([str(column) for column in df.columns], ["股票代码"])
    name_col = select_column([str(column) for column in df.columns], ["股票简称"])
    industry_col = industry_column_for_market(df, market)
    if not code_col or not name_col:
        raise ValueError("Raw iFinD frame must contain 股票代码 and 股票简称 columns")

    flow_columns: list[tuple[str, str]] = []
    for column in df.columns:
        match = FLOW_COLUMN_RE.search(str(column))
        if match:
            raw_date = match.group(1)
            flow_columns.append((str(column), f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"))
    if not flow_columns:
        raise ValueError("No 资金流向[YYYYMMDD] columns found")

    rows: list[dict[str, object]] = []
    base = df[[code_col, name_col, industry_col] + [column for column, _ in flow_columns]].copy()
    base = base.fillna({code_col: "", name_col: "", industry_col: ""})
    for source_row in base.itertuples(index=False):
        values = dict(zip(base.columns, source_row))
        ths_code = str(values[code_col]).strip().upper()
        name = str(values[name_col]).strip()
        industry_name = str(values[industry_col]).strip()
        ticker = normalize_ticker_for_flow(ths_code, market)
        if not ticker or not industry_name:
            continue
        for column, trade_date in flow_columns:
            flow_amount = pd.to_numeric(values[column], errors="coerce")
            if pd.isna(flow_amount):
                continue
            rows.append(
                {
                    "market": market,
                    "trade_date": trade_date,
                    "ticker": ticker,
                    "ths_code": ths_code,
                    "name": name,
                    "industry_name": industry_name,
                    "flow_amount": float(flow_amount),
                }
            )

    stock_rows = pd.DataFrame(
        rows,
        columns=["market", "trade_date", "ticker", "ths_code", "name", "industry_name", "flow_amount"],
    )
    if stock_rows.empty:
        industry_rows = pd.DataFrame(
            columns=["market", "trade_date", "industry_name", "flow_amount", "stock_count", "positive_count", "negative_count"]
        )
    else:
        grouped = stock_rows.groupby(["market", "trade_date", "industry_name"], as_index=False)
        industry_rows = grouped.agg(
            flow_amount=("flow_amount", "sum"),
            stock_count=("ticker", "nunique"),
            positive_count=("flow_amount", lambda values: int((values > 0).sum())),
            negative_count=("flow_amount", lambda values: int((values < 0).sum())),
        )
    return ParsedFundFlow(stock_rows=stock_rows, industry_rows=industry_rows)


def ensure_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_fund_flows (
            market TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            ths_code TEXT NOT NULL,
            name TEXT NOT NULL,
            industry_name TEXT NOT NULL,
            flow_amount REAL NOT NULL,
            PRIMARY KEY (market, trade_date, ticker)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_stock_fund_flows_industry_date
        ON stock_fund_flows (market, industry_name, trade_date)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS industry_fund_flows (
            market TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            industry_name TEXT NOT NULL,
            flow_amount REAL NOT NULL,
            stock_count INTEGER NOT NULL,
            positive_count INTEGER NOT NULL,
            negative_count INTEGER NOT NULL,
            PRIMARY KEY (market, trade_date, industry_name)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_industry_fund_flows_date
        ON industry_fund_flows (market, trade_date)
        """
    )


def import_to_db(parsed: ParsedFundFlow, db_path: Path = INDUSTRY_FUND_FLOW_DB) -> tuple[int, int]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        ensure_db(conn)
        stock_rows = list(parsed.stock_rows.itertuples(index=False, name=None))
        industry_rows = list(parsed.industry_rows.itertuples(index=False, name=None))
        conn.executemany(
            """
            INSERT INTO stock_fund_flows
            (market, trade_date, ticker, ths_code, name, industry_name, flow_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(market, trade_date, ticker) DO UPDATE SET
                ths_code = excluded.ths_code,
                name = excluded.name,
                industry_name = excluded.industry_name,
                flow_amount = excluded.flow_amount
            """,
            stock_rows,
        )
        conn.executemany(
            """
            INSERT INTO industry_fund_flows
            (market, trade_date, industry_name, flow_amount, stock_count, positive_count, negative_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(market, trade_date, industry_name) DO UPDATE SET
                flow_amount = excluded.flow_amount,
                stock_count = excluded.stock_count,
                positive_count = excluded.positive_count,
                negative_count = excluded.negative_count
            """,
            industry_rows,
        )
    return len(stock_rows), len(industry_rows)


def fetch_raw_frame(market: str, start: date, end: date) -> pd.DataFrame:
    market = normalize_market(market)
    scope = MARKET_SCOPE[market]
    query = build_ifind_query(start, end)
    with ifind_session():
        from iFinDPy import THS_WCQuery  # type: ignore

        payload = THS_WCQuery(query, scope)
        error_code = getattr(payload, "errorcode", None)
        if error_code != 0:
            raise RuntimeError(f"THS_WCQuery failed for {market}: {error_code} {getattr(payload, 'errmsg', '')}")
        df = getattr(payload, "data", None)
        if df is None or df.empty:
            raise RuntimeError(f"THS_WCQuery returned empty data for {market}")
        return df


def fetch_and_save(market: str, start: date, end: date) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    df = fetch_raw_frame(market, start, end)
    path = raw_csv_path(normalize_market(market), start, end)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def import_csv(path: Path, market: str) -> tuple[int, int]:
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    parsed = parse_raw_frame(df, market)
    return import_to_db(parsed)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch, parse, and import iFinD industry fund-flow data.")
    parser.add_argument("--markets", default="us,cn,hk", help="Comma-separated markets: us,cn,hk")
    parser.add_argument("--start-date", default="2026-06-01")
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--csv", action="append", default=[], help="Import an existing raw CSV as market=path")
    parser.add_argument("--fetch", action="store_true", help="Fetch raw CSV from iFinD before importing")
    parser.add_argument("--import-only", action="store_true", help="Import existing default raw CSV paths")
    args = parser.parse_args()

    start = parse_date(args.start_date)
    end = parse_date(args.end_date)
    markets = [normalize_market(item) for item in args.markets.split(",") if item.strip()]

    csv_paths: dict[str, Path] = {}
    for item in args.csv:
        if "=" not in item:
            raise SystemExit("--csv must use market=path")
        market, path = item.split("=", 1)
        csv_paths[normalize_market(market)] = Path(path)

    if args.fetch:
        for market in markets:
            path = fetch_and_save(market, start, end)
            csv_paths[market] = path
            print(f"[saved] {market}: {path}")
    elif args.import_only:
        for market in markets:
            csv_paths.setdefault(market, raw_csv_path(market, start, end))

    if not csv_paths:
        raise SystemExit("Nothing to do. Use --fetch, --import-only, or --csv market=path.")

    for market, path in csv_paths.items():
        stock_count, industry_count = import_csv(path, market)
        print(f"[imported] {market}: stock_rows={stock_count} industry_rows={industry_count} source={path}")


if __name__ == "__main__":
    main()
