from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = EXPERIMENT_DIR / "output"
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))

from interactive_daily_brief import generate_html  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render daily ranking brief HTML.")
    parser.add_argument("--window", type=int, default=10, choices=[10], help="Daily brief uses 10-day window only.")
    parser.add_argument("--market", choices=["us", "cn", "hk"], default="us", help="Market to render when --input is not provided.")
    parser.add_argument("--as-of-date", default=None, help="Use cached date on or before YYYY-MM-DD.")
    parser.add_argument("--input", default=None, help="Existing brief JSON path.")
    parser.add_argument("--output", default=None, help="Output HTML path.")
    parser.add_argument("--theme", choices=("dark", "light"), default="light", help="Default HTML theme.")
    return parser.parse_args()


def load_or_build_brief(args: argparse.Namespace) -> dict:
    if args.input:
        return json.loads(Path(args.input).read_text(encoding="utf-8"))

    from generate_brief_data import build_brief

    brief = build_brief(args.window, args.as_of_date, top_n=20, move_threshold=10, market=args.market)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / f"daily_brief_{brief['market']}_{brief['as_of_date']}_w{brief['window']}.json"
    json_path.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    return brief


def main() -> None:
    args = parse_args()
    brief = load_or_build_brief(args)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = (
        Path(args.output)
        if args.output
        else OUTPUT_DIR / f"daily_brief_{brief.get('market', 'us')}_{brief['as_of_date']}_w{brief['window']}.html"
    )
    output.write_text(generate_html(brief, args.theme), encoding="utf-8")
    print(f"HTML written: {output}")


if __name__ == "__main__":
    main()
