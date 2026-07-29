from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "backend"))

from app.services.corporate_action_news_service import (  # noqa: E402
    MARKETS,
    build_search_tasks,
    collect_market,
    record_run,
    rematch_events,
)


def parse_markets(value: str) -> list[str]:
    markets = [item.strip().lower() for item in value.split(",") if item.strip()]
    invalid = [item for item in markets if item not in MARKETS]
    if invalid:
        raise ValueError(f"Unsupported markets: {', '.join(invalid)}")
    return list(dict.fromkeys(markets))


def run_market_task(market: str, as_of: date, args: argparse.Namespace) -> tuple[dict[str, object], bool]:
    """Run one market in isolation so one failure never suppresses the other market jobs."""
    task_name = f"corporate-actions:{market}"
    try:
        result = collect_market(market, as_of, args.lookback_days, args.max_results, args.dry_run)
        return {"task": task_name, **result}, bool(result["errors"])
    except Exception as exc:
        error = str(exc)
        if not args.dry_run:
            record_run(
                market, as_of, as_of - timedelta(days=args.lookback_days), "failed",
                len(build_search_tasks(market)), 0, 0, [error],
            )
        return {"task": task_name, "market": market, "status": "failed", "error": error}, True


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect recent buyback and reduction news, then mark stock-pool matches.")
    parser.add_argument("--markets", default="us,cn,hk", help="Comma-separated markets: us,cn,hk.")
    parser.add_argument("--as-of-date", default=date.today().isoformat(), help="Search cutoff date in YYYY-MM-DD.")
    parser.add_argument("--lookback-days", type=int, default=30, choices=range(1, 91), metavar="1-90")
    parser.add_argument("--max-results", type=int, default=10, choices=range(1, 11), metavar="1-10")
    parser.add_argument("--dry-run", action="store_true", help="Search and extract, but do not write SQLite data.")
    parser.add_argument("--rematch-only", action="store_true", help="Recalculate stock-pool flags without web searches.")
    parser.add_argument("--include-events", action="store_true", help="Include structured event details in per-market task output.")
    args = parser.parse_args()

    markets = parse_markets(args.markets)
    if args.rematch_only:
        print(json.dumps({"rematched": rematch_events(markets)}, ensure_ascii=True))
        return
    try:
        as_of = date.fromisoformat(args.as_of_date)
    except ValueError as exc:
        raise SystemExit("--as-of-date must use YYYY-MM-DD") from exc

    failed = 0
    for market in markets:
        result, task_failed = run_market_task(market, as_of, args)
        # Keep console output safe for legacy Windows code pages; collected text remains UTF-8 in SQLite.
        display_result = result if args.include_events else {key: value for key, value in result.items() if key != "events"}
        print(json.dumps(display_result, ensure_ascii=True, indent=2))
        failed += int(task_failed)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
