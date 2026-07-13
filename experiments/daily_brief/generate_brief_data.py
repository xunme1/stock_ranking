from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
EXPERIMENT_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))

from app.core.config import COMPANY_PROFILES_FILE  # noqa: E402
from app.services.data_loader import normalize_market, normalize_ticker_for_market  # noqa: E402
from app.services.ranking_service import default_benchmark_for_market, ranking_cache_path  # noqa: E402
from llm_analysis import generate_model_interpretation  # noqa: E402


OUTPUT_DIR = EXPERIMENT_DIR / "output"

TECH_TYPES = {
    "科技股",
    "软件服务",
    "半导体",
    "半导体设备",
    "AI芯片",
    "云计算",
    "互联网平台",
    "互联网消费",
    "网络安全",
    "信息服务",
    "存储硬件",
    "硬件设备",
    "光通信",
    "光通信材料",
    "网络设备",
    "工业科技",
    "金融科技",
    "支付网络",
    "游戏娱乐",
    "流媒体",
    "媒体通信",
    "通信服务",
}
TECH_KEYWORDS = ("科技", "软件", "半导体", "芯片", "云", "互联网", "网络", "通信", "硬件", "存储", "光", "游戏", "流媒体")


def clean_float(value: Any, digits: int = 3) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return round(result, digits)


def clean_int(value: Any) -> int | None:
    try:
        if pd.isna(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def field(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, pd.Series):
        return row.get(name, default)
    return getattr(row, name, default)


def load_ranking(window: int, market: str) -> pd.DataFrame:
    path = ranking_cache_path(window, market)
    if not path.exists():
        raise FileNotFoundError(f"Ranking cache not found: {path}")
    df = pd.read_csv(path, dtype={"ticker": str, "benchmark": str, "name": str})
    df["as_of_date"] = df["as_of_date"].astype(str)
    df["ticker"] = df["ticker"].astype(str).map(lambda ticker: normalize_ticker_for_market(ticker, market))
    numeric_columns = [
        "rank",
        "close",
        "ma_center",
        "atr",
        "atr_score",
        "price_vs_center_pct",
        "price_change_3d_pct",
        "excess_atr_vs_benchmark",
    ]
    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


def load_company_names() -> dict[str, str]:
    if not COMPANY_PROFILES_FILE.exists():
        return {}
    df = pd.read_csv(COMPANY_PROFILES_FILE)
    names: dict[str, str] = {}
    for row in df.fillna("").itertuples(index=False):
        ticker = normalize_ticker_for_market(str(getattr(row, "ticker", "")), "us")
        name = str(getattr(row, "name", "")).strip()
        if ticker and name and name.lower() != "nan":
            names[ticker] = name
    return names


def row_to_item(row: Any, names: dict[str, str], market: str) -> dict[str, Any]:
    ticker = normalize_ticker_for_market(str(field(row, "ticker", "")), market)
    cached_name = str(field(row, "name", "") or "").strip()
    name = names.get(ticker, "") if market == "us" else cached_name
    if name.lower() == "nan":
        name = ""
    display = ticker if market == "us" else name or ticker
    return {
        "rank": clean_int(field(row, "rank")),
        "ticker": ticker,
        "name": name,
        "display": display,
        "sector": str(field(row, "sector", "") or "Unknown"),
        "stock_type": str(field(row, "stock_type", "") or "Unknown"),
        "has_options": str(field(row, "has_options", "") or "U"),
        "close": clean_float(field(row, "close"), 2),
        "atr_score": clean_float(field(row, "atr_score"), 3),
        "price_vs_center_pct": clean_float(field(row, "price_vs_center_pct"), 2),
        "price_change_3d_pct": clean_float(field(row, "price_change_3d_pct"), 2),
        "excess_atr_vs_benchmark": clean_float(field(row, "excess_atr_vs_benchmark"), 3),
    }


def item_with_change(
    row: Any,
    names: dict[str, str],
    market: str,
    previous_rank_map: dict[str, int],
    previous_close_map: dict[str, float],
) -> dict[str, Any]:
    item = row_to_item(row, names, market)
    previous_rank = previous_rank_map.get(item["ticker"])
    item["previous_rank"] = previous_rank
    item["rank_change"] = previous_rank - item["rank"] if previous_rank and item["rank"] else None

    previous_close = previous_close_map.get(item["ticker"])
    close = item.get("close")
    item["daily_change_pct"] = (
        clean_float((float(close) / previous_close - 1) * 100, 2)
        if previous_close and close
        else None
    )
    return item


def brief_category(item: dict[str, Any], market: str) -> str:
    stock_type = str(item.get("stock_type") or "")
    sector = str(item.get("sector") or "")
    text = f"{sector}/{stock_type}"
    if market == "us":
        return stock_type or "Unknown"
    if "半导体" in text or "芯片" in text or "IC" in text or "封装" in text:
        return "半导体"
    if any(keyword in text for keyword in ["AI算力", "通信", "光通信", "ICT", "数据中心", "算力网络"]):
        return "AI算力与通信"
    if any(keyword in text for keyword in ["人工智能", "AI应用", "大模型", "软件", "网络安全", "互联网", "游戏", "传媒", "数字金融"]):
        return "互联网软件与AI应用"
    if any(keyword in text for keyword in ["消费电子", "电子元件", "AI硬件", "电子/AI硬件", "PCB", "显示", "电池模组", "智能硬件"]):
        return "电子硬件"
    if any(keyword in text for keyword in ["汽车", "新能源车", "智能驾驶", "机器人", "热管理", "执行器"]):
        return "汽车与机器人"
    if any(keyword in text for keyword in ["医疗", "医药", "健康", "创新药"]):
        return "医疗健康"
    if any(keyword in text for keyword in ["家用电器", "美容护理", "纺织服饰", "农林牧渔", "消费", "社会服务"]):
        return "消费"
    if any(keyword in text for keyword in ["电力", "新能源", "储能", "输变电", "光伏", "风电"]):
        return "电力新能源"
    if any(keyword in text for keyword in ["商业航天", "国防军工", "军工", "航天"]):
        return "军工航天"
    if any(keyword in text for keyword in ["房地产", "建筑材料", "钢铁", "环保", "交通运输"]):
        return "传统行业"
    return sector or stock_type or "其他"


def type_distribution(items: list[dict[str, Any]], limit: int = 8, market: str = "us") -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in items:
        stock_type = brief_category(item, market)
        counts[stock_type] = counts.get(stock_type, 0) + 1
    total = sum(counts.values())
    if total <= 0:
        return []
    rows = [
        {
            "stock_type": stock_type,
            "count": count,
            "pct": clean_float(count / total * 100, 1),
        }
        for stock_type, count in counts.items()
    ]
    rows.sort(key=lambda item: (-int(item["count"]), str(item["stock_type"])))
    return rows[:limit]


def is_technology_item(item: dict[str, Any]) -> bool:
    stock_type = str(item.get("stock_type") or "")
    sector = str(item.get("sector") or "")
    if stock_type in TECH_TYPES:
        return True
    return any(keyword in stock_type or keyword in sector for keyword in TECH_KEYWORDS)


def build_technology_focus(latest_items: list[dict[str, Any]], top_n: int) -> dict[str, Any]:
    tech_items = [item for item in latest_items if item.get("ticker") != "QQQ" and is_technology_item(item)]
    tech_by_rank = sorted(tech_items, key=lambda item: item.get("rank") or 9999)
    strong_up = sorted(
        [
            item
            for item in tech_items
            if (item.get("daily_change_pct") is not None and item["daily_change_pct"] > 0)
            or (item.get("rank_change") is not None and item["rank_change"] > 0)
        ],
        key=lambda item: (
            -(item.get("daily_change_pct") if item.get("daily_change_pct") is not None else -999),
            item.get("rank") or 9999,
        ),
    )
    top20_tech = [item for item in tech_items if item.get("rank") and item["rank"] <= top_n]
    return {
        "count": len(tech_items),
        "top20_count": len(top20_tech),
        "industry_distribution": type_distribution(tech_items, limit=10),
        "top10": tech_by_rank[:10],
        "strong_up": strong_up[:10],
    }


def build_rank_history(recent: pd.DataFrame, tickers: set[str]) -> dict[str, list[dict[str, Any]]]:
    history: dict[str, list[dict[str, Any]]] = {}
    for ticker in sorted(tickers):
        ticker_rows = recent[recent["ticker"] == ticker].sort_values("as_of_date")
        history[ticker] = [
            {"date": str(row.as_of_date), "rank": clean_int(row.rank)}
            for row in ticker_rows.itertuples(index=False)
        ]
    return history


def _names(items: list[dict[str, Any]], limit: int = 4) -> str:
    labels = [str(item.get("name") or item.get("ticker") or "") for item in items[:limit]]
    labels = [label for label in labels if label]
    return "、".join(labels) if labels else "暂无"


def build_summary(
    market_label: str,
    latest_date: str,
    benchmark_item: dict[str, Any],
    stable_top20: list[dict[str, Any]],
    upward_moves: list[dict[str, Any]],
    downward_moves: list[dict[str, Any]],
    entered_top20: list[dict[str, Any]],
    dropped_top20: list[dict[str, Any]],
    type_stats: dict[str, list[dict[str, Any]]],
    technology_focus: dict[str, Any],
) -> list[str]:
    benchmark_label = "QQQ" if market_label == "美股" else "中证500" if market_label == "A股" else "恒生科技"
    lines = [
        f"{latest_date} {market_label}排名缓存已更新，{benchmark_label} 当前排名 #{benchmark_item.get('rank')}，ATR 倍数 {benchmark_item.get('atr_score')}。",
        f"最近 5 个交易日稳定在前20的股票有 {len(stable_top20)} 只，可用于观察强势队列的延续性。",
        f"大幅上升股票包括 {_names(upward_moves)}；大幅下降股票包括 {_names(downward_moves)}。",
        f"今日进入前20 {len(entered_top20)} 只，跌出前20 {len(dropped_top20)} 只。",
    ]
    if market_label == "美股":
        lines.append(f"科技池共 {technology_focus.get('count', 0)} 只，其中 {technology_focus.get('top20_count', 0)} 只位于前20。")
    if type_stats.get("upward_moves"):
        top_type = type_stats["upward_moves"][0]
        lines.append(f"大幅上升股票中占比最高的类型是 {top_type['stock_type']}，数量 {top_type['count']}，占比 {top_type['pct']}%。")
    return lines[:7]


def build_rule_based_analysis(brief: dict[str, Any]) -> str:
    market = brief.get("market", "us")
    market_label = brief.get("market_label", "美股")
    benchmark_label = brief.get("benchmark_label", "QQQ")
    benchmark = brief.get("benchmark", {})
    tech = brief.get("technology_focus", {})
    top_type = (brief.get("type_stats", {}).get("top20") or [{}])[0].get("stock_type", "暂无")
    up_type = (brief.get("type_stats", {}).get("upward_moves") or [{}])[0].get("stock_type", "暂无")
    down_type = (brief.get("type_stats", {}).get("downward_moves") or [{}])[0].get("stock_type", "暂无")
    tech_top = _names(tech.get("top10", []), 5)
    tech_up = _names(tech.get("strong_up", []), 5)
    return (
        f"市场情绪：截至 {brief.get('as_of_date')}，{benchmark_label} 在本轮 {brief.get('window')} 日重心窗口中的排名为 "
        f"#{benchmark.get('rank', '--')}，ATR 倍数为 {benchmark.get('atr_score', '--')}，可作为观察纳指整体风险偏好的基准。"
        f"稳定前20股票数量为 {len(brief.get('stable_top20', []))} 只，说明当前强势队列仍有一定延续性，但需要结合个股当日涨跌和排名跳动确认是否出现拥挤或退潮。"
        f"\n强势结构：今日 Top20 中占比靠前的类型是 {top_type}，大幅上升股票中占比靠前的类型是 {up_type}。"
        f"如果这些类型同时出现在稳定前20和大幅上升列表中，通常代表资金偏好更集中；如果只出现在大幅上升中，则更像短线补涨或轮动。"
        f"\n异常变化：大幅上升股票包括 {_names(brief.get('upward_moves', []), 6)}，大幅下降股票包括 {_names(brief.get('downward_moves', []), 6)}。"
        f"下降端占比靠前的类型是 {down_type}，需要观察其是否从前20持续滑落，还是仅为单日波动造成的排名扰动。"
        + (
            f"\n科技专项：科技池共 {tech.get('count', 0)} 只，其中 {tech.get('top20_count', 0)} 只进入前20；科技股排名前列包括 {tech_top}，"
            f"科技类显著上涨股票包括 {tech_up}。这部分适合单独跟踪，因为它能更直接反映半导体、软件、互联网、云计算、硬件等方向的内部轮动。"
            if market == "us"
            else ""
        )
        + f"\n观察清单：明日重点看 {benchmark_label} 是否继续保持当前相对位置，稳定前20股票是否继续留在强势区，以及强势类型是否出现集中扩散。"
        f"以上为量化排名解读，不构成投资建议。"
    )


def build_brief(window: int, as_of_date: str | None, top_n: int, move_threshold: int, market: str = "us") -> dict[str, Any]:
    market = normalize_market(market)
    benchmark = default_benchmark_for_market(market)
    market_label = {"us": "美股", "cn": "A股", "hk": "港股"}.get(market, market)
    benchmark_label = {"us": "QQQ", "cn": "中证500", "hk": "恒生科技"}.get(market, benchmark)
    df = load_ranking(window, market)
    dates = sorted(df["as_of_date"].dropna().unique().tolist())
    if not dates:
        raise ValueError("Ranking cache has no dates")
    if as_of_date:
        dates = [item for item in dates if item <= as_of_date]
        if not dates:
            raise ValueError(f"No cached dates on or before {as_of_date}")

    latest_date = dates[-1]
    previous_date = dates[-2] if len(dates) >= 2 else latest_date
    recent_dates = dates[-10:]
    stability_dates = dates[-5:]
    names = load_company_names()

    latest = df[df["as_of_date"] == latest_date].copy().sort_values("rank")
    previous = df[df["as_of_date"] == previous_date].copy()
    recent = df[df["as_of_date"].isin(recent_dates)].copy()
    stability = df[df["as_of_date"].isin(stability_dates)].copy()

    previous_rank_map = {str(row.ticker): int(row.rank) for row in previous.itertuples(index=False)}
    previous_close_map = {
        str(row.ticker): float(row.close)
        for row in previous.itertuples(index=False)
        if not pd.isna(row.close)
    }
    latest_rank_map = {str(row.ticker): int(row.rank) for row in latest.itertuples(index=False)}
    latest_items = [
        item_with_change(row, names, market, previous_rank_map, previous_close_map)
        for row in latest.itertuples(index=False)
    ]

    top20 = [item for item in latest_items if item["ticker"] != benchmark][:top_n]

    rank_lists = {
        ticker: [int(rank) for rank in group.sort_values("as_of_date")["rank"].tolist()]
        for ticker, group in stability[stability["ticker"] != benchmark].groupby("ticker")
    }
    stable_top20 = []
    for ticker, ranks in rank_lists.items():
        if len(ranks) == len(stability_dates) and max(ranks) <= top_n and ticker in latest_rank_map:
            row = latest[latest["ticker"] == ticker].iloc[0]
            item = item_with_change(row, names, market, previous_rank_map, previous_close_map)
            item["avg_rank_5"] = round(sum(ranks) / len(ranks), 1)
            item["best_rank_5"] = min(ranks)
            item["worst_rank_5"] = max(ranks)
            stable_top20.append(item)
    stable_top20.sort(key=lambda item: (item["avg_rank_5"], item["rank"]))

    movers = [item for item in latest_items if item["ticker"] != benchmark and item["rank_change"] is not None]
    upward_moves = sorted(
        [item for item in movers if item["rank_change"] > move_threshold],
        key=lambda item: (-(item.get("daily_change_pct") if item.get("daily_change_pct") is not None else -999), item["rank"]),
    )
    downward_moves = sorted(
        [item for item in movers if item["rank_change"] < -move_threshold],
        key=lambda item: (-(item.get("daily_change_pct") if item.get("daily_change_pct") is not None else -999), item["rank"]),
    )
    entered_top20 = sorted(
        [
            item
            for item in movers
            if item["rank"] <= top_n and (item["previous_rank"] is None or item["previous_rank"] > top_n)
        ],
        key=lambda item: item["rank"],
    )
    dropped_top20 = sorted(
        [
            item
            for item in movers
            if item["rank"] > top_n and item["previous_rank"] is not None and item["previous_rank"] <= top_n
        ],
        key=lambda item: item["rank"],
    )

    technology_focus = build_technology_focus(latest_items, top_n) if market == "us" else {
        "count": 0,
        "top20_count": 0,
        "industry_distribution": [],
        "top10": [],
        "strong_up": [],
    }
    type_stats = {
        "stable_top20": type_distribution(stable_top20, market=market),
        "upward_moves": type_distribution(upward_moves, market=market),
        "downward_moves": type_distribution(downward_moves, market=market),
        "top20": type_distribution(top20, market=market),
    }

    focus_tickers = {item["ticker"] for item in top20[:8]}
    focus_tickers.update(item["ticker"] for item in upward_moves[:5])
    focus_tickers.update(item["ticker"] for item in downward_moves[:5])
    focus_tickers.update(item["ticker"] for item in technology_focus.get("top10", [])[:5])
    focus_tickers.add(benchmark)

    benchmark_row = latest[latest["ticker"] == benchmark]
    benchmark_item = row_to_item(benchmark_row.iloc[0], names, market) if not benchmark_row.empty else {}

    brief = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "market": market,
        "market_label": market_label,
        "benchmark_label": benchmark_label,
        "window": window,
        "as_of_date": latest_date,
        "previous_date": previous_date,
        "recent_dates": recent_dates,
        "benchmark": benchmark_item,
        "top20": top20,
        "stable_top20": stable_top20,
        "upward_moves": upward_moves,
        "downward_moves": downward_moves,
        "entered_top20": entered_top20,
        "dropped_top20": dropped_top20,
        "type_stats": type_stats,
        "technology_focus": technology_focus,
        "rank_history": build_rank_history(recent, focus_tickers),
    }
    brief["summary_points"] = build_summary(
        market_label,
        latest_date,
        benchmark_item,
        stable_top20,
        upward_moves,
        downward_moves,
        entered_top20,
        dropped_top20,
        type_stats,
        technology_focus,
    )
    brief["model_interpretation"] = {
        "status": "fallback",
        "text": build_rule_based_analysis(brief),
    }
    return brief


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate structured daily ranking brief data.")
    parser.add_argument("--window", type=int, default=10, choices=[10], help="Ranking window. Daily brief uses 10-day window only.")
    parser.add_argument("--market", choices=["us", "cn", "hk"], default="us", help="Market to generate: us, cn, or hk.")
    parser.add_argument("--as-of-date", default=None, help="Use cached date on or before YYYY-MM-DD.")
    parser.add_argument("--top-n", type=int, default=20, help="Top N threshold.")
    parser.add_argument("--move-threshold", type=int, default=10, help="Rank move threshold.")
    parser.add_argument("--use-llm", action="store_true", help="Call the configured LLM to fill model_interpretation.")
    parser.add_argument("--llm-model", default="deepseek-chat", help="LLM model name. Defaults to DeepSeek; qwen* uses DashScope.")
    parser.add_argument("--llm-timeout", type=int, default=60, help="LLM request timeout seconds.")
    parser.add_argument("--llm-max-tokens", type=int, default=1500, help="LLM max output tokens.")
    parser.add_argument("--output", default=None, help="Output JSON path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    brief = build_brief(args.window, args.as_of_date, args.top_n, args.move_threshold, args.market)
    if args.use_llm:
        try:
            brief["model_interpretation"] = generate_model_interpretation(
                brief,
                model=args.llm_model,
                timeout=args.llm_timeout,
                max_tokens=args.llm_max_tokens,
            )
        except Exception as exc:
            brief["model_interpretation"] = {
                "status": "error",
                "model": args.llm_model,
                "text": brief["model_interpretation"]["text"],
                "error": str(exc),
            }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = Path(args.output) if args.output else OUTPUT_DIR / f"daily_brief_{brief['market']}_{brief['as_of_date']}_w{args.window}.json"
    output.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Brief data written: {output}")


if __name__ == "__main__":
    main()
