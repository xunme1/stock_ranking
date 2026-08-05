from __future__ import annotations

"""Deterministic price/volume checks for earnings-report rendering."""

from datetime import date
from typing import Any

import pandas as pd


def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "close", "volume"}
    if not required.issubset(frame.columns):
        return pd.DataFrame(columns=["date", "close", "volume"])
    output = frame[["date", "close", "volume"]].copy()
    output["date"] = pd.to_datetime(output["date"], errors="coerce").dt.date
    output["close"] = pd.to_numeric(output["close"], errors="coerce")
    output["volume"] = pd.to_numeric(output["volume"], errors="coerce")
    return output.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)


def _common_sessions(stock: pd.DataFrame, benchmark: pd.DataFrame) -> pd.DataFrame:
    return stock.merge(benchmark, on="date", suffixes=("_stock", "_qqq"), how="inner").sort_values("date").reset_index(drop=True)


def _return_pct(current: float, previous: float) -> float | None:
    if not previous:
        return None
    return round((current / previous - 1) * 100, 2)


def pre_earnings_metrics(stock: pd.DataFrame, benchmark: pd.DataFrame, calendar_date: date) -> dict[str, Any]:
    """Use the final common session before the expected release date as pre-event context."""
    common = _common_sessions(_clean_frame(stock), _clean_frame(benchmark))
    common = common[common["date"] < calendar_date].reset_index(drop=True)
    if len(common) < 4:
        return {"kind": "pre_earnings", "status": "missing", "reason": "本地日线不足，无法计算财报前相对表现。"}
    latest = common.iloc[-1]
    one_day = common.iloc[-2]
    three_day = common.iloc[-4]
    stock_1d = _return_pct(float(latest.close_stock), float(one_day.close_stock))
    qqq_1d = _return_pct(float(latest.close_qqq), float(one_day.close_qqq))
    stock_3d = _return_pct(float(latest.close_stock), float(three_day.close_stock))
    qqq_3d = _return_pct(float(latest.close_qqq), float(three_day.close_qqq))
    return {
        "kind": "pre_earnings",
        "status": "available",
        "session_date": latest.date.isoformat(),
        "one_day_stock_pct": stock_1d,
        "one_day_qqq_pct": qqq_1d,
        "one_day_relative_pct": round(stock_1d - qqq_1d, 2) if stock_1d is not None and qqq_1d is not None else None,
        "three_day_stock_pct": stock_3d,
        "three_day_qqq_pct": qqq_3d,
        "three_day_relative_pct": round(stock_3d - qqq_3d, 2) if stock_3d is not None and qqq_3d is not None else None,
    }


def post_earnings_metrics(
    stock: pd.DataFrame,
    benchmark: pd.DataFrame,
    release_date: date,
    release_time: str,
) -> dict[str, Any]:
    """Find the first full regular session that can reflect a confirmed release."""
    common = _common_sessions(_clean_frame(stock), _clean_frame(benchmark))
    if common.empty:
        return {"kind": "post_earnings", "status": "missing", "reason": "缺少股票或 QQQ 本地日线数据。"}
    same_day_allowed = release_time in {"before_market", "during_market"}
    eligible = common[common["date"] >= release_date] if same_day_allowed else common[common["date"] > release_date]
    if eligible.empty:
        return {
            "kind": "post_earnings",
            "status": "pending",
            "reason": "等待财报发布后的首个完整常规交易时段数据。",
        }
    event_index = int(eligible.index[0])
    if event_index == 0:
        return {"kind": "post_earnings", "status": "missing", "reason": "缺少财报日前一交易日，无法计算变化。"}
    event = common.iloc[event_index]
    previous = common.iloc[event_index - 1]
    stock_return = _return_pct(float(event.close_stock), float(previous.close_stock))
    qqq_return = _return_pct(float(event.close_qqq), float(previous.close_qqq))
    volume_window = common.iloc[max(0, event_index - 20):event_index]["volume_stock"].dropna()
    volume_ratio = round(float(event.volume_stock) / float(volume_window.mean()), 2) if len(volume_window) >= 5 and float(volume_window.mean()) else None
    return {
        "kind": "post_earnings",
        "status": "available",
        "session_date": event.date.isoformat(),
        "stock_return_pct": stock_return,
        "qqq_return_pct": qqq_return,
        "relative_return_pct": round(stock_return - qqq_return, 2) if stock_return is not None and qqq_return is not None else None,
        "volume_vs_20d": volume_ratio,
    }
