from __future__ import annotations

"""Build a local Codex research context from the refreshed earnings calendar snapshots."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.earnings_reports import earnings_preview_context, latest_us_data_date  # noqa: E402


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def build_context(data_as_of_date: date, days: int) -> dict[str, object]:
    return earnings_preview_context(data_as_of_date, days)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export upcoming earnings candidates for the next report window.")
    parser.add_argument("--as-of-date", type=parse_date, default=None, help="YYYY-MM-DD latest US data date; defaults to local QQQ latest date")
    parser.add_argument("--days", type=int, choices=range(1, 8), default=3)
    parser.add_argument("--output", default=None, help="Optional UTF-8 JSON output path; otherwise prints JSON")
    args = parser.parse_args()
    data_as_of_date = args.as_of_date or latest_us_data_date()
    content = json.dumps(build_context(data_as_of_date, args.days), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        print(f"Context: {output}")
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
