from __future__ import annotations

import argparse
import json
import mimetypes
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BRIEF_OUTPUT_DIR = PROJECT_ROOT / "experiments" / "daily_brief" / "output"


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


def latest_brief_json(window: int) -> Path:
    candidates = sorted(
        BRIEF_OUTPUT_DIR.glob(f"daily_brief_*_w{window}.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"No daily brief JSON found for window {window}: {BRIEF_OUTPUT_DIR}")
    return candidates[0]


def pdf_for_json(json_path: Path) -> Path:
    pdf_path = json_path.with_suffix(".pdf")
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found for {json_path.name}: {pdf_path}")
    return pdf_path


def discover_latest_reports(windows: list[int]) -> tuple[str, list[Path], list[dict[str, Any]]]:
    attachments: list[Path] = []
    briefs: list[dict[str, Any]] = []
    dates: list[str] = []
    for window in windows:
        json_path = latest_brief_json(window)
        brief = read_json(json_path)
        dates.append(str(brief.get("as_of_date", "")))
        briefs.append(brief)
        attachments.append(pdf_for_json(json_path))
    as_of_date = max([date for date in dates if date], default="latest")
    return as_of_date, attachments, briefs


def build_body(as_of_date: str, briefs: list[dict[str, Any]]) -> str:
    lines = [
        f"你好，附件是 {as_of_date} 的纳指排名异常监测日报。",
        "",
        "本次包含：",
    ]
    for brief in briefs:
        benchmark = brief.get("benchmark") or {}
        lines.append(
            f"- {brief.get('window')}日窗口：稳定前20 {len(brief.get('stable_top20', []))} 只，"
            f"大幅上升 {len(brief.get('upward_moves', []))} 只，"
            f"大幅下降 {len(brief.get('downward_moves', []))} 只，"
            f"QQQ 排名 #{benchmark.get('rank', '--')}。"
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


def parse_windows(value: str) -> list[int]:
    windows = [int(item.strip()) for item in value.split(",") if item.strip()]
    invalid = [window for window in windows if window not in {10, 20}]
    if invalid:
        raise ValueError(f"Unsupported windows: {invalid}. Only 10 and 20 are supported.")
    return windows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send daily ranking brief PDF email.")
    parser.add_argument("--windows", default="10,20", help="Comma-separated ranking windows to attach.")
    parser.add_argument("--to", default=None, help="Override recipients. Comma or semicolon separated.")
    parser.add_argument("--subject", default=None, help="Override email subject.")
    parser.add_argument("--dry-run", action="store_true", help="Validate config and attachments without sending.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    windows = parse_windows(args.windows)
    config = load_config(args.to)
    as_of_date, attachments, briefs = discover_latest_reports(windows)
    subject = args.subject or f"纳指排名异常监测日报 {as_of_date}"
    body = build_body(as_of_date, briefs)
    send_email(config, subject, body, attachments, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
