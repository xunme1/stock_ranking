#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/root/stock_ranking}"
SERVICE_NAME="${SERVICE_NAME:-stock-ranking-api}"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
END_DATE="${END_DATE:-$(date -d 'yesterday' +%F)}"
LOG_DIR="$PROJECT_ROOT/logs"
RUN_LOG="$LOG_DIR/server_daily_update.log"

mkdir -p "$LOG_DIR"

cd "$PROJECT_ROOT"

{
  echo "============================================================"
  echo "Daily update started at $(date '+%F %T %Z')"
  echo "Project root: $PROJECT_ROOT"
  echo "End date: $END_DATE"

  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "ERROR: Python not found or not executable: $PYTHON_BIN"
    exit 1
  fi

  if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    echo "WARNING: .env not found at $PROJECT_ROOT/.env. Polygon/Alpha keys must be configured on the server."
  fi

  TICKERS="$(grep -v '^[[:space:]]*#' config/nasdaq100_tickers.txt | sed '/^[[:space:]]*$/d' | tr '\n' ','),QQQ"

  echo "Updating daily bars..."
  "$PYTHON_BIN" -B scripts/update_latest_daily.py \
    --tickers "$TICKERS" \
    --end-date "$END_DATE" \
    --download-missing \
    --max-retries 2

  echo "Rebuilding ranking cache..."
  "$PYTHON_BIN" -B scripts/build_ranking_cache.py --windows 10,20 --days 20

  echo "Restarting API service: $SERVICE_NAME"
  if command -v systemctl >/dev/null 2>&1; then
    systemctl restart "$SERVICE_NAME"
    systemctl --no-pager --lines=8 status "$SERVICE_NAME" || true
  else
    echo "WARNING: systemctl not found. Please restart the API service manually."
  fi

  echo "Checking API health..."
  if command -v curl >/dev/null 2>&1; then
    curl -fsS http://127.0.0.1:8001/api/health || true
    echo
  fi

  echo "Daily update finished at $(date '+%F %T %Z')"
} 2>&1 | tee -a "$RUN_LOG"

