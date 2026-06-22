# Scripts 说明文档

本目录只保留项目当前核心链路脚本：股票池维护、Nasdaq-100/期权名单维护、历史数据下载、失败重试、每日增量更新。

当前 Web 后端直接读取 `data/raw/daily/{TICKER}.csv`，排名和详情页指标在后端/前端实时计算。因此旧的 Parquet 合并、早期筛选、Excel/Markdown 报表生成脚本已删除。

## 环境变量

脚本会从项目根目录 `.env` 读取 Polygon API key。

推荐配置多个 key，脚本会按 key 池轮流使用：

```text
POLYGON_API_KEY_1=your_key_1
POLYGON_API_KEY_2=your_key_2
POLYGON_API_KEY_3=your_key_3
```

兼容旧变量：

```text
POLYGON_API_KEY=your_key
```

如果同时存在 `POLYGON_API_KEY` 和 `POLYGON_API_KEY_1`，旧变量会被插入 key 池开头，但重复 key 不会重复加入。

## 输出目录

- 原始日线：`data/raw/daily/{TICKER}.csv`
- 下载日志：`logs/download_log.csv`
- 失败列表：`logs/failed_tickers.csv`
- 股票池：`config/tickers.txt`
- Nasdaq-100 名单：`config/nasdaq100_tickers.txt`
- 有期权 Nasdaq-100 名单：`config/nasdaq100_optionable_tickers.txt`

## download_polygon_daily.py

用途：从 Polygon 下载 `config/tickers.txt` 中股票的近 N 年日线 OHLCV 数据。已有非空 CSV 默认跳过，可重复运行续传。

常用命令：

```powershell
.\.venv\Scripts\python -B scripts\download_polygon_daily.py
.\.venv\Scripts\python -B scripts\download_polygon_daily.py --limit 100
.\.venv\Scripts\python -B scripts\download_polygon_daily.py --force
```

CLI 参数：

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--limit` | `None` | 只处理前 N 个 ticker |
| `--years` | `2` | 下载最近 N 年数据 |
| `--key-cooldown-seconds` | `13` | 每个 API key 两次请求间隔 |
| `--sleep-seconds` | `0` | 每个 ticker 后额外全局等待 |
| `--retry-wait-seconds` | `60` | 遇到 HTTP 429 后等待秒数 |
| `--max-retries` | `3` | 单 ticker 最大重试次数 |
| `--force` | `False` | 即使本地 CSV 已存在也重新下载 |

主要函数：

| 函数 | 参数 | 返回值 | 说明 |
| --- | --- | --- | --- |
| `load_api_keys()` | 无 | `list[str]` | 从 `.env` 读取 `POLYGON_API_KEY_1...N` 和旧变量 `POLYGON_API_KEY` |
| `load_tickers(path=TICKERS_FILE, limit=None)` | `Path`, `int \| None` | `list[str]` | 读取 ticker 文件，去空行/注释/重复 |
| `get_date_range(years=2)` | `int` | `tuple[str, str]` | 返回下载起止日期 ISO 字符串 |
| `request_polygon_daily(ticker, start, end, api_key, timeout=30)` | `str, str, str, str, int` | `requests.Response` | 请求 Polygon 日线接口 |
| `parse_polygon_results(ticker, payload)` | `str, dict` | `pd.DataFrame` | 将 Polygon JSON 转为标准日线表 |
| `download_one_ticker(...)` | `ticker, start, end, api_key/api_key_pool, max_retries, retry_wait_seconds, force` | `str` | 下载单个 ticker，返回 `success/skipped/empty/failed` |

CSV 字段：

```text
ticker,date,open,high,low,close,volume,vwap,transactions
```

## update_latest_daily.py

用途：每日更新脚本。只请求本地 CSV 最后日期之后的新数据，并追加/去重保存。适合部署后定时任务运行。

常用命令：

```powershell
.\.venv\Scripts\python -B scripts\update_latest_daily.py
.\.venv\Scripts\python -B scripts\update_latest_daily.py --tickers MRVL,COHR,QQQ
.\.venv\Scripts\python -B scripts\update_latest_daily.py --download-missing
```

CLI 参数：

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--limit` | `None` | 只更新前 N 个 ticker |
| `--tickers` | `None` | 逗号分隔的 ticker 子集 |
| `--end-date` | 今天 | 指定更新截止日期，格式 `YYYY-MM-DD` |
| `--key-cooldown-seconds` | `13` | 每个 API key 冷却秒数 |
| `--sleep-seconds` | `0` | 每个 ticker 后额外等待 |
| `--retry-wait-seconds` | `60` | HTTP 429 等待秒数 |
| `--max-retries` | `3` | 单 ticker 最大重试次数 |
| `--download-missing` | `False` | 本地缺失 CSV 时下载两年历史 |

主要函数：

| 函数 | 参数 | 返回值 | 说明 |
| --- | --- | --- | --- |
| `get_last_local_date(ticker)` | `str` | `date \| None` | 返回本地 CSV 最大交易日 |
| `merge_old_new_data(ticker, new_df)` | `str, pd.DataFrame` | `int` | 合并新旧数据并返回新增行数 |
| `update_one_ticker(ticker, end, api_key_pool, max_retries, retry_wait_seconds, download_missing=False)` | `str, date, ApiKeyPool, int, int, bool` | `str` | 更新单个 ticker，返回 `success/skipped/failed` |

## retry_failed_tickers.py

用途：读取 `logs/failed_tickers.csv`，重新下载失败过的 ticker。适合大批量下载后补漏。

常用命令：

```powershell
.\.venv\Scripts\python -B scripts\retry_failed_tickers.py
.\.venv\Scripts\python -B scripts\retry_failed_tickers.py --limit 50 --force
```

CLI 参数：

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--limit` | `None` | 只重试前 N 个失败 ticker |
| `--years` | `2` | 下载最近 N 年数据 |
| `--key-cooldown-seconds` | `13` | 每个 API key 冷却秒数 |
| `--sleep-seconds` | `0` | 每个 ticker 后额外等待 |
| `--retry-wait-seconds` | `60` | HTTP 429 等待秒数 |
| `--max-retries` | `3` | 单 ticker 最大重试次数 |
| `--force` | `False` | 已存在 CSV 时仍重新下载 |

主要函数：

| 函数 | 参数 | 返回值 | 说明 |
| --- | --- | --- | --- |
| `load_failed_tickers(limit=None)` | `int \| None` | `list[str]` | 从失败日志读取去重 ticker |
| `main()` | 无 | `None` | 构建 key 池并调用 `download_one_ticker()` 重试 |

## build_ticker_pool.py

用途：从 Polygon Reference API 构建 `config/tickers.txt`。可以生成指定数量股票池，也可以拉取 Polygon 返回的全部 active US stock ticker。

常用命令：

```powershell
.\.venv\Scripts\python -B scripts\build_ticker_pool.py --target-count 2000
.\.venv\Scripts\python -B scripts\build_ticker_pool.py --all
.\.venv\Scripts\python -B scripts\build_ticker_pool.py --types CS,ETF --target-count 2000
```

CLI 参数：

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--target-count` | `None` | 输出 ticker 数量；未传且非 `--all` 时默认 2000 |
| `--all` | `False` | 拉取所有 active US stock ticker |
| `--types` | `ALL` | Polygon ticker type 过滤，例如 `CS,ETF`；`ALL` 表示不传 type |
| `--key-cooldown-seconds` | `13` | 每个 API key 冷却秒数 |

主要函数：

| 函数 | 参数 | 返回值 | 说明 |
| --- | --- | --- | --- |
| `load_existing_tickers(path=TICKERS_FILE)` | `Path` | `list[str]` | 读取已有 `config/tickers.txt` |
| `request_reference_page(session, api_key_pool, params=None, next_url=None, timeout=30)` | `requests.Session, ApiKeyPool, dict \| None, str \| None, int` | `dict` | 请求 Polygon reference tickers 单页 |
| `fetch_polygon_tickers(target_count, existing_count, api_key_pool, ticker_types)` | `int \| None, int, ApiKeyPool, list[str \| None]` | `list[str]` | 分页拉取 ticker |
| `build_ticker_pool(target_count, ticker_types, key_cooldown_seconds)` | `int \| None, list[str \| None], int` | `list[str]` | 合并已有 ticker 和新拉取 ticker |
| `save_tickers(tickers, path=TICKERS_FILE)` | `list[str], Path` | `None` | 写入 ticker 文件 |

## build_screen_universe.py

用途：维护 Nasdaq-100 成分股和“有期权”的 Nasdaq-100 子集。当前 Web 默认展示 Nasdaq-100，并支持 2026-06-22 公告调整名单；这个脚本用于刷新基础名单文件。

常用命令：

```powershell
.\.venv\Scripts\python -B scripts\build_screen_universe.py
.\.venv\Scripts\python -B scripts\build_screen_universe.py --use-cache
```

CLI 参数：

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--key-cooldown-seconds` | `13` | 每个 API key 冷却秒数 |
| `--retry-wait-seconds` | `60` | HTTP 429 等待秒数 |
| `--max-retries` | `3` | 期权接口最大重试次数 |
| `--use-cache` | `False` | 如果本地 config 文件存在则复用，不重新联网抓取 |

主要函数：

| 函数 | 参数 | 返回值 | 说明 |
| --- | --- | --- | --- |
| `normalize_ticker(ticker)` | `object` | `str` | 统一 ticker 大写，并将 `.` 替换为 `-` |
| `fetch_nasdaq100_tickers()` | 无 | `list[str]` | 从 Wikipedia 抓取 Nasdaq-100 ticker |
| `request_options_contracts(session, api_key_pool, ticker, max_retries, retry_wait_seconds)` | `requests.Session, ApiKeyPool, str, int, int` | `dict` | 查询单个 ticker 的未到期期权合约 |
| `ticker_has_options(session, api_key_pool, ticker, max_retries, retry_wait_seconds)` | `requests.Session, ApiKeyPool, str, int, int` | `bool` | 判断 ticker 是否有未到期期权 |
| `build_optionable_tickers(tickers, key_cooldown_seconds, max_retries, retry_wait_seconds)` | `list[str], int, int, int` | `list[str]` | 从 ticker 列表中过滤有期权的 ticker |
| `save_tickers(tickers, path)` | `list[str], Path` | `None` | 写入 config 文件 |

## 推荐运行链路

首次准备数据：

```powershell
.\.venv\Scripts\python -B scripts\build_screen_universe.py --use-cache
.\.venv\Scripts\python -B scripts\download_polygon_daily.py
```

每日更新：

```powershell
.\.venv\Scripts\python -B scripts\update_latest_daily.py --download-missing
```

失败补跑：

```powershell
.\.venv\Scripts\python -B scripts\retry_failed_tickers.py
```

刷新大股票池：

```powershell
.\.venv\Scripts\python -B scripts\build_ticker_pool.py --target-count 2000
```

