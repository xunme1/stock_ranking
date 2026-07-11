#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/root/stock_ranking}"
SERVICE_NAME="${SERVICE_NAME:-stock-ranking-api}"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
END_DATE="${END_DATE:-$(date -d 'yesterday' +%F)}"
LOG_DIR="$PROJECT_ROOT/logs"
RUN_LOG="$LOG_DIR/server_update_us.log"

mkdir -p "$LOG_DIR"
cd "$PROJECT_ROOT"

{
  echo "============================================================"
  echo "US daily update started at $(date '+%F %T %Z')"
  echo "Project root: $PROJECT_ROOT"
  echo "End date: $END_DATE"

  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "ERROR: Python not found or not executable: $PYTHON_BIN"
    exit 1
  fi

  TICKERS="$(grep -v '^[[:space:]]*#' config/nasdaq100_tickers.txt | sed '/^[[:space:]]*$/d' | tr '\n' ','),QQQ"

  echo "Updating US daily bars from iFinD..."
  "$PYTHON_BIN" -B scripts/update_latest_daily.py \
    --source ths \
    --tickers "$TICKERS" \
    --end-date "$END_DATE" \
    --download-missing \
    --max-retries 2

  echo "Updating option availability..."
  "$PYTHON_BIN" -B scripts/update_optionable_tickers.py --max-retries 2 || {
    echo "WARNING: option availability update failed. Ranking cache will use the previous option cache if available."
  }

  echo "Updating A-share market cap and industry cache..."
  "$PYTHON_BIN" -B scripts/update_a_share_universe.py --source hybrid --retries 2 --retry-wait-seconds 10 || {
    echo "WARNING: A-share universe update failed. A-share peer cards will use the previous cache if available."
  }

  echo "Rebuilding mapped US/A-share peer cache..."
  "$PYTHON_BIN" -B scripts/build_a_share_peer_cache.py || {
    echo "WARNING: mapped US/A-share peer cache rebuild failed. Detail pages will use the previous peer cache if available."
  }

  echo "Rebuilding US ranking cache..."
  "$PYTHON_BIN" -B scripts/build_ranking_cache.py --windows 10,20 --days 20 --end-date "$END_DATE"

  echo "Restarting API service: $SERVICE_NAME"
  if command -v systemctl >/dev/null 2>&1; then
    systemctl restart "$SERVICE_NAME"
    systemctl --no-pager --lines=8 status "$SERVICE_NAME" || true
  else
    echo "WARNING: systemctl not found. Please restart the API service manually."
  fi

  echo "US daily update finished at $(date '+%F %T %Z')"
} 2>&1 | tee -a "$RUN_LOG"
