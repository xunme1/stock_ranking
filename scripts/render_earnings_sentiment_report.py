from __future__ import annotations

"""Validate a Codex-researched earnings report and render a safe static HTML archive."""

import argparse
import html
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SENTIMENTS = {"positive", "neutral", "negative", "mixed"}
SOURCE_KINDS = {"official", "media"}


class ReportValidationError(ValueError):
    pass


def parse_date(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReportValidationError(f"{field_name} must be an ISO date string")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ReportValidationError(f"{field_name} must be YYYY-MM-DD") from exc


def text(value: object, field_name: str, *, required: bool = True, limit: int = 4000) -> str:
    if value is None and not required:
        return ""
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


def validate_sources(value: object, ticker: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ReportValidationError(f"{ticker}.sources must contain at least one source")
    output: list[dict[str, str]] = []
    for index, source in enumerate(value):
        if not isinstance(source, dict):
            raise ReportValidationError(f"{ticker}.sources[{index}] must be an object")
        kind = source.get("kind")
        if kind not in SOURCE_KINDS:
            raise ReportValidationError(f"{ticker}.sources[{index}].kind must be official or media")
        output.append(
            {
                "kind": str(kind),
                "title": text(source.get("title"), f"{ticker}.sources[{index}].title", limit=500),
                "url": safe_url(source.get("url"), f"{ticker}.sources[{index}].url"),
                "publisher": text(source.get("publisher"), f"{ticker}.sources[{index}].publisher", limit=200),
                "excerpt": text(source.get("excerpt"), f"{ticker}.sources[{index}].excerpt", limit=1000),
            }
        )
    return output


def validate_context(value: object) -> tuple[str, dict[tuple[str, str], dict[str, str]]]:
    if not isinstance(value, dict):
        raise ReportValidationError("context must be an object returned by /api/earnings-reports/context")
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
        if key not in candidate_map:
            raise ReportValidationError(f"{ticker} is not a candidate from the supplied context")
        if key in seen:
            raise ReportValidationError(f"{ticker} appears more than once")
        seen.add(key)
        reported = item.get("reported")
        if not isinstance(reported, bool):
            raise ReportValidationError(f"{ticker}.reported must be boolean")
        actual_release_date = ""
        if item.get("actual_release_date"):
            actual_release_date = parse_date(item["actual_release_date"], f"{ticker}.actual_release_date")
        if reported and not actual_release_date:
            raise ReportValidationError(f"{ticker} must include actual_release_date when reported")
        sentiment = item.get("sentiment")
        if sentiment not in SENTIMENTS:
            raise ReportValidationError(f"{ticker}.sentiment is invalid")
        evidence_level = item.get("evidence_level")
        if evidence_level not in {"confirmed", "limited"}:
            raise ReportValidationError(f"{ticker}.evidence_level must be confirmed or limited")
        sources = validate_sources(item.get("sources"), ticker)
        summary = text(item.get("summary"), f"{ticker}.summary")
        media_view = text(item.get("media_view"), f"{ticker}.media_view")
        if not reported:
            if evidence_level != "limited" or not (summary.startswith("有限证据") and media_view.startswith("有限证据")):
                raise ReportValidationError(f"{ticker} must use the 有限证据 fallback until publication is confirmed")
        if reported and not any(source["kind"] == "official" for source in sources):
            raise ReportValidationError(f"{ticker} reported=true requires an official SEC or company IR source")
        points = item.get("key_points")
        if not isinstance(points, list) or not points:
            raise ReportValidationError(f"{ticker}.key_points must be a non-empty list")
        companies.append(
            {
                "ticker": ticker,
                "company_name": candidate_map[key]["company_name"],
                "calendar_date": calendar_date,
                "announcement_time": candidate_map[key]["announcement_time"],
                "reported": reported,
                "actual_release_date": actual_release_date,
                "sentiment": sentiment,
                "evidence_level": evidence_level,
                "summary": summary,
                "media_view": media_view,
                "key_points": [text(point, f"{ticker}.key_points", limit=800) for point in points],
                "sources": sources,
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


def render_html(report: dict[str, Any]) -> str:
    cards: list[str] = []
    for company in report["companies"]:
        status = "已确认发布" if company["reported"] else "待公开资料确认"
        actual = f" · 实际发布：{company['actual_release_date']}" if company["actual_release_date"] else ""
        points = "".join(f"<li>{html.escape(point)}</li>" for point in company["key_points"])
        sources = "".join(
            "<li><span class=\"source-kind\">"
            + html.escape(source["kind"])
            + "</span> <a href=\""
            + html.escape(source["url"], quote=True)
            + "\" target=\"_blank\" rel=\"noreferrer\">"
            + html.escape(source["title"])
            + "</a><small> · "
            + html.escape(source["publisher"])
            + "</small><p>"
            + html.escape(source["excerpt"])
            + "</p></li>"
            for source in company["sources"]
        )
        cards.append(
            f"<article class=\"card\"><div class=\"card-head\"><div><h2>{html.escape(company['ticker'])} "
            f"<small>{html.escape(company['company_name'])}</small></h2><p>日历日期：{html.escape(company['calendar_date'])} · "
            f"{html.escape(status)}{html.escape(actual)}</p></div><span class=\"tag {html.escape(company['sentiment'])}\">"
            f"{html.escape(company['sentiment'])}</span></div><p>{html.escape(company['summary'])}</p>"
            f"<p><b>媒体补充观点：</b>{html.escape(company['media_view'])}</p><h3>关注要点</h3><ul>{points}</ul>"
            f"<h3>来源</h3><ul class=\"sources\">{sources}</ul></article>"
        )
    risks = "".join(f"<li>{html.escape(note)}</li>" for note in report["risk_notes"])
    return f"""<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>美股财报舆情日报 {html.escape(report['report_date'])}</title><style>body{{margin:0;background:#f4f7fb;color:#18212f;font:15px/1.65 -apple-system,BlinkMacSystemFont,\"Segoe UI\",\"Microsoft YaHei\",sans-serif}}main{{max-width:1100px;margin:auto;padding:32px 20px 56px}}header,.card{{background:#fff;border:1px solid #d8e0eb;border-radius:12px;box-shadow:0 4px 18px #19304a0c}}header{{padding:24px 26px;margin-bottom:18px}}h1,h2,h3,p{{margin-top:0}}h1{{margin-bottom:6px}}.meta,.card-head p,small{{color:#607086}}.summary{{font-size:17px}}.grid{{display:grid;gap:14px}}.card{{padding:20px}}.card-head{{display:flex;justify-content:space-between;gap:12px}}.card h2{{margin-bottom:2px}}.tag{{height:fit-content;border-radius:999px;padding:4px 10px;font-weight:800;font-size:12px;background:#edf2f7}}.tag.positive{{background:#dcfce7;color:#167343}}.tag.negative{{background:#fee2e2;color:#b42318}}.tag.mixed{{background:#fef3c7;color:#925d00}}.sources a{{color:#1f6feb}}.sources p{{margin:3px 0 10px;color:#4b5a6d}}.source-kind{{font-size:11px;font-weight:800;text-transform:uppercase;color:#607086}}</style></head><body><main><header><p class=\"meta\">Codex 联网研究 · 官方来源优先 · 非投资建议</p><h1>美股财报舆情日报 · {html.escape(report['report_date'])}</h1><p class=\"summary\">{html.escape(report['summary'])}</p><p class=\"meta\">整体风向：{html.escape(report['overall_sentiment'])} · 生成时间：{html.escape(report['generated_at'])}</p></header><section class=\"grid\">{''.join(cards)}</section>{('<section class=\"card\"><h2>风险提示</h2><ul>' + risks + '</ul></section>') if risks else ''}</main></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and render a Codex-researched earnings report.")
    parser.add_argument("--input", required=True, help="Research report JSON path")
    parser.add_argument("--context", required=True, help="Saved /api/earnings-reports/context JSON path")
    parser.add_argument("--output-dir", required=True, help="Directory for normalized JSON and HTML")
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    context = json.loads(Path(args.context).read_text(encoding="utf-8"))
    report = validate_report(payload, context)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"earnings_sentiment_{report['report_date']}"
    (output_dir / f"{stem}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / f"{stem}.html").write_text(render_html(report), encoding="utf-8")
    print(f"Rendered: {output_dir / f'{stem}.html'}")


if __name__ == "__main__":
    main()
