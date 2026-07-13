from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.services.industry_fund_flow_service import (
    IndustryFlowQuery,
    available_industry_flow_dates,
    build_industry_flow_ranking,
    build_industry_flow_trend,
    build_industry_stock_flows,
)


router = APIRouter(prefix="/api/industry-flows", tags=["industry-flows"])


@router.get("/dates")
def get_industry_flow_dates(
    market: str = Query("us", pattern="^(us|cn|hk)$"),
    limit: int = Query(260, ge=1, le=2000),
) -> dict[str, object]:
    try:
        dates = available_industry_flow_dates(market, limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"market": market, "count": len(dates), "dates": dates}


@router.get("/rankings")
def get_industry_flow_rankings(
    market: str = Query("us", pattern="^(us|cn|hk)$"),
    trade_date: date | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, object]:
    try:
        return build_industry_flow_ranking(IndustryFlowQuery(market=market, trade_date=trade_date, limit=limit))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/trend")
def get_industry_flow_trend(
    market: str = Query("us", pattern="^(us|cn|hk)$"),
    industries: str = Query(""),
    top_n: int = Query(8, ge=1, le=20),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
) -> dict[str, object]:
    selected = [item.strip() for item in industries.split(",") if item.strip()]
    try:
        return build_industry_flow_trend(
            market=market,
            industries=selected,
            top_n=top_n,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{industry_name}/stocks")
def get_industry_stock_flows(
    industry_name: str,
    market: str = Query("us", pattern="^(us|cn|hk)$"),
    trade_date: date | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, object]:
    try:
        return build_industry_stock_flows(market=market, industry_name=industry_name, trade_date=trade_date, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
