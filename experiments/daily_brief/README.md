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
# Recommended key pool, read in numeric order.
TAVILY_API_KEY1=first_tavily_key
TAVILY_API_KEY2=second_tavily_key
# Legacy single-key/list formats remain supported.
TAVILY_API_KEY=your_tavily_api_key
TAVILY_API_KEYS=first_tavily_key,second_tavily_key
# One search task is tracked as 5 credits; each key has a 1000-credit monthly cap.
TAVILY_SEARCH_CREDITS=5
TAVILY_MONTHLY_CREDITS=1000
# Used only when creating a new cache; the cache settings take precedence afterwards.
TAVILY_RESET_DAY=1
# Optional; defaults to experiments/daily_brief/output/tavily_usage.json.
TAVILY_USAGE_FILE=experiments/daily_brief/output/tavily_usage.json
DAILY_BRIEF_PUBLIC_BASE_URL=https://your-domain.example/daily-briefs/files
```

`DEEPSEEK_MODEL` is optional and defaults to `deepseek-chat`. `DEEPSEEK_BASE_URL` can override the default compatible API endpoint if needed.

Qwen/DashScope remains available as a fallback when `--llm-model` starts with `qwen` or `dashscope:`. In that case, set `DASHSCOPE_API_KEY` or `BAILIAN_API_KEY`.

Tavily is used for the deep research pipeline when `--use-llm` is enabled. Use `TAVILY_API_KEY1`, `TAVILY_API_KEY2`, and so on for the preferred key pool; numeric suffixes are read in order. `TAVILY_API_KEYS` and `TAVILY_API_KEY` remain supported for old deployments. The local usage file keeps an anonymous per-key monthly credit ledger (key hashes only), selects the least-consumed eligible key for each search task, and skips a key once the configured monthly cap would be exceeded.

The cache contains `settings.reset_day` and each quota period's `resets_at` timestamp. The default reset day is the first day of the month; set `TAVILY_RESET_DAY` only before the cache is created, or edit `settings.reset_day` in the cache later. You may also edit a hashed key's `used_credits` to seed or correct the local balance. When the reset boundary passes, the next search automatically starts a new period without deleting history. If every key is unavailable or web search fails, generation continues with a partial/fallback quantitative report instead of aborting the daily brief.

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

The model pipeline writes a structured `model_interpretation` object with `summary`, Markdown `full_report`, compatibility `report`, `executive_points`, `research_context`, `evidence`, `audit`, and `pipeline` fields. The HTML renderer displays the summary in the interpretation card and opens an in-page drawer that prefers the Markdown full report, with structured `report` fallback for older JSON files. Evidence cards prefer model-generated Chinese `title_zh` and `summary_zh`, and Python normalizes source quality, source type, evidence tier, date relation, causality strength, and confidence.

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
- Executive summary: when LLM output includes `model_interpretation.executive_points`, the first-page conclusions use those model-refined points; otherwise the report falls back to rule-based `summary_points`.
- Distribution and alert sections: stable top 20, large upward movers, large downward movers, and current top 20.
- Current top 20 table and rank-history charts.
- Full-report drawer: citation markers such as `[1]` show a hover/click popover with source title, Chinese summary, evidence tier, source quality, causality strength, and matched audit warnings. The popover can jump to the compact source card or open the original URL.

## Prompt Design

`llm_analysis.py` builds a compact `research_context` from the daily JSON, plans up to 8 targeted search tasks with `deepseek-v4-pro`, prefilters search results into core/background/watchlist/rejected evidence tiers, extracts up to 24 evidence items with `deepseek-v4-pro`, writes a Markdown Chinese research report with `deepseek-v4-pro`, audits unsupported facts, overstated causality, date mismatches, source quality, evidence-tier misuse, number consistency, and investment-advice risk with `deepseek-chat`, then asks `deepseek-chat` to distill 4-6 first-page `executive_points` from the final audited report.

The writer returns a short `summary` for the daily box and a Markdown `full_report` with required sections: 核心结论, 市场结构, 驱动因素与证据, 驱动因素源头拆解, 趋势判断, 关键观察对象, 风险情景, 下一交易日观察, and 免责声明. `text` and a compatibility `report` object are still emitted for backward compatibility.

`executive_points` has the shape `[{text, rationale, evidence_ids, audit_note, priority}]`. It is a presentation layer summary only; generation failure falls back to existing `summary_points` and does not abort the daily brief.

The prompt forbids invented news, fundamentals, earnings explanations, or external facts that are not present in the evidence list. Only `core_evidence` with `can_support_core_driver=true` can support core drivers; background/watchlist evidence may only be used for context or uncertainty. Later-dated evidence can only be used as follow-up observation, not as a same-day market cause. All `deepseek-v4-pro` outputs are cleaned for `<think>` blocks, reasoning prefixes, draft leakage, and Markdown fences before parsing or rendering; malformed JSON is repaired by `deepseek-chat`.

## Notes

- Large upward and downward mover tables are sorted by daily price change descending.
- Technology focus is built from stock-type labels such as software, semiconductor, cloud, internet, hardware, cyber security, optical communication, and related technology categories.
- PDF rendering is retained only as a fallback; the main email flow sends HTML links.
