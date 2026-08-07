from __future__ import annotations

import re
import csv
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from app.core.config import (
    EARNINGS_CALENDAR_FILE,
    EARNINGS_CALENDAR_HISTORY_FILE,
    EARNINGS_SENTIMENT_REPORT_DIR,
)


router = APIRouter(prefix="/api/earnings-reports", tags=["earnings-reports"])
REPORT_RE = re.compile(r"^earnings_sentiment_(?P<date>\d{4}-\d{2}-\d{2})\.html$")


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None


def _read_calendar_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return [
            {key: str(value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def upcoming_earnings_candidates(as_of_date: date, days: int) -> list[dict[str, str]]:
    """Return de-duplicated earnings candidates from today through the next days."""
    end = as_of_date + timedelta(days=days - 1)
    selected: dict[tuple[str, str], dict[str, str]] = {}
    # History can contain a date that has since rolled out of the latest calendar;
    # retain it so an intraday refresh cannot make a still-upcoming candidate vanish.
    for row in _read_calendar_rows(EARNINGS_CALENDAR_HISTORY_FILE) + _read_calendar_rows(EARNINGS_CALENDAR_FILE):
        ticker = row.get("ticker", "").upper()
        earnings_date = row.get("earnings_date", "")
        candidate_date = _parse_date(earnings_date)
        if ticker and candidate_date and as_of_date <= candidate_date <= end:
            selected[(ticker, earnings_date)] = {
                "ticker": ticker,
                "company_name": row.get("company_name", ""),
                "calendar_date": earnings_date,
                "announcement_time": row.get("announcement_time", ""),
            }
    return sorted(selected.values(), key=lambda item: (item["calendar_date"], item["ticker"]))


@router.get("/context")
def get_earnings_report_context(
    as_of_date: date | None = None,
    days: int = Query(default=3, ge=1, le=7),
) -> dict[str, object]:
    """Public, read-only upcoming earnings context for the next report window."""
    report_date = as_of_date or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    window_end = report_date + timedelta(days=days - 1)
    candidates = upcoming_earnings_candidates(report_date, days)
    return {
        "report_date": report_date.isoformat(),
        "window_start": report_date.isoformat(),
        "window_end": window_end.isoformat(),
        "days": days,
        "candidates": candidates,
    }


@router.get("")
def list_earnings_reports() -> dict[str, object]:
    EARNINGS_SENTIMENT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, object]] = []
    for path in EARNINGS_SENTIMENT_REPORT_DIR.glob("earnings_sentiment_*.html"):
        match = REPORT_RE.match(path.name)
        if not match:
            continue
        reports.append({
            "date": match.group("date"),
            "filename": path.name,
            "url": f"/earnings-reports/files/{path.name}",
            "size_bytes": path.stat().st_size,
            "updated_at": path.stat().st_mtime,
        })
    reports.sort(key=lambda item: str(item["date"]), reverse=True)
    return {"count": len(reports), "data": reports}
