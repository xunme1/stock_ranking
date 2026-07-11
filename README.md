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

The script updates US daily bars through iFinD, refreshes option/A-share peer helper caches where possible, rebuilds ranking caches, updates CN/HK daily bars and caches through iFinD, restarts `stock-ranking-api`, and checks `/api/health`.

## Verification

```powershell
Invoke-RestMethod "http://127.0.0.1:8001/api/health"
Invoke-RestMethod "http://127.0.0.1:8001/api/rankings/latest?window=10&benchmark=QQQ&market=us&apply_announced_rebalance=true"
Invoke-RestMethod "http://127.0.0.1:8001/api/rankings/latest?window=10&benchmark=000905&market=cn"
Invoke-RestMethod "http://127.0.0.1:8001/api/rankings/latest?window=10&benchmark=HSTECH&market=hk"
Invoke-RestMethod "http://127.0.0.1:8001/api/stocks/MU/peers"
```
