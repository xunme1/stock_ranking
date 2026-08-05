from __future__ import annotations

"""Validate Codex research and render a safe, market-reaction-focused earnings report."""

import argparse
import html
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
for directory in (BACKEND_DIR, ROOT_DIR / "scripts"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from app.services.data_loader import load_daily_data  # noqa: E402
from earnings_market_metrics import post_earnings_metrics, pre_earnings_metrics  # noqa: E402


SENTIMENTS = {"positive", "neutral", "negative", "mixed"}
SOURCE_KINDS = {"official", "media"}
STATUSES = {"pre_earnings", "post_earnings", "unconfirmed"}
MEDIA_PHASES = {"pre_earnings", "post_earnings", "context"}
RELEASE_TIMES = {"before_market", "during_market", "after_market", "unknown"}
ALIGNMENTS = {"aligned", "divergent", "not_yet_verifiable", "not_applicable"}


class ReportValidationError(ValueError):
    pass


def parse_date(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReportValidationError(f"{field_name} must be an ISO date string")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ReportValidationError(f"{field_name} must be YYYY-MM-DD") from exc


def text(value: object, field_name: str, *, limit: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReportValidationError(f"{field_name} must be non-empty text")
    normalized = value.strip()
    if len(normalized) > limit:
        raise ReportValidationError(f"{field_name} exceeds {limit} characters")
    return normalized


def safe_url(value: object, field_name: str) -> str:
    url = text(value, field_name, limit=2048)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ReportValidationError(f"{field_name} must be an absolute HTTP(S) URL")
    return url


def validate_sources(value: object, ticker: str, status: str, actual_release_date: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ReportValidationError(f"{ticker}.sources must contain at least one source")
    output: list[dict[str, str]] = []
    for index, source in enumerate(value):
        if not isinstance(source, dict):
            raise ReportValidationError(f"{ticker}.sources[{index}] must be an object")
        kind = source.get("kind")
        if kind not in SOURCE_KINDS:
            raise ReportValidationError(f"{ticker}.sources[{index}].kind must be official or media")
        published_date = parse_date(source.get("published_date"), f"{ticker}.sources[{index}].published_date")
        phase = source.get("phase")
        if kind == "media" and phase not in MEDIA_PHASES:
            raise ReportValidationError(f"{ticker}.sources[{index}].phase is invalid")
        if kind == "official" and phase != "context":
            raise ReportValidationError(f"{ticker}.official source phase must be context")
        if kind == "media" and status == "pre_earnings" and phase != "pre_earnings":
            raise ReportValidationError(f"{ticker} pre-earnings media must be labeled pre_earnings")
        if kind == "media" and status == "post_earnings":
            if phase != "post_earnings" or published_date < actual_release_date:
                raise ReportValidationError(f"{ticker} post-earnings media must follow the confirmed release")
        if kind == "media" and status == "unconfirmed" and phase != "context":
            raise ReportValidationError(f"{ticker} unconfirmed media must be labeled context")
        output.append(
            {
                "kind": str(kind),
                "phase": str(phase),
                "published_date": published_date,
                "title": text(source.get("title"), f"{ticker}.sources[{index}].title", limit=500),
                "url": safe_url(source.get("url"), f"{ticker}.sources[{index}].url"),
                "publisher": text(source.get("publisher"), f"{ticker}.sources[{index}].publisher", limit=200),
                "excerpt": text(source.get("excerpt"), f"{ticker}.sources[{index}].excerpt", limit=1000),
            }
        )
    return output


def validate_context(value: object) -> tuple[str, dict[tuple[str, str], dict[str, str]]]:
    if not isinstance(value, dict):
        raise ReportValidationError("context must be a locally generated earnings candidate object")
    report_date = parse_date(value.get("report_date"), "context.report_date")
    candidates = value.get("candidates")
    if not isinstance(candidates, list):
        raise ReportValidationError("context.candidates must be a list")
    candidate_map: dict[tuple[str, str], dict[str, str]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ReportValidationError("context.candidates contains an invalid item")
        ticker = text(candidate.get("ticker"), "context candidate ticker", limit=20).upper()
        calendar_date = parse_date(candidate.get("calendar_date"), f"context.{ticker}.calendar_date")
        candidate_map[(ticker, calendar_date)] = {
            "ticker": ticker,
            "company_name": str(candidate.get("company_name") or "").strip(),
            "calendar_date": calendar_date,
            "announcement_time": str(candidate.get("announcement_time") or "").strip(),
        }
    return report_date, candidate_map


def inferred_status(report_date: str, calendar_date: str, reported: bool) -> str:
    if reported:
        return "post_earnings"
    return "pre_earnings" if calendar_date >= report_date else "unconfirmed"


def market_metrics(ticker: str, status: str, calendar_date: str, actual_release_date: str, release_time: str) -> dict[str, Any]:
    try:
        stock = load_daily_data(ticker)
        qqq = load_daily_data("QQQ")
    except FileNotFoundError:
        return {"kind": "post_earnings" if status == "post_earnings" else "pre_earnings", "status": "missing", "reason": "缺少股票或 QQQ 本地日线数据。"}
    if status == "post_earnings":
        return post_earnings_metrics(stock, qqq, date.fromisoformat(actual_release_date), release_time)
    return pre_earnings_metrics(stock, qqq, date.fromisoformat(calendar_date))


def validate_report(payload: object, context: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ReportValidationError("report input must be a JSON object")
    context_date, candidate_map = validate_context(context)
    report_date = parse_date(payload.get("report_date"), "report_date")
    if report_date != context_date:
        raise ReportValidationError("report_date must equal context.report_date")
    overall_sentiment = payload.get("overall_sentiment")
    if overall_sentiment not in SENTIMENTS:
        raise ReportValidationError("overall_sentiment is invalid")
    raw_companies = payload.get("companies")
    if not isinstance(raw_companies, list):
        raise ReportValidationError("companies must be a list")
    companies: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_companies:
        if not isinstance(item, dict):
            raise ReportValidationError("companies contains an invalid item")
        ticker = text(item.get("ticker"), "company.ticker", limit=20).upper()
        calendar_date = parse_date(item.get("calendar_date"), f"{ticker}.calendar_date")
        key = (ticker, calendar_date)
        if key not in candidate_map or key in seen:
            raise ReportValidationError(f"{ticker} is invalid or duplicated in the supplied context")
        seen.add(key)
        reported = item.get("reported")
        if not isinstance(reported, bool):
            raise ReportValidationError(f"{ticker}.reported must be boolean")
        actual_release_date = parse_date(item["actual_release_date"], f"{ticker}.actual_release_date") if item.get("actual_release_date") else ""
        if reported and not actual_release_date:
            raise ReportValidationError(f"{ticker} must include actual_release_date when reported")
        status = item.get("report_status")
        expected_status = inferred_status(report_date, calendar_date, reported)
        if status != expected_status or status not in STATUSES:
            raise ReportValidationError(f"{ticker}.report_status must be {expected_status}")
        release_time = item.get("release_time", "unknown")
        if release_time not in RELEASE_TIMES:
            raise ReportValidationError(f"{ticker}.release_time is invalid")
        sentiment = item.get("sentiment")
        if sentiment not in SENTIMENTS:
            raise ReportValidationError(f"{ticker}.sentiment is invalid")
        evidence_level = item.get("evidence_level")
        if evidence_level not in {"confirmed", "limited"}:
            raise ReportValidationError(f"{ticker}.evidence_level must be confirmed or limited")
        sources = validate_sources(item.get("sources"), ticker, status, actual_release_date)
        summary = text(item.get("summary"), f"{ticker}.summary")
        media_view = text(item.get("media_view"), f"{ticker}.media_view")
        alignment = item.get("media_market_alignment")
        if alignment not in ALIGNMENTS:
            raise ReportValidationError(f"{ticker}.media_market_alignment is invalid")
        official_url = str(item.get("official_confirmation_url") or "")
        if status == "post_earnings":
            if evidence_level != "confirmed" or not official_url or official_url not in {source["url"] for source in sources if source["kind"] == "official"}:
                raise ReportValidationError(f"{ticker} post_earnings requires an official confirmation URL")
            if not [source for source in sources if source["kind"] == "media"] and not media_view.startswith("有限证据"):
                raise ReportValidationError(f"{ticker} needs a 有限证据 media fallback when no qualified post-earnings article exists")
        else:
            if evidence_level != "limited" or not (summary.startswith("有限证据") and media_view.startswith("有限证据")):
                raise ReportValidationError(f"{ticker} must use the 有限证据 fallback until release is confirmed")
            if alignment != "not_applicable":
                raise ReportValidationError(f"{ticker} may not claim post-earnings alignment before confirmation")
        points = item.get("key_points")
        if not isinstance(points, list) or not points:
            raise ReportValidationError(f"{ticker}.key_points must be a non-empty list")
        metrics = market_metrics(ticker, status, calendar_date, actual_release_date, release_time)
        if status == "post_earnings" and metrics.get("status") != "available" and alignment != "not_yet_verifiable":
            raise ReportValidationError(f"{ticker} must wait for price verification when no post-earnings session exists")
        companies.append(
            {
                "ticker": ticker,
                "company_name": candidate_map[key]["company_name"],
                "calendar_date": calendar_date,
                "announcement_time": candidate_map[key]["announcement_time"],
                "report_status": status,
                "reported": reported,
                "actual_release_date": actual_release_date,
                "release_time": release_time,
                "official_confirmation_url": official_url,
                "sentiment": sentiment,
                "evidence_level": evidence_level,
                "summary": summary,
                "media_view": media_view,
                "media_market_alignment": alignment,
                "key_points": [text(point, f"{ticker}.key_points", limit=800) for point in points],
                "sources": sources,
                "market_metrics": metrics,
            }
        )
    if seen != set(candidate_map):
        missing = sorted(ticker for ticker, _ in set(candidate_map) - seen)
        raise ReportValidationError(f"report must include every context candidate; missing: {', '.join(missing)}")
    risk_notes = payload.get("risk_notes", [])
    if not isinstance(risk_notes, list):
        raise ReportValidationError("risk_notes must be a list")
    return {
        "report_date": report_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall_sentiment": overall_sentiment,
        "summary": text(payload.get("summary"), "summary"),
        "companies": companies,
        "risk_notes": [text(note, "risk_notes", limit=800) for note in risk_notes],
    }


def fmt_pct(value: object) -> str:
    return "--" if value is None else f"{float(value):+.2f}%"


def status_label(status: str) -> str:
    return {"pre_earnings": "财报前：市场预期", "post_earnings": "财报后：实际反应", "unconfirmed": "待官方确认"}[status]


def metrics_html(metrics: dict[str, Any]) -> str:
    if metrics.get("status") != "available":
        return f"<p class=\"metric-note\">{html.escape(str(metrics.get('reason') or '行情数据暂不可用。'))}</p>"
    if metrics["kind"] == "post_earnings":
        return "<div class=\"metric-grid\">" + "".join(
            f"<div><small>{label}</small><b>{value}</b></div>"
            for label, value in [
                ("首个完整交易日", html.escape(metrics["session_date"])),
                ("个股涨跌", fmt_pct(metrics.get("stock_return_pct"))),
                ("相对 QQQ", fmt_pct(metrics.get("relative_return_pct"))),
                ("成交量 / 20日均量", "--" if metrics.get("volume_vs_20d") is None else f"{metrics['volume_vs_20d']:.2f}x"),
            ]
        ) + "</div>"
    return "<div class=\"metric-grid\">" + "".join(
        f"<div><small>{label}</small><b>{value}</b></div>"
        for label, value in [
            ("财报前最后交易日", html.escape(metrics["session_date"])),
            ("财报前1日相对 QQQ", fmt_pct(metrics.get("one_day_relative_pct"))),
            ("财报前3日相对 QQQ", fmt_pct(metrics.get("three_day_relative_pct"))),
        ]
    ) + "</div>"


def render_html(report: dict[str, Any]) -> str:
    counts = {status: sum(company["report_status"] == status for company in report["companies"]) for status in STATUSES}
    verified = sum(company["market_metrics"].get("status") == "available" for company in report["companies"] if company["report_status"] == "post_earnings")
    cards: list[str] = []
    for company in report["companies"]:
        status = company["report_status"]
        points = "".join(f"<li>{html.escape(point)}</li>" for point in company["key_points"])
        sources = "".join(
            f"<li><span class=\"source-kind\">{html.escape(source['kind'])} · {html.escape(source['phase'])}</span> "
            f"<time>{html.escape(source['published_date'])}</time> <a href=\"{html.escape(source['url'], quote=True)}\" target=\"_blank\" rel=\"noreferrer\">{html.escape(source['title'])}</a>"
            f"<small> · {html.escape(source['publisher'])}</small><p>{html.escape(source['excerpt'])}</p></li>"
            for source in company["sources"]
        )
        official = f"<p><b>官方确认：</b><a href=\"{html.escape(company['official_confirmation_url'], quote=True)}\" target=\"_blank\" rel=\"noreferrer\">查看官方披露</a></p>" if company["official_confirmation_url"] else ""
        narrative_title = "媒体对实际反应的解释" if status == "post_earnings" else "媒体预期 / 有限证据"
        cards.append(
            f"<article class=\"card {html.escape(status)}\"><div class=\"card-head\"><div><h2>{html.escape(company['ticker'])} <small>{html.escape(company['company_name'])}</small></h2>"
            f"<p>日历日期：{html.escape(company['calendar_date'])} · {html.escape(status_label(status))}</p></div><span class=\"tag {html.escape(company['sentiment'])}\">{html.escape(company['sentiment'])}</span></div>"
            f"<p class=\"company-summary\">{html.escape(company['summary'])}</p>{official}<h3>行情验证</h3>{metrics_html(company['market_metrics'])}"
            f"<p><b>{narrative_title}：</b>{html.escape(company['media_view'])}</p><p class=\"alignment\"><b>媒体叙事与行情：</b>{html.escape(company['media_market_alignment'])}</p>"
            f"<h3>关注要点</h3><ul>{points}</ul><h3>来源时间线</h3><ul class=\"sources\">{sources}</ul></article>"
        )
    risks = "".join(f"<li>{html.escape(note)}</li>" for note in report["risk_notes"])
    return f"""<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>美股财报市场反应日报 {html.escape(report['report_date'])}</title><style>body{{margin:0;background:#f3f6fb;color:#172033;font:15px/1.65 -apple-system,BlinkMacSystemFont,\"Segoe UI\",\"Microsoft YaHei\",sans-serif}}main{{max-width:1120px;margin:auto;padding:32px 20px 56px}}header,.card{{background:#fff;border:1px solid #d9e2ef;border-radius:14px;box-shadow:0 4px 18px #19304a0c}}header{{padding:26px;margin-bottom:18px}}h1,h2,h3,p{{margin-top:0}}h1{{margin-bottom:6px}}.meta,.card-head p,small,time{{color:#607086}}.summary{{font-size:17px}}.summary-grid,.metric-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}}.summary-grid div,.metric-grid div{{background:#f6f8fc;border-radius:9px;padding:9px 11px}}.summary-grid b,.metric-grid b{{display:block;font-size:17px}}.grid{{display:grid;gap:14px}}.card{{padding:20px}}.card-head{{display:flex;justify-content:space-between;gap:12px}}.card h2{{margin-bottom:2px}}.tag{{height:fit-content;border-radius:999px;padding:4px 10px;font-weight:800;font-size:12px;background:#edf2f7}}.tag.positive{{background:#dcfce7;color:#167343}}.tag.negative{{background:#fee2e2;color:#b42318}}.tag.mixed{{background:#fef3c7;color:#925d00}}.pre_earnings{{border-left:4px solid #4f83cc}}.post_earnings{{border-left:4px solid #19a96b}}.unconfirmed{{border-left:4px solid #e5a33d}}.sources a{{color:#1f6feb}}.sources p{{margin:3px 0 10px;color:#4b5a6d}}.source-kind{{font-size:11px;font-weight:800;text-transform:uppercase;color:#607086}}.metric-note{{padding:9px 11px;background:#fff7e6;border-radius:8px;color:#805b10}}.alignment{{background:#f6f8fc;padding:9px 11px;border-radius:8px}}</style></head><body><main><header><p class=\"meta\">Codex 联网研究 · 官方确认优先 · 媒体与行情分开验证 · 非投资建议</p><h1>美股财报市场反应日报 · {html.escape(report['report_date'])}</h1><p class=\"summary\">{html.escape(report['summary'])}</p><section class=\"summary-grid\"><div><small>近三日候选</small><b>{len(report['companies'])}</b></div><div><small>已确认发布</small><b>{counts['post_earnings']}</b></div><div><small>财报前预期</small><b>{counts['pre_earnings']}</b></div><div><small>待官方确认</small><b>{counts['unconfirmed']}</b></div><div><small>财报后行情已验证</small><b>{verified}</b></div></section><p class=\"meta\">整体风向：{html.escape(report['overall_sentiment'])} · 生成时间：{html.escape(report['generated_at'])}</p></header><section class=\"grid\">{''.join(cards)}</section>{('<section class=\"card\"><h2>风险提示</h2><ul>' + risks + '</ul></section>') if risks else ''}</main></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and render a market-reaction-focused earnings report.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    report = validate_report(json.loads(Path(args.input).read_text(encoding="utf-8")), json.loads(Path(args.context).read_text(encoding="utf-8")))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"earnings_sentiment_{report['report_date']}"
    (output_dir / f"{stem}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / f"{stem}.html").write_text(render_html(report), encoding="utf-8")
    print(f"Rendered: {output_dir / f'{stem}.html'}")


if __name__ == "__main__":
    main()
