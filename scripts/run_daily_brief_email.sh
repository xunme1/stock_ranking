#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/root/stock_ranking}"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
WINDOWS="${WINDOWS:-10,20}"
USE_LLM="${USE_LLM:-1}"
LLM_MODEL="${LLM_MODEL:-qwen3.7-plus}"
LLM_TIMEOUT="${LLM_TIMEOUT:-180}"
LLM_MAX_TOKENS="${LLM_MAX_TOKENS:-1500}"
MAIL_TO_OVERRIDE="${MAIL_TO_OVERRIDE:-}"
DRY_RUN="${DRY_RUN:-0}"
LOG_DIR="$PROJECT_ROOT/logs"
RUN_LOG="$LOG_DIR/daily_brief_email.log"

mkdir -p "$LOG_DIR"
cd "$PROJECT_ROOT"

IFS=',' read -r -a WINDOW_LIST <<< "$WINDOWS"

{
  echo "============================================================"
  echo "Daily brief pipeline started at $(date '+%F %T %Z')"
  echo "Project root: $PROJECT_ROOT"
  echo "Windows: $WINDOWS"
  echo "Use LLM: $USE_LLM"

  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "ERROR: Python not found or not executable: $PYTHON_BIN"
    exit 1
  fi

  for WINDOW in "${WINDOW_LIST[@]}"; do
    WINDOW="$(echo "$WINDOW" | xargs)"
    if [[ "$WINDOW" != "10" && "$WINDOW" != "20" ]]; then
      echo "ERROR: Unsupported window: $WINDOW"
      exit 1
    fi

    echo "Generating daily brief data for ${WINDOW}-day window..."
    GENERATE_ARGS=(
      -B experiments/daily_brief/generate_brief_data.py
      --window "$WINDOW"
    )
    if [[ "$USE_LLM" == "1" ]]; then
      GENERATE_ARGS+=(
        --use-llm
        --llm-model "$LLM_MODEL"
        --llm-timeout "$LLM_TIMEOUT"
        --llm-max-tokens "$LLM_MAX_TOKENS"
      )
    fi
    "$PYTHON_BIN" "${GENERATE_ARGS[@]}"

    JSON_FILE="$(ls -t experiments/daily_brief/output/daily_brief_*_w${WINDOW}.json | head -1)"
    echo "Rendering PDF: $JSON_FILE"
    "$PYTHON_BIN" -B experiments/daily_brief/render_pdf.py --input "$JSON_FILE"
  done

  echo "Sending daily brief email..."
  SEND_ARGS=(
    -B scripts/send_daily_brief_email.py
    --windows "$WINDOWS"
  )
  if [[ -n "$MAIL_TO_OVERRIDE" ]]; then
    SEND_ARGS+=(--to "$MAIL_TO_OVERRIDE")
  fi
  if [[ "$DRY_RUN" == "1" ]]; then
    SEND_ARGS+=(--dry-run)
  fi
  "$PYTHON_BIN" "${SEND_ARGS[@]}"

  echo "Daily brief pipeline finished at $(date '+%F %T %Z')"
} 2>&1 | tee -a "$RUN_LOG"
