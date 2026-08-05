from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter

from app.core.config import EARNINGS_SENTIMENT_REPORT_DIR


router = APIRouter(prefix="/api/earnings-reports", tags=["earnings-reports"])
REPORT_RE = re.compile(r"^earnings_sentiment_(?P<date>\d{4}-\d{2}-\d{2})\.html$")


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
