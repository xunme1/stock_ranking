from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.core.config import CN_DEFAULT_BENCHMARK, DEFAULT_BENCHMARK, HK_DEFAULT_BENCHMARK
from app.core.config import MAX_WINDOW, MIN_WINDOW
from app.services.ranking_service import RankingConfig, available_dates, build_ranking, build_ranking_alerts


router = APIRouter(prefix="/api/rankings", tags=["rankings"])


@router.get("/latest")
def get_latest_ranking(
    window: int = Query(10, ge=MIN_WINDOW, le=MAX_WINDOW),
    as_of_date: date | None = Query(None),
    benchmark: str | None = Query(None, min_length=1, max_length=12),
    market: str = Query("us", pattern="^(us|cn|hk)$"),
    apply_announced_rebalance: bool = Query(False),
) -> dict[str, object]:
    try:
        return build_ranking(
            RankingConfig(
                window=window,
                benchmark=benchmark,
                market=market,
                apply_announced_rebalance=apply_announced_rebalance,
                as_of_date=as_of_date,
            )
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/dates")
def get_ranking_dates(
    benchmark: str | None = Query(None, min_length=1, max_length=12),
    market: str = Query("us", pattern="^(us|cn|hk)$"),
    limit: int = Query(260, ge=20, le=2000),
) -> dict[str, object]:
    effective_benchmark = benchmark or (CN_DEFAULT_BENCHMARK if market == "cn" else HK_DEFAULT_BENCHMARK if market == "hk" else DEFAULT_BENCHMARK)
    try:
        dates = available_dates(effective_benchmark, limit, market)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"benchmark": effective_benchmark.upper(), "market": market, "count": len(dates), "dates": dates}


@router.get("/alerts")
def get_ranking_alerts(
    window: int = Query(10, ge=MIN_WINDOW, le=MAX_WINDOW),
    as_of_date: date | None = Query(None),
    benchmark: str | None = Query(None, min_length=1, max_length=12),
    market: str = Query("us", pattern="^(us|cn|hk)$"),
    days: int = Query(5, ge=3, le=20),
    top_n: int = Query(20, ge=5, le=100),
    move_threshold: int = Query(10, ge=1, le=100),
) -> dict[str, object]:
    try:
        return build_ranking_alerts(
            window=window,
            benchmark=benchmark,
            market=market,
            as_of_date=as_of_date,
            days=days,
            top_n=top_n,
            move_threshold=move_threshold,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
