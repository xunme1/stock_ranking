from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote


def file_url(path: Path) -> str:
    resolved = path.resolve()
    return "file:///" + quote(str(resolved).replace("\\", "/"), safe="/:")


def find_browser() -> str | None:
    candidates = [
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("google-chrome"),
        shutil.which("chrome"),
        shutil.which("msedge"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


def render_with_playwright(html_path: Path, pdf_path: Path) -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1120, "height": 1600})
        page.goto(file_url(html_path), wait_until="networkidle")
        page.pdf(
            path=str(pdf_path),
            format="A4",
            landscape=True,
            print_background=True,
            margin={"top": "10mm", "right": "10mm", "bottom": "10mm", "left": "10mm"},
        )
        browser.close()
    return True


def render_with_browser(html_path: Path, pdf_path: Path) -> None:
    browser = find_browser()
    if not browser:
        raise RuntimeError(
            "No Chromium-compatible browser found. Install Playwright or Chrome/Edge to export HTML reports to PDF."
        )

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_root = Path(__file__).resolve().parents[2] / ".tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    user_data_dir = tempfile.mkdtemp(prefix="daily-brief-browser-", dir=str(tmp_root))
    command = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-pdf-header-footer",
        "--print-to-pdf-no-header",
        f"--user-data-dir={user_data_dir}",
        f"--print-to-pdf={pdf_path.resolve()}",
        file_url(html_path),
    ]
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )
    if result.returncode != 0:
        command[1] = "--headless"
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
    if result.returncode != 0:
        raise RuntimeError(
            "Browser PDF export failed.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a daily brief HTML file to PDF.")
    parser.add_argument("--input", required=True, help="Input HTML path.")
    parser.add_argument("--output", default=None, help="Output PDF path. Defaults to the input path with .pdf suffix.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    html_path = Path(args.input)
    if not html_path.exists():
        raise FileNotFoundError(f"HTML input not found: {html_path}")
    pdf_path = Path(args.output) if args.output else html_path.with_suffix(".pdf")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    if not render_with_playwright(html_path, pdf_path):
        render_with_browser(html_path, pdf_path)

    print(f"PDF written: {pdf_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
