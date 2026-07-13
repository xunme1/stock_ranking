from __future__ import annotations

import argparse
import html
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
BRIEF_OUTPUT_DIR = PROJECT_ROOT / "experiments" / "daily_brief" / "output"
DEFAULT_PUBLIC_BASE_URL = "http://127.0.0.1:8001/daily-briefs/files"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.ranking_service import ranking_cache_path  # noqa: E402


MARKET_LABELS = {
    "us": "美股",
    "cn": "A股",
    "hk": "港股",
}


def split_recipients(value: str) -> list[str]:
    return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]


def load_config(cli_to: str | None = None) -> dict[str, str]:
    load_dotenv(PROJECT_ROOT / ".env")
    config = {
        "SMTP_HOST": os.getenv("SMTP_HOST", "").strip(),
        "SMTP_PORT": os.getenv("SMTP_PORT", "").strip(),
        "SMTP_USER": (os.getenv("SMTP_USER") or os.getenv("SMTP_USERNAME") or "").strip(),
        "SMTP_PASSWORD": os.getenv("SMTP_PASSWORD", "").strip(),
        "MAIL_FROM": (os.getenv("MAIL_FROM") or os.getenv("SMTP_FROM") or "").strip(),
        "PUBLIC_BASE_URL": (
            os.getenv("DAILY_BRIEF_PUBLIC_BASE_URL")
            or os.getenv("DAILY_BRIEF_BASE_URL")
            or os.getenv("PUBLIC_DAILY_BRIEF_BASE_URL")
            or DEFAULT_PUBLIC_BASE_URL
        ).strip(),
    }
    config["MAIL_TO"] = (cli_to or os.getenv("MAIL_TO") or os.getenv("SMTP_TO") or "").strip()

    required = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "MAIL_FROM"]
    missing = [key for key in required if not config[key]]
    if not config["MAIL_TO"]:
        missing.append("MAIL_TO")
    if missing:
        raise RuntimeError(f"Missing email environment variables: {', '.join(missing)}")
    return config


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_cache_date(window: int, market: str) -> str:
    path = ranking_cache_path(window, market)
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(f"Ranking cache not found for {market} window {window}: {path}")
    df = pd.read_csv(path, usecols=["as_of_date"], dtype={"as_of_date": str})
    dates = sorted({str(item) for item in df["as_of_date"].dropna().tolist() if str(item).strip()})
    if not dates:
        raise ValueError(f"Ranking cache has no as_of_date for {market} window {window}: {path}")
    return dates[-1]


def latest_brief_json(window: int, market: str, expected_date: str | None = None) -> Path:
    candidates = sorted(BRIEF_OUTPUT_DIR.glob(f"daily_brief_{market}_*_w{window}.json"))
    if not candidates:
        raise FileNotFoundError(f"No daily brief JSON found for market {market} window {window}: {BRIEF_OUTPUT_DIR}")

    matched: list[tuple[str, Path]] = []
    for path in candidates:
        try:
            brief = read_json(path)
        except json.JSONDecodeError:
            continue
        as_of_date = str(brief.get("as_of_date", "")).strip()
        if not as_of_date:
            continue
        if expected_date is None or as_of_date == expected_date:
            matched.append((as_of_date, path))

    if not matched:
        if expected_date:
            raise FileNotFoundError(
                f"No daily brief JSON found for market {market} window {window} at cache date {expected_date}."
            )
        raise FileNotFoundError(f"No valid daily brief JSON found for market {market} window {window}.")

    return sorted(matched, key=lambda item: (item[0], item[1].stat().st_mtime), reverse=True)[0][1]


def html_for_json(json_path: Path) -> Path:
    html_path = json_path.with_suffix(".html")
    if not html_path.exists():
        raise FileNotFoundError(f"HTML not found for {json_path.name}: {html_path}")
    return html_path


def report_url(public_base_url: str, html_path: Path) -> str:
    return f"{public_base_url.rstrip('/')}/{html_path.name}"


def discover_latest_reports(
    markets: list[str],
    window: int,
    validate_cache_date: bool = True,
) -> tuple[str, list[Path], list[dict[str, Any]]]:
    html_files: list[Path] = []
    briefs: list[dict[str, Any]] = []
    labels: list[str] = []

    for market in markets:
        expected_date = latest_cache_date(window, market) if validate_cache_date else None
        json_path = latest_brief_json(window, market, expected_date)
        brief = read_json(json_path)
        as_of_date = str(brief.get("as_of_date", "")).strip()
        if validate_cache_date and expected_date and as_of_date != expected_date:
            raise RuntimeError(
                f"{MARKET_LABELS.get(market, market)}日报日期 {as_of_date} "
                f"不是最新缓存日期 {expected_date}，请先重新生成日报。"
            )
        briefs.append(brief)
        html_files.append(html_for_json(json_path))
        labels.append(f"{brief.get('market_label') or MARKET_LABELS.get(market, market)} {as_of_date}")

    return " / ".join(labels), html_files, briefs


def brief_rows(briefs: list[dict[str, Any]], html_files: list[Path], public_base_url: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for brief, html_file in zip(briefs, html_files):
        benchmark = brief.get("benchmark") or {}
        market = str(brief.get("market") or "")
        rows.append(
            {
                "market_label": brief.get("market_label") or MARKET_LABELS.get(market, market),
                "as_of_date": brief.get("as_of_date"),
                "stable_count": len(brief.get("stable_top20", [])),
                "up_count": len(brief.get("upward_moves", [])),
                "down_count": len(brief.get("downward_moves", [])),
                "benchmark_label": brief.get("benchmark_label") or "基准",
                "benchmark_rank": benchmark.get("rank", "--"),
                "url": report_url(public_base_url, html_file),
            }
        )
    return rows


def build_text_body(as_of_label: str, rows: list[dict[str, Any]]) -> str:
    lines = [
        f"你好，今日的排名异常监测日报已生成：{as_of_label}。",
        "",
        "请点击下方链接查看 HTML 版日报：",
    ]
    for row in rows:
        lines.append(
            f"- {row['market_label']} {row['as_of_date']}：{row['url']} "
            f"（稳定前20 {row['stable_count']} 只，大幅上升 {row['up_count']} 只，"
            f"大幅下降 {row['down_count']} 只，{row['benchmark_label']} 排名 #{row['benchmark_rank']}）"
        )
    lines.extend(
        [
            "",
            "以上为量化排名日报自动发送，仅用于辅助观察，不构成投资建议。",
        ]
    )
    return "\n".join(lines)


def build_html_body(as_of_label: str, rows: list[dict[str, Any]]) -> str:
    items = []
    for row in rows:
        url = html.escape(str(row["url"]), quote=True)
        title = html.escape(f"{row['market_label']} {row['as_of_date']}")
        summary = html.escape(
            f"稳定前20 {row['stable_count']} 只，"
            f"大幅上升 {row['up_count']} 只，"
            f"大幅下降 {row['down_count']} 只，"
            f"{row['benchmark_label']} 排名 #{row['benchmark_rank']}"
        )
        items.append(
            f'<li style="margin:12px 0;">'
            f'<a href="{url}" style="font-weight:700;color:#1d4ed8;">{title}</a>'
            f'<div style="color:#475569;margin-top:4px;">{summary}</div>'
            f"</li>"
        )
    return f"""\
<!doctype html>
<html>
  <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;line-height:1.6;color:#0f172a;">
    <p>你好，今日的排名异常监测日报已生成：{html.escape(as_of_label)}。</p>
    <ul style="padding-left:20px;">{''.join(items)}</ul>
    <p style="color:#64748b;">以上为量化排名日报自动发送，仅用于辅助观察，不构成投资建议。</p>
  </body>
</html>
"""


def build_bodies(
    as_of_label: str,
    briefs: list[dict[str, Any]],
    html_files: list[Path],
    public_base_url: str,
) -> tuple[str, str]:
    rows = brief_rows(briefs, html_files, public_base_url)
    return build_text_body(as_of_label, rows), build_html_body(as_of_label, rows)


def send_email(
    config: dict[str, str],
    subject: str,
    text_body: str,
    html_body: str,
    html_files: list[Path],
    dry_run: bool = False,
) -> None:
    recipients = split_recipients(config["MAIL_TO"])
    if not recipients:
        raise RuntimeError("MAIL_TO has no valid recipients.")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config["MAIL_FROM"]
    message["To"] = ", ".join(recipients)
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    if dry_run:
        print("Dry run OK")
        print(f"Subject: {subject}")
        print(f"To: {', '.join(recipients)}")
        print("HTML links:")
        for html_file in html_files:
            print(f"- {report_url(config['PUBLIC_BASE_URL'], html_file)}")
        return

    host = config["SMTP_HOST"]
    port = int(config["SMTP_PORT"])
    if port == 465:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=context, timeout=60) as server:
            server.login(config["SMTP_USER"], config["SMTP_PASSWORD"])
            server.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=60) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
            server.login(config["SMTP_USER"], config["SMTP_PASSWORD"])
            server.send_message(message)
    print(f"Email sent to {', '.join(recipients)} with {len(html_files)} HTML link(s).")


def parse_markets(value: str) -> list[str]:
    markets = [item.strip().lower() for item in value.split(",") if item.strip()]
    invalid = [market for market in markets if market not in {"us", "cn", "hk"}]
    if invalid:
        raise ValueError(f"Unsupported markets: {invalid}. Only us, cn and hk are supported.")
    return markets or ["us", "cn", "hk"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send daily ranking brief email with HTML report links.")
    parser.add_argument("--window", type=int, default=10, choices=[10], help="Ranking window to send. Daily brief uses 10 only.")
    parser.add_argument("--markets", default="us,cn,hk", help="Comma-separated markets to send: us,cn,hk.")
    parser.add_argument("--to", default=None, help="Override recipients. Comma or semicolon separated.")
    parser.add_argument("--subject", default=None, help="Override email subject.")
    parser.add_argument("--public-base-url", default=None, help="Override public base URL for HTML report links.")
    parser.add_argument("--dry-run", action="store_true", help="Validate config and HTML links without sending.")
    parser.add_argument(
        "--no-cache-date-check",
        action="store_true",
        help="Use latest generated briefs without checking whether their dates match ranking caches.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    markets = parse_markets(args.markets)
    config = load_config(args.to)
    if args.public_base_url:
        config["PUBLIC_BASE_URL"] = args.public_base_url.strip()

    as_of_label, html_files, briefs = discover_latest_reports(
        markets,
        args.window,
        validate_cache_date=not args.no_cache_date_check,
    )
    subject = args.subject or f"排名异常监测日报 {as_of_label}"
    text_body, html_body = build_bodies(as_of_label, briefs, html_files, config["PUBLIC_BASE_URL"])
    send_email(config, subject, text_body, html_body, html_files, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
