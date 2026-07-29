from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from app.services.corporate_action_news_service import query_news, service_status


router = APIRouter(prefix="/api/corporate-actions", tags=["corporate-actions"])


@router.get("/news")
def get_corporate_action_news(
    market: str = Query(..., pattern="^(us|cn|hk)$"),
    as_of_date: date | None = Query(None),
    lookback_days: int = Query(30, ge=1, le=90),
    event_type: str = Query("all", pattern="^(all|buyback|reduction)$"),
    attention: str = Query("all", pattern="^(all|high|normal)$"),
    in_stock_pool: bool | None = Query(None),
    ticker: str | None = Query(None, min_length=1, max_length=20),
    limit: int = Query(200, ge=1, le=500),
) -> dict[str, object]:
    return query_news(market, as_of_date, lookback_days, event_type, attention, in_stock_pool, ticker, limit)


@router.get("/status")
def get_corporate_action_status() -> dict[str, object]:
    return service_status()
