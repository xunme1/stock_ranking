# US Stock Daily Data Project

This project downloads and caches daily US stock OHLCV data from Polygon.io. The current stage focuses on the historical daily data download loop only. Data merge, indicator calculation, and stock screening scripts are intentionally left for a later stage.

## Project Tree

```text
us_stock_data_project/
├── config/
│   └── tickers.txt
├── data/
│   ├── raw/
│   │   └── daily/
│   └── processed/
├── logs/
├── scripts/
│   ├── download_polygon_daily.py
│   └── retry_failed_tickers.py
├── .env
├── .gitignore
├── README.md
└── requirements.txt
```

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

API keys are read from `.env`:

```text
POLYGON_API_KEY_1=your_api_key_1
POLYGON_API_KEY_2=your_api_key_2
```

## Tickers

Edit `config/tickers.txt` to control the stock pool. One ticker per line. Blank lines and lines starting with `#` are ignored.

Build a larger ticker pool from Polygon reference data while keeping existing tickers first:

```powershell
.\.venv\Scripts\python -B scripts\build_ticker_pool.py --target-count 2000
```

Build the full active US stock ticker pool returned by Polygon:

```powershell
.\.venv\Scripts\python -B scripts\build_ticker_pool.py --all
```

## Download Daily Data

Download all tickers in `config/tickers.txt`:

```powershell
.\.venv\Scripts\python scripts\download_polygon_daily.py
```

Download the first 100 tickers:

```powershell
.\.venv\Scripts\python scripts\download_polygon_daily.py --limit 100
```

By default the script waits 13 seconds per API key after each requested ticker. With multiple keys configured, it rotates through the key pool while keeping a separate cooldown for each key. Existing non-empty CSV files are skipped, so the script can be run repeatedly and resumed after interruption.

## Retry Failed Tickers

```powershell
.\.venv\Scripts\python scripts\retry_failed_tickers.py
```

## Merge Daily Data

Merge all downloaded CSV files:

```powershell
.\.venv\Scripts\python scripts\merge_daily_data.py
```

Merge a small ticker subset for testing:

```powershell
.\.venv\Scripts\python scripts\merge_daily_data.py --tickers MRVL,COHR --output data\processed\test_mrvl_cohr_daily.parquet
```

## Build Stock Screen

```powershell
.\.venv\Scripts\python scripts\build_stock_screen.py
```

Run the screen on a small test parquet:

```powershell
.\.venv\Scripts\python scripts\build_stock_screen.py --input data\processed\test_mrvl_cohr_daily.parquet --output-all data\processed\test_mrvl_cohr_screen_all.csv --output-selected data\processed\test_mrvl_cohr_screen_selected.csv
```

Build a short-term MA5/MA10 screen:

```powershell
.\.venv\Scripts\python -B scripts\build_ma5_ma10_screen.py
```

Build a Nasdaq-100 + optionable ticker universe, then run the original MA10 daily/weekly screen on it:

```powershell
.\.venv\Scripts\python -B scripts\build_screen_universe.py
.\.venv\Scripts\python -B scripts\build_stock_screen.py --tickers-file config\nasdaq100_optionable_tickers.txt --output-all data\processed\stock_screen_nasdaq100_optionable_all.csv --output-selected data\processed\stock_screen_nasdaq100_optionable_selected.csv
```

Build a relative strength report for selected stocks versus QQQ:

```powershell
.\.venv\Scripts\python -B scripts\build_relative_strength_report.py
```

## Update Latest Daily Data

Append only new dates to existing per-ticker CSV files:

```powershell
.\.venv\Scripts\python -B scripts\update_latest_daily.py
```

If a ticker is missing locally and should be downloaded from scratch:

```powershell
.\.venv\Scripts\python -B scripts\update_latest_daily.py --download-missing
```

## Outputs

Raw daily CSV files are written to:

```text
data/raw/daily/{TICKER}.csv
```

Each CSV includes:

```text
ticker,date,open,high,low,close,volume,vwap,transactions
```

Logs are written to:

```text
logs/download_log.csv
logs/failed_tickers.csv
```

## Notes

- The script downloads recent two-year daily adjusted aggregate bars.
- HTTP 429 responses wait 60 seconds before retrying.
- Each ticker is retried up to 3 times.
- A single ticker failure is logged and does not stop the whole run.
