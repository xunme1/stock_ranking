from __future__ import annotations

import argparse
import math
import os
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable, TypeVar

import pandas as pd
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_FILE = ROOT_DIR / "data" / "fundamental" / "a_share_universe.csv"
T = TypeVar("T")
EASTMONEY_SPOT_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_SPOT_FIELDS = (
    "f2,f3,f5,f6,f9,f12,f14,f20,f21,f23"
)
EASTMONEY_A_SHARE_FS = "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048"


def normalize_code(value: object) -> str:
    text = str(value or "").strip()
    return text.zfill(6) if text.isdigit() else text


def parse_number(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "nan", "None"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_akshare():
    try:
        import akshare as ak  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "AkShare is not installed. Run: .\\.venv\\Scripts\\pip.exe install akshare"
        ) from exc
    return ak


def load_tushare():
    try:
        import tushare as ts  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "Tushare is not installed. Run: .\\.venv\\Scripts\\pip.exe install tushare"
        ) from exc

    load_dotenv(ROOT_DIR / ".env")
    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if not token:
        raise SystemExit("Missing TUSHARE_TOKEN in .env or environment.")
    ts.set_token(token)
    return ts.pro_api()


def call_with_retries(
    func: Callable[[], T],
    *,
    label: str,
    retries: int = 3,
    wait_seconds: int = 10,
) -> T:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - external data source can fail transiently.
            last_exc = exc
            if attempt >= retries:
                break
            print(f"[warn] {label} failed on attempt {attempt}/{retries}: {exc}", flush=True)
            print(f"[warn] retrying in {wait_seconds} seconds...", flush=True)
            time.sleep(wait_seconds)
    assert last_exc is not None
    raise last_exc


def normalize_spot_columns(df: pd.DataFrame) -> pd.DataFrame:
    column_map = {
        "代码": "code",
        "名称": "name",
        "最新价": "latest_price",
        "涨跌幅": "change_pct",
        "成交量": "volume",
        "成交额": "turnover",
        "总市值": "market_cap_cny",
        "流通市值": "float_market_cap_cny",
        "市盈率-动态": "pe_dynamic",
        "市净率": "pb",
    }
    keep = [column for column in column_map if column in df.columns]
    result = df[keep].rename(columns=column_map).copy()
    result["code"] = result["code"].map(normalize_code)

    for column in [
        "latest_price",
        "change_pct",
        "volume",
        "turnover",
        "market_cap_cny",
        "float_market_cap_cny",
        "pe_dynamic",
        "pb",
    ]:
        if column in result.columns:
            result[column] = result[column].map(parse_number)

    result["market_cap_100m_cny"] = result["market_cap_cny"] / 100_000_000
    result["float_market_cap_100m_cny"] = result["float_market_cap_cny"] / 100_000_000
    return result


def normalize_tushare_columns(basic_df: pd.DataFrame, daily_df: pd.DataFrame) -> pd.DataFrame:
    basic = basic_df.copy()
    daily = daily_df.copy()
    if "ts_code" not in basic.columns or "ts_code" not in daily.columns:
        raise RuntimeError("Tushare response is missing ts_code.")

    df = basic.merge(daily, on="ts_code", how="left")
    result = pd.DataFrame(
        {
            "code": df.get("symbol", ""),
            "ts_code": df.get("ts_code", ""),
            "name": df.get("name", ""),
            "area": df.get("area", ""),
            "industry": df.get("industry", ""),
            "market": df.get("market", ""),
            "list_date": df.get("list_date", ""),
            "trade_date": df.get("trade_date", ""),
            "latest_price": df.get("close", ""),
            "change_pct": df.get("pct_chg", ""),
            "market_cap_100m_cny": df.get("total_mv", ""),
            "float_market_cap_100m_cny": df.get("circ_mv", ""),
            "pe_ttm": df.get("pe_ttm", ""),
            "pb": df.get("pb", ""),
            "turnover_rate": df.get("turnover_rate", ""),
        }
    )
    result["code"] = result["code"].map(normalize_code)
    for column in [
        "latest_price",
        "change_pct",
        "market_cap_100m_cny",
        "float_market_cap_100m_cny",
        "pe_ttm",
        "pb",
        "turnover_rate",
    ]:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["market_cap_cny"] = result["market_cap_100m_cny"] * 100_000_000
    result["float_market_cap_cny"] = result["float_market_cap_100m_cny"] * 100_000_000
    result["industry_boards"] = result["industry"].fillna("").astype(str)
    result["concept_boards"] = ""
    return result


def latest_tushare_trade_date(pro, *, retries: int, wait_seconds: int) -> str:
    today = datetime.now().strftime("%Y%m%d")
    calendar = call_with_retries(
        lambda: pro.trade_cal(
            exchange="SSE",
            start_date="20200101",
            end_date=today,
            is_open="1",
            fields="cal_date,is_open",
        ),
        label="Tushare trade calendar",
        retries=retries,
        wait_seconds=wait_seconds,
    )
    if calendar.empty:
        raise RuntimeError("Tushare trade calendar returned empty data.")
    dates = sorted(calendar["cal_date"].astype(str).tolist())
    if not dates:
        raise RuntimeError("Tushare trade calendar returned no open dates.")
    if dates[-1] == today and len(dates) >= 2:
        return dates[-2]
    return dates[-1]


def fetch_tushare_universe(
    *,
    trade_date: str | None = None,
    retries: int = 3,
    wait_seconds: int = 10,
) -> pd.DataFrame:
    pro = load_tushare()
    target_date = trade_date or latest_tushare_trade_date(
        pro,
        retries=retries,
        wait_seconds=wait_seconds,
    )
    print(f"Fetching Tushare stock_basic and daily_basic for {target_date}...", flush=True)
    basic_df = call_with_retries(
        lambda: pro.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,area,industry,market,list_date",
        ),
        label="Tushare stock_basic",
        retries=retries,
        wait_seconds=wait_seconds,
    )
    daily_df = call_with_retries(
        lambda: pro.daily_basic(
            trade_date=target_date,
            fields=(
                "ts_code,trade_date,close,pct_chg,turnover_rate,"
                "pe_ttm,pb,total_mv,circ_mv"
            ),
        ),
        label="Tushare daily_basic",
        retries=retries,
        wait_seconds=wait_seconds,
    )
    if daily_df.empty:
        raise RuntimeError(
            f"Tushare daily_basic returned empty data for {target_date}. "
            "Try an earlier date with --trade-date YYYYMMDD."
        )
    return normalize_tushare_columns(basic_df, daily_df)


def fetch_tushare_basic(
    *,
    retries: int = 3,
    wait_seconds: int = 10,
) -> pd.DataFrame:
    pro = load_tushare()
    print("Fetching Tushare stock_basic for A-share industry types...", flush=True)
    return call_with_retries(
        lambda: pro.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,area,industry,market,list_date",
        ),
        label="Tushare stock_basic",
        retries=retries,
        wait_seconds=wait_seconds,
    )


def merge_tushare_basic(spot_df: pd.DataFrame, basic_df: pd.DataFrame) -> pd.DataFrame:
    basic = basic_df.copy()
    basic["code"] = basic["symbol"].map(normalize_code)
    keep_columns = ["code", "ts_code", "area", "industry", "market", "list_date"]
    merged = spot_df.merge(basic[keep_columns], on="code", how="left")
    merged["industry_boards"] = merged["industry"].fillna("").astype(str)
    if "concept_boards" not in merged.columns:
        merged["concept_boards"] = ""
    return merged


def merge_existing_industry_cache(
    spot_df: pd.DataFrame,
    cache_file: Path = OUTPUT_FILE,
) -> pd.DataFrame:
    if not cache_file.exists() or cache_file.stat().st_size == 0:
        spot_df["ts_code"] = ""
        spot_df["area"] = ""
        spot_df["industry"] = ""
        spot_df["market"] = ""
        spot_df["list_date"] = ""
        spot_df["industry_boards"] = ""
        spot_df["concept_boards"] = ""
        return spot_df

    cached = pd.read_csv(cache_file, dtype={"code": str}).fillna("")
    cached["code"] = cached["code"].map(normalize_code)
    keep_columns = [
        column
        for column in [
            "code",
            "ts_code",
            "area",
            "industry",
            "market",
            "list_date",
            "industry_boards",
            "concept_boards",
        ]
        if column in cached.columns
    ]
    merged = spot_df.merge(cached[keep_columns], on="code", how="left")
    for column in ["ts_code", "area", "industry", "market", "list_date", "industry_boards", "concept_boards"]:
        if column not in merged.columns:
            merged[column] = ""
        merged[column] = merged[column].fillna("").astype(str)
    return merged


def fetch_eastmoney_spot_direct(
    *,
    retries: int = 3,
    wait_seconds: int = 10,
    page_size: int = 100,
    max_pages: int | None = None,
) -> pd.DataFrame:
    try:
        from curl_cffi import requests as curl_requests  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "curl_cffi is not installed. Run: .\\.venv\\Scripts\\pip.exe install curl_cffi"
        ) from exc

    def request_page(page: int) -> dict:
        params = {
            "pn": page,
            "pz": page_size,
            "po": 1,
            "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2,
            "invt": 2,
            "fid": "f12",
            "fs": EASTMONEY_A_SHARE_FS,
            "fields": EASTMONEY_SPOT_FIELDS,
        }
        response = curl_requests.get(
            EASTMONEY_SPOT_URL,
            params=params,
            timeout=30,
            impersonate="chrome",
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("data"):
            raise RuntimeError(f"Eastmoney returned empty data for page {page}")
        return payload

    first_payload = call_with_retries(
        lambda: request_page(1),
        label="Eastmoney spot page 1",
        retries=retries,
        wait_seconds=wait_seconds,
    )
    data = first_payload["data"]
    total = int(data.get("total") or 0)
    pages = max(1, math.ceil(total / page_size))
    if max_pages:
        pages = min(pages, max_pages)
    rows = list(data.get("diff") or [])
    print(f"Eastmoney spot pages={pages}, total={total}", flush=True)

    for page in range(2, pages + 1):
        payload = call_with_retries(
            lambda page=page: request_page(page),
            label=f"Eastmoney spot page {page}",
            retries=retries,
            wait_seconds=wait_seconds,
        )
        rows.extend(payload["data"].get("diff") or [])
        print(f"[{page}/{pages}] spot rows={len(rows)}", flush=True)

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame()
    return pd.DataFrame(
        {
            "代码": df.get("f12", ""),
            "名称": df.get("f14", ""),
            "最新价": df.get("f2", ""),
            "涨跌幅": df.get("f3", ""),
            "成交量": df.get("f5", ""),
            "成交额": df.get("f6", ""),
            "总市值": df.get("f20", ""),
            "流通市值": df.get("f21", ""),
            "市盈率-动态": df.get("f9", ""),
            "市净率": df.get("f23", ""),
        }
    )


def fetch_board_members(
    name_func,
    cons_func,
    *,
    label_column: str,
    max_boards: int | None = None,
    retries: int = 3,
    wait_seconds: int = 10,
) -> dict[str, set[str]]:
    boards = call_with_retries(
        name_func,
        label=f"{label_column} board list",
        retries=retries,
        wait_seconds=wait_seconds,
    )
    if "板块名称" not in boards.columns:
        return {}

    names = [str(name).strip() for name in boards["板块名称"].dropna().tolist()]
    if max_boards:
        names = names[:max_boards]

    memberships: dict[str, set[str]] = defaultdict(set)
    for index, board_name in enumerate(names, start=1):
        if not board_name:
            continue
        try:
            members = call_with_retries(
                lambda board_name=board_name: cons_func(symbol=board_name),
                label=f"{label_column} {board_name}",
                retries=retries,
                wait_seconds=wait_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - external data source can fail per board.
            print(f"[warn] failed to fetch {label_column} {board_name}: {exc}", flush=True)
            continue

        code_column = "代码" if "代码" in members.columns else None
        if not code_column:
            continue
        for code in members[code_column].dropna().tolist():
            memberships[normalize_code(code)].add(board_name)
        print(f"[{index}/{len(names)}] {label_column}: {board_name} members={len(members)}", flush=True)

    return memberships


def join_memberships(df: pd.DataFrame, memberships: dict[str, set[str]], column: str) -> pd.DataFrame:
    df[column] = df["code"].map(lambda code: ";".join(sorted(memberships.get(code, set()))))
    return df


def save_universe(df: pd.DataFrame, output_file: Path = OUTPUT_FILE) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_file, index=False, encoding="utf-8-sig")


def build_a_share_universe(
    *,
    source: str = "eastmoney",
    include_concepts: bool = True,
    include_boards: bool = True,
    max_industries: int | None = None,
    max_concepts: int | None = None,
    retries: int = 3,
    retry_wait_seconds: int = 10,
    spot_source: str = "direct",
    spot_pages: int | None = None,
    trade_date: str | None = None,
) -> pd.DataFrame:
    if source == "tushare":
        df = fetch_tushare_universe(
            trade_date=trade_date,
            retries=retries,
            wait_seconds=retry_wait_seconds,
        )
        df["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return df.sort_values("market_cap_cny", ascending=False, na_position="last")

    print("Fetching A-share spot market data...", flush=True)
    if spot_source == "akshare":
        ak = load_akshare()
        raw_spot_df = call_with_retries(
            ak.stock_zh_a_spot_em,
            label="A-share spot market",
            retries=retries,
            wait_seconds=retry_wait_seconds,
        )
    else:
        raw_spot_df = fetch_eastmoney_spot_direct(
            retries=retries,
            wait_seconds=retry_wait_seconds,
            max_pages=spot_pages,
        )
    spot_df = normalize_spot_columns(raw_spot_df)

    if source == "hybrid":
        try:
            basic_df = fetch_tushare_basic(
                retries=retries,
                wait_seconds=retry_wait_seconds,
            )
            spot_df = merge_tushare_basic(spot_df, basic_df)
        except Exception as exc:  # noqa: BLE001 - keep the market-cap cache even if Tushare is rate limited.
            print(f"[warn] Tushare industry merge failed: {exc}", flush=True)
            print("[warn] Preserving industry fields from the previous A-share cache when available.", flush=True)
            spot_df = merge_existing_industry_cache(spot_df)
        spot_df["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return spot_df.sort_values("market_cap_cny", ascending=False, na_position="last")

    if not include_boards:
        spot_df["industry_boards"] = ""
        spot_df["concept_boards"] = ""
        spot_df["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return spot_df.sort_values("market_cap_cny", ascending=False, na_position="last")

    ak = load_akshare()
    print("Fetching Eastmoney industry board memberships...", flush=True)
    industry_memberships = fetch_board_members(
        ak.stock_board_industry_name_em,
        ak.stock_board_industry_cons_em,
        label_column="industry",
        max_boards=max_industries,
        retries=retries,
        wait_seconds=retry_wait_seconds,
    )
    spot_df = join_memberships(spot_df, industry_memberships, "industry_boards")

    if include_concepts:
        print("Fetching Eastmoney concept board memberships...", flush=True)
        concept_memberships = fetch_board_members(
            ak.stock_board_concept_name_em,
            ak.stock_board_concept_cons_em,
            label_column="concept",
            max_boards=max_concepts,
            retries=retries,
            wait_seconds=retry_wait_seconds,
        )
        spot_df = join_memberships(spot_df, concept_memberships, "concept_boards")
    else:
        spot_df["concept_boards"] = ""

    spot_df["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return spot_df.sort_values("market_cap_cny", ascending=False, na_position="last")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download A-share spot market cap and board memberships into one cache table."
    )
    parser.add_argument("--output", default=str(OUTPUT_FILE), help="Output CSV path.")
    parser.add_argument(
        "--source",
        choices=["eastmoney", "tushare", "hybrid"],
        default="eastmoney",
        help=(
            "A-share data source. Use hybrid for Tushare industry types plus "
            "Eastmoney/AkShare-style market cap."
        ),
    )
    parser.add_argument(
        "--trade-date",
        default=None,
        help="Tushare trade date in YYYYMMDD. Defaults to latest open trading day.",
    )
    parser.add_argument(
        "--no-concepts",
        action="store_true",
        help="Only fetch industry boards. This is faster but less useful for fine-grained mapping.",
    )
    parser.add_argument(
        "--spot-only",
        action="store_true",
        help="Only fetch A-share spot market cap table. Skip industry/concept board memberships.",
    )
    parser.add_argument("--max-industries", type=int, default=None, help="Debug limit for industry boards.")
    parser.add_argument("--max-concepts", type=int, default=None, help="Debug limit for concept boards.")
    parser.add_argument("--retries", type=int, default=3, help="Retries for each AkShare call.")
    parser.add_argument("--retry-wait-seconds", type=int, default=10, help="Seconds to wait before retrying.")
    parser.add_argument(
        "--spot-pages",
        type=int,
        default=None,
        help="Debug limit for direct Eastmoney spot pages. Each page has about 100 stocks.",
    )
    parser.add_argument(
        "--spot-source",
        choices=["direct", "akshare"],
        default="direct",
        help="Use direct Eastmoney pagination or AkShare stock_zh_a_spot_em for the spot table.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = build_a_share_universe(
        source=args.source,
        include_concepts=not args.no_concepts,
        include_boards=not args.spot_only,
        max_industries=args.max_industries,
        max_concepts=args.max_concepts,
        retries=args.retries,
        retry_wait_seconds=args.retry_wait_seconds,
        spot_source=args.spot_source,
        spot_pages=args.spot_pages,
        trade_date=args.trade_date,
    )
    output_file = Path(args.output)
    save_universe(df, output_file)
    print(f"Saved {len(df)} rows: {output_file}")
    print(df[["code", "name", "market_cap_100m_cny", "industry_boards", "concept_boards"]].head(20))


if __name__ == "__main__":
    main()
