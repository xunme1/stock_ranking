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
import scripts.import_corporate_action_oss as oss_import_script  # noqa: E402


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


def direct_event(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "schema_version": "corporate-action-event/v2",
        "agent_record_id": "us-buyback-001",
        "source_agent": "direct-agent",
        "market": "us",
        "ticker": "AAPL",
        "company_name": "Apple Inc.",
        "exchange": "NASDAQ",
        "event_type": "buyback",
        "event_stage": "authorized",
        "actor_name": "Apple Inc.",
        "actor_type": "company",
        "headline": "Apple authorizes a share repurchase",
        "headline_zh": "苹果授权股份回购",
        "summary_zh": "苹果宣布新的股份回购授权。",
        "quantity_text": "",
        "amount_text": "$100 billion",
        "ownership_change_text": "",
        "published_at": "2026-08-19",
        "event_date": "2026-08-19",
        "source_url": "https://example.com/direct/apple-buyback",
        "source_domain": "example.com",
        "source_quality": "primary",
        "confidence": 0.95,
        "evidence_text": "The Board authorized a new $100 billion share repurchase program.",
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

    def test_oss_candidate_validation_normalizes_optional_fields(self) -> None:
        candidate, source_agent = oss_import_script.validate_candidate(
            {
                "schema_version": "corporate-action-candidate/v1",
                "source_agent": "cn-agent-1",
                "market": "cn",
                "event_type": "buyback",
                "headline": "Example buyback",
                "published_at": "2026-08-19",
                "source_url": "https://Example.com/news/1",
            },
            "corporate-actions/v1/incoming/cn/sample.jsonl",
            1,
        )
        self.assertEqual(candidate["event_stage"], "announced")
        self.assertEqual(candidate["source_domain"], "example.com")
        self.assertEqual(source_agent, "cn-agent-1")

    def test_oss_parser_keeps_valid_rows_and_reports_invalid_rows(self) -> None:
        valid = json.dumps({
            "schema_version": "corporate-action-candidate/v1", "market": "hk", "event_type": "reduction",
            "headline": "Example stake sale", "published_at": "2026-08-19", "source_url": "https://example.com/news/2",
        })
        candidates, errors, source_agent = oss_import_script.parse_jsonl(
            (valid + "\nnot-json\n").encode(), "batch.jsonl"
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual(source_agent, "")

    def test_v2_validation_requires_complete_evidenced_event(self) -> None:
        parsed, source_agent = oss_import_script.validate_direct_event(direct_event(), "batch.jsonl", 1)
        self.assertEqual(parsed["source_schema"], "corporate-action-event/v2")
        self.assertEqual(parsed["evidence_text"], direct_event()["evidence_text"])
        self.assertEqual(source_agent, "direct-agent")

    def test_v2_parser_quarantines_invalid_fields_and_duplicate_agent_ids(self) -> None:
        invalid_rows = [
            direct_event(evidence_text=""),
            direct_event(agent_record_id="bad-url", source_url="not-a-url"),
            direct_event(agent_record_id="bad-date", published_at="2026/08/19"),
            direct_event(agent_record_id="low-confidence", confidence=0.69),
            direct_event(agent_record_id="bad-type", event_type="issuance"),
            direct_event(agent_record_id="no-company", company_name=""),
            direct_event(agent_record_id="duplicate"),
            direct_event(agent_record_id="duplicate", source_url="https://example.com/direct/duplicate"),
        ]
        candidates, direct_events, rejected, source_agent = oss_import_script.parse_import_jsonl(
            ("\n".join(json.dumps(row) for row in invalid_rows) + "\n").encode(), "batch.jsonl"
        )
        self.assertEqual(candidates, [])
        self.assertEqual(len(direct_events), 1)
        self.assertEqual(len(rejected), 7)
        self.assertTrue(all(row.error_code == "validation_error" for row in rejected))
        self.assertEqual(source_agent, "direct-agent")

    def test_oss_explicit_object_mode_uses_head_without_listing(self) -> None:
        class Metadata:
            etag = "etag-a"
            content_length = 123

        class FakeBucket:
            def head_object(self, key: str) -> Metadata:
                self.key = key
                return Metadata()

        bucket = FakeBucket()
        objects = oss_import_script.explicit_objects(bucket, ["/incoming/cn/batch.jsonl", "incoming/cn/batch.jsonl"])
        self.assertEqual(objects, [oss_import_script.OssObjectRef("incoming/cn/batch.jsonl", "etag-a", 123)])
        self.assertEqual(bucket.key, "incoming/cn/batch.jsonl")

    def test_oss_streaming_read_enforces_body_limit_and_etag(self) -> None:
        class FakeResponse:
            etag = "etag-a"
            content_length = 6

            def __init__(self) -> None:
                self.offset = 0

            def read(self, size: int) -> bytes:
                body = b"abcdef"
                chunk = body[self.offset:self.offset + size]
                self.offset += len(chunk)
                return chunk

        class FakeBucket:
            def get_object(self, _key: str) -> FakeResponse:
                return FakeResponse()

        self.assertEqual(oss_import_script.read_object_payload(FakeBucket(), "batch.jsonl", 6, "etag-a"), b"abcdef")
        with self.assertRaisesRegex(ValueError, "changed while importing"):
            oss_import_script.read_object_payload(FakeBucket(), "batch.jsonl", 6, "etag-other")
        with self.assertRaisesRegex(ValueError, "exceeds limit"):
            oss_import_script.read_object_payload(FakeBucket(), "batch.jsonl", 5, "etag-a")

    def test_import_parser_enforces_row_and_v1_candidate_limits(self) -> None:
        direct_body = (json.dumps(direct_event()) + "\n" + json.dumps(direct_event(agent_record_id="second"))).encode()
        with self.assertRaisesRegex(ValueError, "row count exceeds limit 1"):
            oss_import_script.parse_import_jsonl(direct_body, "batch.jsonl", max_rows=1)
        v1 = {
            "schema_version": "corporate-action-candidate/v1", "market": "us", "event_type": "buyback",
            "headline": "Share repurchase", "published_at": "2026-08-19", "source_url": "https://example.com/v1",
        }
        v1_body = (json.dumps(v1) + "\n" + json.dumps({**v1, "source_url": "https://example.com/v1-2"})).encode()
        with self.assertRaisesRegex(ValueError, "v1 candidate count exceeds limit 1"):
            oss_import_script.parse_import_jsonl(v1_body, "batch.jsonl", max_v1_candidates=1)

    @patch.object(oss_import_script, "archive_candidates")
    def test_oss_object_import_is_idempotent_per_etag(self, archive_candidates) -> None:
        class FakeResponse:
            def __init__(self, body: bytes) -> None:
                self.body = body

            def read(self) -> bytes:
                return self.body

        class FakeBucket:
            def __init__(self, body: bytes) -> None:
                self.body = body

            def get_object(self, _key: str) -> FakeResponse:
                return FakeResponse(self.body)

        body = (json.dumps({
            "schema_version": "corporate-action-candidate/v1", "market": "us", "event_type": "buyback",
            "headline": "Apple buyback", "published_at": "2026-08-19", "source_url": "https://example.com/news/3",
        }) + "\n").encode()
        archive_candidates.side_effect = lambda candidates, *_args, **_kwargs: [event()] if candidates else []
        bucket = FakeBucket(body)
        first = oss_import_script.import_object(bucket, "test-bucket", "incoming/us/batch.jsonl", "etag-a", len(body), 1024, db_path=self.db_path)
        second = oss_import_script.import_object(bucket, "test-bucket", "incoming/us/batch.jsonl", "etag-a", len(body), 1024, db_path=self.db_path)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "skipped")
        self.assertEqual(archive_candidates.call_count, 1)

    @patch.object(service, "load_pool_entries")
    @patch.object(oss_import_script, "archive_candidates")
    def test_v2_object_imports_directly_without_candidate_structuring(self, archive_candidates, load_pool_entries) -> None:
        class FakeResponse:
            def __init__(self, body: bytes) -> None:
                self.body = body

            def read(self) -> bytes:
                return self.body

        class FakeBucket:
            def __init__(self, body: bytes) -> None:
                self.body = body

            def get_object(self, _key: str) -> FakeResponse:
                return FakeResponse(self.body)

        pools = {
            "us": [service.PoolEntry("us", "AAPL", "Apple Inc.")],
            "cn": [service.PoolEntry("cn", "000001", "平安银行")],
            "hk": [service.PoolEntry("hk", "00020.HK", "示例公司")],
        }
        load_pool_entries.side_effect = lambda market: pools[market]
        rows = [
            direct_event(),
            direct_event(agent_record_id="cn-reduction-001", market="cn", ticker="000001.SZ", company_name="平安银行", event_type="reduction", event_stage="announced", source_url="https://example.com/direct/cn", headline="Shareholder reduction", headline_zh="股东减持", summary_zh="股东披露减持计划。", evidence_text="The shareholder plans to reduce its holdings."),
            direct_event(agent_record_id="hk-buyback-001", market="hk", ticker="0020.HK", company_name="示例公司", event_type="buyback", event_stage="executed", source_url="https://example.com/direct/hk", headline="Share repurchase", headline_zh="股份回购", summary_zh="公司已回购股份。", evidence_text="The Company repurchased shares in the market."),
        ]
        body = ("\n".join(json.dumps(row) for row in rows) + "\n").encode()
        result = oss_import_script.import_object(FakeBucket(body), "test-bucket", "incoming/direct.jsonl", "etag-v2", len(body), 10000, db_path=self.db_path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["accepted_rows"], 3)
        self.assertEqual(result["quarantined_rows"], 0)
        archive_candidates.assert_not_called()
        for market in ("us", "cn", "hk"):
            data = service.query_news(market, date(2026, 8, 19), db_path=self.db_path)["data"]
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["attention_level"], "high")
            self.assertEqual(data[0]["source_schema"], "corporate-action-event/v2")
            self.assertTrue(data[0]["agent_record_id"])
            self.assertEqual(data[0]["source_agent"], "direct-agent")
            self.assertTrue(data[0]["evidence_text"])

    @patch.object(service, "load_pool_entries", return_value=[])
    def test_invalid_v2_rows_are_quarantined_without_news_write(self, _load_pool_entries) -> None:
        class FakeResponse:
            def read(self) -> bytes:
                return json.dumps(direct_event(evidence_text="")).encode()

        class FakeBucket:
            def get_object(self, _key: str) -> FakeResponse:
                return FakeResponse()

        result = oss_import_script.import_object(FakeBucket(), "test-bucket", "incoming/bad-v2.jsonl", "etag-bad", 200, 1000, db_path=self.db_path)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["accepted_rows"], 0)
        self.assertEqual(result["quarantined_rows"], 1)
        self.assertEqual(service.query_news("us", date(2026, 8, 19), db_path=self.db_path)["count"], 0)
        with service.db_connection(self.db_path) as conn:
            rejected = conn.execute("SELECT error_code, source_agent, raw_payload FROM corporate_action_import_rejections").fetchone()
        self.assertEqual(rejected["error_code"], "validation_error")
        self.assertEqual(rejected["source_agent"], "direct-agent")
        self.assertIn("evidence_text", rejected["raw_payload"])
        status = service.service_status(self.db_path)
        us = next(item for item in status["data"] if item["market"] == "us")
        self.assertEqual(us["quarantined_count"], 1)
        self.assertIn("evidence_text", us["last_quarantine_error"])

    @patch.object(service, "load_pool_entries", return_value=[])
    def test_retry_partial_reprocesses_an_otherwise_skipped_object(self, _load_pool_entries) -> None:
        class FakeResponse:
            def read(self) -> bytes:
                return json.dumps(direct_event(evidence_text="")).encode()

        class FakeBucket:
            def __init__(self) -> None:
                self.calls = 0

            def get_object(self, _key: str) -> FakeResponse:
                self.calls += 1
                return FakeResponse()

        bucket = FakeBucket()
        first = oss_import_script.import_object(bucket, "test-bucket", "incoming/partial.jsonl", "etag-partial", 200, 1000, db_path=self.db_path)
        skipped = oss_import_script.import_object(bucket, "test-bucket", "incoming/partial.jsonl", "etag-partial", 200, 1000, db_path=self.db_path)
        retried = oss_import_script.import_object(
            bucket, "test-bucket", "incoming/partial.jsonl", "etag-partial", 200, 1000,
            db_path=self.db_path, retry_partial=True,
        )
        self.assertEqual(first["status"], "partial")
        self.assertEqual(skipped["status"], "skipped")
        self.assertEqual(retried["status"], "partial")
        self.assertEqual(bucket.calls, 2)

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
        self.assertIsNone(service._candidate_from_result({"title": "Company buyback", "content": "share repurchase", "url": "javascript:alert(1)", "published_date": "2026-07-10"}, task))

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

    @patch("app.services.corporate_action_news_service.requests.get")
    def test_unsafe_tavily_url_is_never_fetched_for_date_resolution(self, get) -> None:
        task = {"market": "us", "event_type": "buyback", "query": "ignored"}
        result = service._candidate_from_result(
            {"title": "Company buyback", "content": "share repurchase", "url": "javascript:alert(1)", "published_date": ""},
            task,
            resolve_date=True,
        )
        self.assertIsNone(result)
        get.assert_not_called()

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
