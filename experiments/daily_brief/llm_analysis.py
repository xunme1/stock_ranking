from __future__ import annotations

import json
import math
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
DASHSCOPE_COMPAT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DEEPSEEK_COMPAT_URL = "https://api.deepseek.com/chat/completions"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_DEEPSEEK_PRO_MODEL = "deepseek-v4-pro"
MAX_RESEARCH_TASKS = 8
MAX_EVIDENCE_ITEMS = 24
MIN_FULL_REPORT_CHARS = 1800
MAX_PREFILTERED_SEARCH_RESULTS = 40
EVENT_KEYWORDS = (
    "公告",
    "财报",
    "业绩",
    "预告",
    "监管",
    "政策",
    "减持",
    "增持",
    "回购",
    "guidance",
    "earnings",
    "results",
    "outlook",
    "forecast",
    "sec",
    "filing",
    "approval",
    "regulatory",
    "policy",
)
REQUIRED_REPORT_SECTIONS = (
    "核心结论",
    "市场结构",
    "驱动因素与证据",
    "驱动因素源头拆解",
    "趋势判断",
    "关键观察对象",
    "风险情景",
    "下一交易日观察",
)

PRIMARY_SOURCE_DOMAINS = (
    "sec.gov",
    "nasdaq.com",
    "nyse.com",
    "hkexnews.hk",
    "sse.com.cn",
    "szse.cn",
    "hkex.com.hk",
    "investor.",
    "ir.",
)
MAINSTREAM_SOURCE_DOMAINS = (
    "reuters.com",
    "bloomberg.com",
    "cnbc.com",
    "wsj.com",
    "marketwatch.com",
    "finance.yahoo.com",
    "caixin.com",
    "stcn.com",
    "21jingji.com",
)

FINAL_SECTION_RE = re.compile(r"(市场情绪|强势结构|异常变化|科技专项|类型占比|观察清单|核心摘要|完整研报)\s*[：:\n]")
OPENING_SECTION_RE = re.compile(r"(市场情绪|核心摘要|完整研报)\s*[：:\n]")
THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.IGNORECASE | re.DOTALL)
THINK_PREFIX_RE = re.compile(r"^\s*(思考过程|推理过程|分析过程|Reasoning|Thought process)\s*[：:\n]", re.IGNORECASE)
REASONING_LEAK_RE = re.compile(r"^\s*(我们需要|需要解读|要求[:：]|We need|We are asked)", re.IGNORECASE)
DRAFT_LEAK_RE = re.compile(r"(可以提到|描述\s*QQQ|描述.*相对位置|需要解读数据|给定\s*JSON|写作要求)")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _elapsed(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _bounded_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _safe_float(value: Any) -> float | None:
    quality_issues: list[str] = []
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _domain(url: str) -> str:
    host = urlparse(str(url or "")).netloc.lower()
    return host.removeprefix("www.")


def _url_key(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if not parsed.netloc:
        return str(url or "").strip().rstrip("/")
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower().removeprefix('www.')}{path}".rstrip("/")


def _source_quality(url: str) -> str:
    host = _domain(url)
    if any(token in host for token in PRIMARY_SOURCE_DOMAINS):
        return "primary"
    if any(host.endswith(token) or token in host for token in MAINSTREAM_SOURCE_DOMAINS):
        return "mainstream"
    return "other"


def _source_type(url: str) -> str:
    host = _domain(url)
    if any(token in host for token in ("investor.", "ir.")):
        return "company"
    if any(token in host for token in ("sec.gov", "sse.com.cn", "szse.cn", "hkexnews.hk", "hkex.com.hk")):
        return "regulator"
    if any(token in host for token in ("nasdaq.com", "nyse.com")):
        return "exchange"
    if _source_quality(url) == "mainstream":
        return "media"
    return "other"


def _parse_date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text, text[:10]):
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            continue
    return None


def _date_relation(value: Any, as_of_value: Any) -> str:
    parsed = _parse_date(value)
    as_of = _parse_date(as_of_value)
    if not parsed or not as_of:
        return "unknown"
    if parsed.date() > as_of.date():
        return "after_as_of"
    if parsed.date() == as_of.date():
        return "same_day"
    return "before_as_of"


def _days_from_as_of(value: Any, as_of_value: Any) -> int | None:
    parsed = _parse_date(value)
    as_of = _parse_date(as_of_value)
    if not parsed or not as_of:
        return None
    return (as_of.date() - parsed.date()).days


def _tokenize_query_text(value: Any) -> set[str]:
    text = str(value or "").lower()
    tokens = set(re.findall(r"[a-z0-9.\-]{2,}|[\u4e00-\u9fff]{2,}", text))
    stop_words = {
        "stock",
        "stocks",
        "news",
        "market",
        "earnings",
        "announcement",
        "日报",
        "市场",
        "股票",
        "行业",
    }
    return {token for token in tokens if token not in stop_words}


def _compact_items(items: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for item in items[:limit]:
        compacted.append(
            {
                "rank": item.get("rank"),
                "ticker": item.get("ticker"),
                "name": item.get("name"),
                "display": item.get("display"),
                "sector": item.get("sector"),
                "stock_type": item.get("stock_type"),
                "daily_change_pct": item.get("daily_change_pct"),
                "rank_change": item.get("rank_change"),
                "atr_score": item.get("atr_score"),
                "price_vs_center_pct": item.get("price_vs_center_pct"),
                "price_change_3d_pct": item.get("price_change_3d_pct"),
            }
        )
    return compacted


def _label(item: dict[str, Any]) -> str:
    return str(item.get("display") or item.get("name") or item.get("ticker") or "").strip()


def _names(items: list[dict[str, Any]], limit: int = 5) -> str:
    values = [_label(item) for item in items[:limit]]
    values = [value for value in values if value]
    return "、".join(values) if values else "暂无"


def _item_identity(item: dict[str, Any]) -> str:
    return str(item.get("ticker") or item.get("display") or item.get("name") or "").strip().upper()


def _safe_pct(part: int | float, total: int | float) -> float:
    if not total:
        return 0.0
    return round(float(part) / float(total) * 100, 2)


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _string_list(value: Any, limit: int = 8) -> list[str]:
    result: list[str] = []
    for item in _listify(value):
        if isinstance(item, dict):
            text = item.get("text") or item.get("summary") or item.get("analysis") or item.get("title")
        else:
            text = item
        text = str(text or "").strip()
        if text:
            result.append(text[:800])
    return result[:limit]


def _compact_subject(item: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
    return {
        "ticker": item.get("ticker"),
        "display": item.get("display"),
        "name": item.get("name"),
        "rank": item.get("rank"),
        "daily_change_pct": item.get("daily_change_pct"),
        "rank_change": item.get("rank_change"),
        "atr_score": item.get("atr_score"),
        "price_vs_center_pct": item.get("price_vs_center_pct"),
        "price_change_3d_pct": item.get("price_change_3d_pct"),
        "stock_type": item.get("stock_type"),
        "sector": item.get("sector"),
        "reason": reason,
    }


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
        "dual_window_top20": _compact_items(brief.get("dual_window_top20", []), 20),
        "technology_focus": {
            "count": tech.get("count"),
            "top20_count": tech.get("top20_count"),
            "industry_distribution": tech.get("industry_distribution", []),
            "top10": _compact_items(tech.get("top10", []), 10),
            "strong_up": _compact_items(tech.get("strong_up", []), 10),
        },
    }


def validate_brief_data(brief: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    required_fields = ["market", "as_of_date", "window", "benchmark", "top20", "upward_moves", "downward_moves"]
    for field in required_fields:
        if field not in brief:
            issues.append({"severity": "error", "code": "missing_field", "message": f"缺失字段: {field}"})

    parsed_as_of = _parse_date(brief.get("as_of_date"))
    if not parsed_as_of:
        issues.append({"severity": "error", "code": "invalid_date", "message": "as_of_date 不是有效日期"})

    recent_dates = [str(item) for item in brief.get("recent_dates", []) if str(item).strip()]
    if parsed_as_of and recent_dates and str(brief.get("as_of_date")) not in recent_dates:
        issues.append({"severity": "warning", "code": "date_mismatch", "message": "as_of_date 不在 recent_dates 中"})

    numeric_ranges = {
        "rank": (1, 10000),
        "daily_change_pct": (-100, 300),
        "price_change_3d_pct": (-100, 500),
        "price_vs_center_pct": (-200, 500),
        "atr_score": (-100, 100),
    }
    list_fields = ["top20", "stable_top20", "upward_moves", "downward_moves", "entered_top20", "dropped_top20"]
    for list_field in list_fields:
        values = brief.get(list_field, [])
        if values is None:
            continue
        if not isinstance(values, list):
            issues.append({"severity": "error", "code": "invalid_type", "message": f"{list_field} 必须是数组"})
            continue
        seen: set[str] = set()
        for index, item in enumerate(values):
            if not isinstance(item, dict):
                issues.append({"severity": "error", "code": "invalid_item", "message": f"{list_field}[{index}] 不是对象"})
                continue
            ticker = str(item.get("ticker") or "").strip()
            if not ticker:
                issues.append({"severity": "warning", "code": "missing_ticker", "message": f"{list_field}[{index}] 缺少 ticker"})
            elif ticker in seen:
                issues.append({"severity": "warning", "code": "duplicate_ticker", "message": f"{list_field} 中重复股票: {ticker}"})
            seen.add(ticker)
            for key, (minimum, maximum) in numeric_ranges.items():
                if key not in item or item.get(key) is None:
                    continue
                number = _safe_float(item.get(key))
                if number is None:
                    issues.append({"severity": "warning", "code": "invalid_number", "message": f"{ticker or list_field}.{key} 不是有效数值"})
                elif number < minimum or number > maximum:
                    issues.append({"severity": "warning", "code": "number_out_of_range", "message": f"{ticker or list_field}.{key} 超出范围: {number}"})

    status = "error" if any(item["severity"] == "error" for item in issues) else "warning" if issues else "ok"
    return {
        "status": status,
        "checked_at": _now(),
        "issue_count": len(issues),
        "issues": issues,
    }


def _top_type(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return rows[0] if rows else {"stock_type": "暂无", "count": 0, "pct": 0}


def extract_research_features(brief: dict[str, Any]) -> dict[str, Any]:
    top20 = brief.get("top20", []) or []
    upward = brief.get("upward_moves", []) or []
    downward = brief.get("downward_moves", []) or []
    entered = brief.get("entered_top20", []) or []
    dropped = brief.get("dropped_top20", []) or []
    stable = brief.get("stable_top20", []) or []
    benchmark = brief.get("benchmark", {}) or {}
    type_stats = brief.get("type_stats", {}) or {}
    tech = brief.get("technology_focus", {}) or {}

    avg_top20_change = None
    if top20:
        changes = [_safe_float(item.get("daily_change_pct")) for item in top20]
        changes = [item for item in changes if item is not None]
        avg_top20_change = round(sum(changes) / len(changes), 2) if changes else None

    positive_count = sum(1 for item in top20 if (_safe_float(item.get("daily_change_pct")) or 0) > 0)
    benchmark_rank = _safe_float(benchmark.get("rank"))
    benchmark_strength_gap = round((benchmark_rank or 0) - 20, 2) if benchmark_rank is not None else None
    turnover_rate = _safe_pct(len(entered) + len(dropped), len(top20) or 20)
    top20_leading_type = _top_type(type_stats.get("top20", []))
    leader_concentration_pct = _safe_float(top20_leading_type.get("pct"))
    if leader_concentration_pct is None:
        leader_concentration_pct = _safe_pct(_safe_int(top20_leading_type.get("count")) or 0, len(top20) or 1)
    abnormal_up = [
        _compact_subject(item, "large_up_or_rank_jump")
        for item in upward
        if abs(_safe_float(item.get("daily_change_pct")) or 0) >= 5 or abs(_safe_float(item.get("rank_change")) or 0) >= 20
    ]
    abnormal_down = [
        _compact_subject(item, "large_down_or_rank_drop")
        for item in downward
        if abs(_safe_float(item.get("daily_change_pct")) or 0) >= 5 or abs(_safe_float(item.get("rank_change")) or 0) >= 20
    ]

    key_subjects = []
    seen_subjects: set[str] = set()
    for source, rows, limit in (
        ("top_leaders", top20, 5),
        ("upward_moves", upward, 6),
        ("downward_moves", downward, 6),
        ("entered_top20", entered, 4),
        ("dropped_top20", dropped, 4),
        ("technology_focus", tech.get("strong_up", []) or [], 4),
    ):
        for item in rows[:limit]:
            identity = _item_identity(item)
            if not identity or identity in seen_subjects:
                continue
            seen_subjects.add(identity)
            subject = _compact_subject(item, source)
            subject["source"] = source
            key_subjects.append(subject)

    return {
        "market_state": {
            "market": brief.get("market"),
            "market_label": brief.get("market_label"),
            "as_of_date": brief.get("as_of_date"),
            "window": brief.get("window"),
            "benchmark_label": brief.get("benchmark_label"),
            "benchmark_rank": benchmark.get("rank"),
            "benchmark_atr_score": benchmark.get("atr_score"),
            "benchmark_price_vs_center_pct": benchmark.get("price_vs_center_pct"),
            "benchmark_3d_change_pct": benchmark.get("price_change_3d_pct"),
            "benchmark_strength_gap_to_top20": benchmark_strength_gap,
            "top20_avg_daily_change_pct": avg_top20_change,
            "top20_positive_count": positive_count,
            "top20_positive_rate_pct": _safe_pct(positive_count, len(top20)),
            "top20_count": len(top20),
        },
        "industry_strength": {
            "top20": type_stats.get("top20", []),
            "stable_top20": type_stats.get("stable_top20", []),
            "upward_moves": type_stats.get("upward_moves", []),
            "downward_moves": type_stats.get("downward_moves", []),
            "top20_leading_type": top20_leading_type,
            "upward_leading_type": _top_type(type_stats.get("upward_moves", [])),
            "downward_leading_type": _top_type(type_stats.get("downward_moves", [])),
            "leader_concentration_pct": leader_concentration_pct,
        },
        "turnover": {
            "stable_top20_count": len(stable),
            "entered_top20_count": len(entered),
            "dropped_top20_count": len(dropped),
            "upward_move_count": len(upward),
            "downward_move_count": len(downward),
            "top20_turnover_rate_pct": turnover_rate,
            "entered_names": [_label(item) for item in entered[:8]],
            "dropped_names": [_label(item) for item in dropped[:8]],
        },
        "anomalies": {
            "large_up_or_rank_jump": abnormal_up[:8],
            "large_down_or_rank_drop": abnormal_down[:8],
            "large_up_count": len(abnormal_up),
            "large_down_count": len(abnormal_down),
        },
        "technology": {
            "count": tech.get("count", 0),
            "top20_count": tech.get("top20_count", 0),
            "industry_distribution": tech.get("industry_distribution", []),
            "top10": _compact_items(tech.get("top10", []), 10),
            "strong_up": _compact_items(tech.get("strong_up", []), 10),
        },
        "key_subjects": key_subjects[:24],
    }


def build_research_context(
    brief: dict[str, Any],
    validation: dict[str, Any],
    features: dict[str, Any],
) -> dict[str, Any]:
    market = features.get("market_state", {})
    industry = features.get("industry_strength", {})
    turnover = features.get("turnover", {})
    anomalies = features.get("anomalies", {})
    technology = features.get("technology", {})
    benchmark_label = market.get("benchmark_label") or brief.get("benchmark_label") or "基准"
    top_type = industry.get("top20_leading_type", {}) or {}
    up_type = industry.get("upward_leading_type", {}) or {}
    down_type = industry.get("downward_leading_type", {}) or {}
    key_objects = []
    for item in features.get("key_subjects", [])[:18]:
        key_objects.append(
            {
                "ticker": item.get("ticker"),
                "display": item.get("display") or item.get("name"),
                "stock_type": item.get("stock_type"),
                "sector": item.get("sector"),
                "rank": item.get("rank"),
                "daily_change_pct": item.get("daily_change_pct"),
                "rank_change": item.get("rank_change"),
                "why_research": item.get("reason") or item.get("source"),
            }
        )

    research_questions = [
        f"{benchmark_label} 排名与 Top20 强势股之间是否存在明显强弱背离？",
        f"Top20 换手率 {turnover.get('top20_turnover_rate_pct')}% 是否意味着主线扩散或切换？",
        f"Top20 主要类型 {top_type.get('stock_type')} 的集中度是否足以支撑趋势延续？",
        f"上升集中在 {up_type.get('stock_type')}、下降集中在 {down_type.get('stock_type')} 是否对应公开事件或行业逻辑？",
    ]
    if anomalies.get("large_up_count") or anomalies.get("large_down_count"):
        research_questions.append("大幅上升/下降个股是否存在可验证的公告、财报、监管或宏观事件？")
    if technology.get("top20_count"):
        research_questions.append("科技观察池进入 Top20 的比例是否说明风险偏好或题材拥挤度变化？")

    return {
        "as_of_date": brief.get("as_of_date"),
        "market": brief.get("market"),
        "market_label": brief.get("market_label"),
        "benchmark_label": benchmark_label,
        "data_facts": {
            "benchmark": {
                "rank": market.get("benchmark_rank"),
                "atr_score": market.get("benchmark_atr_score"),
                "price_vs_center_pct": market.get("benchmark_price_vs_center_pct"),
                "price_change_3d_pct": market.get("benchmark_3d_change_pct"),
            },
            "top20": {
                "count": market.get("top20_count"),
                "avg_daily_change_pct": market.get("top20_avg_daily_change_pct"),
                "positive_count": market.get("top20_positive_count"),
                "positive_rate_pct": market.get("top20_positive_rate_pct"),
            },
            "turnover": turnover,
            "industry": {
                "top20_leading_type": top_type,
                "upward_leading_type": up_type,
                "downward_leading_type": down_type,
                "leader_concentration_pct": industry.get("leader_concentration_pct"),
            },
        },
        "derived_signals": {
            "benchmark_strength_gap_to_top20": market.get("benchmark_strength_gap_to_top20"),
            "top20_turnover_rate_pct": turnover.get("top20_turnover_rate_pct"),
            "leader_concentration_pct": industry.get("leader_concentration_pct"),
            "large_up_count": anomalies.get("large_up_count"),
            "large_down_count": anomalies.get("large_down_count"),
            "technology_top20_count": technology.get("top20_count"),
            "validation_status": validation.get("status"),
        },
        "research_questions": research_questions,
        "key_objects": key_objects,
        "source_slices": {
            "top20": _compact_items(brief.get("top20", []), 12),
            "upward_moves": _compact_items(brief.get("upward_moves", []), 12),
            "downward_moves": _compact_items(brief.get("downward_moves", []), 12),
            "entered_top20": _compact_items(brief.get("entered_top20", []), 8),
            "dropped_top20": _compact_items(brief.get("dropped_top20", []), 8),
        },
    }


def fallback_summary(brief: dict[str, Any], features: dict[str, Any] | None = None) -> str:
    features = features or extract_research_features(brief)
    market = features.get("market_state", {})
    industry = features.get("industry_strength", {})
    turnover = features.get("turnover", {})
    benchmark_label = market.get("benchmark_label") or brief.get("benchmark_label") or "基准"
    top_type = industry.get("top20_leading_type", {}).get("stock_type", "暂无")
    up_type = industry.get("upward_leading_type", {}).get("stock_type", "暂无")
    down_type = industry.get("downward_leading_type", {}).get("stock_type", "暂无")
    return (
        f"截至 {market.get('as_of_date')}，{benchmark_label} 排名 #{market.get('benchmark_rank')}，"
        f"ATR 倍数 {market.get('benchmark_atr_score')}，Top20 平均日涨跌为 {market.get('top20_avg_daily_change_pct')}%。"
        f"稳定前20共有 {turnover.get('stable_top20_count', 0)} 只，进入/跌出前20分别为 "
        f"{turnover.get('entered_top20_count', 0)}/{turnover.get('dropped_top20_count', 0)} 只。"
        f"当前 Top20 主要类型为 {top_type}，大幅上升集中在 {up_type}，下行压力集中在 {down_type}。"
        "以上为量化排名解读，不构成投资建议。"
    )


def fallback_full_report(brief: dict[str, Any], features: dict[str, Any] | None = None) -> str:
    features = features or extract_research_features(brief)
    market = features.get("market_state", {})
    industry = features.get("industry_strength", {})
    turnover = features.get("turnover", {})
    tech = features.get("technology", {})
    benchmark_label = market.get("benchmark_label") or brief.get("benchmark_label") or "基准"
    return (
        "核心摘要\n"
        f"{fallback_summary(brief, features)}\n\n"
        "量化结构\n"
        f"{benchmark_label} 当前排名 #{market.get('benchmark_rank')}，价格相对重心偏离 "
        f"{market.get('benchmark_price_vs_center_pct')}%，近3日涨跌 {market.get('benchmark_3d_change_pct')}%。"
        f"Top20 中 {market.get('top20_positive_count')} 只收涨，说明榜单内部的价格确认度需要结合换手观察。\n\n"
        "行业强弱\n"
        f"Top20 主要类型分布为 {json.dumps(industry.get('top20', [])[:5], ensure_ascii=False)}。"
        f"上升榜单主要类型为 {json.dumps(industry.get('upward_moves', [])[:5], ensure_ascii=False)}；"
        f"下降榜单主要类型为 {json.dumps(industry.get('downward_moves', [])[:5], ensure_ascii=False)}。\n\n"
        "榜单换手\n"
        f"最近5个交易日稳定前20为 {turnover.get('stable_top20_count')} 只，"
        f"新进入前20包括 {'、'.join(turnover.get('entered_names', [])[:6]) or '暂无'}，"
        f"跌出前20包括 {'、'.join(turnover.get('dropped_names', [])[:6]) or '暂无'}。\n\n"
        "科技观察\n"
        f"科技观察池共 {tech.get('count', 0)} 只，其中 {tech.get('top20_count', 0)} 只进入总榜前20。"
        "若没有外部证据支持，本报告不将单日异动归因于新闻、财报或宏观事件。\n\n"
        "以上为量化排名解读，不构成投资建议。"
    )


def build_llm_messages(brief: dict[str, Any]) -> list[dict[str, str]]:
    payload = build_analysis_payload(brief)
    benchmark_label = str(brief.get("benchmark_label", "QQQ"))
    return [
        {
            "role": "system",
            "content": "你是严谨的量化排名日报分析师。只能基于给定 JSON 写作，不得编造外部事实。",
        },
        {
            "role": "user",
            "content": (
                "请根据下方结构化数据生成中文量化日报摘要，必须覆盖基准相对位置、稳定前20、"
                "大幅上升/下降、类型占比和观察清单。结尾写明不构成投资建议。"
                f"基准: {benchmark_label}\nJSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
            ),
        },
    ]


def build_research_plan_messages(
    brief: dict[str, Any],
    validation: dict[str, Any],
    features: dict[str, Any],
    research_context: dict[str, Any],
) -> list[dict[str, str]]:
    payload = {
        "research_context": research_context,
        "validation": validation,
        "features": features,
    }
    return [
        {
            "role": "system",
            "content": (
                "你是研究规划模型。根据量化日报特征生成研究计划和联网搜索任务。"
                "只输出 JSON，不输出 Markdown。搜索任务要围绕榜单异动、行业强弱、关键股票和基准。"
            ),
        },
        {
            "role": "user",
            "content": (
                "输出格式: {\"research_questions\":[...],\"search_tasks\":["
                "{\"query\":\"...\",\"target\":\"...\",\"reason\":\"...\",\"priority\":1}]}。\n"
                "搜索任务只围绕异常行业、关键股票、基准指数/ETF、宏观/政策/监管事件生成，最多 8 个高价值任务。"
                "不要为每只股票机械生成任务。搜索 query 应包含股票代码或公司名、事件关键词、日期或市场名称。\n"
                f"输入 JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
            ),
        },
    ]


def build_evidence_messages(
    brief: dict[str, Any],
    features: dict[str, Any],
    research_context: dict[str, Any],
    research_plan: dict[str, Any],
    search_results: list[dict[str, Any]],
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是证据提取模型。只能从搜索结果中提取可支持研报结论的证据。"
                "不要补充搜索结果之外的事实。为每条证据生成中文标题和中文摘要。"
                "输入搜索结果已经过 Python 预筛，包含 evidence_tier、evidence_score、can_support_core_driver。"
                "晚于日报日期的材料不能作为当日行情原因，只能标记为后续观察。只输出 JSON。"
            ),
        },
        {
            "role": "user",
            "content": (
                "输出格式: {\"evidence\":[{\"id\":\"1\",\"title\":\"...\",\"url\":\"...\","
                "\"title_zh\":\"中文标题\",\"summary_zh\":\"80字以内中文摘要\",\"source\":\"...\",\"published_at\":\"...\","
                "\"event_date\":\"...\",\"topic\":\"...\",\"claim\":\"搜索结果支持的事实主张\",\"affected_tickers\":[\"...\"],"
                "\"source_type\":\"company|exchange|regulator|media|data|other\",\"source_quality\":\"primary|mainstream|other\","
                "\"evidence_tier\":\"core_evidence|background_evidence|watchlist_evidence\",\"can_support_core_driver\":true,"
                "\"supports_json_signal\":true,\"causality_strength\":\"strong|medium|weak|follow_up|none\","
                "\"confidence\":0.0,\"snippet\":\"...\",\"relevance\":\"这条证据支持了哪个结论或研究问题\",\"used_by\":[\"...\"]}]}。"
                "最多保留 24 条，优先 core_evidence。"
                "Python 标记 can_support_core_driver=false 或 source_quality=other 的材料只能作为背景或待验证线索，不得升级为核心驱动。\n"
                f"日报日期: {brief.get('as_of_date')}\n"
                f"研究上下文:\n{json.dumps(research_context, ensure_ascii=False, indent=2)}\n"
                f"特征:\n{json.dumps(features, ensure_ascii=False, indent=2)}\n"
                f"研究计划:\n{json.dumps(research_plan, ensure_ascii=False, indent=2)}\n"
                f"搜索结果:\n{json.dumps(search_results, ensure_ascii=False, indent=2)}"
            ),
        },
    ]


def build_writer_messages(
    brief: dict[str, Any],
    validation: dict[str, Any],
    features: dict[str, Any],
    research_context: dict[str, Any],
    research_plan: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是机构风格的中文研报写作模型。以量化排名为主线，外部事件只能来自 evidence，"
                "引用用 [1]、[2] 这样的编号。不要把没有证据的猜测写成事实。"
                "只输出 JSON 外壳，不输出 Markdown fence，不输出思考过程。"
            ),
        },
        {
            "role": "user",
            "content": (
                "输出 JSON: {\"summary\":\"用于日报卡片的 250-450 字中文摘要\","
                "\"full_report\":\"完整 Markdown 中文研报\"}。\n"
                "full_report 必须是长篇 Markdown 正文，必须包含以下二级标题："
                "核心结论、市场结构、驱动因素与证据、驱动因素源头拆解、趋势判断、关键观察对象、风险情景、下一交易日观察、免责声明。\n"
                "驱动因素与证据必须逐条展开，每条至少写：现象、源头、证据、影响链条、置信度、不确定性、引用编号。"
                "趋势判断必须写足逻辑链：量化信号、证据支持、反证条件、后续验证指标。"
                "若 evidence 为空，只写量化结构，不做新闻归因。"
                "只有 evidence_tier=core_evidence 且 can_support_core_driver=true 的证据可以支撑核心驱动。"
                "background_evidence 只能写进行业背景或趋势背景；watchlist_evidence/source_quality=other 只能写成不确定性或待验证线索。\n"
                f"研究上下文:\n{json.dumps(research_context, ensure_ascii=False, indent=2)}\n"
                f"校验:\n{json.dumps(validation, ensure_ascii=False, indent=2)}\n"
                f"特征:\n{json.dumps(features, ensure_ascii=False, indent=2)}\n"
                f"研究计划:\n{json.dumps(research_plan, ensure_ascii=False, indent=2)}\n"
                f"证据:\n{json.dumps(evidence, ensure_ascii=False, indent=2)}"
            ),
        },
    ]


def build_audit_messages(
    brief: dict[str, Any],
    features: dict[str, Any],
    research_context: dict[str, Any],
    evidence: list[dict[str, Any]],
    report: dict[str, Any],
) -> list[dict[str, str]]:
    compact_evidence = [
        {
            "id": item.get("id"),
            "title_zh": item.get("title_zh") or item.get("title"),
            "source": item.get("source"),
            "published_at": item.get("published_at"),
            "event_date": item.get("event_date"),
            "topic": item.get("topic"),
            "claim": item.get("claim"),
            "affected_tickers": item.get("affected_tickers"),
            "source_quality": item.get("source_quality"),
            "evidence_tier": item.get("evidence_tier"),
            "can_support_core_driver": item.get("can_support_core_driver"),
            "causality_strength": item.get("causality_strength"),
            "supports_json_signal": item.get("supports_json_signal"),
            "summary_zh": item.get("summary_zh") or item.get("relevance"),
        }
        for item in evidence[:MAX_EVIDENCE_ITEMS]
    ]
    compact_report = {
        "summary": report.get("summary", "")[:1200],
        "full_report": report.get("full_report", "")[:10000],
        "report": report.get("report", {}),
    }
    return [
        {
            "role": "system",
            "content": (
                "你是事实和逻辑审计模型。检查研报是否存在无证据外部事实、过度归因、日期不匹配、"
                "来源质量不足、量化逻辑不一致。特别检查研报是否把 background_evidence 或 watchlist_evidence "
                "误写成核心驱动，或把 can_support_core_driver=false 的证据用于强因果归因。只输出 JSON。"
            ),
        },
        {
            "role": "user",
            "content": (
                "输出格式: {\"status\":\"ok|warning|fail\",\"issues\":[{\"type\":\"unsupported|overstated|date_mismatch|source_quality|number_mismatch|missing_contradiction|investment_advice_risk|logic\","
                "\"severity\":\"low|medium|high\",\"message\":\"...\"}],\"final_notes\":\"...\"}。\n"
                f"日报日期: {brief.get('as_of_date')}\n"
                f"研究上下文:\n{json.dumps(research_context, ensure_ascii=False, indent=2)}\n"
                f"特征:\n{json.dumps(features, ensure_ascii=False, indent=2)}\n"
                f"证据:\n{json.dumps(compact_evidence, ensure_ascii=False, indent=2)}\n"
                f"研报:\n{json.dumps(compact_report, ensure_ascii=False, indent=2)}"
            ),
        },
    ]


def build_executive_points_messages(
    brief: dict[str, Any],
    report: dict[str, Any],
    evidence: list[dict[str, Any]],
    audit: dict[str, Any],
) -> list[dict[str, str]]:
    compact_evidence = [
        {
            "id": item.get("id"),
            "title_zh": item.get("title_zh") or item.get("title"),
            "summary_zh": item.get("summary_zh") or item.get("claim") or item.get("relevance"),
            "source": item.get("source"),
            "published_at": item.get("published_at"),
            "evidence_tier": item.get("evidence_tier"),
            "source_quality": item.get("source_quality"),
            "can_support_core_driver": item.get("can_support_core_driver"),
            "causality_strength": item.get("causality_strength"),
        }
        for item in evidence[:MAX_EVIDENCE_ITEMS]
    ]
    compact_report = {
        "summary": report.get("summary", "")[:1200],
        "full_report": report.get("full_report", "")[:12000],
    }
    return [
        {
            "role": "system",
            "content": (
                "你是中文金融日报的信息提炼编辑。请从最终研报中提炼首页最值得优先看的核心结论。"
                "结论要短、具体、有信息增量，避免重复原始榜单流水账。只输出 JSON。"
            ),
        },
        {
            "role": "user",
            "content": (
                "输出格式: {\"executive_points\":[{\"text\":\"首页展示的一句话结论\","
                "\"rationale\":\"30-80字依据\", \"evidence_ids\":[\"1\"], \"audit_note\":\"可选审计提示\","
                "\"priority\":1}]}。\n"
                "要求：输出 4-6 条；优先覆盖市场状态、主线/行业、关键驱动、趋势判断、风险或下一交易日观察；"
                "如果结论依赖证据，必须填 evidence_ids；如果审计提示削弱了结论，需要写入 audit_note；"
                "不要写投资建议，不要发明研报和证据之外的信息。\n"
                f"市场: {brief.get('market_label') or brief.get('market')}，日期: {brief.get('as_of_date')}\n"
                f"旧规则结论:\n{json.dumps(brief.get('summary_points', []), ensure_ascii=False, indent=2)}\n"
                f"最终研报:\n{json.dumps(compact_report, ensure_ascii=False, indent=2)}\n"
                f"证据:\n{json.dumps(compact_evidence, ensure_ascii=False, indent=2)}\n"
                f"审计:\n{json.dumps(audit, ensure_ascii=False, indent=2)}"
            ),
        },
    ]


def load_dashscope_key() -> str:
    load_dotenv(ROOT_DIR / ".env")
    key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("BAILIAN_API_KEY")
    if not key:
        raise RuntimeError("Missing DASHSCOPE_API_KEY or BAILIAN_API_KEY in environment.")
    return key


def load_deepseek_key() -> str:
    load_dotenv(ROOT_DIR / ".env")
    key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_KEY")
    if not key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY in environment.")
    return key


def load_tavily_key() -> str:
    load_dotenv(ROOT_DIR / ".env")
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing TAVILY_API_KEY in environment.")
    return key


def deepseek_model_name(model: str | None) -> str:
    load_dotenv(ROOT_DIR / ".env")
    if model and model != DEFAULT_DEEPSEEK_MODEL:
        return model
    return os.getenv("DEEPSEEK_MODEL") or os.getenv("DEEPSEEK_CHAT_MODEL") or DEFAULT_DEEPSEEK_MODEL


def deepseek_base_url() -> str:
    load_dotenv(ROOT_DIR / ".env")
    return os.getenv("DEEPSEEK_BASE_URL") or os.getenv("DEEPSEEK_API_BASE") or DEEPSEEK_COMPAT_URL


def should_use_dashscope(model: str) -> bool:
    value = model.lower()
    return value.startswith("qwen") or value.startswith("dashscope:")


def post_llm_request(url: str, api_key: str, payload: dict[str, Any], timeout: int) -> requests.Response:
    session = requests.Session()
    session.trust_env = False
    return session.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )


def extract_choice_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("LLM response has no choices.")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        text = "\n".join(str(item.get("text") or item.get("content") or "") for item in content if isinstance(item, dict))
    else:
        text = str(content or "")
    raw_text = text.strip()
    cleaned = clean_model_text(raw_text)
    if cleaned:
        return cleaned
    if raw_text.lstrip().startswith("{") or re.search(r"\{.*\}", raw_text, re.DOTALL):
        return raw_text
    finish_reason = choices[0].get("finish_reason") or choices[0].get("finish_details")
    raise RuntimeError(f"LLM returned empty content. finish_reason={finish_reason}")


def clean_model_text(text: str) -> str:
    text = THINK_BLOCK_RE.sub("", str(text or "")).strip()
    text = re.sub(r"^```(?:json|markdown|md)?\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*```$", "", text).strip()
    text = THINK_PREFIX_RE.sub("", text).strip()
    if REASONING_LEAK_RE.search(text):
        match = OPENING_SECTION_RE.search(text)
        text = text[match.start() :].strip() if match else ""
    else:
        match = FINAL_SECTION_RE.search(text)
        if match and match.start() > 0 and not text.lstrip().startswith("{"):
            text = text[match.start() :].strip()
    if DRAFT_LEAK_RE.search(text[:500]):
        return ""
    return text


def clean_report_text(text: str) -> str:
    text = THINK_BLOCK_RE.sub("", str(text or "")).strip()
    text = re.sub(r"^```(?:markdown|md)?\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*```$", "", text).strip()
    text = THINK_PREFIX_RE.sub("", text).strip()
    return text


def _format_report_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            if item in (None, "", []):
                continue
            formatted = _format_report_value(item)
            if formatted:
                parts.append(f"{key}: {formatted}")
        return "；".join(parts)
    if isinstance(value, list):
        return "；".join(_format_report_value(item) for item in value if _format_report_value(item))
    return str(value).strip()


def _normalize_driver_items(value: Any, limit: int = 8) -> list[dict[str, Any]]:
    drivers: list[dict[str, Any]] = []
    for item in _listify(value):
        if isinstance(item, dict):
            evidence_ids = item.get("evidence_ids") or item.get("evidence") or item.get("citations") or []
            if not isinstance(evidence_ids, list):
                evidence_ids = [evidence_ids]
            drivers.append(
                {
                    "title": str(item.get("title") or item.get("topic") or item.get("driver") or "驱动因素").strip()[:120],
                    "analysis": str(item.get("analysis") or item.get("summary") or item.get("text") or item.get("claim") or "").strip()[:1200],
                    "evidence_ids": [str(value) for value in evidence_ids if str(value).strip()][:6],
                    "confidence": item.get("confidence"),
                    "causality": item.get("causality") or item.get("causality_strength"),
                }
            )
        else:
            text = str(item or "").strip()
            if text:
                drivers.append({"title": text[:80], "analysis": text[:1200], "evidence_ids": [], "confidence": None, "causality": None})
    return drivers[:limit]


def fallback_report_object(brief: dict[str, Any], features: dict[str, Any], evidence: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    market = features.get("market_state", {})
    industry = features.get("industry_strength", {})
    turnover = features.get("turnover", {})
    anomalies = features.get("anomalies", {})
    benchmark_label = market.get("benchmark_label") or brief.get("benchmark_label") or "基准"
    return {
        "headline": f"{market.get('market_label') or brief.get('market_label') or '市场'}量化动能研报",
        "market_regime": {
            "state": "量化排名观察",
            "basis": f"{benchmark_label} 排名 #{market.get('benchmark_rank')}，Top20 平均日涨跌 {market.get('top20_avg_daily_change_pct')}%。",
        },
        "executive_summary": [fallback_summary(brief, features)],
        "quantitative_reading": [
            f"Top20 收涨比例 {market.get('top20_positive_rate_pct')}%，换手率 {turnover.get('top20_turnover_rate_pct')}%。",
            f"稳定前20 {turnover.get('stable_top20_count')} 只，进入/跌出前20为 {turnover.get('entered_top20_count')}/{turnover.get('dropped_top20_count')} 只。",
            f"异常上升/下降数量为 {anomalies.get('large_up_count')}/{anomalies.get('large_down_count')}。",
        ],
        "drivers": [
            {
                "title": "量化结构主导",
                "analysis": "当前结论主要来自榜单排名、ATR 动能、价格相对重心和短期涨跌的交叉验证；没有证据支持的外部事件不作为事实原因。",
                "evidence_ids": [],
                "confidence": 0.55,
                "causality": "weak",
            }
        ],
        "trend_judgment": [
            f"Top20 主要类型为 {industry.get('top20_leading_type', {}).get('stock_type')}，集中度 {industry.get('leader_concentration_pct')}%。",
            "若强势股继续稳定在前排且换手下降，趋势延续的可信度更高；若换手继续抬升，需要警惕主线切换。",
        ],
        "watchlist": features.get("key_subjects", [])[:8],
        "risk_scenarios": [
            "榜单换手继续升高，说明资金可能在短线主题之间快速切换。",
            "基准排名继续弱于强势股时，个股主线可能面临市场广度不足的约束。",
        ],
        "next_session_watch": [
            "观察进入 Top20 的新对象是否延续强势。",
            "观察大幅下行行业是否继续拖累风险偏好。",
        ],
        "disclaimer": "本报告基于量化排名和公开证据生成，仅供研究参考，不构成投资建议。",
    }


def render_structured_report(report: dict[str, Any], model_markdown: str = "") -> str:
    lines: list[str] = []
    headline = str(report.get("headline") or "模型研报").strip()
    lines.append(f"# {headline}")

    section_map = [
        ("market_regime", "市场状态"),
        ("executive_summary", "核心摘要"),
        ("quantitative_reading", "量化结构"),
        ("drivers", "驱动因素与证据"),
        ("trend_judgment", "趋势判断"),
        ("watchlist", "关键研究对象"),
        ("risk_scenarios", "风险情景"),
        ("next_session_watch", "下一交易日观察"),
    ]
    for key, title in section_map:
        value = report.get(key)
        if value in (None, "", []):
            continue
        lines.append(f"\n## {title}")
        if key == "drivers":
            for item in _normalize_driver_items(value):
                evidence_ids = " ".join(f"[{eid}]" for eid in item.get("evidence_ids", []))
                confidence = item.get("confidence")
                suffix = f"（置信度 {confidence}）" if confidence not in (None, "") else ""
                lines.append(f"- **{item.get('title') or '驱动因素'}**{suffix}：{item.get('analysis') or ''} {evidence_ids}".strip())
        elif key == "watchlist":
            for item in _listify(value)[:10]:
                if isinstance(item, dict):
                    label = item.get("display") or item.get("ticker") or item.get("name") or "观察对象"
                    detail = _format_report_value({k: v for k, v in item.items() if k not in {"display", "ticker", "name"}})
                    lines.append(f"- **{label}**：{detail}" if detail else f"- **{label}**")
                else:
                    lines.append(f"- {_format_report_value(item)}")
        elif isinstance(value, list):
            for item in value[:10]:
                formatted = _format_report_value(item)
                if formatted:
                    lines.append(f"- {formatted}")
        elif isinstance(value, dict):
            for item_key, item_value in value.items():
                formatted = _format_report_value(item_value)
                if formatted:
                    lines.append(f"- **{item_key}**：{formatted}")
        else:
            lines.append(str(value).strip())

    disclaimer = str(report.get("disclaimer") or "").strip()
    if disclaimer:
        lines.append(f"\n## 免责声明\n{disclaimer}")

    extra = clean_report_text(model_markdown)
    if extra and extra not in "\n".join(lines):
        lines.append(f"\n## 模型正文补充\n{extra}")
    return "\n".join(line for line in lines if str(line).strip())


def normalize_report_output(
    data: dict[str, Any],
    brief: dict[str, Any],
    features: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_report = data.get("report") if isinstance(data.get("report"), dict) else {}
    report = fallback_report_object(brief, features, evidence)
    for key in (
        "headline",
        "market_regime",
        "executive_summary",
        "quantitative_reading",
        "drivers",
        "trend_judgment",
        "watchlist",
        "risk_scenarios",
        "next_session_watch",
        "disclaimer",
    ):
        if key in raw_report and raw_report[key] not in (None, "", []):
            report[key] = raw_report[key]

    report["drivers"] = _normalize_driver_items(report.get("drivers"))
    if not _string_list(report.get("executive_summary")):
        report["executive_summary"] = [fallback_summary(brief, features)]
    if not _string_list(report.get("quantitative_reading")) and not isinstance(report.get("quantitative_reading"), dict):
        report["quantitative_reading"] = fallback_report_object(brief, features, evidence)["quantitative_reading"]

    summary = str(data.get("summary") or "").strip()
    if not summary:
        summary = " ".join(_string_list(report.get("executive_summary"), limit=3)) or fallback_summary(brief, features)
    full_report = clean_report_text(str(data.get("full_report") or ""))
    if not full_report:
        full_report = render_structured_report(report)
    cleaned_summary = clean_model_text(summary) or fallback_summary(brief, features)
    return {
        "summary": cleaned_summary,
        "full_report": clean_report_text(full_report),
        "report": report,
    }


def normalize_executive_points(raw_items: Any, brief: dict[str, Any], limit: int = 6) -> list[dict[str, Any]]:
    if isinstance(raw_items, dict):
        raw_items = raw_items.get("executive_points") or raw_items.get("points") or raw_items.get("items") or []
    if not isinstance(raw_items, list):
        raw_items = []
    points: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items, start=1):
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("conclusion") or item.get("summary") or "").strip()
            rationale = str(item.get("rationale") or item.get("reason") or item.get("basis") or "").strip()
            audit_note = str(item.get("audit_note") or item.get("audit") or "").strip()
            evidence_ids = item.get("evidence_ids") or item.get("evidence") or item.get("citations") or []
            priority = _safe_int(item.get("priority")) or index
        else:
            text = str(item or "").strip()
            rationale = ""
            audit_note = ""
            evidence_ids = []
            priority = index
        if not text:
            continue
        if not isinstance(evidence_ids, list):
            evidence_ids = [evidence_ids]
        points.append(
            {
                "text": clean_model_text(text)[:260],
                "rationale": clean_model_text(rationale)[:220],
                "evidence_ids": [str(value).strip() for value in evidence_ids if str(value).strip()][:6],
                "audit_note": clean_model_text(audit_note)[:180],
                "priority": max(1, priority),
            }
        )
    if points:
        return sorted(points, key=lambda item: item.get("priority") or 999)[:limit]

    fallback_points = brief.get("summary_points") if isinstance(brief, dict) else []
    if not isinstance(fallback_points, list):
        fallback_points = []
    return [
        {
            "text": str(text).strip()[:260],
            "rationale": "规则摘要兜底。",
            "evidence_ids": [],
            "audit_note": "",
            "priority": index,
        }
        for index, text in enumerate(fallback_points[:limit], start=1)
        if str(text).strip()
    ]


def report_quality_issues(full_report: str) -> list[str]:
    text = clean_report_text(full_report)
    issues: list[str] = []
    if len(text) < MIN_FULL_REPORT_CHARS:
        issues.append(f"full_report_too_short:{len(text)}")
    missing = [section for section in REQUIRED_REPORT_SECTIONS if section not in text]
    if missing:
        issues.append("missing_sections:" + ",".join(missing))
    section_matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", text))
    sections: dict[str, str] = {}
    for index, match in enumerate(section_matches):
        title = match.group(1).strip()
        next_start = section_matches[index + 1].start() if index + 1 < len(section_matches) else len(text)
        for required in REQUIRED_REPORT_SECTIONS:
            if required in title:
                sections[required] = text[match.end() : next_start].strip()
                break
    if "驱动因素与证据" in text:
        driver_text = sections.get("驱动因素与证据", "")
        if len(driver_text) < 400 or not re.search(r"\[\d+\]", driver_text):
            issues.append("driver_section_insufficient")
    if "趋势判断" in text:
        trend_text = sections.get("趋势判断", "")
        if len(trend_text) < 250:
            issues.append("trend_section_insufficient")
    return issues


def parse_json_text(text: str) -> dict[str, Any]:
    cleaned = clean_model_text(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("LLM JSON output must be an object.")
    return data


def build_json_repair_messages(raw_text: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "你是 JSON 修复器。只输出合法 JSON 对象，不解释，不补充新事实，不输出 Markdown。",
        },
        {
            "role": "user",
            "content": (
                "下面是一个模型输出的近似 JSON，可能存在缺逗号、字符串未闭合、尾部截断或 Markdown 包裹。"
                "请尽最大可能修复为合法 JSON 对象；无法恢复的字段用空字符串、空数组或空对象代替。\n"
                f"原始文本:\n{str(raw_text or '')[:30000]}"
            ),
        },
    ]


def parse_or_repair_json_text(text: str, timeout: int = 60) -> tuple[dict[str, Any], bool]:
    try:
        return parse_json_text(text), False
    except Exception:
        repaired_text, _, _ = call_chat_model(
            build_json_repair_messages(text),
            DEFAULT_DEEPSEEK_MODEL,
            timeout,
            6000,
            temperature=0,
            json_mode=True,
            use_env_model=False,
        )
        return parse_json_text(repaired_text), True


def call_chat_model(
    messages: list[dict[str, str]],
    model: str | None,
    timeout: int,
    max_tokens: int,
    temperature: float = 0.2,
    json_mode: bool = False,
    use_env_model: bool = True,
) -> tuple[str, str, str]:
    model_name = deepseek_model_name(model) if use_env_model else (model or DEFAULT_DEEPSEEK_MODEL)
    if should_use_dashscope(model_name):
        provider = "dashscope"
        api_key = load_dashscope_key()
        url = DASHSCOPE_COMPAT_URL
        request_model = model_name.removeprefix("dashscope:")
    else:
        provider = "deepseek"
        api_key = load_deepseek_key()
        url = deepseek_base_url()
        request_model = model_name

    payload = {
        "model": request_model,
        "messages": messages,
        "temperature": temperature,
        "top_p": 0.8,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    response = post_llm_request(
        url,
        api_key,
        payload,
        timeout,
    )
    response.raise_for_status()
    return extract_choice_text(response.json()), provider, request_model


def _fallback_search_tasks(brief: dict[str, Any], features: dict[str, Any], limit: int = MAX_RESEARCH_TASKS) -> list[dict[str, Any]]:
    market_label = brief.get("market_label") or brief.get("market") or "market"
    as_of_date = brief.get("as_of_date") or ""
    tasks: list[dict[str, Any]] = []
    for item in features.get("key_subjects", [])[:limit]:
        label = _label(item)
        ticker = str(item.get("ticker") or "").strip()
        if not label and not ticker:
            continue
        query = f"{ticker} {label} stock news earnings announcement {as_of_date}".strip()
        tasks.append(
            {
                "query": query,
                "target": ticker or label,
                "reason": f"{market_label}日报关键研究对象: {item.get('source')}",
                "priority": 1 if item.get("source") in {"upward_moves", "downward_moves"} else 2,
            }
        )
    benchmark_label = brief.get("benchmark_label") or ""
    if benchmark_label:
        tasks.append(
            {
                "query": f"{benchmark_label} market news {as_of_date}",
                "target": benchmark_label,
                "reason": "基准指数或ETF的市场背景",
                "priority": 3,
            }
        )
    return tasks[:limit]


def generate_research_plan(
    brief: dict[str, Any],
    validation: dict[str, Any],
    features: dict[str, Any],
    research_context: dict[str, Any],
    model: str,
    timeout: int,
    max_tokens: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    text, provider, model_name = call_chat_model(
        build_research_plan_messages(brief, validation, features, research_context),
        DEFAULT_DEEPSEEK_PRO_MODEL,
        timeout,
        max(max_tokens, 4000),
        json_mode=True,
        use_env_model=False,
    )
    data, repaired = parse_or_repair_json_text(text, timeout)
    tasks = data.get("search_tasks") if isinstance(data.get("search_tasks"), list) else []
    normalized_tasks = []
    for item in tasks[:MAX_RESEARCH_TASKS]:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "").strip()
        if not query:
            continue
        normalized_tasks.append(
            {
                "query": query[:240],
                "target": str(item.get("target") or "")[:80],
                "reason": str(item.get("reason") or "")[:240],
                "priority": _safe_int(item.get("priority")) or 3,
            }
        )
    if not normalized_tasks:
        normalized_tasks = _fallback_search_tasks(brief, features)
    data["search_tasks"] = normalized_tasks
    return data, {"stage": "research_plan", "status": "ok", "provider": provider, "model": model_name, "duration_ms": _elapsed(started), "json_repaired": repaired}


def tavily_search(query: str, max_results: int, timeout: int) -> list[dict[str, Any]]:
    api_key = load_tavily_key()
    session = requests.Session()
    session.trust_env = False
    response = session.post(
        TAVILY_SEARCH_URL,
        json={
            "api_key": api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    return payload.get("results") or []


def run_tavily_searches(
    research_plan: dict[str, Any],
    brief: dict[str, Any],
    max_results: int,
    lookback_days: int,
    timeout: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.perf_counter()
    tasks = [item for item in research_plan.get("search_tasks", []) if isinstance(item, dict)][:MAX_RESEARCH_TASKS]
    max_results = _bounded_int(max_results, 1, 10)
    cutoff = None
    as_of = _parse_date(brief.get("as_of_date"))
    if as_of:
        cutoff = as_of - timedelta(days=_bounded_int(lookback_days, 1, 90))

    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_urls: set[str] = set()
    for task in tasks:
        query = str(task.get("query") or "").strip()
        if not query:
            continue
        try:
            rows = tavily_search(query, max_results=max_results, timeout=timeout)
        except Exception as exc:
            errors.append(f"{query}: {exc}")
            continue
        for row in rows:
            url = str(row.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            published_at = row.get("published_date") or row.get("published_at") or row.get("date") or ""
            parsed_published = _parse_date(published_at)
            if cutoff and parsed_published and parsed_published < cutoff:
                continue
            seen_urls.add(url)
            normalized.append(
                {
                    "query": query,
                    "target": task.get("target"),
                    "title": str(row.get("title") or "")[:240],
                    "url": url,
                    "source": _domain(url),
                    "source_quality": _source_quality(url),
                    "source_type": _source_type(url),
                    "published_at": str(published_at or ""),
                    "date_relation": _date_relation(published_at, brief.get("as_of_date")),
                    "snippet": str(row.get("content") or row.get("snippet") or "")[:900],
                    "score": row.get("score"),
                }
            )

    normalized.sort(key=lambda item: ({"primary": 0, "mainstream": 1, "other": 2}.get(item["source_quality"], 3), -(float(item.get("score") or 0))))
    return normalized[:40], {
        "stage": "web_search",
        "status": "partial" if errors else "ok",
        "duration_ms": _elapsed(started),
        "task_count": len(tasks),
        "result_count": len(normalized),
        "errors": errors,
    }


def score_search_result(row: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
    source_quality = str(row.get("source_quality") or _source_quality(str(row.get("url") or "")))
    source_type = str(row.get("source_type") or _source_type(str(row.get("url") or "")))
    date_relation = str(row.get("date_relation") or _date_relation(row.get("published_at"), brief.get("as_of_date")))
    days_from_as_of = _days_from_as_of(row.get("published_at"), brief.get("as_of_date"))
    tavily_score = _safe_float(row.get("score")) or 0.0
    title = str(row.get("title") or "")
    snippet = str(row.get("snippet") or "")
    target = str(row.get("target") or "")
    query = str(row.get("query") or "")
    text_blob = f"{title} {snippet} {query}".lower()
    target_tokens = _tokenize_query_text(target)
    query_tokens = _tokenize_query_text(query)
    target_matched = bool(target_tokens and any(token in text_blob for token in target_tokens))
    query_overlap = len(query_tokens & _tokenize_query_text(f"{title} {snippet}"))
    has_event_keyword = any(keyword.lower() in text_blob for keyword in EVENT_KEYWORDS)

    score = 0.0
    score += {"primary": 45, "mainstream": 35, "other": 10}.get(source_quality, 0)
    score += {"company": 22, "exchange": 22, "regulator": 22, "media": 12, "data": 8, "other": 0}.get(source_type, 0)
    if date_relation == "after_as_of":
        score -= 100
    elif days_from_as_of is None:
        score -= 5
    elif days_from_as_of < 0:
        score -= 100
    elif days_from_as_of == 0:
        score += 20
    elif days_from_as_of <= 2:
        score += 16
    elif days_from_as_of <= 7:
        score += 10
    elif days_from_as_of <= 30:
        score -= 2
    else:
        score -= 25
    score += min(15.0, max(0.0, tavily_score) * 15.0)
    if target_matched:
        score += 10
    elif target:
        score -= 12
    score += min(8, query_overlap * 2)
    if has_event_keyword:
        score += 8

    reject_reasons: list[str] = []
    if date_relation == "after_as_of" or (days_from_as_of is not None and days_from_as_of < 0):
        reject_reasons.append("after_as_of")
    if days_from_as_of is not None and days_from_as_of > 90:
        reject_reasons.append("too_old")
    if target and not target_matched and query_overlap == 0:
        reject_reasons.append("target_mismatch")
    if not title and not snippet:
        reject_reasons.append("empty_content")

    can_support_core_driver = not reject_reasons and source_quality in {"primary", "mainstream"} and date_relation != "after_as_of"
    if days_from_as_of is not None and days_from_as_of > 14:
        can_support_core_driver = False
    if source_quality == "other":
        can_support_core_driver = False

    if reject_reasons:
        tier = "rejected_evidence"
    elif can_support_core_driver and score >= 62:
        tier = "core_evidence"
    elif source_quality in {"primary", "mainstream"} and (days_from_as_of is None or days_from_as_of <= 45):
        tier = "background_evidence"
    else:
        tier = "watchlist_evidence"

    if tier == "background_evidence" and days_from_as_of is not None and days_from_as_of <= 7 and source_quality == "mainstream" and has_event_keyword and score >= 55:
        tier = "core_evidence"
        can_support_core_driver = True

    return {
        "evidence_score": round(score, 2),
        "evidence_tier": tier,
        "can_support_core_driver": can_support_core_driver,
        "reject_reason": ", ".join(reject_reasons),
        "days_from_as_of": days_from_as_of,
        "target_matched": target_matched,
        "query_overlap": query_overlap,
        "has_event_keyword": has_event_keyword,
    }


def prefilter_search_results(
    search_results: list[dict[str, Any]],
    brief: dict[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    started = time.perf_counter()
    buckets: dict[str, list[dict[str, Any]]] = {
        "core_evidence": [],
        "background_evidence": [],
        "watchlist_evidence": [],
        "rejected_evidence": [],
    }
    for row in search_results:
        scored = {**row, **score_search_result(row, brief)}
        tier = scored.get("evidence_tier") if scored.get("evidence_tier") in buckets else "watchlist_evidence"
        buckets[str(tier)].append(scored)

    for tier, rows in buckets.items():
        rows.sort(
            key=lambda item: (
                {"core_evidence": 0, "background_evidence": 1, "watchlist_evidence": 2, "rejected_evidence": 3}.get(str(item.get("evidence_tier")), 9),
                -(float(item.get("evidence_score") or 0)),
                {"primary": 0, "mainstream": 1, "other": 2}.get(str(item.get("source_quality")), 3),
            )
        )

    candidates = (
        buckets["core_evidence"][:MAX_EVIDENCE_ITEMS]
        + buckets["background_evidence"][:MAX_EVIDENCE_ITEMS]
        + buckets["watchlist_evidence"][:MAX_EVIDENCE_ITEMS]
    )
    candidates = sorted(candidates, key=lambda item: ({"core_evidence": 0, "background_evidence": 1, "watchlist_evidence": 2}.get(str(item.get("evidence_tier")), 9), -(float(item.get("evidence_score") or 0))))[
        :MAX_PREFILTERED_SEARCH_RESULTS
    ]
    buckets["candidate_evidence"] = candidates

    stage = {
        "stage": "evidence_prefilter",
        "status": "ok",
        "duration_ms": _elapsed(started),
        "input_count": len(search_results),
        "candidate_count": len(candidates),
        "core_count": len(buckets["core_evidence"]),
        "background_count": len(buckets["background_evidence"]),
        "watchlist_count": len(buckets["watchlist_evidence"]),
        "rejected_count": len(buckets["rejected_evidence"]),
        "rejected_reasons": {},
    }
    reasons: dict[str, int] = {}
    for row in buckets["rejected_evidence"]:
        for reason in str(row.get("reject_reason") or "unknown").split(","):
            reason = reason.strip() or "unknown"
            reasons[reason] = reasons.get(reason, 0) + 1
    stage["rejected_reasons"] = reasons
    return buckets, stage


def normalize_evidence(raw_items: Any, search_results: list[dict[str, Any]], limit: int = MAX_EVIDENCE_ITEMS) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        raw_items = []
    url_lookup = {_url_key(str(item.get("url") or "")): item for item in search_results if item.get("url")}
    evidence: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for index, item in enumerate(raw_items[:limit], start=1):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        url_key = _url_key(url)
        if not url or url_key in seen_urls:
            continue
        source_row = url_lookup.get(url_key, {})
        source_was_prefiltered = bool(source_row)
        seen_urls.add(url_key)
        event_date = str(item.get("event_date") or item.get("published_at") or source_row.get("published_at") or "")
        published_at = str(item.get("published_at") or source_row.get("published_at") or "")
        date_relation = item.get("date_relation") or source_row.get("date_relation") or ""
        source_quality = str(item.get("source_quality") or source_row.get("source_quality") or _source_quality(url))
        source_type = str(item.get("source_type") or source_row.get("source_type") or _source_type(url))
        source_tier = str(source_row.get("evidence_tier") or "")
        evidence_tier = str(item.get("evidence_tier") or source_tier or "watchlist_evidence")
        if evidence_tier not in {"core_evidence", "background_evidence", "watchlist_evidence"}:
            evidence_tier = "watchlist_evidence"
        if source_tier in {"background_evidence", "watchlist_evidence"} and evidence_tier == "core_evidence":
            evidence_tier = source_tier
        if not source_was_prefiltered and evidence_tier == "core_evidence":
            evidence_tier = "watchlist_evidence"
        supports_json_signal = item.get("supports_json_signal")
        if not isinstance(supports_json_signal, bool):
            supports_json_signal = date_relation != "after_as_of"
        can_support_core_driver = item.get("can_support_core_driver")
        source_can_support = source_row.get("can_support_core_driver")
        if not isinstance(can_support_core_driver, bool):
            can_support_core_driver = bool(source_can_support) if isinstance(source_can_support, bool) else evidence_tier == "core_evidence"
        if not source_was_prefiltered:
            can_support_core_driver = False
        causality_strength = str(item.get("causality_strength") or "").strip().lower()
        if causality_strength not in {"strong", "medium", "weak", "follow_up", "none"}:
            causality_strength = "follow_up" if date_relation == "after_as_of" else "weak"
        if date_relation == "after_as_of":
            supports_json_signal = False
            causality_strength = "follow_up"
            can_support_core_driver = False
            evidence_tier = "watchlist_evidence"
        if source_quality == "other":
            can_support_core_driver = False
            if evidence_tier == "core_evidence":
                evidence_tier = "watchlist_evidence"
        if source_can_support is False:
            can_support_core_driver = False
            if evidence_tier == "core_evidence":
                evidence_tier = "background_evidence" if source_quality in {"primary", "mainstream"} else "watchlist_evidence"
        confidence = _safe_float(item.get("confidence"))
        if confidence is None:
            confidence = 0.75 if source_quality == "primary" else 0.6 if source_quality == "mainstream" else 0.45
        affected_tickers = item.get("affected_tickers")
        if not isinstance(affected_tickers, list):
            target = source_row.get("target") or item.get("used_by") or item.get("topic")
            affected_tickers = [str(target)] if target else []
        evidence.append(
            {
                "id": str(item.get("id") or index),
                "title": str(item.get("title") or source_row.get("title") or "")[:240],
                "title_zh": str(item.get("title_zh") or item.get("title") or source_row.get("title") or "")[:120],
                "url": url,
                "source": str(item.get("source") or source_row.get("source") or _domain(url)),
                "published_at": published_at,
                "event_date": event_date,
                "date_relation": date_relation,
                "topic": str(item.get("topic") or source_row.get("target") or "")[:120],
                "claim": str(item.get("claim") or item.get("relevance") or item.get("summary_zh") or source_row.get("snippet") or "")[:360],
                "affected_tickers": [str(value)[:40] for value in affected_tickers if str(value).strip()][:8],
                "source_type": source_type,
                "source_quality": source_quality,
                "evidence_tier": evidence_tier,
                "evidence_score": source_row.get("evidence_score") or item.get("evidence_score"),
                "can_support_core_driver": can_support_core_driver,
                "reject_reason": str(source_row.get("reject_reason") or item.get("reject_reason") or "")[:240],
                "days_from_as_of": source_row.get("days_from_as_of") if source_row.get("days_from_as_of") is not None else item.get("days_from_as_of"),
                "supports_json_signal": supports_json_signal,
                "causality_strength": causality_strength,
                "confidence": round(max(0.0, min(1.0, confidence)), 2),
                "snippet": str(item.get("snippet") or source_row.get("snippet") or "")[:900],
                "summary_zh": str(item.get("summary_zh") or item.get("relevance") or item.get("snippet") or source_row.get("snippet") or "")[:180],
                "relevance": str(item.get("relevance") or "")[:300],
                "used_by": item.get("used_by") if isinstance(item.get("used_by"), list) else [],
            }
        )
    for index, item in enumerate(evidence, start=1):
        item["id"] = str(index)
    return evidence


def extract_evidence(
    brief: dict[str, Any],
    features: dict[str, Any],
    research_context: dict[str, Any],
    research_plan: dict[str, Any],
    search_results: list[dict[str, Any]],
    model: str,
    timeout: int,
    max_tokens: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.perf_counter()
    if not search_results:
        return [], {"stage": "evidence_extract", "status": "skipped", "duration_ms": _elapsed(started), "evidence_count": 0}
    text, provider, model_name = call_chat_model(
        build_evidence_messages(brief, features, research_context, research_plan, search_results),
        DEFAULT_DEEPSEEK_PRO_MODEL,
        timeout,
        max(max_tokens, 12000),
        json_mode=True,
        use_env_model=False,
    )
    data, repaired = parse_or_repair_json_text(text, timeout)
    evidence = normalize_evidence(data.get("evidence"), search_results)
    return evidence, {
        "stage": "evidence_extract",
        "status": "ok",
        "provider": provider,
        "model": model_name,
        "duration_ms": _elapsed(started),
        "evidence_count": len(evidence),
        "json_repaired": repaired,
    }


def write_research_report(
    brief: dict[str, Any],
    validation: dict[str, Any],
    features: dict[str, Any],
    research_context: dict[str, Any],
    research_plan: dict[str, Any],
    evidence: list[dict[str, Any]],
    model: str,
    timeout: int,
    max_report_tokens: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    text, provider, model_name = call_chat_model(
        build_writer_messages(brief, validation, features, research_context, research_plan, evidence),
        DEFAULT_DEEPSEEK_PRO_MODEL,
        timeout,
        max_report_tokens,
        temperature=0.25,
        json_mode=True,
        use_env_model=False,
    )
    data, repaired = parse_or_repair_json_text(text, timeout)
    report = normalize_report_output(data, brief, features, evidence)
    return report, {
        "stage": "report_write",
        "status": "ok",
        "provider": provider,
        "model": model_name,
        "duration_ms": _elapsed(started),
        "json_repaired": repaired,
    }


def audit_research_report(
    brief: dict[str, Any],
    features: dict[str, Any],
    research_context: dict[str, Any],
    evidence: list[dict[str, Any]],
    report: dict[str, Any],
    model: str,
    timeout: int,
    max_tokens: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    text, provider, model_name = call_chat_model(
        build_audit_messages(brief, features, research_context, evidence, report),
        DEFAULT_DEEPSEEK_MODEL,
        timeout,
        max(max_tokens, 4000),
        temperature=0.1,
        json_mode=True,
        use_env_model=False,
    )
    data, repaired = parse_or_repair_json_text(text, timeout)
    audit = {
        "status": data.get("status") if data.get("status") in {"ok", "warning", "fail"} else "warning",
        "issues": data.get("issues") if isinstance(data.get("issues"), list) else [],
        "final_notes": str(data.get("final_notes") or ""),
    }
    return audit, {
        "stage": "audit",
        "status": "ok",
        "provider": provider,
        "model": model_name,
        "duration_ms": _elapsed(started),
        "audit_status": audit["status"],
        "json_repaired": repaired,
    }


def audit_requires_revision(audit: dict[str, Any]) -> bool:
    if audit.get("status") == "fail":
        return True
    serious_types = {"unsupported", "overstated", "date_mismatch", "number_mismatch", "investment_advice_risk"}
    for issue in audit.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        if issue.get("severity") == "high":
            return True
        if issue.get("type") in serious_types and issue.get("severity") in {"medium", "high"}:
            return True
    return False


def build_revision_messages(
    brief: dict[str, Any],
    validation: dict[str, Any],
    features: dict[str, Any],
    research_context: dict[str, Any],
    evidence: list[dict[str, Any]],
    report: dict[str, Any],
    audit: dict[str, Any],
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是中文研报修订模型。根据审计问题修订报告，删除无证据事实、弱化过度归因、修正日期和数字。"
                "如果审计问题包含 report_quality，必须补厚 full_report 中的驱动因素与证据、驱动因素源头拆解、趋势判断等章节。"
                "只输出 JSON，字段仍为 summary、full_report、report。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请只基于研究上下文和证据修订。若证据不足，明确写为假设或观察项，不得写成确定原因。\n"
                "full_report 必须保留 Markdown 二级标题，并逐条展开驱动因素的现象、源头、证据、影响链条、置信度、不确定性、引用编号。\n"
                f"日报日期: {brief.get('as_of_date')}\n"
                f"校验:\n{json.dumps(validation, ensure_ascii=False, indent=2)}\n"
                f"研究上下文:\n{json.dumps(research_context, ensure_ascii=False, indent=2)}\n"
                f"特征:\n{json.dumps(features, ensure_ascii=False, indent=2)}\n"
                f"证据:\n{json.dumps(evidence[:MAX_EVIDENCE_ITEMS], ensure_ascii=False, indent=2)}\n"
                f"原报告:\n{json.dumps(report, ensure_ascii=False, indent=2)}\n"
                f"审计问题:\n{json.dumps(audit, ensure_ascii=False, indent=2)}"
            ),
        },
    ]


def revise_research_report(
    brief: dict[str, Any],
    validation: dict[str, Any],
    features: dict[str, Any],
    research_context: dict[str, Any],
    evidence: list[dict[str, Any]],
    report: dict[str, Any],
    audit: dict[str, Any],
    model: str,
    timeout: int,
    max_report_tokens: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    text, provider, model_name = call_chat_model(
        build_revision_messages(brief, validation, features, research_context, evidence, report, audit),
        DEFAULT_DEEPSEEK_MODEL,
        timeout,
        max_report_tokens,
        temperature=0.15,
        json_mode=True,
        use_env_model=False,
    )
    data, repaired = parse_or_repair_json_text(text, timeout)
    revised = normalize_report_output(data, brief, features, evidence)
    return revised, {
        "stage": "report_revision",
        "status": "ok",
        "provider": provider,
        "model": model_name,
        "duration_ms": _elapsed(started),
        "json_repaired": repaired,
    }


def generate_executive_points(
    brief: dict[str, Any],
    report: dict[str, Any],
    evidence: list[dict[str, Any]],
    audit: dict[str, Any],
    timeout: int,
    max_tokens: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.perf_counter()
    text, provider, model_name = call_chat_model(
        build_executive_points_messages(brief, report, evidence, audit),
        DEFAULT_DEEPSEEK_MODEL,
        timeout,
        max(max_tokens, 2500),
        temperature=0.18,
        json_mode=True,
        use_env_model=False,
    )
    data, repaired = parse_or_repair_json_text(text, timeout)
    points = normalize_executive_points(data, brief)
    return points, {
        "stage": "executive_points",
        "status": "ok" if points else "partial",
        "provider": provider,
        "model": model_name,
        "duration_ms": _elapsed(started),
        "point_count": len(points),
        "json_repaired": repaired,
    }


def generate_dashscope_interpretation(
    brief: dict[str, Any],
    model: str,
    timeout: int,
    max_tokens: int,
) -> dict[str, Any]:
    return generate_model_interpretation(brief, model=model, timeout=timeout, max_tokens=max_tokens, disable_web=True)


def generate_deepseek_interpretation(
    brief: dict[str, Any],
    model: str | None,
    timeout: int,
    max_tokens: int,
) -> dict[str, Any]:
    return generate_model_interpretation(brief, model=model or DEFAULT_DEEPSEEK_MODEL, timeout=timeout, max_tokens=max_tokens, disable_web=True)


def generate_model_interpretation(
    brief: dict[str, Any],
    model: str = DEFAULT_DEEPSEEK_MODEL,
    timeout: int = 60,
    max_tokens: int = 1500,
    research_depth: str = "full",
    search_results: int = 5,
    lookback_days: int = 7,
    max_report_tokens: int = 12000,
    disable_web: bool = False,
) -> dict[str, Any]:
    started_all = time.perf_counter()
    stages: list[dict[str, Any]] = []
    errors: list[str] = []
    provider = "deepseek"
    resolved_model = DEFAULT_DEEPSEEK_PRO_MODEL

    validation_started = time.perf_counter()
    validation = validate_brief_data(brief)
    stages.append({"stage": "validation", "status": validation["status"], "duration_ms": _elapsed(validation_started), "issue_count": validation["issue_count"]})

    features_started = time.perf_counter()
    features = extract_research_features(brief)
    stages.append({"stage": "feature_extract", "status": "ok", "duration_ms": _elapsed(features_started)})

    context_started = time.perf_counter()
    research_context = build_research_context(brief, validation, features)
    stages.append({"stage": "research_context", "status": "ok", "duration_ms": _elapsed(context_started)})

    research_plan: dict[str, Any] = {
        "research_questions": [],
        "search_tasks": _fallback_search_tasks(brief, features),
        "fallback": True,
    }
    try:
        research_plan, stage = generate_research_plan(brief, validation, features, research_context, model, timeout, max_tokens)
        stages.append(stage)
    except Exception as exc:
        errors.append(f"research_plan: {exc}")
        stages.append({"stage": "research_plan", "status": "error", "error": str(exc)})

    raw_search_results: list[dict[str, Any]] = []
    screened_results: dict[str, list[dict[str, Any]]] = {
        "core_evidence": [],
        "background_evidence": [],
        "watchlist_evidence": [],
        "rejected_evidence": [],
        "candidate_evidence": [],
    }
    if disable_web or research_depth == "quant":
        stages.append({"stage": "web_search", "status": "skipped", "result_count": 0, "reason": "disabled"})
    else:
        try:
            raw_search_results, stage = run_tavily_searches(
                research_plan,
                brief,
                max_results=search_results,
                lookback_days=lookback_days,
                timeout=timeout,
            )
            stages.append(stage)
            if stage.get("errors"):
                errors.extend(f"web_search: {item}" for item in stage["errors"])
        except Exception as exc:
            errors.append(f"web_search: {exc}")
            stages.append({"stage": "web_search", "status": "error", "error": str(exc), "result_count": 0})

    screened_results, stage = prefilter_search_results(raw_search_results, brief)
    stages.append(stage)
    candidate_search_results = screened_results.get("candidate_evidence", [])

    evidence: list[dict[str, Any]] = []
    try:
        evidence, stage = extract_evidence(brief, features, research_context, research_plan, candidate_search_results, model, timeout, max_tokens)
        stages.append(stage)
    except Exception as exc:
        errors.append(f"evidence_extract: {exc}")
        stages.append({"stage": "evidence_extract", "status": "error", "error": str(exc), "evidence_count": 0})
        evidence = normalize_evidence(candidate_search_results[:MAX_EVIDENCE_ITEMS], candidate_search_results)

    quality_issues: list[str] = []
    try:
        report, stage = write_research_report(
            brief,
            validation,
            features,
            research_context,
            research_plan,
            evidence,
            model,
            timeout,
            max_report_tokens,
        )
        quality_issues = report_quality_issues(report.get("full_report", ""))
        if quality_issues:
            stage["status"] = "partial"
            stage["quality_issues"] = quality_issues
        stages.append(stage)
    except Exception as exc:
        errors.append(f"report_write: {exc}")
        fallback_object = fallback_report_object(brief, features, evidence)
        report = {
            "summary": fallback_summary(brief, features),
            "full_report": render_structured_report(fallback_object),
            "report": fallback_object,
        }
        stages.append({"stage": "report_write", "status": "error", "error": str(exc)})

    audit = {"status": "warning" if errors else "ok", "issues": [], "final_notes": "未执行模型审计。"}
    try:
        audit, stage = audit_research_report(brief, features, research_context, evidence, report, model, timeout, max_tokens)
        stages.append(stage)
    except Exception as exc:
        errors.append(f"audit: {exc}")
        audit = {
            "status": "warning",
            "issues": [{"type": "audit_unavailable", "severity": "medium", "message": str(exc)}],
            "final_notes": "模型审计失败，已保留研报与证据链供人工复核。",
        }
        stages.append({"stage": "audit", "status": "error", "error": str(exc)})

    revision_audit = audit
    if quality_issues:
        revision_audit = {
            **audit,
            "status": "warning",
            "issues": list(audit.get("issues") or [])
            + [
                {
                    "type": "report_quality",
                    "severity": "high",
                    "message": "研报正文质量门槛未通过，需要补全或加厚以下部分: " + ", ".join(quality_issues),
                }
            ],
            "final_notes": (audit.get("final_notes") or "") + " 研报正文质量门槛未通过，需补写。",
        }

    if audit_requires_revision(revision_audit):
        try:
            revised_report, stage = revise_research_report(
                brief,
                validation,
                features,
                research_context,
                evidence,
                report,
                revision_audit,
                model,
                timeout,
                max_report_tokens,
            )
            report = revised_report
            quality_issues = report_quality_issues(report.get("full_report", ""))
            if quality_issues:
                stage["status"] = "partial"
                stage["quality_issues"] = quality_issues
            stages.append(stage)
            try:
                audit, stage = audit_research_report(brief, features, research_context, evidence, report, model, timeout, max_tokens)
                stage["stage"] = "audit_after_revision"
                stages.append(stage)
            except Exception as exc:
                errors.append(f"audit_after_revision: {exc}")
                stages.append({"stage": "audit_after_revision", "status": "error", "error": str(exc)})
        except Exception as exc:
            errors.append(f"report_revision: {exc}")
            stages.append({"stage": "report_revision", "status": "error", "error": str(exc)})

    executive_points = normalize_executive_points([], brief)
    try:
        executive_points, stage = generate_executive_points(brief, report, evidence, audit, timeout, max_tokens)
        stages.append(stage)
    except Exception as exc:
        errors.append(f"executive_points: {exc}")
        stages.append({"stage": "executive_points", "status": "error", "error": str(exc), "point_count": len(executive_points)})

    if errors or any(stage.get("status") in {"error", "partial"} for stage in stages):
        status = "partial"
    elif audit.get("status") in {"warning", "fail"} or validation.get("status") == "error":
        status = "partial"
    else:
        status = "ok"

    if report["summary"] == fallback_summary(brief, features) and any(stage.get("stage") == "report_write" and stage.get("status") == "error" for stage in stages):
        status = "fallback"

    return {
        "status": status,
        "provider": provider,
        "model": resolved_model,
        "generated_at": _now(),
        "summary": report["summary"],
        "full_report": report["full_report"],
        "report": report.get("report") or {},
        "executive_points": executive_points,
        "text": report["summary"],
        "validation": validation,
        "features": features,
        "research_context": research_context,
        "research_plan": research_plan,
        "evidence": evidence,
        "audit": audit,
        "pipeline": {
            "research_depth": research_depth,
            "disable_web": disable_web,
            "lookback_days": lookback_days,
            "search_results_per_task": search_results,
            "evidence_prefilter": {
                "core_count": len(screened_results.get("core_evidence", [])),
                "background_count": len(screened_results.get("background_evidence", [])),
                "watchlist_count": len(screened_results.get("watchlist_evidence", [])),
                "rejected_count": len(screened_results.get("rejected_evidence", [])),
                "candidate_count": len(screened_results.get("candidate_evidence", [])),
                "rejected_sample": [
                    {
                        "title": item.get("title"),
                        "source": item.get("source"),
                        "reject_reason": item.get("reject_reason"),
                        "evidence_score": item.get("evidence_score"),
                    }
                    for item in screened_results.get("rejected_evidence", [])[:5]
                ],
            },
            "duration_ms": _elapsed(started_all),
            "stages": stages,
            "errors": errors,
        },
    }
