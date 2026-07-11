#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/root/stock_ranking}"
SERVICE_NAME="${SERVICE_NAME:-stock-ranking-api}"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
END_DATE="${END_DATE:-$(date +%F)}"
LOG_DIR="$PROJECT_ROOT/logs"
RUN_LOG="$LOG_DIR/server_update_hk.log"

mkdir -p "$LOG_DIR"
cd "$PROJECT_ROOT"

{
  echo "============================================================"
  echo "Hong Kong daily update started at $(date '+%F %T %Z')"
  echo "Project root: $PROJECT_ROOT"
  echo "End date: $END_DATE"

  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "ERROR: Python not found or not executable: $PYTHON_BIN"
    exit 1
  fi

  "$PYTHON_BIN" -B scripts/update_asia_daily_and_cache.py \
    --source ths \
    --markets hk \
    --end-date "$END_DATE" \
    --windows 10,20 \
    --cache-days 20 \
    --sleep-seconds 0 \
    --require-end-date

  echo "Restarting API service: $SERVICE_NAME"
  if command -v systemctl >/dev/null 2>&1; then
    systemctl restart "$SERVICE_NAME"
    systemctl --no-pager --lines=8 status "$SERVICE_NAME" || true
  else
    echo "WARNING: systemctl not found. Please restart the API service manually."
  fi

  echo "Hong Kong daily update finished at $(date '+%F %T %Z')"
} 2>&1 | tee -a "$RUN_LOG"
