from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from app.core.config import CN_DEFAULT_BENCHMARK, DEFAULT_BENCHMARK, HK_DEFAULT_BENCHMARK, RANKING_CACHE_DIR
from app.services.data_loader import (
    load_daily_data,
    load_earnings_calendar,
    load_optionable_status,
    load_stock_profiles_for_market,
    load_ticker_file,
    load_ticker_file_for_market,
    normalize_market,
    normalize_ticker,
    normalize_ticker_for_market,
)


ANNOUNCED_2026_06_22_ADDS = ["ALAB", "CRWV", "NBIS", "RKLB", "TER"]
ANNOUNCED_2026_06_22_REMOVES = ["CHTR", "CTSH", "INSM", "VRSK", "ZS"]

RANKING_CACHE_COLUMNS = [
    "as_of_date",
    "window",
    "benchmark",
    "rank",
    "ticker",
    "name",
    "type",
    "has_options",
    "sector",
    "stock_type",
    "date",
    "close",
    "latest_ma",
    "ma_center",
    "atr",
    "atr_score",
    "price_vs_center_pct",
    "price_change_3d_pct",
    "excess_atr_vs_benchmark",
]


@dataclass
class RankingConfig:
    window: int = 10
    benchmark: str | None = DEFAULT_BENCHMARK
    market: str = "us"
    apply_announced_rebalance: bool = False
    as_of_date: date | None = None


def apply_rebalance(tickers: list[str]) -> list[str]:
    remove_set = set(ANNOUNCED_2026_06_22_REMOVES)
    result = [ticker for ticker in tickers if ticker not in remove_set]
    for ticker in ANNOUNCED_2026_06_22_ADDS:
        if ticker not in result:
            result.append(ticker)
    return result


def default_benchmark_for_market(market: str) -> str:
    if market == "cn":
        return CN_DEFAULT_BENCHMARK
    if market == "hk":
        return HK_DEFAULT_BENCHMARK
    return DEFAULT_BENCHMARK


def true_range(df: pd.DataFrame) -> pd.Series:
    previous_close = df["close"].shift(1)
    return pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - previous_close).abs(),
            (df["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def clean_number(value: object) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def trim_to_as_of_date(df: pd.DataFrame, as_of_date: date | None) -> pd.DataFrame:
    if as_of_date is None:
        return df
    return df[df["date"].dt.date <= as_of_date]


def latest_available_date(ticker: str, market: str = "us") -> date:
    df = load_daily_data(ticker, market)
    if df.empty:
        raise ValueError(f"No daily data for {ticker}")
    return df.iloc[-1]["date"].date()


def available_dates(ticker: str, limit: int = 260, market: str = "us") -> list[str]:
    df = load_daily_data(ticker, market).tail(limit)
    return [row.date.date().isoformat() for row in df.itertuples(index=False)]


def atr_window_for_ranking(window: int) -> int:
    return 20 if window == 10 else window


def ranking_cache_path(window: int, market: str = "us") -> Path:
    suffix = "" if normalize_market(market) == "us" else f"_{normalize_market(market)}"
    return RANKING_CACHE_DIR / f"ranking_window_{window}{suffix}.csv"


def load_ranking_cache(window: int, market: str = "us") -> pd.DataFrame:
    path = ranking_cache_path(window, market)
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=RANKING_CACHE_COLUMNS)
    df = pd.read_csv(path, dtype={"ticker": str, "benchmark": str}, encoding="utf-8-sig")
    for column in RANKING_CACHE_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    numeric_columns = [
        "window",
        "rank",
        "close",
        "latest_ma",
        "ma_center",
        "atr",
        "atr_score",
        "price_vs_center_pct",
        "price_change_3d_pct",
        "excess_atr_vs_benchmark",
    ]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df[RANKING_CACHE_COLUMNS]


def save_ranking_cache(window: int, new_rows: pd.DataFrame, market: str = "us") -> None:
    RANKING_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = ranking_cache_path(window, market)
    old_rows = load_ranking_cache(window, market)
    combined = pd.concat([old_rows, new_rows], ignore_index=True)
    combined = combined.dropna(subset=["as_of_date", "ticker"])
    combined["ticker"] = combined["ticker"].astype(str).map(lambda item: normalize_ticker_for_market(item, market))
    combined["benchmark"] = combined["benchmark"].astype(str).map(lambda item: normalize_ticker_for_market(item, market))
    combined["as_of_date"] = combined["as_of_date"].astype(str)
    combined = combined.drop_duplicates(subset=["as_of_date", "window", "benchmark", "ticker"], keep="last")
    combined = combined.sort_values(["as_of_date", "rank", "ticker"])
    combined[RANKING_CACHE_COLUMNS].to_csv(path, index=False, encoding="utf-8-sig")


def cached_ranking_frame(window: int, benchmark: str, as_of_date: date, market: str = "us") -> pd.DataFrame | None:
    df = load_ranking_cache(window, market)
    if df.empty:
        return None
    target_date = as_of_date.isoformat()
    benchmark = normalize_ticker_for_market(benchmark, market)
    matched = df[(df["as_of_date"].astype(str) == target_date) & (df["benchmark"].astype(str) == benchmark)]
    if matched.empty:
        return None
    result = matched.drop(columns=["as_of_date", "window", "benchmark"]).copy()
    result["rank"] = result["rank"].astype(int)
    return result.sort_values("rank").reset_index(drop=True)


def _alert_item(
    ticker: str,
    name: str,
    latest_rank: int,
    previous_rank: int | None,
    recent_ranks: list[int],
    daily_change_pct: float | None = None,
) -> dict[str, object]:
    rank_change = previous_rank - latest_rank if previous_rank is not None else None
    return {
        "ticker": ticker,
        "name": name,
        "rank": latest_rank,
        "previous_rank": previous_rank,
        "rank_change": rank_change,
        "daily_change_pct": daily_change_pct,
        "avg_rank_5": sum(recent_ranks) / len(recent_ranks) if recent_ranks else None,
        "best_rank_5": min(recent_ranks) if recent_ranks else None,
        "worst_rank_5": max(recent_ranks) if recent_ranks else None,
    }


def build_ranking_alerts(
    window: int,
    benchmark: str | None = DEFAULT_BENCHMARK,
    market: str = "us",
    as_of_date: date | None = None,
    days: int = 5,
    top_n: int = 20,
    move_threshold: int = 10,
) -> dict[str, object]:
    market = normalize_market(market)
    benchmark = normalize_ticker_for_market(benchmark or default_benchmark_for_market(market), market)
    cache = load_ranking_cache(window, market)
    if cache.empty:
        raise ValueError(f"No ranking cache found for window {window}")

    cache = cache[cache["benchmark"].astype(str) == benchmark].copy()
    if cache.empty:
        raise ValueError(f"No ranking cache found for benchmark {benchmark}")

    dates = sorted(str(item) for item in cache["as_of_date"].dropna().unique())
    if as_of_date is not None:
        dates = [item for item in dates if item <= as_of_date.isoformat()]
    recent_dates = dates[-days:]
    if len(recent_dates) < 2:
        raise ValueError("At least two cached dates are required for ranking alerts")

    latest_date = recent_dates[-1]
    previous_date = recent_dates[-2]
    recent = cache[cache["as_of_date"].isin(recent_dates)].copy()
    latest = recent[recent["as_of_date"] == latest_date].copy()
    previous = recent[recent["as_of_date"] == previous_date].copy()
    latest = latest[latest["ticker"] != benchmark]
    previous = previous[previous["ticker"] != benchmark]

    rank_lists = {
        str(ticker): [int(rank) for rank in group.sort_values("as_of_date")["rank"].tolist()]
        for ticker, group in recent[recent["ticker"] != benchmark].groupby("ticker")
    }
    previous_rank = {str(row.ticker): int(row.rank) for row in previous.itertuples(index=False)}
    latest_rank = {str(row.ticker): int(row.rank) for row in latest.itertuples(index=False)}
    previous_close = {str(row.ticker): float(row.close) for row in previous.itertuples(index=False)}
    latest_close = {str(row.ticker): float(row.close) for row in latest.itertuples(index=False)}
    latest_name = {
        str(row.ticker): str(getattr(row, "name", "") or "")
        for row in latest.itertuples(index=False)
    }
    daily_change_pct = {
        ticker: (latest_close[ticker] / previous_close[ticker] - 1) * 100
        for ticker in latest_close
        if ticker in previous_close and previous_close[ticker]
    }

    stable_top20 = [
        _alert_item(ticker, latest_name.get(ticker, ""), latest_rank[ticker], previous_rank.get(ticker), ranks, daily_change_pct.get(ticker))
        for ticker, ranks in rank_lists.items()
        if len(ranks) == len(recent_dates) and max(ranks) <= top_n and ticker in latest_rank
    ]
    stable_top20.sort(key=lambda item: (float(item["avg_rank_5"] or 999), int(item["rank"])))

    movers = [
        _alert_item(ticker, latest_name.get(ticker, ""), rank, previous_rank.get(ticker), rank_lists.get(ticker, []), daily_change_pct.get(ticker))
        for ticker, rank in latest_rank.items()
        if ticker in previous_rank and abs(previous_rank[ticker] - rank) > move_threshold
    ]
    upward = sorted(
        [item for item in movers if (item["rank_change"] or 0) > 0],
        key=lambda item: (
            -abs(int(item["rank_change"] or 0)),
            -(float(item["daily_change_pct"]) if item["daily_change_pct"] is not None else float("-inf")),
            int(item["rank"]),
        ),
    )
    downward = sorted(
        [item for item in movers if (item["rank_change"] or 0) < 0],
        key=lambda item: (
            -abs(int(item["rank_change"] or 0)),
            -(float(item["daily_change_pct"]) if item["daily_change_pct"] is not None else float("-inf")),
            int(item["rank"]),
        ),
    )

    entered_top20 = [
        _alert_item(ticker, latest_name.get(ticker, ""), rank, previous_rank.get(ticker), rank_lists.get(ticker, []), daily_change_pct.get(ticker))
        for ticker, rank in latest_rank.items()
        if rank <= top_n and previous_rank.get(ticker, top_n + 1) > top_n
    ]
    entered_top20.sort(key=lambda item: int(item["rank"]))

    dropped_top20 = [
        _alert_item(ticker, latest_name.get(ticker, ""), rank, previous_rank.get(ticker), rank_lists.get(ticker, []), daily_change_pct.get(ticker))
        for ticker, rank in latest_rank.items()
        if rank > top_n and previous_rank.get(ticker, top_n + 1) <= top_n
    ]
    dropped_top20.sort(key=lambda item: int(item["rank"]))

    return {
        "window": window,
        "benchmark": benchmark,
        "as_of_date": latest_date,
        "previous_date": previous_date,
        "dates": recent_dates,
        "top_n": top_n,
        "move_threshold": move_threshold,
        "stable_top20": stable_top20,
        "upward_moves": upward,
        "downward_moves": downward,
        "entered_top20": entered_top20,
        "dropped_top20": dropped_top20,
    }


def calculate_ticker_score(
    ticker: str,
    window: int,
    benchmark: str,
    market: str,
    as_of_date: date | None,
    optionable_status: dict[str, str],
    stock_profiles: dict[str, dict[str, str]],
) -> dict[str, object] | None:
    market = normalize_market(market)
    df = load_daily_data(ticker, market)
    df = trim_to_as_of_date(df, as_of_date)
    atr_window = atr_window_for_ranking(window)
    minimum_rows = max(window * 2 - 1, atr_window)
    if len(df) < minimum_rows:
        return None

    df = df.copy()
    df["ma"] = df["close"].rolling(window).mean()
    df["atr"] = true_range(df).rolling(atr_window).mean()

    center = df["ma"].dropna().tail(window).mean()
    latest = df.iloc[-1]
    atr = clean_number(latest["atr"])
    close = clean_number(latest["close"])

    if close is None or atr is None or atr == 0 or not math.isfinite(center):
        return None

    atr_score = (close - float(center)) / atr
    price_vs_center_pct = (close / float(center) - 1) * 100
    close_3d_ago = clean_number(df.iloc[-4]["close"]) if len(df) >= 4 else None
    price_change_3d_pct = (close / close_3d_ago - 1) * 100 if close_3d_ago else None
    ticker = normalize_ticker_for_market(ticker, market)
    profile = stock_profiles.get(ticker, {})
    is_benchmark = ticker == benchmark
    has_options = "Y" if is_benchmark else optionable_status.get(ticker, "U")
    if market == "cn":
        row_type = "CSI 500 Index" if is_benchmark else "A-share Stock"
        benchmark_name = "\u4e2d\u8bc1500"
    elif market == "hk":
        row_type = "Hang Seng TECH Index" if is_benchmark else "Hong Kong Stock"
        benchmark_name = "\u6052\u751f\u79d1\u6280"
    else:
        row_type = "Nasdaq-100 ETF" if is_benchmark else "Nasdaq-100 Stock"
        benchmark_name = ""
    default_sector = "\u6307\u6570" if is_benchmark and market in {"cn", "hk"} else "ETF" if is_benchmark else "Unknown"
    default_stock_type = default_sector if is_benchmark else "\u5176\u4ed6"

    return {
        "ticker": ticker,
        "name": profile.get("name", benchmark_name if is_benchmark else ""),
        "type": row_type,
        "has_options": has_options if has_options in {"Y", "N", "U"} else "U",
        "sector": profile.get("sector", default_sector),
        "stock_type": profile.get("stock_type", default_stock_type),
        "date": latest["date"].date().isoformat(),
        "close": close,
        "latest_ma": clean_number(latest["ma"]),
        "ma_center": clean_number(center),
        "atr": atr,
        "atr_score": atr_score,
        "price_vs_center_pct": price_vs_center_pct,
        "price_change_3d_pct": price_change_3d_pct,
    }


def build_ranking_frame(
    universe: list[str],
    window: int,
    benchmark: str,
    market: str,
    as_of_date: date,
    optionable_status: dict[str, str],
    stock_profiles: dict[str, dict[str, str]],
) -> tuple[pd.DataFrame, list[str], float]:
    rows = []
    skipped: list[str] = []
    for ticker in universe:
        try:
            row = calculate_ticker_score(
                ticker,
                window,
                benchmark,
                market,
                as_of_date,
                optionable_status,
                stock_profiles,
            )
        except FileNotFoundError:
            row = None
        if row is None:
            skipped.append(ticker)
        else:
            rows.append(row)

    if not rows:
        raise ValueError("No ranking rows generated")

    df = pd.DataFrame(rows)
    benchmark_rows = df[df["ticker"] == benchmark]
    if benchmark_rows.empty:
        raise ValueError(f"Benchmark {benchmark} is missing from ranking")

    benchmark_score = float(benchmark_rows.iloc[0]["atr_score"])
    df["excess_atr_vs_benchmark"] = df["atr_score"] - benchmark_score
    df = df.sort_values("atr_score", ascending=False).reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))
    return df, skipped, benchmark_score


def build_and_cache_ranking_frame(
    universe: list[str],
    window: int,
    benchmark: str,
    market: str,
    as_of_date: date,
    optionable_status: dict[str, str],
    stock_profiles: dict[str, dict[str, str]],
) -> tuple[pd.DataFrame, list[str], float]:
    df, skipped, benchmark_score = build_ranking_frame(
        universe,
        window,
        benchmark,
        market,
        as_of_date,
        optionable_status,
        stock_profiles,
    )
    cache_rows = df.copy()
    cache_rows.insert(0, "benchmark", benchmark)
    cache_rows.insert(0, "window", window)
    cache_rows.insert(0, "as_of_date", as_of_date.isoformat())
    save_ranking_cache(window, cache_rows.reindex(columns=RANKING_CACHE_COLUMNS), market)
    return df, skipped, benchmark_score


def previous_trading_dates(benchmark: str, as_of_date: date, count: int, market: str = "us") -> list[date]:
    df = load_daily_data(benchmark, market)
    df = trim_to_as_of_date(df, as_of_date)
    dates = [item.date() for item in df["date"].tail(count + 1)]
    return list(reversed(dates[:-1]))[:count]


def rank_map_for_date(
    universe: list[str],
    window: int,
    benchmark: str,
    market: str,
    as_of_date: date,
    optionable_status: dict[str, str],
    stock_profiles: dict[str, dict[str, str]],
    use_cache: bool = True,
) -> dict[str, int]:
    cached = cached_ranking_frame(window, benchmark, as_of_date, market) if use_cache else None
    if cached is not None:
        return {str(row.ticker): int(row.rank) for row in cached.itertuples(index=False)}
    try:
        df, _, _ = build_ranking_frame(universe, window, benchmark, market, as_of_date, optionable_status, stock_profiles)
    except ValueError:
        return {}
    return {str(row.ticker): int(row.rank) for row in df.itertuples(index=False)}


def build_ranking(config: RankingConfig) -> dict[str, object]:
    market = normalize_market(config.market)
    benchmark = normalize_ticker_for_market(config.benchmark or default_benchmark_for_market(market), market)
    effective_as_of_date = config.as_of_date or latest_available_date(benchmark, market)
    optionable_status = {} if market in {"cn", "hk"} else load_optionable_status()
    stock_profiles = load_stock_profiles_for_market(market)
    earnings_calendar = {} if market in {"cn", "hk"} else load_earnings_calendar()
    tickers = load_ticker_file_for_market(market)
    if market == "us" and config.apply_announced_rebalance:
        tickers = apply_rebalance(tickers)

    universe = list(tickers)
    if benchmark not in universe:
        universe.append(benchmark)

    use_cache = market in {"cn", "hk"} or config.apply_announced_rebalance
    cached = cached_ranking_frame(config.window, benchmark, effective_as_of_date, market) if use_cache else None
    if cached is None:
        df, skipped, benchmark_score = build_and_cache_ranking_frame(
            universe,
            config.window,
            benchmark,
            market,
            effective_as_of_date,
            optionable_status,
            stock_profiles,
        )
    else:
        df = cached
        skipped = []
        benchmark_score = float(df.loc[df["ticker"] == benchmark, "atr_score"].iloc[0])

    prior_dates = previous_trading_dates(benchmark, effective_as_of_date, 10, market)
    prior_rank_maps = [
        rank_map_for_date(
            universe,
            config.window,
            benchmark,
            market,
            prior_date,
            optionable_status,
            stock_profiles,
            use_cache,
        )
        for prior_date in prior_dates
    ]
    previous_rank_1 = prior_rank_maps[0] if len(prior_rank_maps) >= 1 else {}
    previous_rank_2 = prior_rank_maps[1] if len(prior_rank_maps) >= 2 else {}

    df["previous_rank_1"] = df["ticker"].map(previous_rank_1).astype("Int64")
    df["previous_rank_2"] = df["ticker"].map(previous_rank_2).astype("Int64")
    df["rank_change"] = df["previous_rank_1"] - df["rank"]
    current_rank_map = {str(row.ticker): int(row.rank) for row in df.itertuples(index=False)}
    rank_maps_by_date = dict(zip(prior_dates, prior_rank_maps))
    rank_maps_by_date[effective_as_of_date] = current_rank_map
    history_dates = list(reversed(prior_dates)) + [effective_as_of_date]
    df["rank_history"] = df.apply(
        lambda row: [
            {
                "date": history_date.isoformat(),
                "rank": rank_maps_by_date.get(history_date, {}).get(str(row["ticker"])),
            }
            for history_date in history_dates
        ],
        axis=1,
    )
    df["earnings_date"] = df["ticker"].map(
        lambda ticker: earnings_calendar.get(str(ticker), {}).get("earnings_date", "")
    )

    return {
        "window": config.window,
        "market": market,
        "as_of_date": effective_as_of_date.isoformat(),
        "benchmark": benchmark,
        "benchmark_rank": int(df.loc[df["ticker"] == benchmark, "rank"].iloc[0]),
        "benchmark_score": benchmark_score,
        "count": len(df),
        "skipped": skipped,
        "data": df.to_dict(orient="records"),
    }
