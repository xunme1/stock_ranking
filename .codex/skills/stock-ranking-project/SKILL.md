---
name: stock-ranking-project
description: Use this skill when working on the stock_ranking / us_stock_data_project repository: Nasdaq-100 ATR ranking web app, Polygon daily-data download/update scripts, ranking cache, A-share peer mapping, daily HTML brief, sector cloud experiment, local/server runbooks, and context-recovery for future agents.
metadata:
  short-description: Work on the stock ranking web app
---

# Stock Ranking Project

Use this skill whenever the task touches this repository. It is both an onboarding guide for a new agent and a compact memory after context compression.

## Repository

Typical local root:

```text
E:\stock_ranking\us_stock_data_project
```

Server root used so far:

```text
/root/stock_ranking
```

The repo is a Nasdaq-100 relative-strength ranking web app. It downloads Polygon daily OHLCV data, computes ranking metrics, exposes a FastAPI backend, renders a Vite/React frontend, and has experiments for HTML daily briefs and sector treemaps.

## First Rules

- Do not revert unrelated dirty files. This repo often has local daily CSV changes and experimental outputs.
- Before committing, stage only the requested files and check `git diff --cached --name-only`.
- Backend data loaders use `lru_cache`; after changing CSV caches, restart the backend.
- Frontend dev server proxies `/api` to `http://127.0.0.1:8001` via `frontend/vite.config.ts`.
- If `git` reports `.git/index.lock`, check there is no running git process, then remove the stale lock with approval if needed.
- Never print or commit `.env` API keys.

## Project Structure

```text
backend/app/
  main.py                 FastAPI app, CORS, routers, /api/health
  api/rankings.py         /api/rankings/latest, /dates, /alerts
  api/stocks.py           /api/stocks/{ticker}/daily, /profile, /peers
  core/config.py          canonical project paths and constants
  services/data_loader.py CSV loaders and cached data access
  services/ranking_service.py ranking math, alert logic, cache handling

frontend/
  src/api.ts              typed API client
  src/App.tsx             main UI, ranking table, detail page, charts, cards
  src/styles.css          layout and visual styling
  vite.config.ts          dev proxy to backend

scripts/
  download_polygon_daily.py       initial Polygon daily download
  update_latest_daily.py          append latest US daily rows
  build_ranking_cache.py          cache recent 10/20-day rankings
  update_optionable_tickers.py    option availability cache
  update_a_share_universe.py      A-share market cap/change/industry cache
  build_a_share_peer_cache.py     curated CSV -> detail-page A-share peers
  update_company_profiles.py      Polygon company profile + Chinese summary
  update_earnings_calendar.py     Alpha Vantage earnings dates
  server_daily_update.sh          server daily data pipeline + API restart
  run_daily_brief_email.sh        generate HTML briefs and email report links

config/
  nasdaq100_tickers.txt           ranking universe
  stock_profiles.csv              broad stock type labels for homepage
  stock_subtypes.csv              fine detail-page type per US ticker
  us_a_share_peer_mapping.csv     curated US-to-A-share mapping source

data/
  raw/daily/{TICKER}.csv          Polygon daily OHLCV source of truth
  processed/rankings/*.csv        cached 10/20-day ranking history
  fundamental/*.csv               options, earnings, profiles, A-share peers

experiments/
  daily_brief/                    ranking anomaly brief JSON/HTML + LLM text
  sector_cloud/                   standalone sector treemap HTML
```

## Core Ranking Logic

Ranking metric lives in `backend/app/services/ranking_service.py`.

- `window=10` or `20` is the moving-average-center window exposed in the UI.
- For `window=10`, ATR uses 20 days by design: `atr_window_for_ranking(10) -> 20`.
- Score is the latest close versus the moving-average center, divided by ATR.
- QQQ is the default benchmark.
- Cached ranking files are `data/processed/rankings/ranking_window_10.csv` and `ranking_window_20.csv`.
- Ranking alert card uses cached recent ranks: stable top 20, large upward/downward moves, entered top 20, dropped top 20.

## A-Share Peer Mapping

Detail page A-share peers are no longer fuzzy matched. The current canonical path is:

```text
config/us_a_share_peer_mapping.csv
  -> scripts/build_a_share_peer_cache.py
  -> config/stock_subtypes.csv
  -> data/fundamental/a_share_subtype_leaders.csv
  -> /api/stocks/{ticker}/peers
  -> StockPeersCard in frontend/src/App.tsx
```

The mapping CSV is semicolon-separated and may be GBK/GB18030 encoded. The builder auto-detects common encodings.

If frontend still shows old peer data after rebuilding caches, restart backend because loader caches are process-local.

## Read More When Needed

- Function signatures and usage notes: `references/functions.md`
- Local and server runbooks, commands, env vars, cron/systemd/nginx notes: `references/operations.md`

## Common Commands

Local backend:

```powershell
cd E:\stock_ranking\us_stock_data_project
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload --app-dir backend
```

Local frontend:

```powershell
cd E:\stock_ranking\us_stock_data_project\frontend
npm run dev
```

Build frontend:

```powershell
cd E:\stock_ranking\us_stock_data_project\frontend
npm run build
```

Update ranking stock pool data only:

```powershell
.\.venv\Scripts\python.exe -B scripts\update_latest_daily.py --tickers "$(Get-Content config\nasdaq100_tickers.txt | Where-Object { $_ -and -not $_.StartsWith('#') } | Join-String -Separator ',')",QQQ --download-missing --max-retries 2
.\.venv\Scripts\python.exe -B scripts\build_ranking_cache.py --windows 10,20 --days 20
```

Rebuild A-share peer cache:

```powershell
.\.venv\Scripts\python.exe -B scripts\update_a_share_universe.py --source hybrid --spot-source akshare --retries 2 --retry-wait-seconds 10
.\.venv\Scripts\python.exe -B scripts\build_a_share_peer_cache.py
```

Generate 10-day daily brief HTML:

```powershell
.\.venv\Scripts\python.exe -B experiments\daily_brief\generate_brief_data.py --window 10
.\.venv\Scripts\python.exe -B experiments\daily_brief\render_html.py --input experiments\daily_brief\output\daily_brief_YYYY-MM-DD_w10.json
```

## Verification Checklist

- `GET http://127.0.0.1:8001/api/health` returns `{"status":"ok"}`.
- `GET /api/rankings/latest?window=10&benchmark=QQQ&apply_announced_rebalance=true` returns data.
- `GET /api/stocks/MU/peers` returns `source: "csv_mapping"` and A-share peers from `config/us_a_share_peer_mapping.csv`.
- `npm run build` passes after frontend edits.
- If HTML daily-brief layout changes, render the HTML and inspect output visually.
