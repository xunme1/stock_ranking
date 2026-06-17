from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.services.data_loader import load_daily_data, normalize_ticker
from app.services.ranking_service import trim_to_as_of_date


router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/{ticker}/daily")
def get_stock_daily(
    ticker: str,
    limit: int = Query(260, ge=20, le=2000),
    as_of_date: date | None = Query(None),
) -> dict[str, object]:
    normalized = normalize_ticker(ticker)
    try:
        df = trim_to_as_of_date(load_daily_data(normalized), as_of_date).tail(limit)
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
