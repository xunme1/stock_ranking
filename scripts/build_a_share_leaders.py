from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
A_SHARE_UNIVERSE_FILE = ROOT_DIR / "data" / "fundamental" / "a_share_universe.csv"
STOCK_SUBTYPES_FILE = ROOT_DIR / "config" / "stock_subtypes.csv"
OUTPUT_FILE = ROOT_DIR / "data" / "fundamental" / "a_share_subtype_leaders.csv"


def split_keywords(value: object) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    return [item.strip() for item in text.replace(",", ";").split(";") if item.strip()]


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(f"CSV not found: {path}")
    return pd.read_csv(path, dtype={"code": str}).fillna("")


def build_search_text(df: pd.DataFrame) -> pd.Series:
    columns = [column for column in ["name", "industry_boards", "concept_boards"] if column in df.columns]
    if not columns:
        return pd.Series([""] * len(df), index=df.index)
    return df[columns].astype(str).agg(";".join, axis=1)


def find_leaders_for_keywords(
    a_share_df: pd.DataFrame,
    *,
    keywords: list[str],
    top_n: int = 3,
) -> pd.DataFrame:
    if not keywords:
        return a_share_df.iloc[0:0].copy()

    search_text = build_search_text(a_share_df)
    mask = pd.Series(False, index=a_share_df.index)
    for keyword in keywords:
        mask = mask | search_text.str.contains(keyword, case=False, regex=False, na=False)

    candidates = a_share_df[mask].copy()
    if candidates.empty:
        return candidates

    candidates["market_cap_cny"] = pd.to_numeric(candidates.get("market_cap_cny"), errors="coerce")
    return candidates.sort_values("market_cap_cny", ascending=False, na_position="last").head(top_n)


def build_a_share_leaders(
    *,
    a_share_file: Path = A_SHARE_UNIVERSE_FILE,
    subtypes_file: Path = STOCK_SUBTYPES_FILE,
    top_n: int = 3,
) -> pd.DataFrame:
    a_share_df = load_csv(a_share_file)
    subtypes_df = load_csv(subtypes_file)

    rows: list[dict[str, object]] = []
    grouped_rows: list[dict[str, str]] = []
    for (sub_type, sub_type_cn), group in subtypes_df.groupby(["sub_type", "sub_type_cn"], dropna=False):
        keywords: list[str] = []
        seen: set[str] = set()
        for value in group["a_share_keywords"].tolist():
            for keyword in split_keywords(value):
                if keyword not in seen:
                    seen.add(keyword)
                    keywords.append(keyword)
        grouped_rows.append(
            {
                "sub_type": str(sub_type),
                "sub_type_cn": str(sub_type_cn),
                "a_share_keywords": ";".join(keywords),
            }
        )

    subtype_groups = pd.DataFrame(grouped_rows).sort_values(["sub_type_cn", "sub_type"])
    for subtype in subtype_groups.itertuples(index=False):
        keywords = split_keywords(getattr(subtype, "a_share_keywords", ""))
        leaders = find_leaders_for_keywords(a_share_df, keywords=keywords, top_n=top_n)
        for rank, leader in enumerate(leaders.itertuples(index=False), start=1):
            rows.append(
                {
                    "sub_type": getattr(subtype, "sub_type", ""),
                    "sub_type_cn": getattr(subtype, "sub_type_cn", ""),
                    "a_share_keywords": ";".join(keywords),
                    "rank": rank,
                    "code": getattr(leader, "code", ""),
                    "name": getattr(leader, "name", ""),
                    "market_cap_cny": getattr(leader, "market_cap_cny", ""),
                    "market_cap_100m_cny": getattr(leader, "market_cap_100m_cny", ""),
                    "latest_price": getattr(leader, "latest_price", ""),
                    "change_pct": getattr(leader, "change_pct", ""),
                    "industry_boards": getattr(leader, "industry_boards", ""),
                    "concept_boards": getattr(leader, "concept_boards", ""),
                }
            )

    return pd.DataFrame(rows)


def save_leaders(df: pd.DataFrame, output_file: Path = OUTPUT_FILE) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_file, index=False, encoding="utf-8-sig")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build top A-share leaders by US stock fine-grained subtype keywords."
    )
    parser.add_argument("--a-share-file", default=str(A_SHARE_UNIVERSE_FILE), help="A-share universe cache.")
    parser.add_argument("--subtypes-file", default=str(STOCK_SUBTYPES_FILE), help="US stock subtype mapping.")
    parser.add_argument("--output", default=str(OUTPUT_FILE), help="Output CSV path.")
    parser.add_argument("--top-n", type=int, default=3, help="Number of A-share leaders per subtype.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = build_a_share_leaders(
        a_share_file=Path(args.a_share_file),
        subtypes_file=Path(args.subtypes_file),
        top_n=args.top_n,
    )
    output_file = Path(args.output)
    save_leaders(df, output_file)
    print(f"Saved {len(df)} rows: {output_file}")
    if not df.empty:
        print(df[["sub_type_cn", "rank", "code", "name", "market_cap_100m_cny"]].head(30))


if __name__ == "__main__":
    main()
