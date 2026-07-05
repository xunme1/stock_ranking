from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def run_step(label: str, command: list[str]) -> None:
    print("=" * 72, flush=True)
    print(label, flush=True)
    print(" ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT_DIR, check=True)


def parse_markets(value: str) -> list[str]:
    aliases = {
        "all": ["cn", "hk"],
        "asia": ["cn", "hk"],
        "both": ["cn", "hk"],
        "cn": ["cn"],
        "a": ["cn"],
        "ashare": ["cn"],
        "hk": ["hk"],
    }
    result: list[str] = []
    for raw_item in value.split(","):
        item = raw_item.strip().lower()
        if not item:
            continue
        if item not in aliases:
            raise ValueError(f"Unsupported market: {raw_item}")
        for market in aliases[item]:
            if market not in result:
                result.append(market)
    return result or ["cn", "hk"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update A-share/Hong Kong daily bars and rebuild ranking caches.")
    parser.add_argument("--markets", default="cn,hk", help="Markets to update: cn,hk,all. Defaults to cn,hk.")
    parser.add_argument("--end-date", default=date.today().isoformat(), help="End date in YYYY-MM-DD.")
    parser.add_argument("--windows", default="10,20", help="Ranking windows to rebuild, for example 10,20.")
    parser.add_argument("--cache-days", type=int, default=10, help="Recent benchmark trading days to keep in cache.")
    parser.add_argument("--cn-days", type=int, default=30, help="A-share lookback days for missing local CSVs.")
    parser.add_argument("--hk-days", type=int, default=60, help="Hong Kong lookback days for missing local CSVs.")
    parser.add_argument("--sleep-seconds", type=float, default=2.0, help="Sleep after each data request.")
    parser.add_argument("--retries", type=int, default=2, help="Retries per ticker.")
    parser.add_argument("--timeout", type=float, default=15.0, help="A-share AkShare stock request timeout seconds.")
    parser.add_argument("--skip-data", action="store_true", help="Only rebuild ranking caches.")
    parser.add_argument("--skip-cache", action="store_true", help="Only update daily data.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    markets = parse_markets(args.markets)
    python = sys.executable

    print(f"Project root: {ROOT_DIR}", flush=True)
    print(f"Markets: {', '.join(markets)}", flush=True)
    print(f"End date: {args.end_date}", flush=True)

    if not args.skip_data:
        if "cn" in markets:
            run_step(
                "Updating A-share daily data",
                [
                    python,
                    "-B",
                    "scripts/update_cn_daily.py",
                    "--days",
                    str(args.cn_days),
                    "--end-date",
                    args.end_date,
                    "--sleep-seconds",
                    str(args.sleep_seconds),
                    "--retries",
                    str(args.retries),
                    "--timeout",
                    str(args.timeout),
                ],
            )
        if "hk" in markets:
            run_step(
                "Updating Hong Kong daily data",
                [
                    python,
                    "-B",
                    "scripts/update_hk_daily.py",
                    "--days",
                    str(args.hk_days),
                    "--end-date",
                    args.end_date,
                    "--sleep-seconds",
                    str(args.sleep_seconds),
                    "--retries",
                    str(args.retries),
                ],
            )

    if not args.skip_cache:
        for market in markets:
            run_step(
                f"Rebuilding {market} ranking cache",
                [
                    python,
                    "-B",
                    "scripts/build_ranking_cache.py",
                    "--market",
                    market,
                    "--windows",
                    args.windows,
                    "--days",
                    str(args.cache_days),
                    "--end-date",
                    args.end_date,
                ],
            )

    print("=" * 72, flush=True)
    print("A-share/Hong Kong update finished.", flush=True)


if __name__ == "__main__":
    main()
