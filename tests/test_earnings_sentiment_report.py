from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

import scripts.generate_earnings_sentiment_report as report  # noqa: E402


class EarningsSentimentReportTests(unittest.TestCase):
    def test_recent_earnings_uses_history_and_current_calendar(self) -> None:
        with patch.object(report, "read_calendar_rows", side_effect=[
            [{"ticker": "AAPL", "earnings_date": "2026-08-03", "company_name": "Apple"}],
            [
                {"ticker": "MSFT", "earnings_date": "2026-08-05", "company_name": "Microsoft"},
                {"ticker": "OLD", "earnings_date": "2026-08-01", "company_name": "Old"},
            ],
        ]):
            rows = report.recent_earnings(date(2026, 8, 5), days=3)

        self.assertEqual([(row["ticker"], row["earnings_date"]) for row in rows], [("MSFT", "2026-08-05"), ("AAPL", "2026-08-03")])

    def test_report_html_does_not_render_unverified_urls_from_model(self) -> None:
        page = report.report_html(
            date(2026, 8, 5),
            [{"ticker": "AAPL", "earnings_date": "2026-08-05", "company_name": "Apple"}],
            {"AAPL": [{"title": "Primary source", "url": "https://example.com/source", "source": "example.com", "snippet": "Results"}]},
            {"overall_sentiment": "positive", "summary": "Test", "companies": [{"ticker": "AAPL", "reported": True, "sentiment": "positive", "summary": "Good", "media_view": "Positive", "key_points": ["Beat"], "source_urls": ["https://invalid.example/report"]}]},
            "test",
            None,
        )
        self.assertIn("https://example.com/source", page)
        self.assertNotIn("https://invalid.example/report", page)

    def test_report_html_uses_search_viewpoint_when_model_omits_company(self) -> None:
        page = report.report_html(
            date(2026, 8, 5),
            [{"ticker": "MSFT", "earnings_date": "2026-08-05", "company_name": "Microsoft"}],
            {"MSFT": [{"title": "Results commentary", "url": "https://example.com/msft", "source": "example.com", "snippet": "Revenue beat expectations and guidance was maintained."}]},
            {"overall_sentiment": "neutral", "summary": "Test", "companies": []},
            "test",
            "test-model",
        )
        self.assertIn("有限证据下的检索观点", page)
        self.assertIn("Revenue beat expectations", page)
