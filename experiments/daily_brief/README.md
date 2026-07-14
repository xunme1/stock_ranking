# Daily Ranking Brief

This module generates a structured daily ranking-anomaly brief and an HTML report from the existing ranking cache.

## Data Source

The brief reads cached ranking files from:

```text
data/processed/rankings/ranking_window_10.csv
```

Generated JSON and HTML files are written to `experiments/daily_brief/output/`. The output folder is ignored by git.

## Environment

LLM analysis is optional. If you want the model to fill the first-page analysis, set the DeepSeek key in `.env`:

```env
DEEPSEEK_API_KEY=your_api_key
DEEPSEEK_MODEL=deepseek-chat
TAVILY_API_KEY=your_tavily_api_key
DAILY_BRIEF_PUBLIC_BASE_URL=https://your-domain.example/daily-briefs/files
```

`DEEPSEEK_MODEL` is optional and defaults to `deepseek-chat`. `DEEPSEEK_BASE_URL` can override the default compatible API endpoint if needed.

Qwen/DashScope remains available as a fallback when `--llm-model` starts with `qwen` or `dashscope:`. In that case, set `DASHSCOPE_API_KEY` or `BAILIAN_API_KEY`.

Tavily is used for the deep research pipeline when `--use-llm` is enabled. If `TAVILY_API_KEY` is missing or web search fails, generation continues with a partial/fallback quantitative report instead of aborting the daily brief.

## Generate Without LLM

```powershell
.\.venv\Scripts\python.exe -B experiments\daily_brief\generate_brief_data.py --window 10
.\.venv\Scripts\python.exe -B experiments\daily_brief\render_html.py --input experiments\daily_brief\output\daily_brief_YYYY-MM-DD_w10.json
```

The generator includes a rule-based placeholder analysis, so the HTML report can be rendered even when the model is not called.

## Generate With DeepSeek Analysis

```powershell
.\.venv\Scripts\python.exe -B experiments\daily_brief\generate_brief_data.py --window 10 --use-llm --llm-timeout 180 --llm-max-tokens 1500
.\.venv\Scripts\python.exe -B experiments\daily_brief\render_html.py --input experiments\daily_brief\output\daily_brief_YYYY-MM-DD_w10.json
```

The model pipeline writes a structured `model_interpretation` object with `summary`, Markdown `full_report`, compatibility `report`, `research_context`, `evidence`, `audit`, and `pipeline` fields. The HTML renderer displays the summary in the interpretation card and opens an in-page drawer that prefers the Markdown full report, with structured `report` fallback for older JSON files. Evidence cards prefer model-generated Chinese `title_zh` and `summary_zh`, and Python normalizes source quality, source type, date relation, causality strength, and confidence.

Useful LLM options:

```powershell
.\.venv\Scripts\python.exe -B experiments\daily_brief\generate_brief_data.py --window 10 --use-llm --llm-search-results 5 --llm-lookback-days 7 --llm-max-report-tokens 12000
.\.venv\Scripts\python.exe -B experiments\daily_brief\generate_brief_data.py --window 10 --use-llm --llm-disable-web
```

## Send Email Links

```bash
MARKET_GROUP=us bash scripts/run_daily_brief_email.sh
MARKET_GROUP=asia bash scripts/run_daily_brief_email.sh
```

`MARKET_GROUP=us` sends the US report link. `MARKET_GROUP=asia` sends A-share and Hong Kong report links together. The email uses `DAILY_BRIEF_PUBLIC_BASE_URL` plus each generated HTML filename.

## Report Structure

- Header metrics: benchmark rank, ATR score, distance from center, close date, and model-analysis block.
- Distribution and alert sections: stable top 20, large upward movers, large downward movers, and current top 20.
- Current top 20 table and rank-history charts.

## Prompt Design

`llm_analysis.py` builds a compact `research_context` from the daily JSON, plans up to 8 targeted search tasks with `deepseek-v4-pro`, extracts up to 24 evidence items with `deepseek-v4-pro`, writes a Markdown Chinese research report with `deepseek-v4-pro`, and audits unsupported facts, overstated causality, date mismatches, source quality, number consistency, and investment-advice risk with `deepseek-chat`.

The writer returns a short `summary` for the daily box and a Markdown `full_report` with required sections: 核心结论, 市场结构, 驱动因素与证据, 驱动因素源头拆解, 趋势判断, 关键观察对象, 风险情景, 下一交易日观察, and 免责声明. `text` and a compatibility `report` object are still emitted for backward compatibility.

The prompt forbids invented news, fundamentals, earnings explanations, or external facts that are not present in the evidence list. Later-dated evidence can only be used as follow-up observation, not as a same-day market cause. All `deepseek-v4-pro` outputs are cleaned for `<think>` blocks, reasoning prefixes, draft leakage, and Markdown fences before parsing or rendering; malformed JSON is repaired by `deepseek-chat`.

## Notes

- Large upward and downward mover tables are sorted by daily price change descending.
- Technology focus is built from stock-type labels such as software, semiconductor, cloud, internet, hardware, cyber security, optical communication, and related technology categories.
- PDF rendering is retained only as a fallback; the main email flow sends HTML links.
