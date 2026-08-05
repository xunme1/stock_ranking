# Codex 财报日报自动化

日报不再由服务器调用 DeepSeek 或 Tavily。Codex heartbeat 在工作日北京时间 10:00 先在本地刷新 Alpha Vantage 财报日历和历史快照，再联网研究，并通过 Git 分支将已校验的报告交给服务器展示。日报生成不依赖服务器的公开接口。

## 一次性部署

1. Codex 本地项目 `.env` 配置 `ALPHA_VANTAGE_API_KEY`；不要把该 key 写入任务提示词或 Git。
2. 创建并推送空的 `earnings-reports` 分支；它只保存 `reports/` 下的归档 JSON/HTML。
3. 在服务器安装同步 cron（服务器时区为 Asia/Shanghai）：

```cron
*/15 10-16 * * 1-5 cd /root/stock_ranking && bash scripts/sync_earnings_reports_from_git.sh >> logs/cron_earnings_report_sync.log 2>&1
```

同步只读取 `origin/earnings-reports` 的 `reports/` 目录并替换 `data/processed/earnings_sentiment_reports/`。同步失败时现有归档保持不变。

## Codex heartbeat 提示词

将下列内容作为工作日北京时间 10:00 heartbeat 的任务提示词。不要在任务或仓库中保存 API key。

```text
生成并发布今日美股财报舆情日报。

1. 在项目根目录读取 `config/nasdaq100_tickers.txt` 的所有 ticker 并加上 QQQ，运行 `scripts/update_earnings_calendar.py --tickers <全部ticker> --horizon 3month`。若刷新失败，停止并通知，不使用陈旧日历。
2. 运行 `scripts/build_earnings_report_context.py --output .tmp/earnings-context.json`，以本地当前日历与历史快照生成近三日候选。
3. 对每个候选公司先检索 SEC 披露或公司 IR 新闻稿，确认是否已发布财报；再检索少量主流财经媒体补充市场解读。不得把广泛网络观点作为事实。
4. 为全部候选输出严格 JSON：report_date、overall_sentiment、summary、companies、risk_notes。每个 company 必须带 ticker、calendar_date、reported、actual_release_date（仅 reported=true）、sentiment、evidence_level、summary、media_view、key_points、sources。source 的 kind 只能为 official 或 media，并带 title、url、publisher、excerpt。
5. 未确认发布的公司，evidence_level 必须为 limited，summary 和 media_view 均以“有限证据”开头；确认发布的公司至少提供一个 official 来源。
6. 将研究 JSON 保存为 .tmp/earnings-research.json，运行：
   ./.venv/Scripts/python.exe -B scripts/render_earnings_sentiment_report.py --input .tmp/earnings-research.json --context .tmp/earnings-context.json --output-dir .tmp/earnings-rendered
   （Linux 环境使用 ./.venv/bin/python。）
7. 仅在渲染校验成功后运行：
   ./.venv/Scripts/python.exe -B scripts/publish_earnings_report.py --report-dir .tmp/earnings-rendered --report-date <context.report_date>
8. 若任一步失败，停止，不发布、不覆盖旧日报，并保留错误信息供失败通知使用。
```

## 手工验证

可以先用一份模拟 context 与研究 JSON 运行渲染器，再以 `--dry-run` 运行发布脚本。上线后，服务器同步完成即可通过 `/api/earnings-reports` 或 `/earnings-reports` 查看归档。
