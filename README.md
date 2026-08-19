# Stock Ranking Project

This project is a multi-market relative-strength ranking web app. It maintains local daily OHLCV CSV caches, computes ATR-normalized rankings, serves them through a FastAPI backend, and renders a Vite/React frontend.

The current primary daily-bar source is Tonghuashun iFinD. Polygon remains in the repo for US ticker-pool, option-availability, and company-profile helper scripts where those APIs are still used.

## Project Structure

```text
backend/app/
  main.py                         FastAPI app, CORS, routers, /api/health
  api/rankings.py                 /api/rankings/latest, /dates, /alerts
  api/stocks.py                   /api/stocks/{ticker}/daily, /profile, /peers
  services/data_loader.py         CSV loaders and cached data access
  services/ranking_service.py     ATR ranking math, alert logic, cache handling

frontend/
  src/App.tsx                     Main React UI, rankings, alerts, detail charts
  src/api.ts                      Typed API client
  vite.config.ts                  Dev proxy to http://127.0.0.1:8001

scripts/
  ths_ifind_daily.py              iFinD login, ticker mapping, daily-bar adapter
  download_ths_daily.py           Initial iFinD daily-bar download
  update_latest_daily.py          US daily update, default source: iFinD
  update_cn_daily.py              A-share daily update, default source: iFinD
  update_hk_daily.py              Hong Kong daily update, default source: iFinD
  update_asia_daily_and_cache.py  CN/HK daily update plus ranking cache rebuild
  build_ranking_cache.py          Cache recent 10/20-day ranking histories
  server_daily_update.sh          Server daily pipeline and API restart

data/
  raw/daily/{TICKER}.csv          US daily OHLCV
  raw/cn_daily/{TICKER}.csv       A-share daily OHLCV
  raw/hk_daily/{TICKER}.csv       Hong Kong daily OHLCV
  processed/rankings/*.csv        Cached ranking histories
  fundamental/*.csv               Options, earnings, profiles, A-share peers
```

## Environment

Create the Python environment and install normal Python dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Install the official Tonghuashun iFinD SDK separately; it is not available from PyPI. Run the SDK's `installiFinDPy.py` with this project's virtual environment.

Project root `.env` should include:

```env
THS_IFIND_USERNAME=your_ifind_api_username
THS_IFIND_PASSWORD=your_ifind_api_password

POLYGON_API_KEY_1=optional_polygon_key
ALPHA_VANTAGE_API_KEY=optional_alpha_vantage_key
TUSHARE_TOKEN=optional_tushare_token
```

Never commit `.env`.

## Daily Data

The local CSV schema consumed by the backend is:

```text
ticker,date,open,high,low,close,volume,vwap,transactions
```

CN/HK files may also include `turnover`; backend loaders ignore extra columns.

Download an initial daily history with iFinD:

```powershell
.\.venv\Scripts\python.exe -B scripts\download_ths_daily.py --market us --include-benchmark
.\.venv\Scripts\python.exe -B scripts\download_ths_daily.py --market cn --include-benchmark
.\.venv\Scripts\python.exe -B scripts\download_ths_daily.py --market hk --include-benchmark
```

Run incremental updates:

```powershell
.\.venv\Scripts\python.exe -B scripts\update_latest_daily.py --source ths --download-missing
.\.venv\Scripts\python.exe -B scripts\update_cn_daily.py --source ths
.\.venv\Scripts\python.exe -B scripts\update_hk_daily.py --source ths
```

## Maintain CN/HK Stock Pools

The normalized pool files consumed by the application are `config/cn_stock_pool.csv` and `config/hk_stock_pool.csv`. Add or update a single ticker with the helper script; it normalizes market suffixes and updates an existing ticker in place rather than adding a duplicate.

```powershell
.\.venv\Scripts\python.exe -B scripts\add_stock_to_pool.py --market cn --ticker 002432.SZ --name 九安医疗 --sector 医疗健康 --stock-type 医疗器械/体外诊断
.\.venv\Scripts\python.exe -B scripts\add_stock_to_pool.py --market hk --ticker 0020.HK --name "商汤 - W" --sector 人工智能 --stock-type 视觉AI平台 --is-hstech Y --source-url "https://example.com/reference"
```

Use `--dry-run` to verify the normalized ticker and resulting row before writing. After adding a ticker, download its daily history and rebuild that market's ranking cache.

Update CN/HK daily bars and rebuild CN/HK ranking caches:

```powershell
.\.venv\Scripts\python.exe -B scripts\update_asia_daily_and_cache.py --source ths
```

Fallback sources remain available:

```powershell
.\.venv\Scripts\python.exe -B scripts\update_latest_daily.py --source polygon
.\.venv\Scripts\python.exe -B scripts\update_cn_daily.py --source akshare
.\.venv\Scripts\python.exe -B scripts\update_hk_daily.py --source akshare
```

## Ranking Logic

- Supported markets: `us`, `cn`, `hk`.
- Default benchmarks: `QQQ`, `000905`, `HSTECH`.
- UI ranking windows: `10` and `20`.
- For `window=10`, ATR uses 20 days by design.
- Ranking score is latest close versus the moving-average center, divided by ATR.
- Cached ranking files live in `data/processed/rankings/`.

Build ranking caches:

```powershell
.\.venv\Scripts\python.exe -B scripts\build_ranking_cache.py --market us --windows 10,20 --days 20
.\.venv\Scripts\python.exe -B scripts\build_ranking_cache.py --market cn --windows 10,20 --days 20
.\.venv\Scripts\python.exe -B scripts\build_ranking_cache.py --market hk --windows 10,20 --days 20
```

## Corporate-Action News Monitoring

The backend includes a first-stage event-centric news collector for buybacks and shareholder reductions in the US, A-share, and Hong Kong markets. It searches broadly first, stores both pool and non-pool companies, then marks matching pool tickers as `high` attention. It does not change daily-brief output yet.

Tavily keys are read from `TAVILY_API_KEY1`, `TAVILY_API_KEY2`, and so on (with legacy `TAVILY_API_KEYS` / `TAVILY_API_KEY` support) and are used in round-robin order. A request that receives an authentication or rate-limit error falls through to the remaining keys.

For A-share and Hong Kong tasks, the collector also searches the public Tiger Community feed for `回购` and `减持`. Its `gmtCreate` timestamp is used as the publication date, then the same DeepSeek extraction, stock-pool matching, and canonical-link de-duplication pipeline is applied. Structured extraction defaults to `deepseek-v4-flash` in non-thinking JSON mode; set `DEEPSEEK_MODEL` only when an intentional override is required.

Run a non-writing quality check:

```powershell
.\.venv\Scripts\python.exe -B scripts\update_corporate_action_news.py --markets us,cn,hk --lookback-days 30 --dry-run
```

Write collected events to `data/processed/corporate_action_news.db`:

```powershell
.\.venv\Scripts\python.exe -B scripts\update_corporate_action_news.py --markets us,cn,hk --lookback-days 30
```

Each market is executed as an isolated task: a failed market is recorded without stopping the other two. Storage first canonicalizes the source link (removing common tracking parameters) and de-duplicates the same market/company/event/link combination; one article that names several companies remains as separate company events. The command prints compact per-market summaries by default; add `--include-events` to print every structured event.

Reapply stock-pool flags without new searches:

```powershell
.\.venv\Scripts\python.exe -B scripts\update_corporate_action_news.py --rematch-only
```

Read cached data through `GET /api/corporate-actions/news?market=us` and inspect market freshness through `GET /api/corporate-actions/status`.
The web UI is available at `/corporate-actions?market=us|cn|hk`; the dashboard entry follows the currently selected market.

### OSS agent-batch import

External agents can upload immutable UTF-8 JSONL files below `corporate-actions/v1/incoming/`, for example `corporate-actions/v1/incoming/cn/dt=2026-08-19/agent-a/batch.jsonl`. Each non-empty line must use `schema_version: "corporate-action-candidate/v1"` and include `market`, `event_type` (`buyback` or `reduction`), `headline`, `published_at` (`YYYY-MM-DD`), and an absolute `source_url`; `snippet`, `event_stage`, `source_quality`, `source_domain`, and `source_agent` are optional.

The importer reads the generic OSS variables already supported by the deployment: `END_POINT`, `BUCKET`, `ACCESS_KEY_ID`, and `ACCESS_KEY_SECRET`. To isolate this service from other OSS uses, the equivalent `CORPORATE_ACTION_OSS_ENDPOINT`, `CORPORATE_ACTION_OSS_BUCKET`, `CORPORATE_ACTION_OSS_ACCESS_KEY_ID`, and `CORPORATE_ACTION_OSS_ACCESS_KEY_SECRET` take precedence. Optional `CORPORATE_ACTION_OSS_PREFIX` defaults to `corporate-actions/v1/incoming/` and `CORPORATE_ACTION_OSS_MAX_OBJECT_BYTES` defaults to 5 MiB.

Preview a batch import without SQLite writes:

```powershell
.\.venv\Scripts\python.exe -B scripts\import_corporate_action_oss.py --dry-run
```

Import new OSS object versions into SQLite:

```powershell
.\.venv\Scripts\python.exe -B scripts\import_corporate_action_oss.py
```

The importer tracks `bucket + object_key + ETag` in `corporate_action_imported_objects`; successfully imported and partial objects are skipped on later runs, while an overwritten OSS object has a new ETag and is imported again.

The scheduled prefix scan requires the OSS RAM policy action `oss:ListObjects` for the incoming prefix plus `oss:GetObject` for its objects. If deployment credentials only have object-read permission, import a known batch key without `ListObjects`:

```powershell
.\.venv\Scripts\python.exe -B scripts\import_corporate_action_oss.py --object-key corporate-actions/v1/incoming/cn/dt=2026-08-19/agent-a/batch.jsonl
```

## Local Web App

Backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload --app-dir backend
```

Frontend:

```powershell
cd frontend
npm run dev
```

Open:

```text
http://127.0.0.1:5173/
```

Build check:

```powershell
cd frontend
npm run build
```

## Server Daily Pipeline

Known server root:

```text
/root/stock_ranking
```

Run the all-in-one server update:

```bash
cd /root/stock_ranking
bash scripts/server_daily_update.sh
```

The script updates US daily bars through iFinD, refreshes option status and the Alpha Vantage earnings calendar (for the full Nasdaq-100 pool), refreshes A-share peer helper caches where possible, rebuilds ranking caches, updates CN/HK daily bars and caches through iFinD, restarts `stock-ranking-api`, and checks `/api/health`. A failure to refresh option status, the earnings calendar, or A-share helper caches leaves the previous cache in place and does not block the daily market-data update.

After the US calendar refresh, the server preserves calendar-date snapshots so that a ticker remains eligible after Alpha Vantage advances to the next quarter. The three-day earnings report is researched by a Codex weekday automation: it refreshes the calendar locally, classifies every company as pre-earnings, post-earnings, or unconfirmed, validates media timing against the official release, calculates local price performance versus QQQ, then publishes through the dedicated `earnings-reports` Git branch. This avoids both DeepSeek/Tavily daily research and any dependency on a public server read API. Reports are available in the earnings-calendar modal and at `/earnings-reports`; deployment and automation instructions are in `docs/codex_earnings_report_automation.md`.

## Verification

```powershell
Invoke-RestMethod "http://127.0.0.1:8001/api/health"
Invoke-RestMethod "http://127.0.0.1:8001/api/rankings/latest?window=10&benchmark=QQQ&market=us&apply_announced_rebalance=true"
Invoke-RestMethod "http://127.0.0.1:8001/api/rankings/latest?window=10&benchmark=000905&market=cn"
Invoke-RestMethod "http://127.0.0.1:8001/api/rankings/latest?window=10&benchmark=HSTECH&market=hk"
Invoke-RestMethod "http://127.0.0.1:8001/api/stocks/MU/peers"
```
