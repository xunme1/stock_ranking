# A股市值与细分类型映射脚本

这一组脚本用于给美股详情页增加更细的股票类型，并找到对应细分类型下的 A股市值前三龙头。

## 依赖

```powershell
cd E:\stock_ranking\us_stock_data_project
.\.venv\Scripts\pip.exe install akshare tushare
```

项目的 `requirements.txt` 已包含 `akshare` 和 `tushare`。

`.env` 中需要配置：

```text
TUSHARE_TOKEN=your_token
```

## 生成 A股缓存

推荐使用混合模式：

```powershell
.\.venv\Scripts\python.exe -B scripts\update_a_share_universe.py --source hybrid
```

混合模式含义：

- A股市值、最新价、涨跌幅来自东方财富行情源。
- A股行业类型来自 Tushare `stock_basic`。
- 如果 Tushare 当天限流，脚本会继续更新市值和涨跌幅，并尽量沿用上一版缓存里的行业字段。

输出：

```text
data/fundamental/a_share_universe.csv
```

关键字段：

| 字段 | 含义 |
| --- | --- |
| `code` | A股代码 |
| `name` | 股票名称 |
| `latest_price` | 最新价 |
| `change_pct` | 当日涨跌幅 |
| `market_cap_cny` | 总市值，单位元 |
| `market_cap_100m_cny` | 总市值，单位亿元 |
| `industry_boards` | 行业类型 |

## 生成美股细分类型

```powershell
.\.venv\Scripts\python.exe -B scripts\build_stock_subtypes.py
```

输出：

```text
config/stock_subtypes.csv
```

人工规则配置在：

```text
config/us_stock_subtype_rules.csv
```

## 生成 A股对标龙头

```powershell
.\.venv\Scripts\python.exe -B scripts\build_a_share_leaders.py
```

输出：

```text
data/fundamental/a_share_subtype_leaders.csv
```

该脚本会根据美股细分类型关键词，在 A股 `name`、`industry_boards`、`concept_boards` 中匹配候选股，再按 `market_cap_cny` 降序取前三。

## 每日更新链路

服务器每日更新脚本已接入 A股缓存更新：

```bash
bash scripts/server_daily_update.sh
```

执行顺序包括：

1. 更新美股日线。
2. 更新期权状态。
3. 更新 A股市值、涨跌幅和行业缓存。
4. 重建美股细分类型缓存。
5. 重建 A股对标龙头缓存。
6. 重建排名缓存。
7. 重启后端服务。
