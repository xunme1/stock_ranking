from __future__ import annotations

"""Publish a validated report to the isolated earnings-reports Git branch."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def report_paths(report_dir: Path, report_date: str) -> tuple[Path, Path]:
    stem = f"earnings_sentiment_{report_date}"
    json_path = report_dir / f"{stem}.json"
    html_path = report_dir / f"{stem}.html"
    for path in (json_path, html_path):
        if not path.is_file():
            raise FileNotFoundError(f"Validated report file is missing: {path}")
    return json_path, html_path


def clone_source_for(remote: str) -> str:
    """Resolve a local remote name (normally origin) before cloning outside this repo."""
    result = subprocess.run(
        ["git", "remote", "get-url", remote],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip() if result.returncode == 0 else remote


def publish(
    report_dir: Path,
    report_date: str,
    remote: str,
    branch: str,
    clone_dir: Path,
    dry_run: bool,
) -> None:
    json_path, html_path = report_paths(report_dir, report_date)
    if dry_run:
        print(f"Dry run validated {json_path.name} and {html_path.name}; no Git clone, commit, or push was made.")
        return
    if clone_dir.exists():
        if not (clone_dir / ".git").exists():
            raise RuntimeError(f"Refusing to use non-Git publish directory: {clone_dir}")
        run(["git", "fetch", remote, branch], clone_dir)
        run(["git", "checkout", branch], clone_dir)
        run(["git", "pull", "--ff-only", remote, branch], clone_dir)
    else:
        clone_dir.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--branch", branch, "--single-branch", clone_source_for(remote), str(clone_dir)])

    destination = clone_dir / "reports"
    destination.mkdir(parents=True, exist_ok=True)
    for source in (json_path, html_path):
        target = destination / source.name
        print(f"Copy {source} -> {target}")
        shutil.copy2(source, target)

    paths = [f"reports/{json_path.name}", f"reports/{html_path.name}"]
    run(["git", "add", "--", *paths], clone_dir)
    changed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=clone_dir).returncode != 0
    if not changed:
        print("No report changes to publish.")
        return
    run(["git", "commit", "-m", f"data: publish earnings report {report_date}"], clone_dir)
    run(["git", "push", remote, branch], clone_dir)
    print(f"Published {report_date} to {remote}/{branch}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish a rendered report through the earnings-reports Git branch.")
    parser.add_argument("--report-dir", required=True, help="Directory containing validated JSON and HTML")
    parser.add_argument("--report-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--remote", default="origin", help="Git remote name or URL")
    parser.add_argument("--branch", default="earnings-reports")
    parser.add_argument(
        "--clone-dir",
        default=str(ROOT_DIR / ".tmp" / "earnings-reports-publish"),
        help="Dedicated clone used only for the reports branch",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        publish(
            Path(args.report_dir).resolve(),
            args.report_date,
            args.remote,
            args.branch,
            Path(args.clone_dir).resolve(),
            args.dry_run,
        )
    except (FileNotFoundError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Publish failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
