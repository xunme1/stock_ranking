from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
DASHSCOPE_COMPAT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"


def _compact_items(items: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for item in items[:limit]:
        compacted.append(
            {
                "rank": item.get("rank"),
                "ticker": item.get("ticker"),
                "name": item.get("name"),
                "sector": item.get("sector"),
                "stock_type": item.get("stock_type"),
                "daily_change_pct": item.get("daily_change_pct"),
                "rank_change": item.get("rank_change"),
                "atr_score": item.get("atr_score"),
                "price_vs_center_pct": item.get("price_vs_center_pct"),
            }
        )
    return compacted


def build_analysis_payload(brief: dict[str, Any]) -> dict[str, Any]:
    tech = brief.get("technology_focus", {})
    return {
        "market": brief.get("market", "us"),
        "market_label": brief.get("market_label", "美股"),
        "benchmark_label": brief.get("benchmark_label", "QQQ"),
        "as_of_date": brief.get("as_of_date"),
        "window": brief.get("window"),
        "benchmark": brief.get("benchmark"),
        "summary_points": brief.get("summary_points", [])[:8],
        "type_stats": brief.get("type_stats", {}),
        "stable_top20": _compact_items(brief.get("stable_top20", []), 16),
        "upward_moves": _compact_items(brief.get("upward_moves", []), 16),
        "downward_moves": _compact_items(brief.get("downward_moves", []), 16),
        "entered_top20": _compact_items(brief.get("entered_top20", []), 10),
        "dropped_top20": _compact_items(brief.get("dropped_top20", []), 10),
        "top20": _compact_items(brief.get("top20", []), 20),
        "technology_focus": {
            "count": tech.get("count"),
            "top20_count": tech.get("top20_count"),
            "industry_distribution": tech.get("industry_distribution", []),
            "top10": _compact_items(tech.get("top10", []), 10),
            "strong_up": _compact_items(tech.get("strong_up", []), 10),
        },
    }


def build_llm_messages(brief: dict[str, Any]) -> list[dict[str, str]]:
    payload = build_analysis_payload(brief)
    market = str(brief.get("market", "us"))
    market_label = str(brief.get("market_label", "美股"))
    benchmark_label = str(brief.get("benchmark_label", "QQQ"))

    if market == "us":
        section_requirement = (
            "段落标题固定为：市场情绪、强势结构、异常变化、科技专项、观察清单。"
            "必须提到科技类股票前十和科技类显著上涨股票。"
        )
    else:
        section_requirement = (
            "段落标题固定为：市场情绪、强势结构、异常变化、类型占比、观察清单。"
            "不要写科技专项，不要强行分析科技股前十。"
        )

    system_prompt = (
        f"你是一名{market_label}强弱排名日报分析师。你只能根据用户给出的结构化排名数据做解读，"
        "不能编造新闻、财报、基本面、盘前盘后信息或未提供的外部事实。"
        "你的目标是帮助用户快速理解当日强势股、异常波动和类型占比。"
        "语气专业、克制、容易读，明确说明这不是投资建议。"
    )
    user_prompt = f"""
请根据下面的排名异常监测数据，生成适合放在 PDF 日报第一页的大段中文行情分析。
写作要求：
1. {section_requirement}
2. 总长度控制在 700-1000 个中文字符，让内容比普通摘要更充分。
3. 必须提到 {benchmark_label} 的相对位置、稳定前20数量、大幅上升/下降股票、股票类型占比。
4. 分析上涨/下跌时结合 daily_change_pct、rank_change、atr_score，不要只看排名变化。
5. 不要输出 Markdown 表格，不要输出代码块，不要编造新闻原因。
6. 结尾加一句“以上为量化排名解读，不构成投资建议。”

结构化数据 JSON：
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def load_dashscope_key() -> str:
    load_dotenv(ROOT_DIR / ".env")
    key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("BAILIAN_API_KEY")
    if not key:
        raise RuntimeError("Missing DASHSCOPE_API_KEY or BAILIAN_API_KEY in environment.")
    return key


def generate_model_interpretation(
    brief: dict[str, Any],
    model: str = "qwen3.7-plus",
    timeout: int = 60,
    max_tokens: int = 1500,
) -> dict[str, Any]:
    api_key = load_dashscope_key()
    response = requests.post(
        DASHSCOPE_COMPAT_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": build_llm_messages(brief),
            "temperature": 0.25,
            "top_p": 0.8,
            "max_tokens": max_tokens,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    text = data["choices"][0]["message"]["content"].strip()
    return {
        "status": "ok",
        "provider": "dashscope",
        "model": model,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "text": text,
    }
