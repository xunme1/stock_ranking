# Daily Ranking Brief

This module generates a structured daily ranking-anomaly brief and a PDF report from the existing ranking cache.

## Data Source

The brief reads cached ranking files from:

```text
data/processed/rankings/ranking_window_10.csv
data/processed/rankings/ranking_window_20.csv
```

Generated JSON and PDF files are written to `experiments/daily_brief/output/`. The output folder is ignored by git.

## Environment

LLM analysis is optional. If you want the model to fill the first-page analysis, set one of these variables in `.env`:

```env
DASHSCOPE_API_KEY=your_api_key
BAILIAN_API_KEY=your_api_key
```

`DASHSCOPE_API_KEY` is checked first, then `BAILIAN_API_KEY`.

## Generate Without LLM

```powershell
.\.venv\Scripts\python.exe -B experiments\daily_brief\generate_brief_data.py --window 10
.\.venv\Scripts\python.exe -B experiments\daily_brief\render_pdf.py --input experiments\daily_brief\output\daily_brief_YYYY-MM-DD_w10.json
```

The generator includes a rule-based placeholder analysis, so the PDF can be rendered even when the model is not called.

## Generate With Qwen Analysis

```powershell
.\.venv\Scripts\python.exe -B experiments\daily_brief\generate_brief_data.py --window 10 --use-llm --llm-model qwen3.7-plus --llm-timeout 180 --llm-max-tokens 1500
.\.venv\Scripts\python.exe -B experiments\daily_brief\render_pdf.py --input experiments\daily_brief\output\daily_brief_YYYY-MM-DD_w10.json
```

The model call writes text into `model_interpretation.text`; the PDF renderer displays that text on page 1.

## Report Structure

- Page 1: QQQ rank, QQQ ATR score, QQQ distance from center, close date, and the long model-analysis block.
- Page 2: Stock-type distribution for stable top 20, large upward movers, large downward movers, and current top 20.
- Page 3: Technology focus, including technology top 10, technology type distribution, and notable technology gainers.
- Page 4: Current top 20 table.
- Page 5: Alert tables for stable top 20, large upward movers, and large downward movers.

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
- PDF rendering requires `reportlab`.
