#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/root/stock_ranking}"
SERVICE_NAME="${SERVICE_NAME:-stock-ranking-api}"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
LOOKBACK_DAYS="${LOOKBACK_DAYS:-10}"
END_DATE="${END_DATE:-$(date +%F)}"
START_DATE="${START_DATE:-$(date -d "$LOOKBACK_DAYS days ago" +%F)}"
LOG_DIR="$PROJECT_ROOT/logs"
RUN_LOG="$LOG_DIR/server_industry_fund_flow_update.log"

mkdir -p "$LOG_DIR" "$PROJECT_ROOT/data/raw/industry_fund_flow" "$PROJECT_ROOT/data/processed"

cd "$PROJECT_ROOT"

{
  echo "============================================================"
  echo "Industry fund-flow update started at $(date '+%F %T %Z')"
  echo "Project root: $PROJECT_ROOT"
  echo "Date range: $START_DATE to $END_DATE"
  echo "Markets: us,cn,hk"

  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "ERROR: Python not found or not executable: $PYTHON_BIN"
    exit 1
  fi

  if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    echo "WARNING: .env not found at $PROJECT_ROOT/.env. THS_IFIND_USERNAME and THS_IFIND_PASSWORD must be configured."
  fi

  "$PYTHON_BIN" -B scripts/industry_fund_flow.py \
    --fetch \
    --start-date "$START_DATE" \
    --end-date "$END_DATE" \
    --markets us,cn,hk

  echo "Restarting API service: $SERVICE_NAME"
  if command -v systemctl >/dev/null 2>&1; then
    systemctl restart "$SERVICE_NAME"
    systemctl --no-pager --lines=8 status "$SERVICE_NAME" || true
  else
    echo "WARNING: systemctl not found. Please restart the API service manually."
  fi

  echo "Checking industry fund-flow APIs..."
  if command -v curl >/dev/null 2>&1; then
    for market in us cn hk; do
      curl -fsS "http://127.0.0.1:8001/api/industry-flows/rankings?market=$market&limit=1" >/dev/null
      echo "API check passed: $market"
    done
  fi

  echo "Industry fund-flow update finished at $(date '+%F %T %Z')"
} 2>&1 | tee -a "$RUN_LOG"
