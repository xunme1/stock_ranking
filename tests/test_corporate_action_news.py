from __future__ import annotations

import json
import sys
import tempfile
import unittest
from argparse import Namespace
from datetime import date
from pathlib import Path
from unittest.mock import patch



ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "backend"))

from app.services import corporate_action_news_service as service  # noqa: E402
from app.api import corporate_actions as corporate_actions_api  # noqa: E402
import scripts.update_corporate_action_news as collector_script  # noqa: E402


def event(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "market": "us",
        "ticker": "AAPL",
        "company_name": "Apple Inc.",
        "event_type": "buyback",
        "event_stage": "authorized",
        "actor_name": "",
        "actor_type": "company",
        "headline": "Apple authorizes share repurchase",
        "headline_zh": "苹果授权股份回购",
        "summary_zh": "苹果宣布股份回购授权。",
        "quantity_text": "",
        "amount_text": "$100 billion",
        "ownership_change_text": "",
        "published_at": "2026-07-10",
        "event_date": "2026-07-10",
        "source_url": "https://example.com/apple-buyback",
        "source_domain": "example.com",
        "source_quality": "mainstream",
        "confidence": 0.95,
    }
    base.update(overrides)
    return base


class CorporateActionNewsTests(unittest.TestCase):
    def setUp(self) -> None:
        (ROOT_DIR / ".tmp").mkdir(exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=ROOT_DIR / ".tmp")
        self.db_path = Path(self.temp_dir.name) / "corporate_actions.db"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch.object(service, "load_pool_entries")
    def test_pool_match_marks_known_ticker_high_and_keeps_outside_event(self, load_pool_entries) -> None:
        load_pool_entries.side_effect = lambda market: [service.PoolEntry(market, "AAPL", "Apple Inc.")]
        service.save_events([event(), event(ticker="ZZZZ", company_name="Outside Corp", source_url="https://example.com/outside")], self.db_path)
        result = service.query_news("us", date(2026, 7, 14), db_path=self.db_path)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["in_stock_pool_count"], 1)
        self.assertEqual(result["data"][0]["ticker"], "AAPL")
        self.assertEqual(result["data"][0]["attention_level"], "high")
        self.assertEqual(result["data"][0]["headline_zh"], "苹果授权股份回购")
        self.assertEqual(result["data"][1]["attention_level"], "normal")

    @patch.object(service, "load_pool_entries")
    def test_repeated_source_is_idempotent_and_filters_work(self, load_pool_entries) -> None:
        load_pool_entries.return_value = [service.PoolEntry("cn", "000001", "平安银行")]
        row = event(market="cn", ticker="000001.SZ", company_name="平安银行", event_type="reduction", source_url="https://example.com/pab")
        service.save_events([row], self.db_path)
        service.save_events([{**row, "summary_zh": "更新后的摘要"}], self.db_path)
        result = service.query_news("cn", date(2026, 7, 14), event_type="reduction", attention="high", ticker="000001", db_path=self.db_path)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["data"][0]["ticker"], "000001")
        self.assertEqual(result["data"][0]["summary_zh"], "更新后的摘要")

    @patch.object(service, "load_pool_entries", return_value=[])
    def test_tracking_variants_of_same_url_are_deduplicated(self, _load_pool_entries) -> None:
        source_url = "https://example.com/news/apple-buyback?utm_source=tavily&fbclid=abc#section"
        service.save_events([event(source_url=source_url)], self.db_path)
        service.save_events([event(source_url="https://example.com/news/apple-buyback/")], self.db_path)
        result = service.query_news("us", date(2026, 7, 14), db_path=self.db_path)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["data"][0]["normalized_url"], "https://example.com/news/apple-buyback")

    def test_event_deduplication_keeps_one_company_event_per_canonical_url(self) -> None:
        rows = service.deduplicate_events([
            event(event_stage="authorized", source_url="https://example.com/apple?utm_source=tavily"),
            event(event_stage="executed", amount_text="$100 billion", source_url="https://example.com/apple#update"),
            event(ticker="MSFT", company_name="Microsoft", source_url="https://example.com/apple"),
        ])
        self.assertEqual(len(rows), 2)
        apple = next(row for row in rows if row["ticker"] == "AAPL")
        self.assertEqual(apple["event_stage"], "executed")

    @patch.object(service, "load_pool_entries")
    def test_company_name_pool_match_backfills_missing_us_ticker(self, load_pool_entries) -> None:
        load_pool_entries.return_value = [service.PoolEntry("us", "AAPL", "Apple Inc.")]
        service.save_events([event(ticker="", company_name="Apple Inc.")], self.db_path)
        result = service.query_news("us", date(2026, 7, 14), db_path=self.db_path)
        self.assertEqual(result["data"][0]["ticker"], "AAPL")
        self.assertEqual(result["data"][0]["pool_match_method"], "company_name")

    def test_search_tasks_are_event_centric_not_pool_limited(self) -> None:
        tasks = service.build_search_tasks("hk")
        self.assertEqual(len(tasks), 4)
        self.assertTrue(all("ticker" not in task["query"].lower() for task in tasks))
        self.assertEqual({task["event_type"] for task in tasks}, {"buyback", "reduction"})

    def test_collection_tasks_add_laohu_only_for_cn_and_hk(self) -> None:
        self.assertEqual(len(service.build_collection_tasks("us")), 4)
        cn_tasks = service.build_collection_tasks("cn")
        self.assertEqual(len(cn_tasks), 6)
        self.assertEqual({task["provider"] for task in cn_tasks}, {"tavily", "laohu8"})
        laohu_tasks = [task for task in cn_tasks if task["provider"] == "laohu8"]
        self.assertEqual({task["query"] for task in laohu_tasks}, {"回购", "减持"})

    def test_laohu_candidate_uses_source_timestamp_and_cleans_title(self) -> None:
        task = {"market": "cn", "event_type": "buyback", "query": "回购", "provider": "laohu8"}
        candidate = service._candidate_from_laohu_result(
            {
                "newsId": "123456",
                "title": "甲公司<font color='#f8cc00'>回购</font>股份",
                "listText": "累计回购 100 万股",
                "gmtCreate": 1785448531635,
            },
            task,
        )
        self.assertEqual(candidate["published_at"], "2026-07-31")
        self.assertEqual(candidate["headline"], "甲公司回购股份")
        self.assertEqual(candidate["source_url"], "https://www.laohu8.com/news/123456")

    @patch.object(service, "_load_deepseek_key", return_value="test-key")
    @patch("app.services.corporate_action_news_service.requests.post")
    @patch.dict(service.os.environ, {"DEEPSEEK_MODEL": "deepseek-v4-flash"})
    def test_structuring_uses_deepseek_v4_flash_non_thinking(self, post, _load_key) -> None:
        post.return_value.raise_for_status.return_value = None
        post.return_value.json.return_value = {"choices": [{"message": {"content": json.dumps({"events": [{
            "source_url": "https://example.com/apple-buyback",
            "ticker": "AAPL",
            "company_name": "Apple Inc.",
            "event_type": "buyback",
            "event_stage": "authorized",
            "confidence": 0.95,
        }]})}}]}
        result = service.classify_candidates([{**event(), "snippet": "Apple announced a share repurchase."}], "us")
        self.assertEqual(result[0]["ticker"], "AAPL")
        request_body = post.call_args.kwargs["json"]
        self.assertEqual(request_body["model"], "deepseek-v4-flash")
        self.assertEqual(request_body["thinking"], {"type": "disabled"})

    @patch.object(service, "_load_deepseek_key", return_value="test-key")
    @patch("app.services.corporate_action_news_service.requests.post")
    def test_structuring_splits_large_candidate_sets_for_five_workers(self, post, _load_key) -> None:
        post.return_value.raise_for_status.return_value = None
        post.return_value.json.return_value = {"choices": [{"message": {"content": '{"events": []}'}}]}
        candidates = [
            {**event(source_url=f"https://example.com/news/{index}"), "snippet": "Share repurchase announcement."}
            for index in range(41)
        ]
        result = service.classify_candidates(candidates, "us")
        self.assertEqual(len(result), 41)
        self.assertEqual(post.call_count, 3)
        self.assertEqual(service.DEEPSEEK_STRUCTURING_WORKERS, 5)

    def test_tavily_key_pool_uses_round_robin_order(self) -> None:
        pool = ["load-balance-a", "load-balance-b", "load-balance-c"]
        self.assertEqual(service.balanced_tavily_keys(pool), pool)
        self.assertEqual(service.balanced_tavily_keys(pool), ["load-balance-b", "load-balance-c", "load-balance-a"])
        self.assertEqual(service.balanced_tavily_keys(pool), ["load-balance-c", "load-balance-a", "load-balance-b"])

    @patch.object(collector_script, "record_run")
    @patch.object(collector_script, "collect_market", side_effect=RuntimeError("US task error"))
    def test_market_task_failure_is_isolated_and_recorded(self, _collect_market, record_run) -> None:
        args = Namespace(lookback_days=30, max_results=10, dry_run=False)
        result, failed = collector_script.run_market_task("us", date(2026, 7, 14), args)
        self.assertTrue(failed)
        self.assertEqual(result["task"], "corporate-actions:us")
        self.assertEqual(result["status"], "failed")
        record_run.assert_called_once()

    @patch.object(service, "load_pool_entries", return_value=[])
    def test_status_and_stale_response(self, _load_pool_entries) -> None:
        service.save_events([event()], self.db_path)
        service.record_run("us", date(2026, 7, 10), date(2026, 6, 10), "ok", 4, 1, 1, db_path=self.db_path)
        result = service.query_news("us", date(2026, 7, 14), db_path=self.db_path)
        self.assertTrue(result["stale"])
        status = service.service_status(self.db_path)
        us = next(item for item in status["data"] if item["market"] == "us")
        self.assertEqual(us["event_count"], 1)

    def test_candidate_rejects_old_or_non_event_content(self) -> None:
        task = {"market": "us", "event_type": "buyback", "query": "ignored"}
        self.assertIsNone(service._candidate_from_result({"title": "ETF creation", "content": "ETF creation", "url": "https://example.com", "published_date": "2026-07-10"}, task))
        self.assertIsNone(service._candidate_from_result({"title": "Company buyback", "content": "share repurchase", "url": "https://example.com", "published_date": ""}, task))

    @patch("app.services.corporate_action_news_service.requests.get")
    def test_missing_tavily_date_uses_verified_page_metadata(self, get) -> None:
        get.return_value.text = '<meta property="article:published_time" content="2026-07-10T12:00:00Z">'
        get.return_value.raise_for_status.return_value = None
        task = {"market": "us", "event_type": "buyback", "query": "ignored"}
        candidate = service._candidate_from_result(
            {"title": "Company buyback", "content": "share repurchase", "url": "https://example.com", "published_date": ""},
            task,
            resolve_date=True,
        )
        self.assertEqual(candidate["published_at"], "2026-07-10")

    @patch.object(service, "load_tavily_keys", return_value=[])
    def test_collect_reports_quota_or_key_failure_without_writing(self, _load_keys) -> None:
        result = service.collect_market("us", date(2026, 7, 14), dry_run=True)
        self.assertEqual(result["event_count"], 0)
        self.assertEqual(len(result["errors"]), 4)

    @patch.object(corporate_actions_api, "service_status", return_value={"data": [{"market": "us"}]})
    @patch.object(corporate_actions_api, "query_news")
    def test_api_routes_forward_all_filters(self, query_news, _service_status) -> None:
        query_news.return_value = {"market": "us", "status": "ok", "data": []}
        response = corporate_actions_api.get_corporate_action_news(
            market="us", as_of_date=date(2026, 7, 14), lookback_days=30, event_type="buyback",
            attention="high", in_stock_pool=True, ticker="AAPL", limit=20,
        )
        self.assertEqual(response["status"], "ok")
        self.assertEqual(query_news.call_args.args[0], "us")
        self.assertEqual(query_news.call_args.args[3], "buyback")
        self.assertEqual(query_news.call_args.args[4], "high")
        self.assertEqual(query_news.call_args.args[5], True)
        self.assertEqual(corporate_actions_api.get_corporate_action_status(), {"data": [{"market": "us"}]})


if __name__ == "__main__":
    unittest.main()
