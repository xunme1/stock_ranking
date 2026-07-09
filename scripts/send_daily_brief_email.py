from __future__ import annotations

import argparse
import json
import mimetypes
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
    required = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "MAIL_FROM"]
    config = {key: os.getenv(key, "").strip() for key in required}
    config["MAIL_TO"] = (cli_to or os.getenv("MAIL_TO", "")).strip()
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


def pdf_for_json(json_path: Path) -> Path:
    pdf_path = json_path.with_suffix(".pdf")
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found for {json_path.name}: {pdf_path}")
    return pdf_path


def discover_latest_reports(
    markets: list[str],
    window: int,
    validate_cache_date: bool = True,
) -> tuple[str, list[Path], list[dict[str, Any]]]:
    attachments: list[Path] = []
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
                f"不是最新缓存日期 {expected_date}。请先重新生成日报。"
            )
        briefs.append(brief)
        attachments.append(pdf_for_json(json_path))
        labels.append(f"{brief.get('market_label') or MARKET_LABELS.get(market, market)} {as_of_date}")

    return " / ".join(labels), attachments, briefs


def build_body(as_of_label: str, briefs: list[dict[str, Any]]) -> str:
    lines = [
        f"你好，附件是排名异常监测日报：{as_of_label}。",
        "",
        "本次包含美股、A股、港股三份 10 日窗口日报。各市场按自己的最新缓存日期独立生成：",
    ]
    for brief in briefs:
        benchmark = brief.get("benchmark") or {}
        market_label = brief.get("market_label") or brief.get("market") or ""
        benchmark_label = brief.get("benchmark_label") or "基准"
        lines.append(
            f"- {market_label} {brief.get('as_of_date')}：稳定前20 {len(brief.get('stable_top20', []))} 只，"
            f"大幅上升 {len(brief.get('upward_moves', []))} 只，"
            f"大幅下降 {len(brief.get('downward_moves', []))} 只，"
            f"{benchmark_label} 排名 #{benchmark.get('rank', '--')}。"
        )
    lines.extend(
        [
            "",
            "以上为量化排名日报自动发送，仅用于辅助观察，不构成投资建议。",
        ]
    )
    return "\n".join(lines)


def attach_file(message: EmailMessage, path: Path) -> None:
    content_type, _ = mimetypes.guess_type(path.name)
    maintype, subtype = (content_type or "application/octet-stream").split("/", 1)
    message.add_attachment(
        path.read_bytes(),
        maintype=maintype,
        subtype=subtype,
        filename=path.name,
    )


def send_email(
    config: dict[str, str],
    subject: str,
    body: str,
    attachments: list[Path],
    dry_run: bool = False,
) -> None:
    recipients = split_recipients(config["MAIL_TO"])
    if not recipients:
        raise RuntimeError("MAIL_TO has no valid recipients.")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config["MAIL_FROM"]
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    for attachment in attachments:
        attach_file(message, attachment)

    if dry_run:
        print("Dry run OK")
        print(f"Subject: {subject}")
        print(f"To: {', '.join(recipients)}")
        print("Attachments:")
        for attachment in attachments:
            print(f"- {attachment}")
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
    print(f"Email sent to {', '.join(recipients)} with {len(attachments)} attachment(s).")


def parse_markets(value: str) -> list[str]:
    markets = [item.strip().lower() for item in value.split(",") if item.strip()]
    invalid = [market for market in markets if market not in {"us", "cn", "hk"}]
    if invalid:
        raise ValueError(f"Unsupported markets: {invalid}. Only us, cn and hk are supported.")
    return markets or ["us", "cn", "hk"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send daily ranking brief PDF email.")
    parser.add_argument("--window", type=int, default=10, choices=[10], help="Ranking window to attach. Daily brief uses 10 only.")
    parser.add_argument("--markets", default="us,cn,hk", help="Comma-separated markets to attach: us,cn,hk.")
    parser.add_argument("--to", default=None, help="Override recipients. Comma or semicolon separated.")
    parser.add_argument("--subject", default=None, help="Override email subject.")
    parser.add_argument("--dry-run", action="store_true", help="Validate config and attachments without sending.")
    parser.add_argument(
        "--no-cache-date-check",
        action="store_true",
        help="Attach latest generated briefs without checking whether their dates match ranking caches.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    markets = parse_markets(args.markets)
    config = load_config(args.to)
    as_of_label, attachments, briefs = discover_latest_reports(
        markets,
        args.window,
        validate_cache_date=not args.no_cache_date_check,
    )
    subject = args.subject or f"排名异常监测日报 {as_of_label}"
    body = build_body(as_of_label, briefs)
    send_email(config, subject, body, attachments, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
