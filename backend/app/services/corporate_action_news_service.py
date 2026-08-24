from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from dotenv import load_dotenv

from app.core.config import CORPORATE_ACTION_NEWS_DB, PROJECT_ROOT
from app.services.data_loader import (
    load_cn_stock_profiles,
    load_company_profiles,
    load_hk_stock_profiles,
    load_ticker_file,
    normalize_market,
    normalize_ticker_for_market,
)


TAVILY_SEARCH_URL = "https://api.tavily.com/search"
DEEPSEEK_COMPAT_URL = "https://api.deepseek.com/chat/completions"
LAOHU_SEARCH_URL = "https://frontend-community.laohu8.com/search/v1/news"
MARKETS = ("us", "cn", "hk")
EVENT_TYPES = ("buyback", "reduction")
EVENT_STAGES = ("announced", "authorized", "in_progress", "executed", "completed")
REPURCHASE_SHARES_SCOPES = ("daily", "cumulative", "program_total")
BUYBACK_CHART_WINDOW_DAYS = 10
ATTENTION_LEVELS = ("high", "normal")
MIN_CONFIDENCE = 0.70
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "ref", "referrer"}
EVENT_STAGE_PRIORITY = {stage: index for index, stage in enumerate(EVENT_STAGES)}
LAOHU_SEARCH_WORDS = {"buyback": "回购", "reduction": "减持"}
MAX_LAOHU_RESULTS_PER_EVENT = 30
MAX_STRUCTURING_CANDIDATES = 20
DEEPSEEK_STRUCTURING_WORKERS = 5
LAOHU_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; StockRankingNewsBot/1.0)",
    "Referer": "https://www.laohu8.com/search",
}

_TAVILY_KEY_LOCK = threading.Lock()
_TAVILY_KEY_CURSORS: dict[tuple[str, ...], int] = {}

BUYBACK_RE = re.compile(r"\b(buyback|repurchase|repurchased|share repurchase)\b|回购|购回|注销回购", re.IGNORECASE)
REDUCTION_RE = re.compile(r"\b(insider selling|stake sale|share sale|sold shares|disposal)\b|减持|出售股份|配售股份", re.IGNORECASE)
EXCLUDED_RE = re.compile(r"tax withholding|withholding tax|employee vest|equity vest|etf creation|etf redemption|新股发行|增发|员工持股归属|代扣税|被动基金调仓|基金调仓", re.IGNORECASE)
NUMBER_RE = re.compile(r"(?:\$|US\$|HK\$|人民币|RMB|CNY)?\s?[\d,.]+\s?(?:million|billion|m|bn|亿元|万元|万股|百万股|股份)?", re.IGNORECASE)
PUBLISHED_META_RE = re.compile(
    r"(?:datePublished|article:published_time|publish(?:ed)?(?:_date|Date)?|dateModified)\"?\s*(?:content=|[:=])\s*\"?"
    r"(20\d{2}[-/]\d{1,2}[-/]\d{1,2})",
    re.IGNORECASE,
)

SEARCH_TEMPLATES: dict[str, dict[str, tuple[str, str]]] = {
    "us": {
        "buyback": (
            "US listed companies share buyback repurchase authorization execution",
            "US company stock repurchase buyback completed announcement",
        ),
        "reduction": (
            "US listed company insider selling major shareholder stake sale",
            "US stock director officer shareholder sold shares disposal announcement",
        ),
    },
    "cn": {
        "buyback": (
            "A股 上市公司 股份回购 回购计划 实施 完成 公告",
            "沪深上市公司 回购股份 注销 回购进展 公告",
        ),
        "reduction": (
            "A股 上市公司 大股东 董监高 减持计划 减持实施 公告",
            "沪深上市公司 股东 减持 集中竞价 大宗交易 公告",
        ),
    },
    "hk": {
        "buyback": (
            "港股 上市公司 股份回购 购回股份 注销 公告",
            "Hong Kong listed company share repurchase buyback announcement",
        ),
        "reduction": (
            "港股 上市公司 大股东 董事 减持 出售股份 配售 公告",
            "Hong Kong listed company director substantial shareholder disposal stake sale",
        ),
    },
}


@dataclass(frozen=True)
class PoolEntry:
    market: str
    ticker: str
    name: str


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _norm_text(value: object) -> str:
    return re.sub(r"[^0-9A-Z\u4e00-\u9fff]", "", str(value or "").upper())


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def normalize_source_url(url: str) -> str:
    """Canonicalize a news URL for idempotency while retaining the original link for display."""
    parsed = urlparse(str(url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return str(url or "").strip()
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", urlencode(sorted(query)), ""))


def is_absolute_http_url(url: object) -> bool:
    parsed = urlparse(str(url or "").strip())
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def source_quality(url: str) -> str:
    domain = _domain(url)
    primary = ("sec.gov", "hkexnews.hk", "hkex.com.hk", "cninfo.com.cn", "sse.com.cn", "szse.cn", "nasdaq.com", "nyse.com")
    mainstream = ("reuters.com", "bloomberg.com", "cnbc.com", "wsj.com", "finance.yahoo.com", "caixin.com", "stcn.com", "21jingji.com")
    if any(token in domain for token in primary) or ".ir." in domain or domain.startswith("ir."):
        return "primary"
    if any(token in domain for token in mainstream):
        return "mainstream"
    return "other"


def connect(db_path: Path = CORPORATE_ACTION_NEWS_DB) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_connection(db_path: Path = CORPORATE_ACTION_NEWS_DB):
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_db(db_path: Path = CORPORATE_ACTION_NEWS_DB) -> None:
    with db_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS corporate_action_news (
                event_id TEXT PRIMARY KEY,
                market TEXT NOT NULL,
                ticker TEXT,
                company_name TEXT NOT NULL DEFAULT '',
                company_identity TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_stage TEXT NOT NULL,
                actor_name TEXT NOT NULL DEFAULT '',
                actor_type TEXT NOT NULL DEFAULT '',
                headline TEXT NOT NULL,
                headline_zh TEXT NOT NULL DEFAULT '',
                summary_zh TEXT NOT NULL DEFAULT '',
                quantity_text TEXT NOT NULL DEFAULT '',
                amount_text TEXT NOT NULL DEFAULT '',
                ownership_change_text TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL,
                event_date TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL,
                normalized_url TEXT NOT NULL DEFAULT '',
                source_domain TEXT NOT NULL,
                source_quality TEXT NOT NULL,
                confidence REAL NOT NULL,
                exchange TEXT NOT NULL DEFAULT '',
                source_schema TEXT NOT NULL DEFAULT '',
                agent_record_id TEXT NOT NULL DEFAULT '',
                source_agent TEXT NOT NULL DEFAULT '',
                evidence_text TEXT NOT NULL DEFAULT '',
                repurchase_shares REAL,
                repurchase_shares_scope TEXT NOT NULL DEFAULT '',
                in_stock_pool INTEGER NOT NULL DEFAULT 0,
                attention_level TEXT NOT NULL DEFAULT 'normal',
                pool_match_method TEXT NOT NULL DEFAULT '',
                pool_match_confidence REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_corporate_action_news_market_date
            ON corporate_action_news (market, published_at DESC);
            CREATE INDEX IF NOT EXISTS idx_corporate_action_news_attention
            ON corporate_action_news (market, in_stock_pool DESC, published_at DESC);
            CREATE TABLE IF NOT EXISTS corporate_action_search_runs (
                run_id TEXT PRIMARY KEY,
                market TEXT NOT NULL,
                as_of_date TEXT NOT NULL,
                window_start TEXT NOT NULL,
                window_end TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                status TEXT NOT NULL,
                task_count INTEGER NOT NULL,
                candidate_count INTEGER NOT NULL,
                stored_count INTEGER NOT NULL,
                error_summary TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_corporate_action_runs_market_date
            ON corporate_action_search_runs (market, as_of_date DESC, completed_at DESC);
            CREATE TABLE IF NOT EXISTS corporate_action_pool_matches (
                event_id TEXT NOT NULL,
                market TEXT NOT NULL,
                ticker TEXT NOT NULL,
                match_method TEXT NOT NULL,
                match_confidence REAL NOT NULL,
                matched_at TEXT NOT NULL,
                PRIMARY KEY (event_id, ticker),
                FOREIGN KEY (event_id) REFERENCES corporate_action_news(event_id)
            );
            CREATE TABLE IF NOT EXISTS corporate_action_imported_objects (
                bucket TEXT NOT NULL,
                object_key TEXT NOT NULL,
                etag TEXT NOT NULL,
                source_agent TEXT NOT NULL DEFAULT '',
                imported_at TEXT NOT NULL,
                status TEXT NOT NULL,
                total_rows INTEGER NOT NULL DEFAULT 0,
                accepted_rows INTEGER NOT NULL DEFAULT 0,
                rejected_rows INTEGER NOT NULL DEFAULT 0,
                stored_event_count INTEGER NOT NULL DEFAULT 0,
                deduplicated_v2_rows INTEGER NOT NULL DEFAULT 0,
                error_summary TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (bucket, object_key, etag)
            );
            CREATE INDEX IF NOT EXISTS idx_corporate_action_imported_objects_status
            ON corporate_action_imported_objects (status, imported_at DESC);
            CREATE TABLE IF NOT EXISTS corporate_action_import_rejections (
                rejection_id INTEGER PRIMARY KEY AUTOINCREMENT,
                bucket TEXT NOT NULL,
                object_key TEXT NOT NULL,
                etag TEXT NOT NULL,
                line_number INTEGER NOT NULL,
                market TEXT NOT NULL DEFAULT '',
                schema_version TEXT NOT NULL DEFAULT '',
                source_agent TEXT NOT NULL DEFAULT '',
                raw_payload TEXT NOT NULL,
                error_code TEXT NOT NULL,
                error_summary TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (bucket, object_key, etag, line_number)
            );
            CREATE INDEX IF NOT EXISTS idx_corporate_action_import_rejections_market_status
            ON corporate_action_import_rejections (market, status, created_at DESC);
            CREATE TABLE IF NOT EXISTS corporate_action_price_snapshots (
                event_id TEXT NOT NULL,
                price_date TEXT NOT NULL,
                close REAL NOT NULL,
                data_source TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                PRIMARY KEY (event_id, price_date),
                FOREIGN KEY (event_id) REFERENCES corporate_action_news(event_id)
            );
            CREATE TABLE IF NOT EXISTS corporate_action_chart_fetches (
                event_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                data_source TEXT NOT NULL DEFAULT '',
                window_start TEXT NOT NULL DEFAULT '',
                window_end TEXT NOT NULL DEFAULT '',
                attempted_at TEXT NOT NULL,
                error_summary TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (event_id) REFERENCES corporate_action_news(event_id)
            );
            CREATE INDEX IF NOT EXISTS idx_corporate_action_chart_fetches_status
            ON corporate_action_chart_fetches (status, attempted_at DESC);
            """
        )
        columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(corporate_action_news)").fetchall()}
        if "headline_zh" not in columns:
            conn.execute("ALTER TABLE corporate_action_news ADD COLUMN headline_zh TEXT NOT NULL DEFAULT ''")
        if "normalized_url" not in columns:
            conn.execute("ALTER TABLE corporate_action_news ADD COLUMN normalized_url TEXT NOT NULL DEFAULT ''")
        for column in ("exchange", "source_schema", "agent_record_id", "source_agent", "evidence_text", "repurchase_shares_scope"):
            if column not in columns:
                conn.execute(f"ALTER TABLE corporate_action_news ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        if "repurchase_shares" not in columns:
            conn.execute("ALTER TABLE corporate_action_news ADD COLUMN repurchase_shares REAL")
        import_columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(corporate_action_imported_objects)").fetchall()}
        for column in ("stored_event_count", "deduplicated_v2_rows"):
            if column not in import_columns:
                conn.execute(f"ALTER TABLE corporate_action_imported_objects ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0")
        legacy_urls = conn.execute(
            "SELECT event_id, source_url FROM corporate_action_news WHERE normalized_url = ''"
        ).fetchall()
        if legacy_urls:
            conn.executemany(
                "UPDATE corporate_action_news SET normalized_url=? WHERE event_id=?",
                [(normalize_source_url(str(row["source_url"])), str(row["event_id"])) for row in legacy_urls],
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_corporate_action_news_identity_url "
            "ON corporate_action_news (market, event_type, normalized_url)"
        )


def build_search_tasks(market: str) -> list[dict[str, str]]:
    market = normalize_market(market)
    return [
        {"market": market, "event_type": event_type, "query": query}
        for event_type in EVENT_TYPES
        for query in SEARCH_TEMPLATES[market][event_type]
    ]


def build_laohu_tasks(market: str) -> list[dict[str, str]]:
    """Supplement Chinese-market coverage with the public Tiger Community news search."""
    market = normalize_market(market)
    if market not in {"cn", "hk"}:
        return []
    return [
        {"market": market, "event_type": event_type, "query": query, "provider": "laohu8"}
        for event_type, query in LAOHU_SEARCH_WORDS.items()
    ]


def build_collection_tasks(market: str) -> list[dict[str, str]]:
    return [
        *[{**task, "provider": "tavily"} for task in build_search_tasks(market)],
        *build_laohu_tasks(market),
    ]


def load_tavily_keys() -> list[str]:
    load_dotenv(PROJECT_ROOT / ".env")
    numbered = sorted(
        ((int(match.group(1)), value.strip()) for name, value in os.environ.items() if (match := re.fullmatch(r"TAVILY_API_KEY(\d+)", name)) and value.strip()),
        key=lambda item: item[0],
    )
    keys = [value for _, value in numbered]
    for raw in (os.getenv("TAVILY_API_KEYS", ""), os.getenv("TAVILY_API_KEY", "")):
        keys.extend(value.strip() for value in raw.split(",") if value.strip())
    return list(dict.fromkeys(keys))


def balanced_tavily_keys(keys: list[str] | None = None) -> list[str]:
    """Round-robin the configured key pool; per-request failures still fall through to every remaining key."""
    pool = list(keys if keys is not None else load_tavily_keys())
    if not pool:
        return []
    key = tuple(pool)
    with _TAVILY_KEY_LOCK:
        start = _TAVILY_KEY_CURSORS.get(key, 0) % len(pool)
        _TAVILY_KEY_CURSORS[key] = start + 1
    return pool[start:] + pool[:start]


def tavily_search(query: str, start: date, end: date, max_results: int = 10, timeout: int = 30) -> list[dict[str, Any]]:
    keys = balanced_tavily_keys()
    if not keys:
        raise RuntimeError("Missing Tavily API key")
    errors: list[str] = []
    for key in keys:
        try:
            response = requests.post(
                TAVILY_SEARCH_URL,
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "query": query,
                    "topic": "finance",
                    "search_depth": "basic",
                    "max_results": max(1, min(max_results, 10)),
                    "start_date": start.isoformat(),
                    "end_date": (end + timedelta(days=1)).isoformat(),
                    "include_answer": False,
                    "include_raw_content": False,
                },
                timeout=timeout,
            )
            if response.status_code in (401, 403, 429):
                errors.append(f"HTTP {response.status_code}")
                continue
            response.raise_for_status()
            return list(response.json().get("results") or [])
        except requests.RequestException as exc:
            errors.append(type(exc).__name__)
    raise RuntimeError(f"Tavily search failed: {', '.join(errors) or 'no usable key'}")


def laohu_search(query: str, page: int, timeout: int = 20) -> list[dict[str, Any]]:
    """Fetch one Tiger Community search page and fail loudly on invalid/empty API responses."""
    response = requests.get(
        LAOHU_SEARCH_URL,
        params={"word": query, "pageCount": page},
        headers=LAOHU_HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Tiger Community response is not a JSON object")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Tiger Community response has no data object")
    items = data.get("newsList") or []
    if not isinstance(items, list):
        raise ValueError("Tiger Community response has invalid newsList")
    return [item for item in items if isinstance(item, dict)]


def _parse_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text[:10], text.replace("/", "-")[:10]):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            pass
    return None


def resolve_published_date(result: dict[str, Any], timeout: int = 12) -> date | None:
    """Return an explicitly supplied or page-metadata publication date; never infer it from the search cutoff."""
    for value in (result.get("published_date"), result.get("published_at"), result.get("date")):
        if parsed := _parse_date(value):
            return parsed
    for value in (result.get("content"), result.get("raw_content")):
        match = PUBLISHED_META_RE.search(str(value or ""))
        if match and (parsed := _parse_date(match.group(1))):
            return parsed
    url = str(result.get("url") or "").strip()
    if not is_absolute_http_url(url):
        return None
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; StockRankingNewsBot/1.0)"},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None
    match = PUBLISHED_META_RE.search(response.text[:1_000_000])
    return _parse_date(match.group(1)) if match else None


def _event_type(text: str) -> str | None:
    has_buyback = bool(BUYBACK_RE.search(text))
    has_reduction = bool(REDUCTION_RE.search(text))
    if has_buyback and not has_reduction:
        return "buyback"
    if has_reduction and not has_buyback:
        return "reduction"
    return None


def _event_stage(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("completed", "完成", "完毕")):
        return "completed"
    if any(token in lowered for token in ("executed", "实施", "已回购", "sold")):
        return "executed"
    if any(token in lowered for token in ("in progress", "进展", "ongoing")):
        return "in_progress"
    if any(token in lowered for token in ("authorized", "approval", "授权", "批准")):
        return "authorized"
    return "announced"


def _candidate_from_result(result: dict[str, Any], task: dict[str, str], resolve_date: bool = False) -> dict[str, Any] | None:
    url = str(result.get("url") or "").strip()
    title = str(result.get("title") or "").strip()
    snippet = str(result.get("content") or result.get("snippet") or "").strip()
    text = f"{title} {snippet}"
    event_type = _event_type(text)
    published = resolve_published_date(result) if resolve_date else _parse_date(result.get("published_date") or result.get("published_at") or result.get("date"))
    if not is_absolute_http_url(url) or not title or not event_type or EXCLUDED_RE.search(text) or not published:
        return None
    return {
        "market": task["market"],
        "event_type": event_type,
        "headline": title[:500],
        "snippet": snippet[:2000],
        "published_at": published.isoformat(),
        "source_url": url,
        "normalized_url": normalize_source_url(url),
        "source_domain": _domain(url),
        "source_quality": source_quality(url),
        "event_stage": _event_stage(text),
    }


def _laohu_published_date(timestamp: object) -> date | None:
    try:
        value = float(timestamp)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone(timedelta(hours=8))).date()


def _candidate_from_laohu_result(result: dict[str, Any], task: dict[str, str]) -> dict[str, Any] | None:
    news_id = str(result.get("newsId") or "").strip()
    title = re.sub(r"</?font[^>]*>", "", str(result.get("title") or "")).strip()
    snippet = re.sub(r"</?font[^>]*>", "", str(result.get("listText") or "")).strip()
    snippet = re.sub(r"\s+", " ", snippet)
    published = _laohu_published_date(result.get("gmtCreate"))
    text = f"{title} {snippet}"
    event_type = _event_type(text)
    if not news_id or not title or not event_type or EXCLUDED_RE.search(text) or not published:
        return None
    url = f"https://www.laohu8.com/news/{news_id}"
    return {
        "market": task["market"],
        "event_type": event_type,
        "headline": title[:500],
        "snippet": snippet[:2000],
        "published_at": published.isoformat(),
        "source_url": url,
        "normalized_url": normalize_source_url(url),
        "source_domain": "laohu8.com",
        "source_quality": "other",
        "event_stage": _event_stage(text),
    }


def _fallback_extract(candidate: dict[str, Any]) -> dict[str, Any]:
    text = f"{candidate['headline']} {candidate['snippet']}"
    ticker_match = re.search(r"\((?:NASDAQ|NYSE|HKEX|SEHK|SZSE|SSE)\s*[:：]?\s*([A-Z0-9.]+)\)", text, re.IGNORECASE)
    ticker = ticker_match.group(1) if ticker_match else ""
    return {
        **candidate,
        "ticker": ticker,
        "company_name": "",
        "actor_name": "",
        "actor_type": "company" if candidate["event_type"] == "buyback" else "",
        "headline_zh": candidate["headline"] if re.search(r"[\u4e00-\u9fff]", candidate["headline"]) else "",
        "summary_zh": candidate["snippet"][:500],
        "quantity_text": "",
        "amount_text": "",
        "ownership_change_text": "",
        "event_date": "",
        "confidence": 0.70,
    }


def _load_deepseek_key() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    return os.getenv("DEEPSEEK_API_KEY", "").strip() or os.getenv("DEEPSEEK_KEY", "").strip()


def classify_candidates(
    candidates: list[dict[str, Any]], market: str, timeout: int = 90, diagnostics: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Use DeepSeek when available; retain deterministic, source-bound fallback records otherwise."""
    if len(candidates) > MAX_STRUCTURING_CANDIDATES:
        batches = [candidates[start:start + MAX_STRUCTURING_CANDIDATES] for start in range(0, len(candidates), MAX_STRUCTURING_CANDIDATES)]
        with ThreadPoolExecutor(max_workers=min(DEEPSEEK_STRUCTURING_WORKERS, len(batches))) as executor:
            classified_batches = executor.map(lambda batch: classify_candidates(batch, market, timeout, diagnostics), batches)
            return [event for batch in classified_batches for event in batch]
    key = _load_deepseek_key()
    if not candidates or not key:
        if candidates and diagnostics is not None:
            diagnostics.append("llm_degraded: missing DeepSeek API key")
        return [_fallback_extract(item) for item in candidates]
    compact = [
        {key: item.get(key, "") for key in ("headline", "snippet", "published_at", "source_url", "event_type", "event_stage")}
        for item in candidates[:40]
    ]
    prompt = (
        "你是上市公司行为新闻抽取器。只依据输入新闻抽取回购或现有股东减持事件；"
        "不要推测或补造 ticker、金额、日期。返回 JSON 对象 {\"events\":[...] }，每项必须包含 source_url、"
        "ticker、company_name、event_type、event_stage、actor_name、actor_type、headline_zh、summary_zh、quantity_text、"
        "amount_text、ownership_change_text、event_date、confidence。event_type 只能 buyback/reduction，"
        "event_stage 只能 announced/authorized/in_progress/executed/completed。headline_zh 和 summary_zh 使用简体中文，"
        "保留公司名、代码、金额和数量的原始精度。无法确认的字符串填空，confidence 0 到 1。\n"
        + f"\nOnly extract events for the requested market '{market}'; omit companies listed in other markets.\n"
        + json.dumps({"market": market, "news": compact}, ensure_ascii=False)
    )
    try:
        response = requests.post(
            DEEPSEEK_COMPAT_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"), "messages": [{"role": "user", "content": prompt}], "temperature": 0, "thinking": {"type": "disabled"}, "response_format": {"type": "json_object"}},
            timeout=timeout,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        if diagnostics is not None:
            diagnostics.append(f"llm_degraded: {type(exc).__name__}")
        return [_fallback_extract(item) for item in candidates]

    by_url = {str(item["source_url"]): item for item in candidates}
    extracted: list[dict[str, Any]] = []
    for item in parsed.get("events", []):
        if not isinstance(item, dict):
            continue
        source_url = str(item.get("source_url") or "")
        base = by_url.get(source_url)
        if not base:
            continue
        event_type = str(item.get("event_type") or base["event_type"])
        confidence = float(item.get("confidence") or 0)
        if event_type not in EVENT_TYPES or confidence < MIN_CONFIDENCE:
            continue
        stage = str(item.get("event_stage") or base["event_stage"])
        extracted.append(
            {
                **base,
                "ticker": str(item.get("ticker") or ""),
                "company_name": str(item.get("company_name") or ""),
                "event_type": event_type,
                "event_stage": stage if stage in EVENT_STAGES else base["event_stage"],
                "actor_name": str(item.get("actor_name") or ""),
                "actor_type": str(item.get("actor_type") or ""),
                "headline_zh": str(item.get("headline_zh") or "")[:500],
                "summary_zh": str(item.get("summary_zh") or base["snippet"])[:1000],
                "quantity_text": str(item.get("quantity_text") or ""),
                "amount_text": str(item.get("amount_text") or ""),
                "ownership_change_text": str(item.get("ownership_change_text") or ""),
                "event_date": str(item.get("event_date") or ""),
                "confidence": confidence,
            }
        )
    return extracted or [_fallback_extract(item) for item in candidates]


def load_pool_entries(market: str) -> list[PoolEntry]:
    market = normalize_market(market)
    if market == "cn":
        return [PoolEntry(market, ticker, item.get("name", "")) for ticker, item in load_cn_stock_profiles().items()]
    if market == "hk":
        return [PoolEntry(market, ticker, item.get("name", "")) for ticker, item in load_hk_stock_profiles().items()]
    profiles = load_company_profiles()
    return [PoolEntry("us", ticker, profiles.get(ticker, {}).get("name", "")) for ticker in load_ticker_file()]


def match_pool(event: dict[str, Any], entries: Iterable[PoolEntry]) -> tuple[str, str, float]:
    market = normalize_market(event.get("market"))
    ticker = normalize_ticker_for_market(str(event.get("ticker") or ""), market)
    company = _norm_text(event.get("company_name"))
    entries = list(entries)
    if ticker:
        exact = [entry for entry in entries if entry.ticker == ticker]
        if len(exact) == 1:
            return exact[0].ticker, "ticker", 1.0
    if company:
        exact_name = [entry for entry in entries if _norm_text(entry.name) == company]
        if len(exact_name) == 1:
            return exact_name[0].ticker, "company_name", 0.95
    return "", "", 0.0


def _event_id(event: dict[str, Any]) -> str:
    identity = _norm_text(event.get("ticker") or event.get("company_name")) or str(event.get("source_url") or "")
    normalized_url = normalize_source_url(str(event.get("normalized_url") or event.get("source_url") or ""))
    payload = "|".join((str(event.get("market") or ""), identity, str(event.get("event_type") or ""), normalized_url))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def deduplicate_events(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one strongest extraction per canonical article/company/event-type combination."""
    selected: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for event in events:
        market = normalize_market(event.get("market"))
        identity = _norm_text(event.get("ticker") or event.get("company_name"))
        normalized_url = normalize_source_url(str(event.get("normalized_url") or event.get("source_url") or ""))
        key = (market, str(event.get("event_type") or ""), identity, normalized_url)
        current = selected.get(key)
        if current is None:
            selected[key] = {**event, "market": market, "normalized_url": normalized_url}
            continue
        candidate_score = (
            float(event.get("confidence") or 0),
            sum(bool(str(event.get(field) or "").strip()) for field in ("amount_text", "quantity_text", "ownership_change_text", "event_date")),
            EVENT_STAGE_PRIORITY.get(str(event.get("event_stage") or ""), -1),
        )
        current_score = (
            float(current.get("confidence") or 0),
            sum(bool(str(current.get(field) or "").strip()) for field in ("amount_text", "quantity_text", "ownership_change_text", "event_date")),
            EVENT_STAGE_PRIORITY.get(str(current.get("event_stage") or ""), -1),
        )
        if candidate_score > current_score:
            selected[key] = {**event, "market": market, "normalized_url": normalized_url}
    return list(selected.values())


def save_events(events: Iterable[dict[str, Any]], db_path: Path = CORPORATE_ACTION_NEWS_DB) -> int:
    ensure_db(db_path)
    rows = list(events)
    affected_event_ids: list[str] = []
    now = _now()
    with db_connection(db_path) as conn:
        for event in rows:
            market = normalize_market(event.get("market"))
            normalized_ticker = normalize_ticker_for_market(str(event.get("ticker") or ""), market) if event.get("ticker") else ""
            identity = _norm_text(normalized_ticker or event.get("company_name")) or _norm_text(event.get("source_url"))
            normalized_url = normalize_source_url(str(event.get("normalized_url") or event.get("source_url") or ""))
            event_id = _event_id({**event, "market": market, "ticker": normalized_ticker, "normalized_url": normalized_url})
            identity_candidates = {value for value in (identity, _norm_text(normalized_ticker), _norm_text(event.get("company_name"))) if value}
            existing_rows = conn.execute(
                """SELECT event_id, ticker, company_name, company_identity FROM corporate_action_news
                WHERE market=? AND event_type=? AND normalized_url=?""",
                (market, str(event.get("event_type")), normalized_url),
            ).fetchall()
            for existing in existing_rows:
                existing_identities = {
                    _norm_text(existing["ticker"]), _norm_text(existing["company_name"]), _norm_text(existing["company_identity"])
                }
                if identity_candidates & existing_identities:
                    event_id = str(existing["event_id"])
                    break
            affected_event_ids.append(event_id)
            conn.execute(
                """
                INSERT INTO corporate_action_news (
                    event_id, market, ticker, company_name, company_identity, event_type, event_stage, actor_name, actor_type,
                    headline, headline_zh, summary_zh, quantity_text, amount_text, ownership_change_text, published_at, event_date,
                    source_url, normalized_url, source_domain, source_quality, confidence, exchange, source_schema, agent_record_id, source_agent, evidence_text,
                    repurchase_shares, repurchase_shares_scope, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    ticker=excluded.ticker, company_name=excluded.company_name, event_stage=excluded.event_stage,
                    actor_name=excluded.actor_name, actor_type=excluded.actor_type, headline=excluded.headline,
                    headline_zh=excluded.headline_zh, summary_zh=excluded.summary_zh,
                    quantity_text=excluded.quantity_text, amount_text=excluded.amount_text,
                    ownership_change_text=excluded.ownership_change_text, published_at=excluded.published_at,
                    event_date=excluded.event_date, source_url=excluded.source_url, normalized_url=excluded.normalized_url,
                    source_domain=excluded.source_domain, source_quality=excluded.source_quality,
                    confidence=excluded.confidence, exchange=excluded.exchange, source_schema=excluded.source_schema,
                    agent_record_id=excluded.agent_record_id,
                    source_agent=excluded.source_agent, evidence_text=excluded.evidence_text,
                    repurchase_shares=excluded.repurchase_shares, repurchase_shares_scope=excluded.repurchase_shares_scope,
                    updated_at=excluded.updated_at
                """,
                (
                    event_id, market, normalized_ticker or None, str(event.get("company_name") or ""), identity,
                    str(event.get("event_type")), str(event.get("event_stage")), str(event.get("actor_name") or ""),
                    str(event.get("actor_type") or ""), str(event.get("headline") or ""), str(event.get("headline_zh") or ""),
                    str(event.get("summary_zh") or ""),
                    str(event.get("quantity_text") or ""), str(event.get("amount_text") or ""), str(event.get("ownership_change_text") or ""),
                    str(event.get("published_at")), str(event.get("event_date") or ""), str(event.get("source_url")),
                    normalized_url,
                    str(event.get("source_domain") or _domain(str(event.get("source_url") or ""))),
                    str(event.get("source_quality") or source_quality(str(event.get("source_url") or ""))),
                    float(event.get("confidence") or 0), str(event.get("exchange") or ""),
                    str(event.get("source_schema") or ""), str(event.get("agent_record_id") or ""), str(event.get("source_agent") or ""),
                    str(event.get("evidence_text") or ""),
                    float(event["repurchase_shares"]) if event.get("repurchase_shares") is not None else None,
                    str(event.get("repurchase_shares_scope") or ""), now, now,
                ),
            )
    rematch_events(event_ids=affected_event_ids, db_path=db_path)
    return len(rows)


def is_buyback_chart_eligible(event: dict[str, Any]) -> bool:
    """A chart column must represent a verified, single-day execution."""
    try:
        shares = float(event.get("repurchase_shares"))
    except (TypeError, ValueError):
        return False
    return (
        event.get("event_type") == "buyback"
        and event.get("event_stage") in {"executed", "completed"}
        and event.get("repurchase_shares_scope") == "daily"
        and shares > 0
        and bool(str(event.get("event_date") or "").strip())
        and bool(str(event.get("ticker") or "").strip())
    )


def _stored_event_ids_for_events(events: Iterable[dict[str, Any]], db_path: Path) -> list[str]:
    """Resolve current IDs after upsert, including legacy company-name event IDs."""
    resolved: list[str] = []
    with db_connection(db_path) as conn:
        for event in events:
            market = normalize_market(event.get("market"))
            ticker = normalize_ticker_for_market(str(event.get("ticker") or ""), market) if event.get("ticker") else ""
            normalized_url = normalize_source_url(str(event.get("normalized_url") or event.get("source_url") or ""))
            candidates = {
                value for value in (_norm_text(ticker), _norm_text(event.get("company_name"))) if value
            }
            rows = conn.execute(
                """SELECT event_id, ticker, company_name, company_identity FROM corporate_action_news
                WHERE market=? AND event_type=? AND normalized_url=?""",
                (market, str(event.get("event_type") or ""), normalized_url),
            ).fetchall()
            for row in rows:
                identities = {_norm_text(row["ticker"]), _norm_text(row["company_name"]), _norm_text(row["company_identity"])}
                if candidates & identities:
                    resolved.append(str(row["event_id"]))
                    break
    return list(dict.fromkeys(resolved))


def _record_chart_fetch(
    event_id: str, status: str, window_start: date, window_end: date, data_source: str = "", error_summary: str = "",
    db_path: Path = CORPORATE_ACTION_NEWS_DB,
) -> None:
    with db_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO corporate_action_chart_fetches
            (event_id, status, data_source, window_start, window_end, attempted_at, error_summary)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
              status=excluded.status, data_source=excluded.data_source, window_start=excluded.window_start,
              window_end=excluded.window_end, attempted_at=excluded.attempted_at, error_summary=excluded.error_summary""",
            (event_id, status, data_source, window_start.isoformat(), window_end.isoformat(), _now(), error_summary[:2000]),
        )


def capture_new_buyback_price_snapshots(
    events: Iterable[dict[str, Any]], as_of: date, db_path: Path = CORPORATE_ACTION_NEWS_DB,
) -> dict[str, int]:
    """Capture a one-time, event-scoped 10-calendar-day price snapshot.

    This intentionally does not update the project's raw daily CSV cache: it
    serves imported corporate actions only and keeps out-of-pool price data
    isolated from ranking inputs.
    """
    ensure_db(db_path)
    window_start = as_of - timedelta(days=BUYBACK_CHART_WINDOW_DAYS - 1)
    event_ids = _stored_event_ids_for_events(events, db_path)
    if not event_ids:
        return {"eligible": 0, "captured": 0, "out_of_window": 0, "unavailable": 0, "skipped": 0}
    placeholders = ", ".join("?" for _ in event_ids)
    with db_connection(db_path) as conn:
        rows = conn.execute(
            f"""SELECT news.*, fetch.event_id AS already_fetched
            FROM corporate_action_news AS news
            LEFT JOIN corporate_action_chart_fetches AS fetch ON fetch.event_id = news.event_id
            WHERE news.event_id IN ({placeholders})""",
            event_ids,
        ).fetchall()
    eligible = [dict(row) for row in rows if is_buyback_chart_eligible(dict(row))]
    targets = [row for row in eligible if not row.get("already_fetched")]
    result = {"eligible": len(eligible), "captured": 0, "out_of_window": 0, "unavailable": 0, "skipped": len(eligible) - len(targets)}
    if not targets:
        return result

    try:
        from scripts.ths_ifind_daily import fetch_ifind_history, ifind_session, load_us_exchange_suffixes

        us_exchange_suffixes = load_us_exchange_suffixes()
        with ifind_session():
            for event in targets:
                event_id = str(event["event_id"])
                try:
                    fetched = fetch_ifind_history(
                        str(event["ticker"]), str(event["market"]), window_start, as_of, us_exchange_suffixes,
                    )
                    snapshots = []
                    for item in fetched.frame.itertuples(index=False):
                        try:
                            close = float(getattr(item, "close", None))
                        except (TypeError, ValueError):
                            continue
                        price_date = str(getattr(item, "date", ""))
                        if price_date and math.isfinite(close):
                            snapshots.append((event_id, price_date, close, "ifind", _now()))
                    if not snapshots:
                        raise ValueError("iFinD returned no daily closes")
                    event_date = str(event["event_date"])
                    chart_status = "available" if event_date in {row[1] for row in snapshots} else "out_of_window"
                    with db_connection(db_path) as conn:
                        conn.executemany(
                            """INSERT INTO corporate_action_price_snapshots (event_id, price_date, close, data_source, fetched_at)
                            VALUES (?, ?, ?, ?, ?) ON CONFLICT(event_id, price_date) DO UPDATE SET
                            close=excluded.close, data_source=excluded.data_source, fetched_at=excluded.fetched_at""",
                            snapshots,
                        )
                    _record_chart_fetch(event_id, chart_status, window_start, as_of, "ifind", db_path=db_path)
                    result["captured" if chart_status == "available" else "out_of_window"] += 1
                except Exception as exc:  # noqa: BLE001 - a single vendor failure must not abort an OSS batch.
                    _record_chart_fetch(event_id, "unavailable", window_start, as_of, "ifind", str(exc), db_path)
                    result["unavailable"] += 1
    except Exception as exc:  # noqa: BLE001 - login/SDK failures apply to every remaining event.
        for event in targets:
            _record_chart_fetch(str(event["event_id"]), "unavailable", window_start, as_of, "ifind", str(exc), db_path)
            result["unavailable"] += 1
    return result


def _buyback_chart_status(event: dict[str, Any], fetch: dict[str, Any] | None) -> str:
    if not is_buyback_chart_eligible(event):
        return "not_eligible"
    return str(fetch.get("status") or "unavailable") if fetch else "unavailable"


def get_buyback_chart(event_id: str, db_path: Path = CORPORATE_ACTION_NEWS_DB) -> dict[str, Any] | None:
    ensure_db(db_path)
    with db_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM corporate_action_news WHERE event_id = ?", (event_id,)).fetchone()
        if not row:
            return None
        event = dict(row)
        fetch_row = conn.execute("SELECT * FROM corporate_action_chart_fetches WHERE event_id = ?", (event_id,)).fetchone()
        fetch = dict(fetch_row) if fetch_row else None
        snapshots = conn.execute(
            "SELECT price_date, close FROM corporate_action_price_snapshots WHERE event_id = ? ORDER BY price_date", (event_id,)
        ).fetchall()
    status = _buyback_chart_status(event, fetch)
    messages = {
        "not_eligible": "该事件未提供可核验的单日实际回购股数、回购日期或证券代码。",
        "out_of_window": "回购日不在入库时保存的 10 个自然日行情窗口内。",
        "unavailable": str(fetch.get("error_summary") or "该事件的行情快照尚未取得。") if fetch else "该事件的行情快照尚未取得。",
    }
    return {
        "event_id": event_id,
        "market": event["market"],
        "ticker": event["ticker"],
        "company_name": event["company_name"],
        "event_date": event["event_date"],
        "repurchase_shares": event["repurchase_shares"],
        "repurchase_shares_scope": event["repurchase_shares_scope"],
        "status": status,
        "message": messages.get(status, ""),
        "window_start": str(fetch.get("window_start") or "") if fetch else "",
        "window_end": str(fetch.get("window_end") or "") if fetch else "",
        "data_source": str(fetch.get("data_source") or "") if fetch else "",
        "data": [dict(item) for item in snapshots],
    }


def archive_candidates(
    candidates: list[dict[str, Any]], market: str, db_path: Path = CORPORATE_ACTION_NEWS_DB, write: bool = True,
    diagnostics: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Structure externally supplied candidates and archive only valid company events."""
    market = normalize_market(market)
    events = classify_candidates(candidates, market, diagnostics=diagnostics)
    events = [
        event
        for event in events
        if float(event.get("confidence") or 0) >= MIN_CONFIDENCE
        and (str(event.get("ticker") or "").strip() or str(event.get("company_name") or "").strip())
    ]
    events = deduplicate_events(events)
    if write and events:
        save_events(events, db_path)
    return events


def imported_object_exists(
    bucket: str, object_key: str, etag: str, db_path: Path = CORPORATE_ACTION_NEWS_DB, include_partial: bool = True,
    include_rejected_oversize: bool = False,
) -> bool:
    ensure_db(db_path)
    with db_connection(db_path) as conn:
        statuses = ["ok"]
        if include_partial:
            statuses.append("partial")
        if include_rejected_oversize:
            statuses.append("rejected_oversize")
        placeholders = ", ".join("?" for _ in statuses)
        row = conn.execute(
            f"SELECT 1 FROM corporate_action_imported_objects WHERE bucket=? AND object_key=? AND etag=? AND status IN ({placeholders})",
            (bucket, object_key, etag, *statuses),
        ).fetchone()
    return row is not None


def record_imported_object(
    bucket: str,
    object_key: str,
    etag: str,
    status: str,
    total_rows: int,
    accepted_rows: int,
    rejected_rows: int,
    stored_event_count: int = 0,
    deduplicated_v2_rows: int = 0,
    source_agent: str = "",
    errors: list[str] | None = None,
    db_path: Path = CORPORATE_ACTION_NEWS_DB,
) -> None:
    ensure_db(db_path)
    with db_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO corporate_action_imported_objects
            (bucket, object_key, etag, source_agent, imported_at, status, total_rows, accepted_rows, rejected_rows,
             stored_event_count, deduplicated_v2_rows, error_summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bucket, object_key, etag) DO UPDATE SET
              source_agent=excluded.source_agent, imported_at=excluded.imported_at, status=excluded.status,
              total_rows=excluded.total_rows, accepted_rows=excluded.accepted_rows,
              rejected_rows=excluded.rejected_rows, stored_event_count=excluded.stored_event_count,
              deduplicated_v2_rows=excluded.deduplicated_v2_rows, error_summary=excluded.error_summary""",
            (
                bucket, object_key, etag, source_agent, _now(), status, total_rows, accepted_rows, rejected_rows,
                stored_event_count, deduplicated_v2_rows, " | ".join(errors or [])[:4000],
            ),
        )


def quarantine_import_row(
    bucket: str,
    object_key: str,
    etag: str,
    line_number: int,
    raw_payload: str,
    error_code: str,
    error_summary: str,
    market: str = "",
    schema_version: str = "",
    source_agent: str = "",
    db_path: Path = CORPORATE_ACTION_NEWS_DB,
) -> None:
    """Persist a rejected external row for review without exposing it as a news event."""
    ensure_db(db_path)
    now = _now()
    with db_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO corporate_action_import_rejections
            (bucket, object_key, etag, line_number, market, schema_version, source_agent, raw_payload,
             error_code, error_summary, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            ON CONFLICT(bucket, object_key, etag, line_number) DO UPDATE SET
              market=excluded.market, schema_version=excluded.schema_version, source_agent=excluded.source_agent,
              raw_payload=excluded.raw_payload, error_code=excluded.error_code, error_summary=excluded.error_summary,
              status='pending', updated_at=excluded.updated_at""",
            (
                bucket, object_key, etag, line_number, normalize_market(market) if market else "",
                schema_version[:100], source_agent[:200], raw_payload[:20000], error_code[:100], error_summary[:2000], now, now,
            ),
        )


def rematch_events(
    markets: Iterable[str] = MARKETS, event_ids: Iterable[str] | None = None, db_path: Path = CORPORATE_ACTION_NEWS_DB,
) -> int:
    ensure_db(db_path)
    normalized_markets = [normalize_market(market) for market in markets]
    target_ids = list(dict.fromkeys(str(event_id) for event_id in event_ids or [] if event_id))
    total = 0
    with db_connection(db_path) as conn:
        for market in normalized_markets:
            entries = load_pool_entries(market)
            if not target_ids:
                rows = conn.execute("SELECT event_id, market, ticker, company_name FROM corporate_action_news WHERE market = ?", (market,)).fetchall()
            else:
                rows = []
                for start in range(0, len(target_ids), 900):
                    chunk = target_ids[start:start + 900]
                    placeholders = ", ".join("?" for _ in chunk)
                    rows.extend(conn.execute(
                        f"SELECT event_id, market, ticker, company_name FROM corporate_action_news WHERE market = ? AND event_id IN ({placeholders})",
                        (market, *chunk),
                    ).fetchall())
            for row in rows:
                ticker, method, confidence = match_pool(dict(row), entries)
                in_pool = bool(ticker)
                conn.execute("DELETE FROM corporate_action_pool_matches WHERE event_id = ?", (row["event_id"],))
                conn.execute(
                    """UPDATE corporate_action_news SET
                    ticker=CASE WHEN COALESCE(ticker, '') = '' AND ? <> '' THEN ? ELSE ticker END,
                    in_stock_pool=?, attention_level=?, pool_match_method=?, pool_match_confidence=?, updated_at=?
                    WHERE event_id=?""",
                    (ticker, ticker, int(in_pool), "high" if in_pool else "normal", method, confidence, _now(), row["event_id"]),
                )
                if in_pool:
                    conn.execute(
                        """INSERT INTO corporate_action_pool_matches (event_id, market, ticker, match_method, match_confidence, matched_at)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                        (row["event_id"], market, ticker, method, confidence, _now()),
                    )
                total += 1
    return total


def record_run(
    market: str, as_of: date, start: date, status: str, task_count: int, candidate_count: int, stored_count: int,
    errors: list[str] | None = None, db_path: Path = CORPORATE_ACTION_NEWS_DB,
) -> str:
    ensure_db(db_path)
    completed = _now()
    run_id = hashlib.sha256(f"{market}|{as_of}|{completed}".encode()).hexdigest()[:24]
    with db_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO corporate_action_search_runs
            (run_id, market, as_of_date, window_start, window_end, started_at, completed_at, status, task_count, candidate_count, stored_count, error_summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, normalize_market(market), as_of.isoformat(), start.isoformat(), as_of.isoformat(), completed, completed, status,
             task_count, candidate_count, stored_count, " | ".join(errors or [])[:4000]),
        )
    return run_id


def collect_market(market: str, as_of: date, lookback_days: int = 30, max_results: int = 10, dry_run: bool = False) -> dict[str, Any]:
    market = normalize_market(market)
    start = as_of - timedelta(days=lookback_days)
    tasks = build_collection_tasks(market)
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_urls: set[str] = set()
    for task in tasks:
        provider = task["provider"]
        try:
            if provider == "tavily":
                results = tavily_search(task["query"], start, as_of, max_results=max_results)
                candidate_factory = lambda item: _candidate_from_result(item, task, resolve_date=True)
            else:
                results = []
                for page in range(1, 4):
                    page_results = laohu_search(task["query"], page)
                    if not page_results:
                        break
                    results.extend(page_results)
                    if len(results) >= MAX_LAOHU_RESULTS_PER_EVENT:
                        break
                results = results[:MAX_LAOHU_RESULTS_PER_EVENT]
                candidate_factory = lambda item: _candidate_from_laohu_result(item, task)
        except Exception as exc:
            errors.append(f"{provider}:{task['event_type']}: {exc}")
            continue
        for result in results:
            candidate = candidate_factory(result)
            if not candidate:
                continue
            normalized_url = normalize_source_url(candidate["source_url"])
            if normalized_url in seen_urls:
                continue
            published = _parse_date(candidate["published_at"])
            if not published or not start <= published <= as_of:
                continue
            candidate["normalized_url"] = normalized_url
            seen_urls.add(normalized_url)
            candidates.append(candidate)
    events = classify_candidates(candidates, market)
    events = [
        event for event in events
        if float(event.get("confidence") or 0) >= MIN_CONFIDENCE
        and (str(event.get("ticker") or "").strip() or str(event.get("company_name") or "").strip())
    ]
    events = deduplicate_events(events)
    if not dry_run:
        stored = save_events(events)
        record_run(market, as_of, start, "partial" if errors else "ok", len(tasks), len(candidates), stored, errors)
    else:
        stored = 0
    return {
        "market": market, "as_of_date": as_of.isoformat(), "window_start": start.isoformat(), "task_count": len(tasks),
        "candidate_count": len(candidates), "event_count": len(events), "stored_count": stored, "errors": errors, "events": events,
    }


def _latest_run(market: str, db_path: Path) -> dict[str, Any] | None:
    ensure_db(db_path)
    with db_connection(db_path) as conn:
        row = conn.execute(
            """SELECT * FROM corporate_action_search_runs WHERE market = ? AND status IN ('ok', 'partial')
            ORDER BY as_of_date DESC, completed_at DESC LIMIT 1""", (normalize_market(market),)
        ).fetchone()
    return dict(row) if row else None


def _latest_event_snapshot(market: str, db_path: Path) -> dict[str, str]:
    """Return the newest stored event dates for a market.

    OSS v2 batches are a second, controlled ingestion path.  They do not run
    the web collector, so relying only on ``corporate_action_search_runs``
    would make newly imported rows invisible until a later web collection.
    """
    ensure_db(db_path)
    with db_connection(db_path) as conn:
        row = conn.execute(
            """SELECT MAX(published_at) AS published_at, MAX(updated_at) AS updated_at
            FROM corporate_action_news WHERE market = ?""",
            (normalize_market(market),),
        ).fetchone()
    return {
        "published_at": str(row["published_at"] or "") if row else "",
        "updated_at": str(row["updated_at"] or "") if row else "",
    }


def query_news(
    market: str, as_of_date: date | None = None, lookback_days: int = 30, event_type: str = "all",
    attention: str = "all", in_stock_pool: bool | None = None, ticker: str | None = None, limit: int = 200,
    db_path: Path = CORPORATE_ACTION_NEWS_DB,
) -> dict[str, Any]:
    ensure_db(db_path)
    market = normalize_market(market)
    latest = _latest_run(market, db_path)
    latest_event = _latest_event_snapshot(market, db_path)
    run_as_of = _parse_date(latest.get("as_of_date")) if latest else None
    event_as_of = _parse_date(latest_event["published_at"])
    # Explicit historical queries retain their requested boundary.  For the
    # normal UI path use whichever data source is newest: a collector run or
    # an OSS-imported event.  This makes a V2 upload visible immediately.
    effective_as_of = as_of_date or max((value for value in (run_as_of, event_as_of) if value), default=None)
    if effective_as_of is None:
        return {"market": market, "as_of_date": "", "window_start": "", "lookback_days": lookback_days, "status": "unavailable", "stale": True,
                "last_successful_refresh_at": "", "refresh_through_date": "", "count": 0, "in_stock_pool_count": 0, "outside_stock_pool_count": 0, "data": []}
    start = effective_as_of - timedelta(days=lookback_days)
    filters = ["market = ?", "published_at >= ?", "published_at <= ?"]
    params: list[Any] = [market, start.isoformat(), effective_as_of.isoformat()]
    if event_type != "all":
        filters.append("event_type = ?")
        params.append(event_type)
    if attention != "all":
        filters.append("attention_level = ?")
        params.append(attention)
    if in_stock_pool is not None:
        filters.append("in_stock_pool = ?")
        params.append(int(in_stock_pool))
    if ticker:
        filters.append("ticker = ?")
        params.append(normalize_ticker_for_market(ticker, market))
    where = " AND ".join(filters)
    with db_connection(db_path) as conn:
        counts = conn.execute(
            f"SELECT COUNT(*) AS count, COALESCE(SUM(in_stock_pool), 0) AS pool_count FROM corporate_action_news WHERE {where}", params
        ).fetchone()
        rows = conn.execute(
            f"""SELECT * FROM corporate_action_news WHERE {where}
            ORDER BY in_stock_pool DESC, published_at DESC,
              CASE source_quality WHEN 'primary' THEN 0 WHEN 'mainstream' THEN 1 ELSE 2 END, confidence DESC
            LIMIT ?""", params + [limit]
        ).fetchall()
        event_ids = [str(row["event_id"]) for row in rows]
        fetches: dict[str, dict[str, Any]] = {}
        if event_ids:
            placeholders = ", ".join("?" for _ in event_ids)
            fetches = {
                str(row["event_id"]): dict(row)
                for row in conn.execute(
                    f"SELECT * FROM corporate_action_chart_fetches WHERE event_id IN ({placeholders})", event_ids
                ).fetchall()
            }
    refresh_through_date = max((value for value in (run_as_of, event_as_of) if value), default=None)
    refresh_through = refresh_through_date.isoformat() if refresh_through_date else ""
    stale = not refresh_through or refresh_through < effective_as_of.isoformat()
    latest_refresh_at = str(latest.get("completed_at", "")) if latest else ""
    if event_as_of and (not run_as_of or event_as_of >= run_as_of):
        latest_refresh_at = latest_event["updated_at"]
    count = int(counts["count"] if counts else 0)
    pool_count = int(counts["pool_count"] if counts else 0)
    return {
        "market": market, "as_of_date": effective_as_of.isoformat(), "window_start": start.isoformat(), "lookback_days": lookback_days,
        "status": "stale" if stale else "ok" if count else "empty", "stale": stale,
        "last_successful_refresh_at": latest_refresh_at, "refresh_through_date": refresh_through,
        "count": count, "in_stock_pool_count": pool_count, "outside_stock_pool_count": count - pool_count,
        "data": [
            {
                **dict(row),
                "buyback_chart_status": _buyback_chart_status(dict(row), fetches.get(str(row["event_id"]))),
                "buyback_chart_available": _buyback_chart_status(dict(row), fetches.get(str(row["event_id"]))) == "available",
            }
            for row in rows
        ],
    }


def service_status(db_path: Path = CORPORATE_ACTION_NEWS_DB) -> dict[str, Any]:
    ensure_db(db_path)
    items = []
    for market in MARKETS:
        latest = _latest_run(market, db_path)
        with db_connection(db_path) as conn:
            counts = conn.execute(
                "SELECT COUNT(*) AS count, COALESCE(SUM(in_stock_pool), 0) AS pool_count FROM corporate_action_news WHERE market = ?", (market,)
            ).fetchone()
            quarantined = conn.execute(
                "SELECT COUNT(*) AS count FROM corporate_action_import_rejections WHERE market = ? AND status = 'pending'", (market,)
            ).fetchone()
            latest_rejection = conn.execute(
                """SELECT error_summary FROM corporate_action_import_rejections
                WHERE market = ? AND status = 'pending' ORDER BY updated_at DESC LIMIT 1""", (market,)
            ).fetchone()
        items.append({
            "market": market, "last_successful_as_of_date": str(latest.get("as_of_date", "")) if latest else "",
            "last_successful_refresh_at": str(latest.get("completed_at", "")) if latest else "",
            "last_status": str(latest.get("status", "unavailable")) if latest else "unavailable",
            "last_error": str(latest.get("error_summary", "")) if latest else "",
            "event_count": int(counts["count"]), "in_stock_pool_count": int(counts["pool_count"]),
            "quarantined_count": int(quarantined["count"]),
            "last_quarantine_error": str(latest_rejection["error_summary"]) if latest_rejection else "",
        })
    return {"data": items}
