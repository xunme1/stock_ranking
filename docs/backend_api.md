# Backend API Reference

本文档整理 `backend/app` 当前 FastAPI 后端接口。默认本地服务地址：

```text
http://127.0.0.1:8001
```

## 通用约定

- 返回格式：除静态日报 HTML 文件外，接口均返回 JSON。
- 市场参数 `market`：`us` 美股，`cn` A股，`hk` 港股。
- 日期参数：使用 `YYYY-MM-DD`。
- 参数校验失败：FastAPI 返回 `422 Unprocessable Entity`。
- 业务处理异常：多数业务接口捕获异常并返回 `500`，响应形如 `{"detail": "错误信息"}`。
- 默认基准：美股 `QQQ`，A股 `000905`，港股 `HSTECH`。

## 健康检查

### GET `/api/health`

作用：检查后端服务是否正常运行。

参数：无。

返回值：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `status` | string | 固定为 `ok` |

示例：

```json
{
  "status": "ok"
}
```

## 排名接口

### GET `/api/rankings/latest`

作用：获取指定市场、日期、窗口的 ATR 相对强度排名。若目标日期没有缓存，会尝试实时计算并写入缓存。

参数：

| 参数 | 位置 | 类型 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `window` | query | int | `10` | `2 <= window <= 60` | 均线重心窗口。当前前端主要使用 `10`、`20`；`window=10` 时 ATR 窗口实际使用 20 日 |
| `as_of_date` | query | date | 最新基准交易日 | `YYYY-MM-DD` | 指定排名日期；不传则使用基准最新可用日期 |
| `benchmark` | query | string | 按市场默认 | 长度 1-12 | 基准代码 |
| `market` | query | string | `us` | `us`/`cn`/`hk` | 市场 |

返回值：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `window` | int | 本次排名窗口 |
| `market` | string | 市场 |
| `as_of_date` | string | 排名日期 |
| `benchmark` | string | 基准代码 |
| `benchmark_rank` | int | 基准在排名中的名次 |
| `benchmark_score` | number | 基准 ATR 分数 |
| `count` | int | `data` 行数 |
| `skipped` | string[] | 因数据缺失或指标不足跳过的 ticker；若命中缓存通常为空 |
| `data` | RankingRow[] | 排名数据 |

`RankingRow` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `rank` | int | 当前排名，1 为最强 |
| `ticker` | string | 股票代码 |
| `name` | string | 股票名称；美股可能为空 |
| `type` | string | 市场内证券类型，例如 `Nasdaq-100 Stock`、`A-share Stock`、`Hong Kong Stock` |
| `has_options` | string | 期权状态：`Y` 有，`N` 无，`U` 未知；A股/港股通常为 `U` |
| `sector` | string | 大类行业或项目配置中的行业标签 |
| `stock_type` | string | 更细的股票类型 |
| `date` | string | 该行指标对应的交易日 |
| `close` | number | 收盘价 |
| `latest_ma` | number/null | 最新 `window` 日均线 |
| `ma_center` | number/null | 均线重心 |
| `atr` | number | ATR |
| `atr_score` | number | `(close - ma_center) / atr` |
| `price_vs_center_pct` | number | 收盘价相对均线重心的百分比 |
| `price_change_3d_pct` | number/null | 较 3 个交易日前收盘价涨跌幅 |
| `excess_atr_vs_benchmark` | number | `atr_score - benchmark_score` |
| `previous_rank_1` | int/null | 前 1 个交易日排名 |
| `previous_rank_2` | int/null | 前 2 个交易日排名 |
| `rank_change` | int/null | `previous_rank_1 - rank`，正数表示排名上升 |
| `rank_history` | object[] | 最近排名历史，元素为 `{ "date": string, "rank": int/null }` |
| `earnings_date` | string | 美股财报日期；A股/港股通常为空 |

示例：

```http
GET /api/rankings/latest?window=10&benchmark=QQQ&market=us
GET /api/rankings/latest?window=10&benchmark=000905&market=cn&as_of_date=2026-07-14
```

### GET `/api/rankings/dates`

作用：获取某市场基准的可用交易日期列表，用于日期选择器。

参数：

| 参数 | 位置 | 类型 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `benchmark` | query | string | 按市场默认 | 长度 1-12 | 基准代码 |
| `market` | query | string | `us` | `us`/`cn`/`hk` | 市场 |
| `limit` | query | int | `260` | `20 <= limit <= 2000` | 最多返回多少个交易日 |

返回值：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `benchmark` | string | 实际使用的基准 |
| `market` | string | 市场 |
| `count` | int | 日期数量 |
| `dates` | string[] | 交易日期，升序排列 |

示例：

```json
{
  "benchmark": "QQQ",
  "market": "us",
  "count": 260,
  "dates": ["2025-07-01", "2025-07-02"]
}
```

### GET `/api/rankings/alerts`

作用：基于排名缓存生成排名监测卡片，包括稳定前排、大幅上升/下降、进入/跌出 Top N。

参数：

| 参数 | 位置 | 类型 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `window` | query | int | `10` | `2 <= window <= 60` | 排名窗口 |
| `as_of_date` | query | date | 最新缓存日期 | `YYYY-MM-DD` | 截止日期 |
| `benchmark` | query | string | 按市场默认 | 长度 1-12 | 基准代码 |
| `market` | query | string | `us` | `us`/`cn`/`hk` | 市场 |
| `days` | query | int | `5` | `3 <= days <= 20` | 观察最近多少个缓存日期 |
| `top_n` | query | int | `20` | `5 <= top_n <= 100` | Top N 阈值 |
| `move_threshold` | query | int | `10` | `1 <= move_threshold <= 100` | 排名变化绝对值阈值 |

返回值：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `window` | int | 排名窗口 |
| `benchmark` | string | 基准代码 |
| `as_of_date` | string | 最新观察日期 |
| `previous_date` | string | 前一观察日期 |
| `dates` | string[] | 本次观察使用的日期 |
| `top_n` | int | Top N 阈值 |
| `move_threshold` | int | 排名变化阈值 |
| `stable_top20` | AlertItem[] | 最近观察期稳定在 Top N 的股票 |
| `upward_moves` | AlertItem[] | 排名上升超过阈值的股票 |
| `downward_moves` | AlertItem[] | 排名下降超过阈值的股票 |
| `entered_top20` | AlertItem[] | 当日进入 Top N 的股票 |
| `dropped_top20` | AlertItem[] | 当日跌出 Top N 的股票 |

`AlertItem` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ticker` | string | 股票代码 |
| `name` | string | 股票名称 |
| `rank` | int | 最新排名 |
| `previous_rank` | int/null | 前一观察日期排名 |
| `rank_change` | int/null | `previous_rank - rank`，正数表示排名上升 |
| `daily_change_pct` | number/null | 最新日涨跌幅 |
| `avg_rank_5` | number/null | 观察期平均排名，字段名固定为 `_5`，实际由 `days` 参数决定 |
| `best_rank_5` | int/null | 观察期最好排名 |
| `worst_rank_5` | int/null | 观察期最差排名 |

注意：该接口依赖 `data/processed/rankings/` 下的排名缓存。缓存不足时会返回 `500`。

## 股票详情接口

### GET `/api/stocks/{ticker}/daily`

作用：获取单只股票的日线 OHLCV 数据。

路径参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `ticker` | string | 股票代码。会按市场规则标准化 |

Query 参数：

| 参数 | 类型 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `limit` | int | `260` | `20 <= limit <= 2000` | 最多返回多少根日线 |
| `as_of_date` | date | 不限制 | `YYYY-MM-DD` | 只返回该日期及之前的数据 |
| `market` | string | `us` | `us`/`cn`/`hk` | 市场 |

返回值：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ticker` | string | 标准化后的代码 |
| `count` | int | 日线数量 |
| `data` | DailyBar[] | 日线数组 |

`DailyBar` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ticker` | string | 股票代码 |
| `date` | string | 日期 |
| `open` | number | 开盘价 |
| `high` | number | 最高价 |
| `low` | number | 最低价 |
| `close` | number | 收盘价 |
| `volume` | number/null | 成交量 |

错误：

- `404`：本地日线 CSV 不存在。

示例：

```http
GET /api/stocks/MU/daily?limit=120&market=us
GET /api/stocks/000905/daily?limit=260&market=cn
```

### GET `/api/stocks/{ticker}/profile`

作用：获取美股公司资料缓存。当前实现使用美股 ticker 标准化逻辑，主要服务美股详情页。

路径参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `ticker` | string | 股票代码 |

Query 参数：无。

返回值：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ticker` | string | 股票代码 |
| `name` | string | 公司名称 |
| `market` | string | 市场 |
| `exchange` | string | 交易所 |
| `locale` | string | 地域 |
| `primary_exchange` | string | 主交易所 |
| `currency_name` | string | 交易货币 |
| `market_cap` | string | 市值，字符串格式 |
| `sic_description` | string | SIC 行业描述 |
| `homepage_url` | string | 官网 |
| `description` | string | 英文简介 |
| `summary_zh` | string | 中文摘要 |
| `source` | string | 数据来源 |
| `updated_at` | string | 更新时间 |

注意：若没有缓存资料，会返回同结构空字符串字段，而不是 `404`。

### GET `/api/stocks/{ticker}/peers`

作用：获取美股细分赛道对应的 A 股对标龙头列表。

路径参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `ticker` | string | 美股代码 |

Query 参数：无。

返回值：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ticker` | string | 标准化后的美股代码 |
| `sub_type` | string | 英文/内部细分类型 |
| `sub_type_cn` | string | 中文细分类型 |
| `a_share_keywords` | string | A 股匹配关键词，通常用分号分隔 |
| `source` | string | 映射来源，例如 `csv_mapping` |
| `a_share_leaders` | AShareLeader[] | A 股对标列表 |

`AShareLeader` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `sub_type` | string | 细分类型 |
| `sub_type_cn` | string | 中文细分类型 |
| `a_share_keywords` | string | 匹配关键词 |
| `rank` | int | 对标列表排名 |
| `code` | string | A 股 6 位代码 |
| `name` | string | A 股名称 |
| `market_cap_cny` | string | 总市值，人民币 |
| `market_cap_100m_cny` | string | 总市值，亿元人民币 |
| `latest_price` | string | 最新价 |
| `change_pct` | string | 涨跌幅 |
| `industry_boards` | string | 行业板块 |
| `concept_boards` | string | 概念板块 |

注意：若没有映射，会返回空 `sub_type`、空 `a_share_leaders`，而不是 `404`。

## 行业资金流接口

### GET `/api/industry-flows/dates`

作用：获取行业资金流数据库中某市场可用日期。

参数：

| 参数 | 位置 | 类型 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `market` | query | string | `us` | `us`/`cn`/`hk` | 市场 |
| `limit` | query | int | `260` | `1 <= limit <= 2000` | 最多返回多少个日期 |

返回值：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `market` | string | 市场 |
| `count` | int | 日期数量 |
| `dates` | string[] | 日期数组，升序排列 |

### GET `/api/industry-flows/rankings`

作用：获取指定市场、日期的行业资金流入/流出排名。

参数：

| 参数 | 位置 | 类型 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `market` | query | string | `us` | `us`/`cn`/`hk` | 市场 |
| `trade_date` | query | date | 最新可用日期 | `YYYY-MM-DD` | 交易日期 |
| `limit` | query | int | `100` | `1 <= limit <= 500` | 最多返回行业数量 |

返回值：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `market` | string | 市场 |
| `trade_date` | string | 交易日期 |
| `count` | int | 行业数量 |
| `data` | IndustryFlowRow[] | 行业资金流排名 |

`IndustryFlowRow` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `rank` | int | 按 `flow_amount` 降序生成的排名 |
| `market` | string | 市场 |
| `trade_date` | string | 交易日期 |
| `industry_name` | string | 行业名称 |
| `flow_amount` | number | 资金流金额 |
| `stock_count` | int | 行业内股票数量 |
| `positive_count` | int | 资金流为正的股票数量 |
| `negative_count` | int | 资金流为负的股票数量 |

### GET `/api/industry-flows/trend`

作用：获取若干行业的资金流时间序列。若不传 `industries`，默认取最新日期资金流排名前 `top_n` 的行业。

参数：

| 参数 | 位置 | 类型 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `market` | query | string | `us` | `us`/`cn`/`hk` | 市场 |
| `industries` | query | string | 空字符串 | 逗号分隔 | 指定行业名列表，例如 `半导体,互联网` |
| `top_n` | query | int | `8` | `1 <= top_n <= 20` | 未指定行业时，选取最新日期资金流前 N 行业 |
| `start_date` | query | date | 不限制 | `YYYY-MM-DD` | 起始日期 |
| `end_date` | query | date | 不限制 | `YYYY-MM-DD` | 结束日期 |

返回值：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `market` | string | 市场 |
| `industries` | string[] | 实际返回的行业名 |
| `series` | IndustryFlowSeries[] | 行业时间序列 |

`IndustryFlowSeries` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `industry_name` | string | 行业名称 |
| `points` | object[] | 时间序列点 |

`points` 元素：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `date` | string | 交易日期 |
| `flow_amount` | number | 资金流金额 |

### GET `/api/industry-flows/{industry_name}/stocks`

作用：获取某行业在指定日期下的成分股票资金流排名。

路径参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `industry_name` | string | 行业名称，需要 URL 编码 |

Query 参数：

| 参数 | 类型 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `market` | string | `us` | `us`/`cn`/`hk` | 市场 |
| `trade_date` | date | 最新可用日期 | `YYYY-MM-DD` | 交易日期 |
| `limit` | int | `200` | `1 <= limit <= 1000` | 最多返回股票数量 |

返回值：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `market` | string | 市场 |
| `trade_date` | string | 交易日期 |
| `industry_name` | string | 行业名称 |
| `count` | int | 股票数量 |
| `data` | IndustryStockFlowRow[] | 成分股资金流排名 |

`IndustryStockFlowRow` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `rank` | int | 按 `flow_amount` 降序生成的排名 |
| `ticker` | string | 股票代码 |
| `ths_code` | string | 同花顺代码 |
| `name` | string | 股票名称 |
| `industry_name` | string | 行业名称 |
| `flow_amount` | number | 资金流金额 |

## 每日报告接口

### GET `/api/daily-briefs`

作用：列出已生成的每日 HTML 报告。只收集文件名匹配 `daily_brief_{market}_{date}_w10.html` 的报告。

参数：无。

返回值：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `count` | int | 报告数量 |
| `dates` | string[] | 报告日期，倒序 |
| `data` | DailyBriefReport[] | 报告条目，按日期和市场倒序 |

`DailyBriefReport` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `market` | string | `us`/`cn`/`hk` |
| `market_label` | string | 中文市场名：美股/A股/港股 |
| `date` | string | 报告日期 |
| `window` | int | 报告窗口，目前正则只匹配 `10` |
| `filename` | string | 文件名 |
| `url` | string | 静态访问 URL |
| `size_bytes` | int | 文件大小 |
| `updated_at` | number | 文件修改时间，Unix timestamp |

### GET `/daily-briefs/files/{filename}`

作用：访问每日 HTML 报告静态文件。

路径参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `filename` | string | `experiments/daily_brief/output/` 下的 HTML 文件名 |

返回值：HTML 文件内容，由 FastAPI `StaticFiles` 提供。

## 前端当前使用的主要接口

- 首页排名：`GET /api/rankings/latest`
- 日期选择器：`GET /api/rankings/dates`
- 排名监测：`GET /api/rankings/alerts`
- 股票详情 K 线：`GET /api/stocks/{ticker}/daily`
- 公司简介：`GET /api/stocks/{ticker}/profile`
- A 股对标：`GET /api/stocks/{ticker}/peers`
- 行业资金流页面：`GET /api/industry-flows/dates`、`GET /api/industry-flows/rankings`、`GET /api/industry-flows/trend`、`GET /api/industry-flows/{industry_name}/stocks`
- 历史日报：`GET /api/daily-briefs` 和 `/daily-briefs/files/{filename}`
