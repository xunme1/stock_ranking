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
DAILY_BRIEF_PUBLIC_BASE_URL=https://your-domain.example/daily-briefs/files
```

`DEEPSEEK_MODEL` is optional and defaults to `deepseek-chat`. `DEEPSEEK_BASE_URL` can override the default compatible API endpoint if needed.

Qwen/DashScope remains available as a fallback when `--llm-model` starts with `qwen` or `dashscope:`. In that case, set `DASHSCOPE_API_KEY` or `BAILIAN_API_KEY`.

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

The model call writes text into `model_interpretation.text`; the HTML renderer displays that text in the interpretation section.

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

`llm_analysis.py` asks the model to use only the supplied JSON data and write five sections:

- 市场情绪
- 强势结构
- 异常变化
- 科技专项
- 观察清单

The prompt forbids invented news, fundamentals, earnings explanations, or external facts.

## Notes

- Large upward and downward mover tables are sorted by daily price change descending.
- Technology focus is built from stock-type labels such as software, semiconductor, cloud, internet, hardware, cyber security, optical communication, and related technology categories.
- PDF rendering is retained only as a fallback; the main email flow sends HTML links.
