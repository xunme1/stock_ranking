# Function Index

This reference lists the main functions agents need when modifying or operating the project. Load this file when a task asks for implementation details, function behavior, or script internals.

## Backend: `backend/app/services/data_loader.py`

- `normalize_ticker(ticker: str) -> str`  
  Uppercases ticker strings. Use before dictionary lookups and file paths.

- `ticker_csv_path(ticker: str) -> Path`  
  Returns `data/raw/daily/{TICKER}.csv`.

- `load_daily_csv_cached(ticker: str, mtime_ns: int) -> pd.DataFrame`  
  Cached CSV reader. Pass file mtime from `load_daily_data`; do not call directly unless preserving cache invalidation.

- `load_daily_data(ticker: str) -> pd.DataFrame`  
  Main daily OHLCV loader. Returns sorted rows with parsed dates and numeric OHLCV fields. Raises `FileNotFoundError` if CSV is missing.

- `load_ticker_file(path=NASDAQ100_FILE) -> list[str]`  
  Reads ticker text files, skipping blank/comment lines and duplicates.

- `load_ticker_set(path=NASDAQ100_OPTIONABLE_FILE) -> set[str]`  
  Cached set form of a ticker file.

- `load_optionable_tickers(path=OPTIONABLE_TICKERS_FILE) -> set[str]`  
  Returns tickers whose option status is `Y`.

- `load_optionable_status(path=OPTIONABLE_TICKERS_FILE) -> dict[str, str]`  
  Returns `{ticker: "Y"|"N"|"U"}` from `data/fundamental/optionable_tickers.csv`.

- `load_stock_profiles(path=STOCK_PROFILES_FILE) -> dict[str, dict[str, str]]`  
  Loads broad homepage labels: sector and stock_type.

- `load_stock_subtypes(path=STOCK_SUBTYPES_FILE) -> dict[str, dict[str, str]]`  
  Loads fine detail-page labels generated from curated A-share mapping. Restart backend after updating this file.

- `load_a_share_subtype_leaders(path=A_SHARE_SUBTYPE_LEADERS_FILE) -> dict[str, list[dict[str, str]]]`  
  Loads mapped A-share peer cards keyed by `sub_type`; output feeds `/api/stocks/{ticker}/peers`.

- `load_earnings_calendar(path=EARNINGS_CALENDAR_FILE) -> dict[str, dict[str, str]]`  
  Loads expected earnings date/time fields.

- `load_company_profiles(path=COMPANY_PROFILES_FILE) -> dict[str, dict[str, str]]`  
  Loads Polygon company profile and Chinese summary for the detail page.

## Backend: `backend/app/services/ranking_service.py`

- `apply_rebalance(tickers: list[str]) -> list[str]`  
  Applies the announced 2026-06-22 Nasdaq-100 changes. Homepage defaults to applying this in frontend requests.

- `true_range(df: pd.DataFrame) -> pd.Series`  
  Computes daily true range from high/low/previous close.

- `clean_number(value: object) -> float | None`  
  Converts finite numeric values; returns `None` for invalid/NaN.

- `trim_to_as_of_date(df: pd.DataFrame, as_of_date: date | None) -> pd.DataFrame`  
  Filters daily data to a chosen close date. Used by ranking and K-line endpoints.

- `latest_available_date(ticker: str) -> date`  
  Returns the last local trading date for a ticker.

- `available_dates(ticker: str, limit=260) -> list[str]`  
  Returns available close dates for date picker logic.

- `atr_window_for_ranking(window: int) -> int`  
  Returns `20` when `window == 10`; otherwise returns `window`.

- `ranking_cache_path(window: int) -> Path`  
  Returns `data/processed/rankings/ranking_window_{window}.csv`.

- `load_ranking_cache(window: int) -> pd.DataFrame`  
  Reads ranking cache and normalizes expected columns. Returns empty frame if missing.

- `save_ranking_cache(window: int, new_rows: pd.DataFrame) -> None`  
  Merges and de-duplicates ranking cache rows by date/window/benchmark/ticker.

- `cached_ranking_frame(window: int, benchmark: str, as_of_date: date) -> pd.DataFrame | None`  
  Returns cached ranking rows for one date if available.

- `build_ranking_alerts(window, benchmark="QQQ", as_of_date=None, days=5, top_n=20, move_threshold=10) -> dict[str, object]`  
  Builds anomaly card data: stable top20, upward/downward moves, entered/dropped top20. Requires ranking cache.

- `calculate_ticker_score(ticker, window, benchmark, as_of_date, optionable_status, stock_profiles) -> dict | None`  
  Computes one ticker’s close, moving-average center, ATR, ATR score, 3-day change, option status, stock type. Returns `None` if data is insufficient.

- `build_ranking_frame(universe, window, benchmark, as_of_date, optionable_status, stock_profiles) -> tuple[pd.DataFrame, list[str], float]`  
  Computes ranking rows for a universe. Returns `(frame, skipped_tickers, benchmark_score)`.

- `build_and_cache_ranking_frame(...) -> tuple[pd.DataFrame, list[str], float]`  
  Computes ranking and writes it to cache.

- `previous_trading_dates(benchmark, as_of_date, count) -> list[date]`  
  Uses benchmark data to find previous trading dates for rank history.

- `rank_map_for_date(..., use_cache=True) -> dict[str, int]`  
  Returns `{ticker: rank}` for historical rank markers.

- `build_ranking(config: RankingConfig) -> dict[str, object]`  
  Main service entry for `/api/rankings/latest`. Prefer this over calling lower-level scoring functions.

## Backend API

`backend/app/api/rankings.py`

- `get_latest_ranking(window=10, as_of_date=None, benchmark="QQQ", apply_announced_rebalance=False) -> dict`  
  HTTP `GET /api/rankings/latest`. Query params mirror arguments.

- `get_ranking_dates(benchmark="QQQ", limit=260) -> dict`  
  HTTP `GET /api/rankings/dates`. Drives enabled trading dates in the UI.

- `get_ranking_alerts(window=10, as_of_date=None, benchmark="QQQ", days=5, top_n=20, move_threshold=10) -> dict`  
  HTTP `GET /api/rankings/alerts`. Drives ranking anomaly modal/card.

`backend/app/api/stocks.py`

- `get_stock_daily(ticker, limit=260, as_of_date=None) -> dict`  
  HTTP `GET /api/stocks/{ticker}/daily`. Used by K-line and volume charts.

- `get_stock_profile(ticker) -> dict`  
  HTTP `GET /api/stocks/{ticker}/profile`. Detail-page company intro card.

- `get_stock_peers(ticker) -> dict`  
  HTTP `GET /api/stocks/{ticker}/peers`. Detail-page fine type and A-share peer card.

## Frontend API: `frontend/src/api.ts`

- `requestJson<T>(path: string) -> Promise<T>`  
  Fetch wrapper. Uses `VITE_API_BASE` if present; otherwise relies on Vite/nginx `/api` proxy.

- `fetchRanking(window, asOfDate, applyAnnouncedRebalance)`  
  Calls `/api/rankings/latest`. Homepage ranking table.

- `fetchRankingDates(limit=260)`  
  Calls `/api/rankings/dates`. Trading-date selector.

- `fetchRankingAlerts(window, asOfDate="")`  
  Calls `/api/rankings/alerts`. Ranking anomaly modal and detail-page alert context.

- `fetchDailyBars(ticker, limit=260, asOfDate="")`  
  Calls `/api/stocks/{ticker}/daily`. K-line, moving averages, volume.

- `fetchStockProfile(ticker)`  
  Calls `/api/stocks/{ticker}/profile`.

- `fetchStockPeers(ticker)`  
  Calls `/api/stocks/{ticker}/peers`.

## Scripts: US Data

`scripts/download_polygon_daily.py`

- `load_api_keys() -> list[str]` reads `POLYGON_API_KEY_1...N` plus fallback `POLYGON_API_KEY`.
- `load_tickers(path, limit) -> list[str]` reads `config/tickers.txt`.
- `request_polygon_daily(ticker, start, end, api_key, timeout=30) -> Response` calls Polygon aggregates.
- `parse_polygon_results(ticker, payload) -> pd.DataFrame` normalizes Polygon JSON to daily CSV schema.
- `download_one_ticker(...) -> str` is the reusable single-ticker worker returning `success`, `skipped`, `empty`, or `failed`.
- `main()` parses CLI and downloads/resumes all requested tickers.

`scripts/update_latest_daily.py`

- `get_last_local_date(ticker) -> date | None` reads the latest local CSV date.
- `previous_weekday(value: date) -> date` backs off weekends for default end date.
- `merge_old_new_data(ticker, new_df) -> int` appends, sorts, de-dupes and returns new row count.
- `update_one_ticker(...) -> str` single-ticker incremental updater.
- `main()` updates a ticker subset or the configured ticker file.

`scripts/build_ticker_pool.py`

- `load_existing_tickers(path) -> list[str]` preserves existing ticker order.
- `fetch_polygon_tickers(...) -> list[str]` pages through Polygon reference tickers.
- `build_ticker_pool(...) -> list[str]` combines existing and newly fetched tickers.
- `save_tickers(tickers, path) -> None` writes one ticker per line.

`scripts/build_screen_universe.py`

- `fetch_nasdaq100_tickers() -> list[str]` scrapes Nasdaq-100 members.
- `ticker_has_options(...) -> bool` checks active option contracts via Polygon.
- `build_optionable_tickers(...) -> list[str]` filters optionable names.
- `main()` writes `config/nasdaq100_tickers.txt` and `config/nasdaq100_optionable_tickers.txt`.

`scripts/update_optionable_tickers.py`

- `load_existing_status(path) -> dict` reads existing `Y/N/U` statuses.
- `load_universe(...) -> list[str]` builds the update universe.
- `query_optionable(ticker, api_key, timeout) -> tuple[str | None, str]` returns option status and reason.
- `update_one_ticker(...) -> dict[str, str]` merges current and existing status.
- `main()` writes `data/fundamental/optionable_tickers.csv`.

## Scripts: Ranking and Fundamental Caches

`scripts/build_ranking_cache.py`

- `recent_trading_dates(benchmark, days, end_date) -> list[date]` chooses dates to cache.
- `main()` builds ranking caches for `--windows 10,20 --days N`.

`scripts/update_a_share_universe.py`

- `normalize_code(value) -> str` produces six-digit A-share codes.
- `parse_number(value) -> float | None` robust numeric parser.
- `load_akshare()` and `load_tushare()` import clients and validate env.
- `normalize_spot_columns(df) -> pd.DataFrame` converts AkShare/Eastmoney spot columns to project schema.
- `fetch_tushare_universe(...) -> pd.DataFrame` gets Tushare daily-basic market cap data.
- `fetch_eastmoney_spot_direct(...) -> pd.DataFrame` gets A-share spot data with direct Eastmoney paging.
- `merge_tushare_basic(...)` and `merge_existing_industry_cache(...)` enrich or preserve industry fields.
- `build_a_share_universe(...) -> pd.DataFrame` main builder. Use `--source hybrid --spot-source akshare` when possible.
- `save_universe(df, output_file) -> None` writes `data/fundamental/a_share_universe.csv`.

`scripts/build_a_share_peer_cache.py`

- `read_mapping(path) -> pd.DataFrame` reads semicolon CSV with encoding fallback.
- `normalize_a_share_code(value) -> str` removes `.SH/.SZ` and zero-pads.
- `load_stock_profile_maps() -> tuple[...]` gets broad type and SIC metadata.
- `load_a_share_universe(path) -> dict[str, dict]` maps A-share code to latest market fields.
- `subtype_for_ticker(ticker) -> str` returns `mapped_{ticker}`.
- `build_stock_subtypes(mapping_df) -> pd.DataFrame` creates `config/stock_subtypes.csv`.
- `build_a_share_leaders(mapping_df, universe) -> pd.DataFrame` creates peer leaders and sorts each mapped trio by refreshed market cap.
- `save_csv(df, path) -> None` writes UTF-8-SIG CSV.
- `main()` builds both detail-page peer caches.

`scripts/update_company_profiles.py`

- `request_ticker_details(ticker, api_key) -> dict` calls Polygon ticker details.
- `profile_row(ticker, details, updated_at) -> dict` normalizes company profile CSV row.
- `build_summary(profile) -> str` creates fallback Chinese-ish summary from profile data.
- `translate_cached_descriptions(path, sleep_seconds) -> int` translates uncached English summaries.
- `ranked_tickers(limit, window) -> list[str]` selects ranking-priority tickers.
- `main()` refreshes `data/fundamental/company_profiles.csv`.

`scripts/update_earnings_calendar.py`

- `fetch_earnings_calendar(api_key, horizon) -> pd.DataFrame` calls Alpha Vantage.
- `top_ranked_tickers(limit, window) -> list[str]` uses ranking cache priority.
- `build_output_rows(calendar_df, tickers) -> list[dict[str, str]]` maps API rows to tracked tickers.
- `main()` writes `data/fundamental/earnings_calendar.csv`.

## Scripts: Daily Brief and Email

`experiments/daily_brief/generate_brief_data.py`

- `load_ranking(window) -> pd.DataFrame` reads ranking cache.
- `row_to_item(row, names) -> dict` normalizes ranking rows for JSON.
- `type_distribution(items, limit) -> list[dict]` summarizes stock-type mix.
- `build_technology_focus(latest_items, top_n) -> dict` builds tech-only focus.
- `build_rank_history(recent, tickers) -> dict` produces recent rank history.
- `build_summary(...) -> list[str]` rule-based summary bullets.
- `build_rule_based_analysis(brief) -> str` placeholder model text.
- `build_brief(window, as_of_date, top_n, move_threshold) -> dict` main JSON builder.
- `main()` writes `experiments/daily_brief/output/daily_brief_YYYY-MM-DD_w{window}.json`.

`experiments/daily_brief/llm_analysis.py`

- `build_analysis_payload(brief) -> dict` compacts data sent to model.
- `build_llm_messages(brief) -> list[dict[str, str]]` creates Qwen prompt messages.
- `load_dashscope_key() -> str` reads `DASHSCOPE_API_KEY` or `BAILIAN_API_KEY`.
- `generate_model_interpretation(brief, model, timeout, max_tokens) -> dict` calls DashScope-compatible API.

`experiments/daily_brief/render_html.py`

- Project-compatible CLI wrapper for the interactive HTML renderer.
- Supports `--input`, `--output`, `--market`, `--as-of-date`, and `--theme`.
- `main()` writes `experiments/daily_brief/output/daily_brief_{market}_YYYY-MM-DD_w10.html`.

`experiments/daily_brief/interactive_daily_brief.py`

- `generate_html(data, theme="dark") -> str` renders a structured daily brief JSON into a standalone interactive HTML report.
- `load_report(path) -> dict` validates an existing daily brief JSON file.
- `main()` can be used directly with `input.json -o report.html --theme light`.

`experiments/daily_brief/html_to_pdf.py`

- Exports a generated HTML report to PDF through Playwright when available, otherwise a local Chromium-compatible browser.
- `main()` writes a PDF next to the input HTML unless `--output` is provided.

`experiments/daily_brief/render_pdf.py`

- `register_font() -> None` chooses usable CJK font; watch server TTC/PostScript issues.
- Drawing helpers: `text`, `right_text`, `center_text`, `panel`, `wrapped`, `fmt`, `pct_color`, `delta_label`.
- Page renderers: `render_page_one` through `render_page_five`.
- `main()` renders PDF from JSON. Retained as a fallback; the main path is JSON -> HTML -> PDF.

`scripts/send_daily_brief_email.py`

- `split_recipients(value) -> list[str]` supports multiple recipients.
- `load_config(cli_to) -> dict[str, str]` reads SMTP env vars and CLI recipient override.
- `discover_latest_reports(windows) -> tuple[str, list[Path], list[dict]]` finds latest PDFs.
- `build_body(as_of_date, briefs) -> str` creates email body.
- `attach_file(message, path) -> None` attaches PDFs.
- `send_email(config, subject, body, attachments, dry_run) -> None` sends via SMTP.
- `main()` sends latest reports for requested windows.

## Experiments: Sector Cloud

`experiments/sector_cloud/generate_sector_cloud.py`

- `load_company_profiles() -> dict[str, dict]` reads market cap metadata.
- `load_latest_ranking(window, as_of_date) -> tuple[pd.DataFrame, str]` selects ranking cache date.
- `build_cloud(window, as_of_date) -> dict` groups ranking rows into treemap data.
- `render_html(data) -> str` returns standalone HTML.
- `main()` writes `experiments/sector_cloud/output/index_w10.html`, `index_w20.html`, and latest `index.html`.
