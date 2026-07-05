from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.services.data_loader import (
    load_a_share_subtype_leaders,
    load_company_profiles,
    load_daily_data,
    load_stock_subtypes,
    normalize_ticker_for_market,
    normalize_ticker,
)
from app.services.ranking_service import trim_to_as_of_date


router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/{ticker}/daily")
def get_stock_daily(
    ticker: str,
    limit: int = Query(260, ge=20, le=2000),
    as_of_date: date | None = Query(None),
    market: str = Query("us", pattern="^(us|cn|hk)$"),
) -> dict[str, object]:
    normalized = normalize_ticker_for_market(ticker, market)
    try:
        df = trim_to_as_of_date(load_daily_data(normalized, market), as_of_date).tail(limit)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    rows = []
    for row in df.itertuples(index=False):
        rows.append(
            {
                "ticker": normalized,
                "date": row.date.date().isoformat(),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume) if hasattr(row, "volume") else None,
            }
        )

    return {"ticker": normalized, "count": len(rows), "data": rows}


@router.get("/{ticker}/profile")
def get_stock_profile(ticker: str) -> dict[str, object]:
    normalized = normalize_ticker(ticker)
    profile = load_company_profiles().get(normalized)
    if not profile:
        return {
            "ticker": normalized,
            "name": "",
            "market": "",
            "exchange": "",
            "locale": "",
            "primary_exchange": "",
            "currency_name": "",
            "market_cap": "",
            "sic_description": "",
            "homepage_url": "",
            "description": "",
            "summary_zh": "",
            "source": "",
            "updated_at": "",
        }
    return profile


@router.get("/{ticker}/peers")
def get_stock_peers(ticker: str) -> dict[str, object]:
    normalized = normalize_ticker(ticker)
    subtype = load_stock_subtypes().get(normalized)
    if not subtype:
        return {
            "ticker": normalized,
            "sub_type": "",
            "sub_type_cn": "",
            "a_share_keywords": "",
            "source": "",
            "a_share_leaders": [],
        }

    leaders = load_a_share_subtype_leaders().get(subtype["sub_type"], [])
    return {
        "ticker": normalized,
        "sub_type": subtype["sub_type"],
        "sub_type_cn": subtype["sub_type_cn"],
        "a_share_keywords": subtype["a_share_keywords"],
        "source": subtype["source"],
        "a_share_leaders": leaders,
    }
