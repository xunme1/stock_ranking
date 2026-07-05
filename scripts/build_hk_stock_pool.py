from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT_DIR / "config" / "hk_stock_pool_source.csv"
DEFAULT_OUTPUT = ROOT_DIR / "config" / "hk_stock_pool.csv"

OUTPUT_COLUMNS = ["ticker", "name", "sector", "stock_type", "is_hstech", "source"]


def clean_text(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"nan", "none"} else text


def normalize_hk_code(value: object) -> str:
    text = clean_text(value).upper()
    if "." in text:
        text = text.split(".", 1)[0]
    if text.startswith("HK"):
        text = text[2:]
    return text.zfill(5) if text.isdigit() else text


def read_source(path: Path) -> pd.DataFrame:
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "gb18030", "gbk"):
        try:
            df = pd.read_csv(path, sep=";", dtype=str, encoding=encoding).fillna("")
            break
        except UnicodeDecodeError as exc:
            last_error = exc
    else:
        assert last_error is not None
        raise last_error

    required = {"股票代码", "公司名称", "一级行业标签"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Missing columns: {', '.join(missing)}")
    return df


def build_pool(source_file: Path = DEFAULT_SOURCE) -> pd.DataFrame:
    source = read_source(source_file)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in source.itertuples(index=False):
        ticker = normalize_hk_code(getattr(row, "股票代码", ""))
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        sector = clean_text(getattr(row, "一级行业标签", ""))
        stock_type = clean_text(getattr(row, "二级行业标签", ""))
        rows.append(
            {
                "ticker": ticker,
                "name": clean_text(getattr(row, "公司名称", "")),
                "sector": sector or "未分类",
                "stock_type": stock_type or sector or "未分类",
                "is_hstech": "Y" if clean_text(getattr(row, "恒生科技成分股", "")) == "是" else "N",
                "source": clean_text(getattr(row, "参考来源", "")),
            }
        )
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS).sort_values("ticker")


def save_pool(df: pd.DataFrame, output_file: Path = DEFAULT_OUTPUT) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_file, index=False, encoding="utf-8-sig")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build normalized Hong Kong stock pool from the curated CSV.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="Semicolon separated source CSV.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output normalized stock pool CSV.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = build_pool(Path(args.source))
    save_pool(df, Path(args.output))
    print(f"Built {len(df)} Hong Kong tickers -> {args.output}")
    print(df.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
