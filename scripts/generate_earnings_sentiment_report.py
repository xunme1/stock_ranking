from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
EXPERIMENT_DIR = ROOT_DIR / "experiments" / "daily_brief"
for directory in (BACKEND_DIR, EXPERIMENT_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from app.core.config import EARNINGS_SENTIMENT_REPORT_DIR  # noqa: E402
from llm_analysis import DEFAULT_DEEPSEEK_MODEL, call_chat_model, tavily_search  # noqa: E402


CALENDAR_FILE = ROOT_DIR / "data" / "fundamental" / "earnings_calendar.csv"
HISTORY_FILE = ROOT_DIR / "data" / "fundamental" / "earnings_calendar_history.csv"


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None


def read_calendar_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return [{key: str(value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def recent_earnings(as_of_date: date, days: int) -> list[dict[str, str]]:
    start = as_of_date - timedelta(days=days - 1)
    selected: dict[tuple[str, str], dict[str, str]] = {}
    # The history is the source of truth for recent event candidates. Including
    # the current calendar also supports a first run before a second snapshot.
    for row in read_calendar_rows(HISTORY_FILE) + read_calendar_rows(CALENDAR_FILE):
        ticker = row.get("ticker", "").upper()
        earnings_date = row.get("earnings_date", "")
        event_date = parse_date(earnings_date)
        if ticker and event_date and start <= event_date <= as_of_date:
            selected[(ticker, earnings_date)] = row
    return sorted(selected.values(), key=lambda item: (item["earnings_date"], item["ticker"]), reverse=True)


def search_company(row: dict[str, str], as_of_date: date, max_results: int, timeout: int) -> list[dict[str, str]]:
    ticker = row["ticker"]
    name = row.get("company_name") or ticker
    query = f"{ticker} {name} earnings results analyst reaction {row['earnings_date']}"
    try:
        results = tavily_search(query, max_results=max_results, timeout=timeout)
    except Exception as exc:  # A report is still archived when a search provider is unavailable.
        return [{"title": "检索失败", "url": "", "source": "", "snippet": str(exc)}]
    output = []
    for item in results[:max_results]:
        output.append(
            {
                "title": str(item.get("title") or "")[:240],
                "url": str(item.get("url") or ""),
                "source": str(item.get("url") or "").split("/")[2] if "/" in str(item.get("url") or "") else "",
                "snippet": str(item.get("content") or item.get("snippet") or "")[:450],
            }
        )
    return output


def parse_json(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    data = json.loads(candidate)
    return data if isinstance(data, dict) else {}


def analyze(rows: list[dict[str, str]], evidence: dict[str, list[dict[str, str]]], as_of_date: date, model: str, timeout: int, max_tokens: int) -> tuple[dict[str, Any], str, str]:
    payload = []
    for row in rows:
        payload.append({"ticker": row["ticker"], "company_name": row.get("company_name", ""), "calendar_date": row["earnings_date"], "sources": evidence.get(row["ticker"], [])})
    messages = [
        {"role": "system", "content": "你是严谨的美股财报舆情分析师。只能依据提供的搜索结果，不得编造业绩、媒体观点、发布日期或链接。"},
        {"role": "user", "content": "请针对近三日财报候选公司输出中文 JSON。字段：overall_sentiment（positive/neutral/negative/mixed）、summary、companies（ticker、reported、actual_release_date、sentiment、summary、media_view、key_points 数组、source_urls 数组）、risk_notes 数组。每一家候选公司都必须有一条 companies 记录；即使证据不足，也必须以“有限证据”开头，谨慎概述搜索片段中已经出现的预期、业绩、指引或市场反应，不能只写暂无观点。reported 仅在搜索结果明确显示已发布财报时为 true；若日期只是日历预期或证据不足则为 false。source_urls 必须仅使用输入中的 URL。\n\n截至日期：" + as_of_date.isoformat() + "\n数据：" + json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        text, provider, model_name = call_chat_model(messages, model, timeout, max_tokens, temperature=0.2, json_mode=True)
        return parse_json(text), provider, model_name
    except Exception as exc:
        return {"overall_sentiment": "neutral", "summary": f"模型分析暂不可用：{exc}", "companies": [], "risk_notes": ["请稍后重新生成，或检查 DeepSeek/DashScope 与 Tavily 配置。"]}, "unavailable", model


def safe_list(value: Any) -> list[str]:
    return [str(item).strip() for item in value] if isinstance(value, list) else []


def evidence_viewpoint(sources: list[dict[str, str]]) -> str:
    snippets = [str(source.get("snippet") or "").strip() for source in sources if source.get("snippet") and source.get("url")]
    if snippets:
        return f"有限证据下的检索观点：{snippets[0][:280]}"
    titles = [str(source.get("title") or "").strip() for source in sources if source.get("title") and source.get("url")]
    if titles:
        return f"有限证据下，检索结果主要指向：{titles[0]}"
    return "未检索到足以概述的公开观点。"


def report_html(as_of_date: date, rows: list[dict[str, str]], evidence: dict[str, list[dict[str, str]]], analysis: dict[str, Any], provider: str, model: str) -> str:
    companies = analysis.get("companies") if isinstance(analysis.get("companies"), list) else []
    by_ticker = {str(item.get("ticker") or "").upper(): item for item in companies if isinstance(item, dict)}
    sentiment = str(analysis.get("overall_sentiment") or "neutral")
    cards = []
    for row in rows:
        ticker = row["ticker"]
        item = by_ticker.get(ticker, {})
        source_rows = evidence.get(ticker, [])
        fallback_viewpoint = evidence_viewpoint(source_rows)
        valid_urls = {source["url"] for source in evidence.get(ticker, []) if source.get("url")}
        chosen_urls = [url for url in safe_list(item.get("source_urls")) if url in valid_urls] or list(valid_urls)[:3]
        source_lookup = {source["url"]: source for source in evidence.get(ticker, [])}
        links = "".join(f'<li><a href="{html.escape(url, quote=True)}" target="_blank" rel="noreferrer">{html.escape(source_lookup.get(url, {}).get("title") or url)}</a></li>' for url in chosen_urls) or "<li>未检索到可引用的公开来源</li>"
        fallback_points = [str(source.get("title") or "").strip() for source in source_rows if source.get("title") and source.get("url")][:2]
        points = "".join(f"<li>{html.escape(point)}</li>" for point in safe_list(item.get("key_points")) or fallback_points) or "<li>未检索到足以概述的公开观点。</li>"
        reported = "已确认发布" if item.get("reported") is True else "待公开资料确认"
        summary = str(item.get("summary") or "").strip() or fallback_viewpoint
        media_view = str(item.get("media_view") or "").strip() or fallback_viewpoint
        cards.append(f'''<article class="card"><div class="card-head"><div><h2>{html.escape(ticker)} <small>{html.escape(row.get("company_name") or "")}</small></h2><p>日历日期：{html.escape(row["earnings_date"])} · {reported}</p></div><span class="tag {html.escape(str(item.get("sentiment") or "neutral"))}">{html.escape(str(item.get("sentiment") or "neutral"))}</span></div><p class="company-summary">{html.escape(summary)}</p><p><b>媒体风向：</b>{html.escape(media_view)}</p><h3>关注要点</h3><ul>{points}</ul><h3>来源</h3><ul class="sources">{links}</ul></article>''')
    if not cards:
        cards.append("<section class='empty'>近三日没有来自财报日历的发布候选公司。本报告仍已归档。</section>")
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>美股财报舆情日报 {as_of_date}</title><style>body{{margin:0;background:#f4f7fb;color:#18212f;font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}}main{{max-width:1100px;margin:auto;padding:32px 20px 56px}}header,.card,.empty{{background:#fff;border:1px solid #d8e0eb;border-radius:12px;box-shadow:0 4px 18px #19304a0c}}header{{padding:24px 26px;margin-bottom:18px}}h1,h2,h3,p{{margin-top:0}}h1{{margin-bottom:6px}}.meta,.card-head p{{color:#607086}}.summary{{font-size:17px}}.grid{{display:grid;gap:14px}}.card{{padding:20px}}.card-head{{display:flex;justify-content:space-between;gap:12px}}.card h2{{margin-bottom:2px}}small{{font-size:13px;color:#607086;font-weight:500}}.tag{{height:fit-content;border-radius:999px;padding:4px 10px;font-weight:800;font-size:12px;background:#edf2f7}}.tag.positive{{background:#dcfce7;color:#167343}}.tag.negative{{background:#fee2e2;color:#b42318}}.tag.mixed{{background:#fef3c7;color:#925d00}}.sources a{{color:#1f6feb}}.empty{{padding:24px;text-align:center;color:#607086}}</style></head><body><main><header><p class="meta">US Earnings Sentiment Daily · 最近三日窗口</p><h1>美股财报舆情日报｜{as_of_date.isoformat()}</h1><p class="summary">{html.escape(str(analysis.get("summary") or "暂无汇总结论。"))}</p><p class="meta">整体风向：{html.escape(sentiment)} · 模型：{html.escape(str(model or "default"))} · 提供方：{html.escape(str(provider or "unavailable"))} · 仅基于公开检索结果，非投资建议。</p></header><section class="grid">{''.join(cards)}</section></main></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and archive a three-day US earnings sentiment report.")
    parser.add_argument("--as-of-date", default=None, help="YYYY-MM-DD; defaults to today.")
    parser.add_argument("--days", type=int, default=3, choices=range(1, 8))
    parser.add_argument("--max-stocks", type=int, default=12)
    parser.add_argument("--max-results", type=int, default=3)
    parser.add_argument("--model", default=DEFAULT_DEEPSEEK_MODEL)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--max-tokens", type=int, default=5000)
    args = parser.parse_args()
    as_of_date = parse_date(args.as_of_date) if args.as_of_date else date.today()
    if as_of_date is None:
        raise ValueError("--as-of-date must be YYYY-MM-DD")
    rows = recent_earnings(as_of_date, args.days)[: args.max_stocks]
    evidence = {row["ticker"]: search_company(row, as_of_date, args.max_results, args.timeout) for row in rows}
    if rows:
        analysis, provider, model_name = analyze(rows, evidence, as_of_date, args.model, args.timeout, args.max_tokens)
    else:
        analysis = {"overall_sentiment": "neutral", "summary": "近三日没有来自财报日历的发布候选公司。", "companies": [], "risk_notes": []}
        provider, model_name = "not_called", args.model or "default"
    EARNINGS_SENTIMENT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    output = EARNINGS_SENTIMENT_REPORT_DIR / f"earnings_sentiment_{as_of_date.isoformat()}.html"
    output.write_text(report_html(as_of_date, rows, evidence, analysis, provider, model_name), encoding="utf-8")
    print(f"Candidates: {len(rows)}")
    print(f"Output: {output}")


if __name__ == "__main__":
    main()
