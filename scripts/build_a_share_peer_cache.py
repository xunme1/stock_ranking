from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MAPPING_FILE = ROOT_DIR / "config" / "us_a_share_peer_mapping.csv"
STOCK_PROFILES_FILE = ROOT_DIR / "config" / "stock_profiles.csv"
COMPANY_PROFILES_FILE = ROOT_DIR / "data" / "fundamental" / "company_profiles.csv"
A_SHARE_UNIVERSE_FILE = ROOT_DIR / "data" / "fundamental" / "a_share_universe.csv"
STOCK_SUBTYPES_OUTPUT = ROOT_DIR / "config" / "stock_subtypes.csv"
A_SHARE_LEADERS_OUTPUT = ROOT_DIR / "data" / "fundamental" / "a_share_subtype_leaders.csv"

STOCK_SUBTYPE_COLUMNS = [
    "ticker",
    "name",
    "sector",
    "stock_type",
    "sub_type",
    "sub_type_cn",
    "a_share_keywords",
    "sic_description",
    "source",
]

A_SHARE_LEADER_COLUMNS = [
    "sub_type",
    "sub_type_cn",
    "a_share_keywords",
    "rank",
    "code",
    "name",
    "market_cap_cny",
    "market_cap_100m_cny",
    "latest_price",
    "change_pct",
    "industry_boards",
    "concept_boards",
    "business_note",
    "mapping_type",
]


def normalize_ticker(value: object) -> str:
    return str(value or "").strip().upper()


def normalize_a_share_code(value: object) -> str:
    text = str(value or "").strip().upper()
    if not text or text in {"NAN", "NONE"}:
        return ""
    code = text.split(".", 1)[0]
    return code.zfill(6) if code.isdigit() else code


def clean_text(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"nan", "none"} else text


def parse_float(value: object) -> float | None:
    text = clean_text(value).replace(",", "")
    if not text or text in {"-", "--"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number):
        return None
    return number


def display_number(value: object) -> str:
    number = parse_float(value)
    if number is None:
        return ""
    return f"{number:.4f}".rstrip("0").rstrip(".")


def read_mapping(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Mapping CSV not found: {path}")
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
    required = {
        "美股代码",
        "美股公司名称",
        "主营细分赛道",
        "映射类型",
        "A股对应赛道",
        "A股Top1代码",
        "A股Top1名称",
        "A股Top2代码",
        "A股Top2名称",
        "A股Top3代码",
        "A股Top3名称",
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Mapping CSV is missing columns: {', '.join(missing)}")
    df["美股代码"] = df["美股代码"].map(normalize_ticker)
    return df[df["美股代码"] != ""].copy()


def read_optional_csv(path: Path, **kwargs: Any) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, **kwargs).fillna("")


def load_stock_profile_maps() -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    profile_df = read_optional_csv(STOCK_PROFILES_FILE, dtype=str)
    profiles: dict[str, dict[str, str]] = {}
    if not profile_df.empty and {"ticker", "sector", "stock_type"}.issubset(profile_df.columns):
        for row in profile_df.itertuples(index=False):
            ticker = normalize_ticker(getattr(row, "ticker", ""))
            if ticker:
                profiles[ticker] = {
                    "sector": clean_text(getattr(row, "sector", "")),
                    "stock_type": clean_text(getattr(row, "stock_type", "")),
                }

    company_df = read_optional_csv(COMPANY_PROFILES_FILE, dtype=str)
    sic_by_ticker: dict[str, str] = {}
    if not company_df.empty and {"ticker", "sic_description"}.issubset(company_df.columns):
        for row in company_df.itertuples(index=False):
            ticker = normalize_ticker(getattr(row, "ticker", ""))
            if ticker:
                sic_by_ticker[ticker] = clean_text(getattr(row, "sic_description", ""))

    return profiles, sic_by_ticker


def load_a_share_universe(path: Path) -> dict[str, dict[str, object]]:
    df = read_optional_csv(path, dtype={"code": str})
    if df.empty:
        return {}
    df["code"] = df["code"].map(normalize_a_share_code)
    return {str(row.code): row._asdict() for row in df.itertuples(index=False) if str(row.code)}


def subtype_for_ticker(ticker: str) -> str:
    return f"mapped_{ticker.lower().replace('.', '_')}"


def build_keyword_text(row: pd.Series, codes: list[str], names: list[str]) -> str:
    values = [
        clean_text(row.get("A股对应赛道", "")),
        clean_text(row.get("主营细分赛道", "")),
        *codes,
        *names,
    ]
    seen: set[str] = set()
    keywords: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            keywords.append(value)
    return ";".join(keywords)


def build_stock_subtypes(mapping_df: pd.DataFrame) -> pd.DataFrame:
    profiles, sic_by_ticker = load_stock_profile_maps()
    rows: list[dict[str, object]] = []
    seen: set[str] = set()

    for _, row in mapping_df.iterrows():
        ticker = normalize_ticker(row["美股代码"])
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)

        codes = [
            normalize_a_share_code(row.get(f"A股Top{idx}代码", ""))
            for idx in range(1, 4)
        ]
        names = [clean_text(row.get(f"A股Top{idx}名称", "")) for idx in range(1, 4)]
        profile = profiles.get(ticker, {})
        fine_type = clean_text(row.get("主营细分赛道", "")) or clean_text(row.get("A股对应赛道", ""))

        rows.append(
            {
                "ticker": ticker,
                "name": clean_text(row.get("美股公司名称", "")),
                "sector": profile.get("sector", ""),
                "stock_type": profile.get("stock_type", ""),
                "sub_type": subtype_for_ticker(ticker),
                "sub_type_cn": fine_type,
                "a_share_keywords": build_keyword_text(row, codes, names),
                "sic_description": sic_by_ticker.get(ticker, ""),
                "source": "csv_mapping",
            }
        )

    return pd.DataFrame(rows, columns=STOCK_SUBTYPE_COLUMNS).sort_values("ticker")


def market_cap_sort_key(row: dict[str, object]) -> float:
    value = parse_float(row.get("market_cap_cny"))
    return value if value is not None else -1.0


def build_a_share_leaders(mapping_df: pd.DataFrame, universe: dict[str, dict[str, object]]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    for _, row in mapping_df.iterrows():
        ticker = normalize_ticker(row["美股代码"])
        if not ticker:
            continue

        sub_type = subtype_for_ticker(ticker)
        sub_type_cn = clean_text(row.get("主营细分赛道", "")) or clean_text(row.get("A股对应赛道", ""))
        mapping_type = clean_text(row.get("映射类型", ""))

        candidates: list[dict[str, object]] = []
        for idx in range(1, 4):
            code = normalize_a_share_code(row.get(f"A股Top{idx}代码", ""))
            mapped_name = clean_text(row.get(f"A股Top{idx}名称", ""))
            if not code and not mapped_name:
                continue

            source = universe.get(code, {})
            estimated_100m = parse_float(row.get(f"Top{idx}总市值估算(亿元)", ""))
            fallback_market_cap = estimated_100m * 100_000_000 if estimated_100m is not None else None
            market_cap_cny = source.get("market_cap_cny", fallback_market_cap)
            market_cap_100m = source.get("market_cap_100m_cny", estimated_100m)

            candidates.append(
                {
                    "sub_type": sub_type,
                    "sub_type_cn": sub_type_cn,
                    "a_share_keywords": build_keyword_text(
                        row,
                        [normalize_a_share_code(row.get(f"A股Top{i}代码", "")) for i in range(1, 4)],
                        [clean_text(row.get(f"A股Top{i}名称", "")) for i in range(1, 4)],
                    ),
                    "rank": idx,
                    "code": code,
                    "name": clean_text(source.get("name", "")) or mapped_name,
                    "market_cap_cny": display_number(market_cap_cny),
                    "market_cap_100m_cny": display_number(market_cap_100m),
                    "latest_price": display_number(source.get("latest_price", "")),
                    "change_pct": display_number(source.get("change_pct", "")),
                    "industry_boards": clean_text(source.get("industry_boards", "")),
                    "concept_boards": clean_text(source.get("concept_boards", "")),
                    "business_note": clean_text(row.get(f"Top{idx}业务说明", "")),
                    "mapping_type": mapping_type,
                }
            )

        candidates.sort(key=market_cap_sort_key, reverse=True)
        for rank, item in enumerate(candidates[:3], start=1):
            item["rank"] = rank
            rows.append(item)

    return pd.DataFrame(rows, columns=A_SHARE_LEADER_COLUMNS).sort_values(["sub_type", "rank"])


def save_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build detail-page US stock subtype and mapped A-share leader caches from a curated CSV."
    )
    parser.add_argument("--mapping-file", default=str(DEFAULT_MAPPING_FILE), help="Curated US/A-share mapping CSV.")
    parser.add_argument("--a-share-file", default=str(A_SHARE_UNIVERSE_FILE), help="A-share universe cache.")
    parser.add_argument("--stock-subtypes-output", default=str(STOCK_SUBTYPES_OUTPUT), help="Output stock subtype CSV.")
    parser.add_argument("--leaders-output", default=str(A_SHARE_LEADERS_OUTPUT), help="Output A-share leaders CSV.")
    args = parser.parse_args()

    mapping_df = read_mapping(Path(args.mapping_file))
    universe = load_a_share_universe(Path(args.a_share_file))
    subtypes_df = build_stock_subtypes(mapping_df)
    leaders_df = build_a_share_leaders(mapping_df, universe)

    save_csv(subtypes_df, Path(args.stock_subtypes_output))
    save_csv(leaders_df, Path(args.leaders_output))

    print(f"Built {len(subtypes_df)} stock subtype rows -> {args.stock_subtypes_output}")
    print(f"Built {len(leaders_df)} mapped A-share leader rows -> {args.leaders_output}")
    if not universe:
        print("WARNING: A-share universe cache is empty, using CSV market-cap estimates only.")


if __name__ == "__main__":
    main()
