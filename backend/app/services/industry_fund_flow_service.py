from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from app.core.config import INDUSTRY_FUND_FLOW_DB
from app.services.data_loader import normalize_market


@dataclass(frozen=True)
class IndustryFlowQuery:
    market: str = "us"
    trade_date: date | None = None
    limit: int = 100


def connect_industry_flow_db() -> sqlite3.Connection:
    conn = sqlite3.connect(INDUSTRY_FUND_FLOW_DB)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_industry_flow_db() -> None:
    INDUSTRY_FUND_FLOW_DB.parent.mkdir(parents=True, exist_ok=True)
    with connect_industry_flow_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_fund_flows (
                market TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                ths_code TEXT NOT NULL,
                name TEXT NOT NULL,
                industry_name TEXT NOT NULL,
                flow_amount REAL NOT NULL,
                PRIMARY KEY (market, trade_date, ticker)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_stock_fund_flows_industry_date
            ON stock_fund_flows (market, industry_name, trade_date)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS industry_fund_flows (
                market TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                industry_name TEXT NOT NULL,
                flow_amount REAL NOT NULL,
                stock_count INTEGER NOT NULL,
                positive_count INTEGER NOT NULL,
                negative_count INTEGER NOT NULL,
                PRIMARY KEY (market, trade_date, industry_name)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_industry_fund_flows_date
            ON industry_fund_flows (market, trade_date)
            """
        )


def latest_industry_flow_date(market: str) -> str:
    ensure_industry_flow_db()
    market = normalize_market(market)
    with connect_industry_flow_db() as conn:
        row = conn.execute(
            "SELECT MAX(trade_date) AS trade_date FROM industry_fund_flows WHERE market = ?",
            (market,),
        ).fetchone()
    if not row or not row["trade_date"]:
        raise ValueError(f"No industry fund flow data for market {market}")
    return str(row["trade_date"])


def available_industry_flow_dates(market: str, limit: int = 260) -> list[str]:
    ensure_industry_flow_db()
    market = normalize_market(market)
    with connect_industry_flow_db() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT trade_date
            FROM industry_fund_flows
            WHERE market = ?
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            (market, limit),
        ).fetchall()
    return list(reversed([str(row["trade_date"]) for row in rows]))


def build_industry_flow_ranking(query: IndustryFlowQuery) -> dict[str, object]:
    ensure_industry_flow_db()
    market = normalize_market(query.market)
    trade_date = query.trade_date.isoformat() if query.trade_date else latest_industry_flow_date(market)
    with connect_industry_flow_db() as conn:
        rows = conn.execute(
            """
            SELECT market, trade_date, industry_name, flow_amount, stock_count, positive_count, negative_count
            FROM industry_fund_flows
            WHERE market = ? AND trade_date = ?
            ORDER BY flow_amount DESC
            LIMIT ?
            """,
            (market, trade_date, query.limit),
        ).fetchall()
    data = [dict(row) for row in rows]
    for index, item in enumerate(data, start=1):
        item["rank"] = index
    return {"market": market, "trade_date": trade_date, "count": len(data), "data": data}


def build_industry_flow_trend(
    market: str,
    industries: list[str] | None = None,
    top_n: int = 8,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, object]:
    ensure_industry_flow_db()
    market = normalize_market(market)
    params: list[object] = [market]
    filters = ["market = ?"]
    if start_date is not None:
        filters.append("trade_date >= ?")
        params.append(start_date.isoformat())
    if end_date is not None:
        filters.append("trade_date <= ?")
        params.append(end_date.isoformat())
    where = " AND ".join(filters)

    selected_industries = [item.strip() for item in industries or [] if item.strip()]
    with connect_industry_flow_db() as conn:
        if not selected_industries:
            latest = latest_industry_flow_date(market)
            selected_industries = [
                str(row["industry_name"])
                for row in conn.execute(
                    """
                    SELECT industry_name
                    FROM industry_fund_flows
                    WHERE market = ? AND trade_date = ?
                    ORDER BY flow_amount DESC
                    LIMIT ?
                    """,
                    (market, latest, top_n),
                ).fetchall()
            ]
        if not selected_industries:
            return {"market": market, "industries": [], "series": []}
        placeholders = ",".join("?" for _ in selected_industries)
        rows = conn.execute(
            f"""
            SELECT industry_name, trade_date, flow_amount
            FROM industry_fund_flows
            WHERE {where} AND industry_name IN ({placeholders})
            ORDER BY industry_name, trade_date
            """,
            params + selected_industries,
        ).fetchall()

    by_industry: dict[str, list[dict[str, object]]] = {industry: [] for industry in selected_industries}
    for row in rows:
        by_industry.setdefault(str(row["industry_name"]), []).append(
            {"date": str(row["trade_date"]), "flow_amount": float(row["flow_amount"])}
        )
    return {
        "market": market,
        "industries": selected_industries,
        "series": [{"industry_name": industry, "points": by_industry.get(industry, [])} for industry in selected_industries],
    }


def build_industry_stock_flows(
    market: str,
    industry_name: str,
    trade_date: date | None = None,
    limit: int = 200,
) -> dict[str, object]:
    ensure_industry_flow_db()
    market = normalize_market(market)
    effective_date = trade_date.isoformat() if trade_date else latest_industry_flow_date(market)
    with connect_industry_flow_db() as conn:
        rows = conn.execute(
            """
            SELECT ticker, ths_code, name, industry_name, flow_amount
            FROM stock_fund_flows
            WHERE market = ? AND trade_date = ? AND industry_name = ?
            ORDER BY flow_amount DESC
            LIMIT ?
            """,
            (market, effective_date, industry_name, limit),
        ).fetchall()
    data = [dict(row) for row in rows]
    for index, item in enumerate(data, start=1):
        item["rank"] = index
    return {
        "market": market,
        "trade_date": effective_date,
        "industry_name": industry_name,
        "count": len(data),
        "data": data,
    }
