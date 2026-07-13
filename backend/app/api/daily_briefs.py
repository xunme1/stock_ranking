from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter

from app.core.config import DAILY_BRIEF_OUTPUT_DIR


router = APIRouter(prefix="/api/daily-briefs", tags=["daily-briefs"])

REPORT_RE = re.compile(r"^daily_brief_(?P<market>us|cn|hk)_(?P<date>\d{4}-\d{2}-\d{2})_w(?P<window>10)\.html$")
MARKET_LABELS = {"us": "美股", "cn": "A股", "hk": "港股"}


def report_item(path: Path) -> dict[str, object] | None:
    match = REPORT_RE.match(path.name)
    if not match:
        return None
    market = match.group("market")
    date = match.group("date")
    window = int(match.group("window"))
    return {
        "market": market,
        "market_label": MARKET_LABELS.get(market, market),
        "date": date,
        "window": window,
        "filename": path.name,
        "url": f"/daily-briefs/files/{path.name}",
        "size_bytes": path.stat().st_size,
        "updated_at": path.stat().st_mtime,
    }


@router.get("")
def list_daily_briefs() -> dict[str, object]:
    DAILY_BRIEF_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for path in DAILY_BRIEF_OUTPUT_DIR.glob("daily_brief_*_w10.html"):
        item = report_item(path)
        if item:
            items.append(item)
    items.sort(key=lambda item: (str(item["date"]), str(item["market"])), reverse=True)
    dates = sorted({str(item["date"]) for item in items}, reverse=True)
    return {
        "count": len(items),
        "dates": dates,
        "data": items,
    }
