from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.core.config import MAX_WINDOW, MIN_WINDOW
from app.services.ranking_service import RankingConfig, available_dates, build_ranking


router = APIRouter(prefix="/api/rankings", tags=["rankings"])


@router.get("/latest")
def get_latest_ranking(
    window: int = Query(10, ge=MIN_WINDOW, le=MAX_WINDOW),
    as_of_date: date | None = Query(None),
    benchmark: str = Query("QQQ", min_length=1, max_length=12),
    apply_announced_rebalance: bool = Query(False),
) -> dict[str, object]:
    try:
        return build_ranking(
            RankingConfig(
                window=window,
                benchmark=benchmark,
                apply_announced_rebalance=apply_announced_rebalance,
                as_of_date=as_of_date,
            )
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/dates")
def get_ranking_dates(
    benchmark: str = Query("QQQ", min_length=1, max_length=12),
    limit: int = Query(260, ge=20, le=2000),
) -> dict[str, object]:
    try:
        dates = available_dates(benchmark, limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"benchmark": benchmark.upper(), "count": len(dates), "dates": dates}
