from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
POOL_FILES = {
    "cn": ROOT_DIR / "config" / "cn_stock_pool.csv",
    "hk": ROOT_DIR / "config" / "hk_stock_pool.csv",
}
POOL_COLUMNS = {
    "cn": ["ticker", "name", "sector", "stock_type", "related_us"],
    "hk": ["ticker", "name", "sector", "stock_type", "is_hstech", "source"],
}


def clean_text(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"nan", "none"} else text


def normalize_ticker(ticker: str, market: str) -> str:
    value = clean_text(ticker).upper()
    if market == "cn":
        if "." in value:
            value = value.split(".", 1)[0]
        if value.startswith(("SH", "SZ", "BJ")):
            value = value[2:]
        value = value.zfill(6) if value.isdigit() else value
        if not re.fullmatch(r"\d{6}", value):
            raise ValueError("A-share ticker must be a six-digit code, for example 002432 or 002432.SZ")
        return value

    if "." in value:
        value = value.split(".", 1)[0]
    if value.startswith("HK"):
        value = value[2:]
    value = value.zfill(5) if value.isdigit() else value
    if not re.fullmatch(r"\d{5}", value):
        raise ValueError("Hong Kong ticker must be a five-digit code, for example 00020 or 0020.HK")
    return value


def load_pool(path: Path, columns: list[str]) -> pd.DataFrame:
    if path.exists() and path.stat().st_size > 0:
        df = pd.read_csv(path, dtype={"ticker": str}, encoding="utf-8-sig").fillna("")
    else:
        df = pd.DataFrame(columns=columns)
    for column in columns:
        if column not in df.columns:
            df[column] = ""
    return df[columns].copy()


def upsert_pool_entry(
    path: Path,
    market: str,
    ticker: str,
    name: str,
    sector: str,
    stock_type: str,
    related_us: str | None = None,
    is_hstech: str | None = None,
    source_url: str | None = None,
) -> tuple[pd.DataFrame, str]:
    columns = POOL_COLUMNS[market]
    normalized_ticker = normalize_ticker(ticker, market)
    df = load_pool(path, columns)
    df["ticker"] = df["ticker"].map(
        lambda value: normalize_ticker(value, market) if clean_text(value) else ""
    )
    df = df[df["ticker"] != ""]

    existing = df[df["ticker"] == normalized_ticker]
    is_new = existing.empty
    current = existing.iloc[-1].to_dict() if not is_new else {}
    row = {
        "ticker": normalized_ticker,
        "name": clean_text(name),
        "sector": clean_text(sector),
        "stock_type": clean_text(stock_type),
    }
    if market == "cn":
        row["related_us"] = clean_text(related_us) if related_us is not None else clean_text(current.get("related_us")) or "-"
    else:
        row["is_hstech"] = clean_text(is_hstech).upper() if is_hstech is not None else clean_text(current.get("is_hstech")) or "N"
        if row["is_hstech"] not in {"Y", "N"}:
            raise ValueError("--is-hstech must be Y or N")
        row["source"] = clean_text(source_url) if source_url is not None else clean_text(current.get("source"))

    df = df[df["ticker"] != normalized_ticker]
    df = pd.concat([df, pd.DataFrame([row], columns=columns)], ignore_index=True)
    df = df.sort_values("ticker", kind="stable").reset_index(drop=True)
    return df, "added" if is_new else "updated"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add or update one stock in the normalized CN/HK stock pool.")
    parser.add_argument("--market", choices=["cn", "hk"], required=True, help="Target pool market.")
    parser.add_argument("--ticker", required=True, help="CN: 002432 or 002432.SZ; HK: 00020 or 0020.HK.")
    parser.add_argument("--name", required=True, help="Stock display name.")
    parser.add_argument("--sector", required=True, help="Primary sector label.")
    parser.add_argument("--stock-type", required=True, help="Secondary stock type label.")
    parser.add_argument("--related-us", default=None, help="CN only: related US companies. Defaults to existing value or '-'.")
    parser.add_argument("--is-hstech", choices=["Y", "N"], default=None, help="HK only: whether it is a Hang Seng Tech constituent.")
    parser.add_argument("--source-url", default=None, help="HK only: reference URL shown in the pool.")
    parser.add_argument("--pool-file", default=None, help="Optional normalized pool CSV override.")
    parser.add_argument("--dry-run", action="store_true", help="Print the result without changing the CSV file.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pool_file = Path(args.pool_file) if args.pool_file else POOL_FILES[args.market]
    df, action = upsert_pool_entry(
        path=pool_file,
        market=args.market,
        ticker=args.ticker,
        name=args.name,
        sector=args.sector,
        stock_type=args.stock_type,
        related_us=args.related_us,
        is_hstech=args.is_hstech,
        source_url=args.source_url,
    )
    normalized_ticker = normalize_ticker(args.ticker, args.market)
    result = df[df["ticker"] == normalized_ticker]
    if args.dry_run:
        print(f"dry run: would {action} {normalized_ticker} in {pool_file}")
    else:
        pool_file.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(pool_file, index=False, encoding="utf-8-sig")
        print(f"{action}: {normalized_ticker} -> {pool_file}")
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
