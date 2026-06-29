from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
TICKER_FILE = ROOT_DIR / "config" / "nasdaq100_tickers.txt"
STOCK_PROFILES_FILE = ROOT_DIR / "config" / "stock_profiles.csv"
COMPANY_PROFILES_FILE = ROOT_DIR / "data" / "fundamental" / "company_profiles.csv"
RULES_FILE = ROOT_DIR / "config" / "us_stock_subtype_rules.csv"
OUTPUT_FILE = ROOT_DIR / "config" / "stock_subtypes.csv"


SECTOR_DEFAULTS = {
    "Information Technology": ("technology", "科技综合", "科技;软件开发;半导体"),
    "Communication Services": ("communication_services", "通信与互联网", "互联网服务;通信设备;文化传媒"),
    "Consumer Discretionary": ("consumer_discretionary", "可选消费", "消费电子;汽车整车;旅游;电商"),
    "Consumer Staples": ("consumer_staples", "必选消费", "食品饮料;零售"),
    "Health Care": ("healthcare", "医药医疗", "创新药;医疗器械;生物制品"),
    "Industrials": ("industrials", "工业", "工业设备;机器人;物流"),
    "Financials": ("financials", "金融", "银行;证券;金融科技"),
    "Utilities": ("utilities", "公用事业", "电力;公用事业"),
    "Energy": ("energy", "能源", "油气;能源"),
    "Materials": ("materials", "材料", "化工;材料"),
    "Real Estate": ("real_estate", "房地产", "房地产"),
}


def normalize_ticker(value: object) -> str:
    return str(value or "").strip().upper()


def load_tickers(path: Path = TICKER_FILE) -> list[str]:
    tickers: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        ticker = normalize_ticker(line)
        if not ticker or ticker.startswith("#") or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)
    return tickers


def load_table(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path).fillna("")


def build_stock_subtypes(
    *,
    ticker_file: Path = TICKER_FILE,
    stock_profiles_file: Path = STOCK_PROFILES_FILE,
    company_profiles_file: Path = COMPANY_PROFILES_FILE,
    rules_file: Path = RULES_FILE,
) -> pd.DataFrame:
    tickers = load_tickers(ticker_file)
    stock_profiles = load_table(stock_profiles_file)
    company_profiles = load_table(company_profiles_file)
    rules = load_table(rules_file)

    stock_profile_map = {
        normalize_ticker(row.ticker): row._asdict()
        for row in stock_profiles.itertuples(index=False)
        if normalize_ticker(getattr(row, "ticker", ""))
    }
    company_profile_map = {
        normalize_ticker(row.ticker): row._asdict()
        for row in company_profiles.itertuples(index=False)
        if normalize_ticker(getattr(row, "ticker", ""))
    }
    rule_map = {
        normalize_ticker(row.ticker): row._asdict()
        for row in rules.itertuples(index=False)
        if normalize_ticker(getattr(row, "ticker", ""))
    }

    rows: list[dict[str, str]] = []
    for ticker in tickers:
        stock_profile = stock_profile_map.get(ticker, {})
        company_profile = company_profile_map.get(ticker, {})
        rule = rule_map.get(ticker, {})
        sector = str(stock_profile.get("sector", "") or "").strip()
        stock_type = str(stock_profile.get("stock_type", "") or "").strip()
        name = str(company_profile.get("name", "") or "").strip()
        sic_description = str(company_profile.get("sic_description", "") or "").strip()

        default_subtype, default_cn, default_keywords = SECTOR_DEFAULTS.get(
            sector,
            ("other", stock_type or "其他", stock_type or "其他"),
        )
        rows.append(
            {
                "ticker": ticker,
                "name": name,
                "sector": sector,
                "stock_type": stock_type,
                "sub_type": str(rule.get("sub_type", "") or default_subtype).strip(),
                "sub_type_cn": str(rule.get("sub_type_cn", "") or default_cn).strip(),
                "a_share_keywords": str(rule.get("a_share_keywords", "") or default_keywords).strip(),
                "sic_description": sic_description,
                "source": "manual_rule" if ticker in rule_map else "sector_default",
            }
        )

    return pd.DataFrame(rows)


def save_subtypes(df: pd.DataFrame, output_file: Path = OUTPUT_FILE) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_file, index=False, encoding="utf-8-sig")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build fine-grained US stock subtype mapping for A-share peer matching."
    )
    parser.add_argument("--output", default=str(OUTPUT_FILE), help="Output CSV path.")
    parser.add_argument("--ticker-file", default=str(TICKER_FILE), help="Ticker universe file.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = build_stock_subtypes(ticker_file=Path(args.ticker_file))
    output_file = Path(args.output)
    save_subtypes(df, output_file)
    print(f"Saved {len(df)} rows: {output_file}")
    print(df[["ticker", "name", "stock_type", "sub_type_cn", "a_share_keywords", "source"]].head(30))


if __name__ == "__main__":
    main()
