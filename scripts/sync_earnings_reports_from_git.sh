#!/usr/bin/env bash
set -euo pipefail

# Fetch only the dedicated report branch, then replace the report archive as one staged update.
PROJECT_ROOT="${PROJECT_ROOT:-/root/stock_ranking}"
BRANCH="${EARNINGS_REPORTS_BRANCH:-earnings-reports}"
REMOTE="${EARNINGS_REPORTS_REMOTE:-origin}"
REPORT_DIR="$PROJECT_ROOT/data/processed/earnings_sentiment_reports"
PARENT_DIR="$(dirname "$REPORT_DIR")"
TMP_BASE="$PROJECT_ROOT/.tmp"
mkdir -p "$TMP_BASE" "$PARENT_DIR"
WORK_DIR="$(mktemp -d "$TMP_BASE/earnings-reports-sync.XXXXXX")"
STAGING_DIR="$PARENT_DIR/.earnings_sentiment_reports.staging.$$"
BACKUP_DIR="$PARENT_DIR/.earnings_sentiment_reports.backup.$$"

cleanup() {
  rm -rf "$WORK_DIR" "$STAGING_DIR"
  if [[ -d "$BACKUP_DIR" && ! -d "$REPORT_DIR" ]]; then
    mv "$BACKUP_DIR" "$REPORT_DIR"
  fi
}
trap cleanup EXIT

cd "$PROJECT_ROOT"
rm -rf "$STAGING_DIR"

echo "Fetching $REMOTE/$BRANCH..."
git fetch "$REMOTE" "$BRANCH"
git cat-file -e "FETCH_HEAD:reports" || {
  echo "ERROR: $BRANCH does not contain the reports/ directory." >&2
  exit 1
}

git archive --format=tar FETCH_HEAD reports | tar -xf - -C "$WORK_DIR"
mkdir -p "$STAGING_DIR"
cp -a "$WORK_DIR/reports/." "$STAGING_DIR/"

if [[ -d "$REPORT_DIR" ]]; then
  rm -rf "$BACKUP_DIR"
  mv "$REPORT_DIR" "$BACKUP_DIR"
fi
mv "$STAGING_DIR" "$REPORT_DIR"
rm -rf "$BACKUP_DIR"
echo "Synchronized earnings report archive to $REPORT_DIR"
