from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

from app.core.config import (
    A_SHARE_SUBTYPE_LEADERS_FILE,
    CN_STOCK_POOL_FILE,
    COMPANY_PROFILES_FILE,
    EARNINGS_CALENDAR_FILE,
    HK_STOCK_POOL_FILE,
    NASDAQ100_FILE,
    NASDAQ100_OPTIONABLE_FILE,
    OPTIONABLE_TICKERS_FILE,
    RAW_CN_DAILY_DIR,
    RAW_DAILY_DIR,
    RAW_HK_DAILY_DIR,
    STOCK_PROFILES_FILE,
    STOCK_SUBTYPES_FILE,
)


def normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def normalize_market(market: str | None) -> str:
    value = str(market or "us").strip().lower()
    if value in {"cn", "a", "ashare", "a-share"}:
        return "cn"
    if value in {"hk", "hkg", "hongkong", "hong-kong"}:
        return "hk"
    return "us"


def normalize_cn_ticker(ticker: str) -> str:
    text = str(ticker or "").strip().upper()
    if "." in text:
        text = text.split(".", 1)[0]
    if text.startswith(("SH", "SZ", "BJ")):
        text = text[2:]
    return text.zfill(6) if text.isdigit() else text


def normalize_hk_ticker(ticker: str) -> str:
    text = str(ticker or "").strip().upper()
    if "." in text:
        text = text.split(".", 1)[0]
    if text.startswith("HK"):
        text = text[2:]
    return text.zfill(5) if text.isdigit() else text


def normalize_ticker_for_market(ticker: str, market: str | None = "us") -> str:
    normalized_market = normalize_market(market)
    if normalized_market == "cn":
        return normalize_cn_ticker(ticker)
    if normalized_market == "hk":
        return normalize_hk_ticker(ticker)
    return normalize_ticker(ticker)


def ticker_csv_path(ticker: str, market: str | None = "us") -> Path:
    normalized_market = normalize_market(market)
    normalized_ticker = normalize_ticker_for_market(ticker, normalized_market)
    directory = RAW_CN_DAILY_DIR if normalized_market == "cn" else RAW_HK_DAILY_DIR if normalized_market == "hk" else RAW_DAILY_DIR
    return directory / f"{normalized_ticker}.csv"


@lru_cache(maxsize=512)
def load_daily_csv_cached(ticker: str, market: str, mtime_ns: int) -> pd.DataFrame:
    path = ticker_csv_path(ticker, market)
    df = pd.read_csv(path)
    df["ticker"] = normalize_ticker_for_market(ticker, market)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for column in ["open", "high", "low", "close", "volume", "vwap", "transactions"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close"])
    return df.sort_values("date").reset_index(drop=True)


def load_daily_data(ticker: str, market: str | None = "us") -> pd.DataFrame:
    normalized_market = normalize_market(market)
    normalized_ticker = normalize_ticker_for_market(ticker, normalized_market)
    path = ticker_csv_path(normalized_ticker, normalized_market)
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(f"Daily CSV not found for {normalized_ticker}")
    return load_daily_csv_cached(normalized_ticker, normalized_market, path.stat().st_mtime_ns).copy()


def load_ticker_file(path: Path = NASDAQ100_FILE) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Ticker file not found: {path}")

    tickers: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        ticker = normalize_ticker(line)
        if not ticker or ticker.startswith("#") or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)
    return tickers


@lru_cache(maxsize=16)
def load_ticker_set(path: Path = NASDAQ100_OPTIONABLE_FILE) -> set[str]:
    if not path.exists():
        return set()
    return set(load_ticker_file(path))


@lru_cache(maxsize=16)
def load_optionable_tickers(path: Path = OPTIONABLE_TICKERS_FILE) -> set[str]:
    return {ticker for ticker, has_options in load_optionable_status(path).items() if has_options == "Y"}


@lru_cache(maxsize=16)
def load_optionable_status(path: Path = OPTIONABLE_TICKERS_FILE) -> dict[str, str]:
    if path.exists() and path.stat().st_size > 0:
        df = pd.read_csv(path)
        if {"ticker", "has_options"}.issubset(df.columns):
            status: dict[str, str] = {}
            for row in df.fillna("").itertuples(index=False):
                ticker = normalize_ticker(str(getattr(row, "ticker", "")))
                has_options = str(getattr(row, "has_options", "")).strip().upper()
                if ticker:
                    status[ticker] = has_options if has_options in {"Y", "N", "U"} else "U"
            return status

    return {}


@lru_cache(maxsize=16)
def load_stock_profiles(path: Path = STOCK_PROFILES_FILE) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    df = pd.read_csv(path, encoding="utf-8-sig")
    profiles: dict[str, dict[str, str]] = {}
    for row in df.fillna("").itertuples(index=False):
        ticker = normalize_ticker(str(getattr(row, "ticker", "")))
        if not ticker:
            continue
        profiles[ticker] = {
            "sector": str(getattr(row, "sector", "")).strip() or "Unknown",
            "stock_type": str(getattr(row, "stock_type", "")).strip() or "其他",
        }
    return profiles


@lru_cache(maxsize=16)
def load_cn_stock_profiles(path: Path = CN_STOCK_POOL_FILE) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype={"ticker": str}).fillna("")
    profiles: dict[str, dict[str, str]] = {}
    for row in df.itertuples(index=False):
        ticker = normalize_cn_ticker(str(getattr(row, "ticker", "")))
        if not ticker:
            continue
        profiles[ticker] = {
            "sector": str(getattr(row, "sector", "")).strip() or "未分类",
            "stock_type": str(getattr(row, "stock_type", "")).strip() or str(getattr(row, "sector", "")).strip() or "未分类",
            "name": str(getattr(row, "name", "")).strip(),
        }
    return profiles


@lru_cache(maxsize=16)
def load_hk_stock_profiles(path: Path = HK_STOCK_POOL_FILE) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype={"ticker": str}).fillna("")
    profiles: dict[str, dict[str, str]] = {}
    for row in df.itertuples(index=False):
        ticker = normalize_hk_ticker(str(getattr(row, "ticker", "")))
        if not ticker:
            continue
        sector = str(getattr(row, "sector", "")).strip()
        profiles[ticker] = {
            "sector": sector or "未分类",
            "stock_type": str(getattr(row, "stock_type", "")).strip() or sector or "未分类",
            "name": str(getattr(row, "name", "")).strip(),
        }
    return profiles


def load_stock_profiles_for_market(market: str | None = "us") -> dict[str, dict[str, str]]:
    normalized_market = normalize_market(market)
    if normalized_market == "cn":
        return load_cn_stock_profiles()
    if normalized_market == "hk":
        return load_hk_stock_profiles()
    return load_stock_profiles()


def load_ticker_file_for_market(market: str | None = "us") -> list[str]:
    normalized_market = normalize_market(market)
    if normalized_market == "cn":
        return list(load_cn_stock_profiles().keys())
    if normalized_market == "hk":
        return list(load_hk_stock_profiles().keys())
    return load_ticker_file()


@lru_cache(maxsize=16)
def load_stock_subtypes(path: Path = STOCK_SUBTYPES_FILE) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    df = pd.read_csv(path, encoding="utf-8-sig")
    subtypes: dict[str, dict[str, str]] = {}
    for row in df.fillna("").itertuples(index=False):
        ticker = normalize_ticker(str(getattr(row, "ticker", "")))
        if not ticker:
            continue
        subtypes[ticker] = {
            "ticker": ticker,
            "name": str(getattr(row, "name", "")).strip(),
            "sector": str(getattr(row, "sector", "")).strip(),
            "stock_type": str(getattr(row, "stock_type", "")).strip(),
            "sub_type": str(getattr(row, "sub_type", "")).strip(),
            "sub_type_cn": str(getattr(row, "sub_type_cn", "")).strip(),
            "a_share_keywords": str(getattr(row, "a_share_keywords", "")).strip(),
            "sic_description": str(getattr(row, "sic_description", "")).strip(),
            "source": str(getattr(row, "source", "")).strip(),
        }
    return subtypes


@lru_cache(maxsize=16)
def load_a_share_subtype_leaders(path: Path = A_SHARE_SUBTYPE_LEADERS_FILE) -> dict[str, list[dict[str, str]]]:
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype={"code": str}, encoding="utf-8-sig").fillna("")
    leaders: dict[str, list[dict[str, str]]] = {}
    for row in df.itertuples(index=False):
        sub_type = str(getattr(row, "sub_type", "")).strip()
        if not sub_type:
            continue
        item = {
            "sub_type": sub_type,
            "sub_type_cn": str(getattr(row, "sub_type_cn", "")).strip(),
            "a_share_keywords": str(getattr(row, "a_share_keywords", "")).strip(),
            "rank": int(getattr(row, "rank", 0) or 0),
            "code": str(getattr(row, "code", "")).strip().zfill(6),
            "name": str(getattr(row, "name", "")).strip(),
            "market_cap_cny": str(getattr(row, "market_cap_cny", "")).strip(),
            "market_cap_100m_cny": str(getattr(row, "market_cap_100m_cny", "")).strip(),
            "latest_price": str(getattr(row, "latest_price", "")).strip(),
            "change_pct": str(getattr(row, "change_pct", "")).strip(),
            "industry_boards": str(getattr(row, "industry_boards", "")).strip(),
            "concept_boards": str(getattr(row, "concept_boards", "")).strip(),
        }
        leaders.setdefault(sub_type, []).append(item)
    for items in leaders.values():
        items.sort(key=lambda item: item["rank"])
    return leaders


@lru_cache(maxsize=16)
def load_earnings_calendar(path: Path = EARNINGS_CALENDAR_FILE) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    calendar: dict[str, dict[str, str]] = {}
    for row in df.fillna("").itertuples(index=False):
        ticker = normalize_ticker(str(getattr(row, "ticker", "")))
        if not ticker:
            continue
        calendar[ticker] = {
            "earnings_date": str(getattr(row, "earnings_date", "")).strip(),
            "earnings_time": str(getattr(row, "earnings_time", "")).strip(),
            "earnings_estimate": str(getattr(row, "earnings_estimate", "")).strip(),
            "earnings_currency": str(getattr(row, "earnings_currency", "")).strip(),
        }
    return calendar


@lru_cache(maxsize=16)
def load_company_profiles(path: Path = COMPANY_PROFILES_FILE) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    df = pd.read_csv(path, encoding="utf-8-sig")
    profiles: dict[str, dict[str, str]] = {}
    for row in df.fillna("").itertuples(index=False):
        ticker = normalize_ticker(str(getattr(row, "ticker", "")))
        if not ticker:
            continue
        profiles[ticker] = {
            "ticker": ticker,
            "name": str(getattr(row, "name", "")).strip(),
            "market": str(getattr(row, "market", "")).strip(),
            "exchange": str(getattr(row, "exchange", "")).strip(),
            "locale": str(getattr(row, "locale", "")).strip(),
            "primary_exchange": str(getattr(row, "primary_exchange", "")).strip(),
            "currency_name": str(getattr(row, "currency_name", "")).strip(),
            "market_cap": str(getattr(row, "market_cap", "")).strip(),
            "sic_description": str(getattr(row, "sic_description", "")).strip(),
            "homepage_url": str(getattr(row, "homepage_url", "")).strip(),
            "description": str(getattr(row, "description", "")).strip(),
            "summary_zh": str(getattr(row, "summary_zh", "")).strip(),
            "source": str(getattr(row, "source", "")).strip(),
            "updated_at": str(getattr(row, "updated_at", "")).strip(),
        }
    return profiles
