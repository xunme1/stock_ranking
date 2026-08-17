from __future__ import annotations

import re
import csv
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Response

from app.core.config import (
    EARNINGS_CALENDAR_FILE,
    EARNINGS_CALENDAR_HISTORY_FILE,
    EARNINGS_SENTIMENT_REPORT_DIR,
)


router = APIRouter(prefix="/api/earnings-reports", tags=["earnings-reports"])
REPORT_RE = re.compile(r"^earnings_sentiment_(?P<date>\d{4}-\d{2}-\d{2})\.html$")
EARNINGS_PREVIEW_BASE_URL = "https://adc-lab-e6rvm8rq-frul696z.oss-cn-hangzhou.aliyuncs.com/earnings_preview/"
EARNINGS_PREVIEW_INDEX_URL = f"{EARNINGS_PREVIEW_BASE_URL}index.json"


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


def _normalise_preview_entry(value: object) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    report_date = str(value.get("report_date", "")).strip()
    url = str(value.get("url", "")).strip()
    if _parse_date(report_date) is None:
        return None
    # Only return public PDF files from the configured OSS report prefix.  The
    # frontend can safely use this payload without accepting arbitrary links.
    if not (url.startswith(EARNINGS_PREVIEW_BASE_URL) and url.lower().endswith(".pdf")):
        return None
    return {
        "report_date": report_date,
        "generated_at": str(value.get("generated_at", "")).strip(),
        "url": url,
    }


def _download_preview_index() -> object:
    try:
        # This OSS endpoint intermittently closes the TLS handshake used by
        # Python's standard HTTP stack.  curl_cffi uses libcurl and has proven
        # reliable for the same public object while keeping certificate checks.
        from curl_cffi import requests as curl_requests  # type: ignore
        response = curl_requests.get(
            EARNINGS_PREVIEW_INDEX_URL,
            headers={"Accept": "application/json", "User-Agent": "stock-ranking-api/1.0"},
            timeout=10,
            impersonate="chrome",
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="财报前瞻报告索引暂时不可用") from exc


def _normalise_preview_index(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="财报前瞻报告索引格式无效")
    latest = _normalise_preview_entry(payload.get("latest"))
    archives_by_key: dict[tuple[str, str], dict[str, str]] = {}
    archives = payload.get("archives", [])
    if isinstance(archives, list):
        for item in archives:
            entry = _normalise_preview_entry(item)
            if entry is not None:
                archives_by_key[(entry["report_date"], entry["url"])] = entry
    return {
        "updated_at": str(payload.get("updated_at", "")).strip(),
        "latest": latest,
        "archives": sorted(
            archives_by_key.values(),
            key=lambda item: (item["report_date"], item["generated_at"], item["url"]),
            reverse=True,
        ),
    }


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


def earnings_preview_context(server_date: date, days: int) -> dict[str, object]:
    """Build the upcoming earnings window from the server's current date."""
    window_start = server_date
    window_end = server_date + timedelta(days=days - 1)
    return {
        "server_date": server_date.isoformat(),
        # Retained for existing API consumers; this is the first preview date.
        "report_date": window_start.isoformat(),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "days": days,
        "candidates": upcoming_earnings_candidates(window_start, days),
    }


@router.get("/context")
def get_earnings_report_context(
    as_of_date: date | None = None,
    days: int = Query(default=3, ge=1, le=7),
) -> dict[str, object]:
    """Public, read-only earnings preview from the server's current date.

    ``as_of_date`` is an optional server-date override for reproducible
    reports and tests. When omitted, the host system's local date is used.
    """
    return earnings_preview_context(as_of_date or datetime.now().date(), days)


@router.get("/previews")
def get_earnings_preview_reports(response: Response) -> dict[str, object]:
    """Return the current OSS report index through the same-origin API.

    OSS intentionally serves the index without browser CORS headers.  Keeping
    this small, fixed upstream proxy on the API lets the website refresh its
    archive list without exposing OSS credentials or accepting arbitrary URLs.
    """
    response.headers["Cache-Control"] = "no-store"
    return _normalise_preview_index(_download_preview_index())


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
