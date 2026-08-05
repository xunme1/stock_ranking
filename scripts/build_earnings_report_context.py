from __future__ import annotations

"""Build a local Codex research context from the refreshed earnings calendar snapshots."""

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.earnings_reports import recent_earnings_candidates  # noqa: E402


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def build_context(report_date: date, days: int) -> dict[str, object]:
    return {
        "report_date": report_date.isoformat(),
        "window_start": (report_date - timedelta(days=days - 1)).isoformat(),
        "days": days,
        "candidates": recent_earnings_candidates(report_date, days),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export local earnings candidates for the Codex research workflow.")
    parser.add_argument("--as-of-date", type=parse_date, default=None, help="YYYY-MM-DD; defaults to today in Asia/Shanghai")
    parser.add_argument("--days", type=int, choices=range(1, 8), default=3)
    parser.add_argument("--output", default=None, help="Optional UTF-8 JSON output path; otherwise prints JSON")
    args = parser.parse_args()
    report_date = args.as_of_date or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    content = json.dumps(build_context(report_date, args.days), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        print(f"Context: {output}")
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
