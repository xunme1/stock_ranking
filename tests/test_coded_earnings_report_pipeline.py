from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from app.api import earnings_reports  # noqa: E402
from build_earnings_report_context import build_context  # noqa: E402
from earnings_market_metrics import post_earnings_metrics, pre_earnings_metrics  # noqa: E402
from render_earnings_sentiment_report import ReportValidationError, render_html, validate_report  # noqa: E402


class EarningsContextTests(unittest.TestCase):
    def test_context_combines_current_and_history_without_duplicates(self) -> None:
        rows = [
            [{"ticker": "NVDA", "company_name": "NVIDIA", "earnings_date": "2026-08-04", "announcement_time": "amc"}],
            [{"ticker": "NVDA", "company_name": "NVIDIA", "earnings_date": "2026-08-04", "announcement_time": "amc"}, {"ticker": "AMD", "company_name": "AMD", "earnings_date": "2026-08-03", "announcement_time": "bmo"}],
        ]
        with patch.object(earnings_reports, "_read_calendar_rows", side_effect=rows):
            context = earnings_reports.get_earnings_report_context(date(2026, 8, 5), 3)
        self.assertEqual([item["ticker"] for item in context["candidates"]], ["NVDA", "AMD"])

    def test_local_context_export_uses_the_same_candidate_source(self) -> None:
        candidates = [{"ticker": "AMD", "company_name": "AMD", "calendar_date": "2026-08-04", "announcement_time": "bmo"}]
        with patch("build_earnings_report_context.recent_earnings_candidates", return_value=candidates):
            context = build_context(date(2026, 8, 5), 3)
        self.assertEqual(context["window_start"], "2026-08-03")
        self.assertEqual(context["candidates"], candidates)


class EarningsMarketMetricsTests(unittest.TestCase):
    def _frame(self, closes: list[float], volumes: list[float]) -> pd.DataFrame:
        start = date(2026, 1, 1)
        return pd.DataFrame({"date": [start + timedelta(days=index) for index in range(len(closes))], "close": closes, "volume": volumes})

    def test_post_market_release_uses_next_regular_session_and_relative_qqq(self) -> None:
        stock = self._frame([100.0] * 10 + [110.0, 111.0], [100.0] * 10 + [220.0, 100.0])
        qqq = self._frame([100.0] * 10 + [101.0, 102.0], [100.0] * 12)
        metrics = post_earnings_metrics(stock, qqq, date(2026, 1, 10), "after_market")
        self.assertEqual(metrics["session_date"], "2026-01-11")
        self.assertEqual(metrics["stock_return_pct"], 10.0)
        self.assertEqual(metrics["relative_return_pct"], 9.0)
        self.assertEqual(metrics["volume_vs_20d"], 2.2)

    def test_pre_earnings_metrics_use_session_before_calendar_date(self) -> None:
        stock = self._frame([100.0, 101.0, 102.0, 105.0, 106.0], [100.0] * 5)
        qqq = self._frame([100.0, 100.0, 101.0, 102.0, 103.0], [100.0] * 5)
        metrics = pre_earnings_metrics(stock, qqq, date(2026, 1, 6))
        self.assertEqual(metrics["session_date"], "2026-01-05")
        self.assertAlmostEqual(metrics["one_day_relative_pct"], -0.03, places=2)
        self.assertAlmostEqual(metrics["three_day_relative_pct"], 1.95, places=2)


class EarningsRendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = {"report_date": "2026-08-05", "candidates": [{"ticker": "NVDA", "company_name": "NVIDIA", "calendar_date": "2026-08-04", "announcement_time": "amc"}]}
        self.payload = {
            "report_date": "2026-08-05", "overall_sentiment": "mixed", "summary": "市场同时关注业绩与后续指引。",
            "companies": [{
                "ticker": "NVDA", "calendar_date": "2026-08-04", "report_status": "post_earnings", "reported": True,
                "actual_release_date": "2026-08-04", "release_time": "after_market", "official_confirmation_url": "https://investor.nvidia.com/news/default.aspx",
                "sentiment": "positive", "evidence_level": "confirmed", "summary": "公司已发布季度业绩。",
                "media_view": "媒体将上涨归因于数据中心业务和上调后的指引。", "media_market_alignment": "aligned", "key_points": ["EPS 高于市场预期"],
                "sources": [
                    {"kind": "official", "phase": "context", "published_date": "2026-08-04", "title": "Quarterly results <script>alert(1)</script>", "url": "https://investor.nvidia.com/news/default.aspx", "publisher": "NVIDIA IR", "excerpt": "官方新闻稿确认业绩已发布。"},
                    {"kind": "media", "phase": "post_earnings", "published_date": "2026-08-05", "title": "Market reaction", "url": "https://www.reuters.com/example", "publisher": "Reuters", "excerpt": "市场反应摘要。"},
                ],
            }], "risk_notes": ["媒体观点不构成投资建议。"],
        }
        self.available_post_metrics = {"kind": "post_earnings", "status": "available", "session_date": "2026-08-05", "stock_return_pct": 4.0, "qqq_return_pct": 1.0, "relative_return_pct": 3.0, "volume_vs_20d": 1.5}

    def test_valid_report_renders_status_metrics_and_escaped_html(self) -> None:
        with patch("render_earnings_sentiment_report.market_metrics", return_value=self.available_post_metrics):
            report = validate_report(self.payload, self.context)
        rendered = render_html(report)
        self.assertIn("财报后：实际反应", rendered)
        self.assertIn("来源时间线", rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertNotIn("<script>alert(1)</script>", rendered)

    def test_post_earnings_media_cannot_predate_release(self) -> None:
        self.payload["companies"][0]["sources"][1]["published_date"] = "2026-08-03"
        with self.assertRaises(ReportValidationError):
            validate_report(self.payload, self.context)

    def test_unconfirmed_company_requires_limited_evidence_and_no_alignment(self) -> None:
        company = self.payload["companies"][0]
        company.update({"report_status": "unconfirmed", "reported": False, "actual_release_date": "", "official_confirmation_url": "", "evidence_level": "limited", "summary": "有限证据：尚未取得官方确认。", "media_view": "有限证据：未找到可归类为财报后反应的媒体报道。", "media_market_alignment": "not_applicable"})
        company["sources"] = [company["sources"][0]]
        with patch("render_earnings_sentiment_report.market_metrics", return_value={"kind": "pre_earnings", "status": "available"}):
            report = validate_report(self.payload, self.context)
        self.assertEqual(report["companies"][0]["report_status"], "unconfirmed")

    def test_rejects_unsafe_source_url(self) -> None:
        self.payload["companies"][0]["sources"][0]["url"] = "javascript:alert(1)"
        with self.assertRaises(ReportValidationError):
            validate_report(self.payload, self.context)


if __name__ == "__main__":
    unittest.main()
