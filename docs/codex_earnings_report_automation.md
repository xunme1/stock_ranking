# Codex 财报市场反应日报自动化

Codex heartbeat 在工作日北京时间 10:00 于本地刷新 Alpha Vantage 财报日历和历史快照，再联网研究、计算本地行情验证，并通过 Git 的 `earnings-reports` 分支交给服务器展示。日报不调用 DeepSeek、Tavily 或服务器公开读取接口。

## 一次性部署

1. Codex 本地项目 `.env` 配置 `ALPHA_VANTAGE_API_KEY`；不要将 key 写入任务提示词或 Git。
2. `earnings-reports` 分支只保存 `reports/` 下的归档 JSON/HTML。
3. 服务器安装同步 cron（Asia/Shanghai）：

```cron
*/15 10-16 * * 1-5 cd /root/stock_ranking && bash scripts/sync_earnings_reports_from_git.sh >> logs/cron_earnings_report_sync.log 2>&1
```

## Codex heartbeat 工作流

1. 读取 `config/nasdaq100_tickers.txt` 并加上 QQQ，运行 `scripts/update_earnings_calendar.py --tickers <全部ticker> --horizon 3month`；刷新失败即停止，不使用陈旧日历。
2. 运行 `scripts/build_earnings_report_context.py --output .tmp/earnings-context.json` 生成近三日候选。
3. 先以 SEC 或公司 IR 确认是否已发布财报，再按状态搜索媒体：
   - `pre_earnings`：仅收集财报前的市场预期、关键变量和可能反应。
   - `post_earnings`：仅收集实际发布后、明确讨论业绩/指引与股价反应的媒体报道。
   - `unconfirmed`：日历日期已过但无官方确认，只输出“有限证据”和日期错位说明。
4. 输出严格 JSON。每家公司需有 `report_status`、`release_time`、`official_confirmation_url`、`media_market_alignment` 和带 `phase`、`published_date` 的来源。媒体来源阶段只能是 `pre_earnings`、`post_earnings` 或 `context`；财报后媒体文章不得早于实际发布日期。
5. 保存研究 JSON 后运行：

```powershell
.\.venv\Scripts\python.exe -B scripts\render_earnings_sentiment_report.py `
  --input .tmp\earnings-research.json `
  --context .tmp\earnings-context.json `
  --output-dir .tmp\earnings-rendered
```

渲染器自行从本地日线 CSV 计算相对 QQQ 与成交量验证；模型不得填造价格数字。仅渲染成功后，运行 `scripts/publish_earnings_report.py` 推送归档。

## 失败与归档

任一步失败均停止，不推送、不覆盖旧日报。行情尚未出现完整常规交易时段时，日报保留“等待行情验证”，但仍可归档官方确认和有时间标记的媒体观点。
