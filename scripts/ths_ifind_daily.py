from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterator

import pandas as pd
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
COMPANY_PROFILES_FILE = ROOT_DIR / "data" / "fundamental" / "company_profiles.csv"

STANDARD_COLUMNS = ["ticker", "date", "open", "high", "low", "close", "volume", "vwap", "transactions"]
EXTENDED_COLUMNS = STANDARD_COLUMNS + ["turnover"]

HISTORY_INDICATORS = "preClose,open,high,low,close,avgPrice,change,changeRatio,volume,amount"
HISTORY_PARAMS = "Interval:D,CPS:1,baseDate:1900-01-01,Currency:YSHB,fill:Previous"


class IFindError(RuntimeError):
    pass


@dataclass
class IFindFetchResult:
    code: str
    frame: pd.DataFrame


def load_ifind_credentials() -> tuple[str, str]:
    load_dotenv(ROOT_DIR / ".env")
    username = os.getenv("THS_IFIND_USERNAME", "").strip()
    password = os.getenv("THS_IFIND_PASSWORD", "").strip()
    if not username or not password:
        raise IFindError("Missing THS_IFIND_USERNAME or THS_IFIND_PASSWORD in .env")
    return username, password


@contextmanager
def ifind_session() -> Iterator[object]:
    try:
        from iFinDPy import THS_GetErrorInfo, THS_iFinDLogin, THS_iFinDLogout  # type: ignore
    except ImportError as exc:
        raise IFindError(
            "iFinDPy is not installed. Install the official iFinD SDK and run its installiFinDPy.py "
            "with the project virtualenv."
        ) from exc

    username, password = load_ifind_credentials()
    login_code = THS_iFinDLogin(username, password)
    if login_code not in {0, -201}:
        error_info = THS_GetErrorInfo(login_code)
        raise IFindError(f"iFinD login failed: {error_info}")
    try:
        yield None
    finally:
        THS_iFinDLogout()


def normalize_us_ticker(ticker: str) -> str:
    return str(ticker or "").strip().upper()


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


def normalize_project_ticker(ticker: str, market: str) -> str:
    if market == "cn":
        return normalize_cn_ticker(ticker)
    if market == "hk":
        return normalize_hk_ticker(ticker)
    return normalize_us_ticker(ticker)


def load_us_exchange_suffixes(path: Path = COMPANY_PROFILES_FILE) -> dict[str, str]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    df = pd.read_csv(path, dtype={"ticker": str}).fillna("")
    exchange_suffixes: dict[str, str] = {}
    exchange_map = {
        "XNAS": ".O",
        "XNYS": ".N",
        "ARCX": ".N",
        "BATS": ".N",
        "XASE": ".A",
    }
    for row in df.itertuples(index=False):
        ticker = normalize_us_ticker(getattr(row, "ticker", ""))
        primary_exchange = str(getattr(row, "primary_exchange", "")).strip().upper()
        suffix = exchange_map.get(primary_exchange)
        if ticker and suffix:
            exchange_suffixes[ticker] = suffix
    return exchange_suffixes


def unique_items(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def ths_code_candidates(ticker: str, market: str, us_exchange_suffixes: dict[str, str] | None = None) -> list[str]:
    market = market.lower()
    if market == "cn":
        code = normalize_cn_ticker(ticker)
        if not code.isdigit():
            return [code]
        if code.startswith(("6", "9")):
            return [f"{code}.SH"]
        if code.startswith(("0", "3")):
            return [f"{code}.SZ"]
        if code.startswith(("4", "8")):
            return [f"{code}.BJ"]
        return [f"{code}.SH", f"{code}.SZ", f"{code}.BJ"]

    if market == "hk":
        code = str(ticker or "").strip().upper()
        if code == "HSTECH":
            return ["HSTECH.HK", "HSTECH"]
        normalized = normalize_hk_ticker(code)
        if normalized.isdigit():
            return [f"{normalized[-4:]}.HK"]
        return [normalized, f"{normalized}.HK"]

    normalized = normalize_us_ticker(ticker)
    if "." in normalized and normalized.rsplit(".", 1)[-1] in {"O", "N", "A"}:
        return [normalized]
    suffixes = us_exchange_suffixes or {}
    preferred = suffixes.get(normalized)
    return unique_items([f"{normalized}{preferred or ''}", f"{normalized}.O", f"{normalized}.N", f"{normalized}.A"])


def fetch_ifind_history(
    ticker: str,
    market: str,
    start: date,
    end: date,
    us_exchange_suffixes: dict[str, str] | None = None,
) -> IFindFetchResult:
    try:
        from iFinDPy import THS_HistoryQuotes, THS_Trans2DataFrame  # type: ignore
    except ImportError as exc:
        raise IFindError("iFinDPy is not installed.") from exc

    project_ticker = normalize_project_ticker(ticker, market)
    last_error = ""
    for ths_code in ths_code_candidates(ticker, market, us_exchange_suffixes):
        payload = THS_HistoryQuotes(
            ths_code,
            HISTORY_INDICATORS,
            HISTORY_PARAMS,
            start.isoformat(),
            end.isoformat(),
        )
        error_code = payload.get("errorcode") if isinstance(payload, dict) else None
        error_message = payload.get("errmsg") if isinstance(payload, dict) else ""
        if error_code != 0:
            last_error = f"{ths_code}: errorcode={error_code} errmsg={error_message}"
            continue
        df = THS_Trans2DataFrame(payload)
        normalized = normalize_ifind_frame(df, project_ticker)
        if not normalized.empty:
            return IFindFetchResult(code=ths_code, frame=normalized)
        last_error = f"{ths_code}: empty data"

    raise IFindError(f"No iFinD daily data for {ticker} ({market}) from {start} to {end}. Last error: {last_error}")


def normalize_ifind_frame(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=EXTENDED_COLUMNS)
    result = pd.DataFrame()
    result["ticker"] = ticker
    result["date"] = pd.to_datetime(df.get("time"), errors="coerce").dt.date.astype(str)
    result["open"] = pd.to_numeric(df.get("open"), errors="coerce")
    result["high"] = pd.to_numeric(df.get("high"), errors="coerce")
    result["low"] = pd.to_numeric(df.get("low"), errors="coerce")
    result["close"] = pd.to_numeric(df.get("close"), errors="coerce")
    result["volume"] = pd.to_numeric(df.get("volume"), errors="coerce")
    result["vwap"] = pd.to_numeric(df.get("avgPrice"), errors="coerce")
    result["transactions"] = pd.NA
    result["turnover"] = pd.to_numeric(df.get("amount"), errors="coerce")
    result = result.dropna(subset=["date", "open", "high", "low", "close"])
    result = result.drop_duplicates(subset=["ticker", "date"], keep="last")
    return result.sort_values(["ticker", "date"]).reset_index(drop=True)


def merge_daily_csv(path: Path, ticker: str, new_df: pd.DataFrame, columns: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        old_df = pd.read_csv(path, dtype={"ticker": str})
    else:
        old_df = pd.DataFrame(columns=columns)
    old_count = len(old_df)
    combined = pd.concat([old_df, new_df], ignore_index=True)
    combined["ticker"] = ticker
    combined["date"] = pd.to_datetime(combined["date"], errors="coerce").dt.date.astype(str)
    combined = combined.dropna(subset=["date", "open", "high", "low", "close"])
    combined = combined.drop_duplicates(subset=["ticker", "date"], keep="last")
    combined = combined.sort_values(["ticker", "date"])
    for column in columns:
        if column not in combined.columns:
            combined[column] = pd.NA
    combined[columns].to_csv(path, index=False, encoding="utf-8-sig")
    return max(len(combined) - old_count, 0)
