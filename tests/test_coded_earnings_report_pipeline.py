from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from app.api import earnings_reports  # noqa: E402
from render_earnings_sentiment_report import (  # noqa: E402
    ReportValidationError,
    render_html,
    validate_report,
)


class EarningsContextTests(unittest.TestCase):
    def test_context_combines_current_and_history_without_duplicates(self) -> None:
        current = Path("current.csv")
        history = Path("history.csv")
        with patch.object(earnings_reports, "EARNINGS_CALENDAR_FILE", current), patch.object(
            earnings_reports, "EARNINGS_CALENDAR_HISTORY_FILE", history
        ), patch.object(
            earnings_reports,
            "_read_calendar_rows",
            side_effect=[
                [
                    {"ticker": "NVDA", "company_name": "NVIDIA", "earnings_date": "2026-08-04", "announcement_time": "amc"}
                ],
                [
                    {"ticker": "NVDA", "company_name": "NVIDIA", "earnings_date": "2026-08-04", "announcement_time": "amc"},
                    {"ticker": "AMD", "company_name": "AMD", "earnings_date": "2026-08-03", "announcement_time": "bmo"},
                ],
            ],
        ):
            context = earnings_reports.get_earnings_report_context(date(2026, 8, 5), 3)
        self.assertEqual(context["report_date"], "2026-08-05")
        self.assertEqual([item["ticker"] for item in context["candidates"]], ["NVDA", "AMD"])


class EarningsRendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = {
            "report_date": "2026-08-05",
            "candidates": [
                {"ticker": "NVDA", "company_name": "NVIDIA", "calendar_date": "2026-08-04", "announcement_time": "amc"}
            ],
        }
        self.payload = {
            "report_date": "2026-08-05",
            "overall_sentiment": "mixed",
            "summary": "市场同时关注业绩与后续指引。",
            "companies": [
                {
                    "ticker": "NVDA",
                    "calendar_date": "2026-08-04",
                    "reported": True,
                    "actual_release_date": "2026-08-04",
                    "sentiment": "positive",
                    "evidence_level": "confirmed",
                    "summary": "公司已发布季度业绩。",
                    "media_view": "媒体重点讨论数据中心业务与指引。",
                    "key_points": ["EPS 高于市场预期"],
                    "sources": [
                        {
                            "kind": "official",
                            "title": "Quarterly results <script>alert(1)</script>",
                            "url": "https://investor.nvidia.com/news/default.aspx",
                            "publisher": "NVIDIA IR",
                            "excerpt": "官方新闻稿确认业绩已发布。",
                        },
                        {
                            "kind": "media",
                            "title": "Market reaction",
                            "url": "https://www.reuters.com/example",
                            "publisher": "Reuters",
                            "excerpt": "市场反应摘要。",
                        },
                    ],
                }
            ],
            "risk_notes": ["媒体观点不构成投资建议。"],
        }

    def test_valid_report_renders_escaped_html(self) -> None:
        report = validate_report(self.payload, self.context)
        rendered = render_html(report)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertNotIn("<script>alert(1)</script>", rendered)
        self.assertIn("https://www.reuters.com/example", rendered)

    def test_unconfirmed_company_requires_limited_evidence_prefix(self) -> None:
        self.payload["companies"][0]["reported"] = False
        self.payload["companies"][0]["actual_release_date"] = ""
        self.payload["companies"][0]["evidence_level"] = "limited"
        with self.assertRaises(ReportValidationError):
            validate_report(self.payload, self.context)

    def test_rejects_unsafe_source_url(self) -> None:
        self.payload["companies"][0]["sources"][0]["url"] = "javascript:alert(1)"
        with self.assertRaises(ReportValidationError):
            validate_report(self.payload, self.context)

    def test_confirmed_company_requires_an_official_source(self) -> None:
        self.payload["companies"][0]["sources"][0]["kind"] = "media"
        with self.assertRaises(ReportValidationError):
            validate_report(self.payload, self.context)

    def test_rejects_company_outside_the_server_context(self) -> None:
        self.payload["companies"][0]["calendar_date"] = "2026-08-05"
        with self.assertRaises(ReportValidationError):
            validate_report(self.payload, self.context)


if __name__ == "__main__":
    unittest.main()
