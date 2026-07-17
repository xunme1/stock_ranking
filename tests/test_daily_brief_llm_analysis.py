from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
DAILY_BRIEF_DIR = ROOT / "experiments" / "daily_brief"
if str(DAILY_BRIEF_DIR) not in sys.path:
    sys.path.insert(0, str(DAILY_BRIEF_DIR))

import llm_analysis  # noqa: E402
import interactive_daily_brief  # noqa: E402


def complete_markdown_report() -> str:
    sections = [
        ("核心结论", "APP 异动值得关注 [1]。本段补充足够长的市场结论，用于验证长文质量门槛。"),
        ("市场结构", "QQQ 与 Top20 的强弱关系显示结构性行情，榜单换手提示资金在主题间迁移。"),
        (
            "驱动因素与证据",
            "1. 现象：APP 大幅异动并进入关键观察对象。源头：主流媒体报道与量化排名同步变化。证据：[1]。"
            "影响链条：公开信息先改善市场对公司短期业务弹性的认知，再通过价格上涨和排名上移反映到动能榜单，"
            "随后吸引同类软件服务股票获得更高关注。置信度：中等。不确定性：单日价格仍可能受技术面、仓位再平衡和市场风险偏好扰动。"
            "反证条件：如果后续排名迅速回落、成交未能延续，或同类股票没有扩散表现，则该驱动更可能只是短线交易而非持续主线。"
            "2. 现象：半导体方向出现相对下行压力。源头：榜单排名变化和下跌列表。证据：[1]。"
            "影响链条：当强势资金离开高波动科技链条，弱势对象更容易被动降权。置信度：低到中等。不确定性：缺少直接公告证据时只能作为量化观察。"
            "这一段还需要说明证据源头的边界：如果来源只是新闻报道或行情观察，就只能证明市场正在讨论相关主题，不能直接证明公司基本面已经变化；"
            "如果来源来自公司公告、交易所或监管披露，才可以作为更强的事实依据进入核心驱动。",
        ),
        ("驱动因素源头拆解", "源头来自主流媒体和公司线索，优先使用 source_quality 较高的材料，低质量来源只作为待验证线索。"),
        (
            "趋势判断",
            "量化信号显示 Top20 仍有相对强度，证据支持个别主题继续活跃；但趋势能否延续取决于三个条件。"
            "第一，强势股需要在下一交易日维持排名和价格确认，否则当前异动更像短线冲高。第二，基准指数不能继续明显弱于 Top20，"
            "否则市场广度不足会压缩强势股的持续性。第三，外部证据需要继续支持核心驱动，若后续公告或新闻与当前解释不一致，"
            "应将驱动降级为待验证假设。后续验证指标包括换手率、Top20 收涨比例、关键股票排名延续、同类行业扩散情况以及引用证据的时间一致性。"
            "如果这些指标同时改善，趋势判断可以从结构性反弹上修为主线延续；如果只剩单一股票强势而行业和基准不配合，则应降低判断置信度。",
        ),
        ("关键观察对象", "APP、PANW、AMD 需要结合排名、成交和外部证据继续跟踪。"),
        ("风险情景", "如果基准走弱扩散到 Top20，强势结构可能失效。"),
        ("下一交易日观察", "观察 APP 是否维持排名上升，以及半导体下跌是否止住。"),
        ("免责声明", "本报告仅供研究参考，不构成投资建议。"),
    ]
    body = "\n\n".join(f"## {title}\n{text}" for title, text in sections)
    return body + "\n\n" + ("补充分析：" + "这是一段用于保证研报长度的趋势和证据链说明。" * 80)


def sample_brief() -> dict:
    return {
        "market": "us",
        "market_label": "美股",
        "benchmark_label": "QQQ",
        "as_of_date": "2026-07-01",
        "previous_date": "2026-06-30",
        "recent_dates": ["2026-06-25", "2026-06-26", "2026-06-29", "2026-06-30", "2026-07-01"],
        "window": 10,
        "benchmark": {
            "ticker": "QQQ",
            "rank": 66,
            "atr_score": 0.115,
            "price_vs_center_pct": 0.3,
            "price_change_3d_pct": 2.64,
        },
        "top20": [
            {"ticker": "PANW", "display": "PANW", "rank": 1, "daily_change_pct": 1.2, "rank_change": 0, "atr_score": 4.9, "stock_type": "网络安全", "sector": "Technology"},
            {"ticker": "VRTX", "display": "VRTX", "rank": 2, "daily_change_pct": -0.4, "rank_change": 1, "atr_score": 3.6, "stock_type": "医药医疗", "sector": "Healthcare"},
        ],
        "stable_top20": [
            {"ticker": "PANW", "display": "PANW", "rank": 1, "daily_change_pct": 1.2, "rank_change": 0, "atr_score": 4.9, "stock_type": "网络安全", "sector": "Technology"}
        ],
        "upward_moves": [
            {"ticker": "APP", "display": "APP", "rank": 16, "daily_change_pct": 9.58, "rank_change": 32, "atr_score": 2.1, "stock_type": "软件服务", "sector": "Technology"}
        ],
        "downward_moves": [
            {"ticker": "AMD", "display": "AMD", "rank": 44, "daily_change_pct": -6.89, "rank_change": -27, "atr_score": 0.2, "stock_type": "半导体", "sector": "Technology"}
        ],
        "entered_top20": [
            {"ticker": "APP", "display": "APP", "rank": 16, "daily_change_pct": 9.58, "rank_change": 32, "atr_score": 2.1, "stock_type": "软件服务", "sector": "Technology"}
        ],
        "dropped_top20": [
            {"ticker": "AMD", "display": "AMD", "rank": 44, "daily_change_pct": -6.89, "rank_change": -27, "atr_score": 0.2, "stock_type": "半导体", "sector": "Technology"}
        ],
        "type_stats": {
            "top20": [{"stock_type": "网络安全", "count": 1, "pct": 50.0}],
            "upward_moves": [{"stock_type": "软件服务", "count": 1, "pct": 100.0}],
            "downward_moves": [{"stock_type": "半导体", "count": 1, "pct": 100.0}],
            "stable_top20": [{"stock_type": "网络安全", "count": 1, "pct": 100.0}],
        },
        "technology_focus": {
            "count": 3,
            "top20_count": 1,
            "industry_distribution": [{"stock_type": "网络安全", "count": 1, "pct": 33.3}],
            "top10": [{"ticker": "PANW", "display": "PANW", "rank": 1, "daily_change_pct": 1.2, "rank_change": 0, "atr_score": 4.9, "stock_type": "网络安全", "sector": "Technology"}],
            "strong_up": [{"ticker": "APP", "display": "APP", "rank": 16, "daily_change_pct": 9.58, "rank_change": 32, "atr_score": 2.1, "stock_type": "软件服务", "sector": "Technology"}],
        },
        "summary_points": ["榜单换手较高。"],
        "rank_history": {},
    }


class DailyBriefLlmAnalysisTests(unittest.TestCase):
    def test_validate_brief_data_reports_duplicate_and_range_issues(self) -> None:
        brief = sample_brief()
        brief["top20"].append(dict(brief["top20"][0], daily_change_pct=999))

        result = llm_analysis.validate_brief_data(brief)

        codes = {issue["code"] for issue in result["issues"]}
        self.assertEqual(result["status"], "warning")
        self.assertIn("duplicate_ticker", codes)
        self.assertIn("number_out_of_range", codes)

    def test_extract_research_features_summarizes_turnover_and_subjects(self) -> None:
        features = llm_analysis.extract_research_features(sample_brief())

        self.assertEqual(features["market_state"]["benchmark_rank"], 66)
        self.assertEqual(features["turnover"]["entered_top20_count"], 1)
        self.assertEqual(features["turnover"]["top20_turnover_rate_pct"], 100.0)
        self.assertEqual(features["industry_strength"]["upward_leading_type"]["stock_type"], "软件服务")
        self.assertIn("large_up_count", features["anomalies"])
        self.assertTrue(any(item["ticker"] == "APP" for item in features["key_subjects"]))

    def test_build_research_context_exposes_questions_and_key_objects(self) -> None:
        brief = sample_brief()
        validation = llm_analysis.validate_brief_data(brief)
        features = llm_analysis.extract_research_features(brief)

        context = llm_analysis.build_research_context(brief, validation, features)

        self.assertEqual(context["data_facts"]["benchmark"]["rank"], 66)
        self.assertTrue(context["research_questions"])
        self.assertTrue(any(item["ticker"] == "APP" for item in context["key_objects"]))

    def test_load_tavily_keys_supports_numbered_pool_and_legacy_compatibility(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TAVILY_API_KEY2": "key-b",
                "TAVILY_API_KEY10": "key-d",
                "TAVILY_API_KEY1": "key-a",
                "TAVILY_API_KEYS": "key-c,key-a",
                "TAVILY_API_KEY": "key-e",
            },
            clear=True,
        ), patch("llm_analysis.load_dotenv"):
            self.assertEqual(llm_analysis.load_tavily_keys(), ["key-a", "key-b", "key-d", "key-c", "key-e"])
            self.assertEqual(llm_analysis.load_tavily_key(), "key-a")

    def test_tavily_key_pool_balances_usage_and_respects_monthly_limit(self) -> None:
        temporary_root = ROOT / ".tmp"
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as temporary_directory:
            usage_path = Path(temporary_directory) / "tavily_usage.json"
            with patch.dict(
                os.environ,
                {"TAVILY_MONTHLY_CREDITS": "10", "TAVILY_SEARCH_CREDITS": "5"},
                clear=False,
            ):
                llm_analysis.record_tavily_usage("key-a", credits=5, status="http_200", usage_path=usage_path)
                llm_analysis.record_tavily_usage("key-b", credits=10, status="http_200", usage_path=usage_path)
                ranked = llm_analysis.rank_tavily_keys(["key-a", "key-b", "key-c"], usage_path=usage_path)

            self.assertEqual([item["api_key"] for item in ranked], ["key-c", "key-a"])
            stored = json.loads(usage_path.read_text(encoding="utf-8"))
            self.assertNotIn("key-a", usage_path.read_text(encoding="utf-8"))
            period, _ = llm_analysis._tavily_period(datetime.now(), 1)
            self.assertEqual(stored["periods"][period]["keys"][llm_analysis._tavily_key_id("key-b")]["used_credits"], 10)

    def test_tavily_usage_cache_uses_configured_reset_day(self) -> None:
        temporary_root = ROOT / ".tmp"
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as temporary_directory:
            usage_path = Path(temporary_directory) / "tavily_usage.json"
            usage_path.write_text(json.dumps({"version": 2, "settings": {"reset_day": 15}, "periods": {}}), encoding="utf-8")
            before_reset = datetime(2026, 7, 14, 12, 0, 0)
            after_reset = datetime(2026, 7, 16, 9, 0, 0)

            llm_analysis.record_tavily_usage("key-a", credits=5, status="http_200", usage_path=usage_path, now=before_reset)
            stored = json.loads(usage_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["settings"]["reset_day"], 15)
            self.assertEqual(stored["periods"]["2026-06-15"]["resets_at"], "2026-07-15T00:00:00")

            ranked = llm_analysis.rank_tavily_keys(["key-a"], usage_path=usage_path, now=after_reset)
            self.assertEqual(ranked[0]["used_credits"], 0)

    def test_tavily_search_rotates_keys_and_records_credits(self) -> None:
        temporary_root = ROOT / ".tmp"
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as temporary_directory:
            usage_path = Path(temporary_directory) / "tavily_usage.json"
            response = Mock()
            response.status_code = 200
            response.json.return_value = {"results": [{"title": "result"}]}
            response.raise_for_status.return_value = None
            session = Mock()
            session.post.return_value = response
            with patch.dict(
                os.environ,
                {
                    "TAVILY_API_KEY1": "key-a",
                    "TAVILY_API_KEY2": "key-b",
                    "TAVILY_API_KEYS": "key-a,key-b",
                    "TAVILY_API_KEY": "",
                    "TAVILY_USAGE_FILE": str(usage_path),
                    "TAVILY_MONTHLY_CREDITS": "1000",
                    "TAVILY_SEARCH_CREDITS": "5",
                },
                clear=True,
            ), patch("llm_analysis.load_dotenv"), patch("llm_analysis.requests.Session", return_value=session):
                self.assertEqual(llm_analysis.tavily_search("first", max_results=5, timeout=10), [{"title": "result"}])
                self.assertEqual(llm_analysis.tavily_search("second", max_results=5, timeout=10), [{"title": "result"}])

            first_key = session.post.call_args_list[0].kwargs["json"]["api_key"]
            second_key = session.post.call_args_list[1].kwargs["json"]["api_key"]
            self.assertEqual([first_key, second_key], ["key-a", "key-b"])
            stored = json.loads(usage_path.read_text(encoding="utf-8"))
            period, _ = llm_analysis._tavily_period(datetime.now(), 1)
            period_keys = stored["periods"][period]["keys"]
            self.assertEqual(period_keys[llm_analysis._tavily_key_id("key-a")]["used_credits"], 5)
            self.assertEqual(period_keys[llm_analysis._tavily_key_id("key-b")]["used_credits"], 5)

    @patch("llm_analysis.tavily_search")
    def test_run_tavily_searches_normalizes_and_filters_results(self, tavily_search) -> None:
        tavily_search.return_value = [
            {
                "title": "Company update",
                "url": "https://investor.example.com/news",
                "published_date": "2026-06-30",
                "content": "Primary source content",
                "score": 0.9,
            },
            {
                "title": "Old update",
                "url": "https://news.example.com/old",
                "published_date": "2026-01-01",
                "content": "Too old",
                "score": 0.7,
            },
        ]
        plan = {"search_tasks": [{"query": "PANW news", "target": "PANW"}]}

        rows, stage = llm_analysis.run_tavily_searches(plan, sample_brief(), max_results=5, lookback_days=7, timeout=10)

        self.assertEqual(stage["status"], "ok")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_quality"], "primary")
        self.assertEqual(rows[0]["source_type"], "company")
        self.assertEqual(rows[0]["date_relation"], "before_as_of")

    def test_normalize_evidence_marks_late_items_as_follow_up(self) -> None:
        search_results = [
            {
                "title": "Late item",
                "url": "https://www.reuters.com/late",
                "source": "reuters.com",
                "source_quality": "mainstream",
                "source_type": "media",
                "published_at": "2026-07-02",
                "date_relation": "after_as_of",
                "snippet": "Late news",
                "target": "APP",
            }
        ]
        raw = [{"id": "1", "url": "https://www.reuters.com/late", "title": "Late item"}]

        evidence = llm_analysis.normalize_evidence(raw, search_results)

        self.assertFalse(evidence[0]["supports_json_signal"])
        self.assertEqual(evidence[0]["causality_strength"], "follow_up")
        self.assertEqual(evidence[0]["source_type"], "media")

    def test_prefilter_search_results_tiers_candidates(self) -> None:
        brief = sample_brief()
        rows = [
            {
                "title": "APP earnings guidance",
                "url": "https://www.reuters.com/app",
                "source": "reuters.com",
                "source_quality": "mainstream",
                "source_type": "media",
                "published_at": "2026-07-01",
                "date_relation": "same_day",
                "snippet": "APP earnings guidance update",
                "target": "APP",
                "query": "APP earnings guidance",
                "score": 0.9,
            },
            {
                "title": "Old semiconductor background",
                "url": "https://www.reuters.com/old",
                "source": "reuters.com",
                "source_quality": "mainstream",
                "source_type": "media",
                "published_at": "2026-06-15",
                "date_relation": "before_as_of",
                "snippet": "Semiconductor policy background",
                "target": "AMD",
                "query": "AMD semiconductor policy",
                "score": 0.7,
            },
            {
                "title": "Ticker blog",
                "url": "https://blog.example.com/app",
                "source": "blog.example.com",
                "source_quality": "other",
                "source_type": "other",
                "published_at": "2026-07-01",
                "date_relation": "same_day",
                "snippet": "APP stock rumor",
                "target": "APP",
                "query": "APP stock",
                "score": 0.8,
            },
            {
                "title": "Future APP item",
                "url": "https://www.reuters.com/future",
                "source": "reuters.com",
                "source_quality": "mainstream",
                "source_type": "media",
                "published_at": "2026-07-02",
                "date_relation": "after_as_of",
                "snippet": "APP future item",
                "target": "APP",
                "query": "APP news",
                "score": 0.9,
            },
        ]

        buckets, stage = llm_analysis.prefilter_search_results(rows, brief)

        self.assertEqual(stage["status"], "ok")
        self.assertTrue(any(item["url"] == "https://www.reuters.com/app" for item in buckets["core_evidence"]))
        self.assertTrue(any(item["url"] == "https://www.reuters.com/old" for item in buckets["background_evidence"]))
        self.assertTrue(any(item["url"] == "https://blog.example.com/app" for item in buckets["watchlist_evidence"]))
        self.assertTrue(any(item["url"] == "https://www.reuters.com/future" for item in buckets["rejected_evidence"]))
        self.assertFalse(any(item["url"] == "https://www.reuters.com/future" for item in buckets["candidate_evidence"]))

    def test_normalize_evidence_does_not_upgrade_other_source_to_core(self) -> None:
        search_results = [
            {
                "title": "Blog item",
                "url": "https://blog.example.com/app",
                "source": "blog.example.com",
                "source_quality": "other",
                "source_type": "other",
                "published_at": "2026-07-01",
                "date_relation": "same_day",
                "snippet": "Blog item",
                "evidence_tier": "watchlist_evidence",
                "can_support_core_driver": False,
            }
        ]
        raw = [
            {
                "url": "https://blog.example.com/app",
                "source_quality": "other",
                "evidence_tier": "core_evidence",
                "can_support_core_driver": True,
                "causality_strength": "strong",
            }
        ]

        evidence = llm_analysis.normalize_evidence(raw, search_results)

        self.assertEqual(evidence[0]["evidence_tier"], "watchlist_evidence")
        self.assertFalse(evidence[0]["can_support_core_driver"])

    def test_normalize_evidence_does_not_upgrade_background_source_to_core(self) -> None:
        search_results = [
            {
                "title": "Reuters item",
                "url": "https://www.reuters.com/markets/story/",
                "source": "reuters.com",
                "source_quality": "mainstream",
                "source_type": "media",
                "published_at": "2026-07-14",
                "date_relation": "same_day",
                "snippet": "Market context",
                "evidence_tier": "background_evidence",
                "can_support_core_driver": False,
            }
        ]
        raw = [
            {
                "url": "https://reuters.com/markets/story",
                "source_quality": "mainstream",
                "evidence_tier": "core_evidence",
                "can_support_core_driver": True,
                "causality_strength": "strong",
            }
        ]

        evidence = llm_analysis.normalize_evidence(raw, search_results)

        self.assertEqual(evidence[0]["evidence_tier"], "background_evidence")
        self.assertFalse(evidence[0]["can_support_core_driver"])

    def test_normalize_evidence_treats_unknown_source_as_watchlist(self) -> None:
        raw = [
            {
                "url": "https://www.reuters.com/markets/unknown",
                "source_quality": "mainstream",
                "evidence_tier": "core_evidence",
                "can_support_core_driver": True,
                "causality_strength": "strong",
            }
        ]

        evidence = llm_analysis.normalize_evidence(raw, [])

        self.assertEqual(evidence[0]["evidence_tier"], "watchlist_evidence")
        self.assertFalse(evidence[0]["can_support_core_driver"])

    def test_normalize_evidence_keeps_up_to_24_items(self) -> None:
        search_results = [
            {
                "title": f"Item {index}",
                "url": f"https://www.reuters.com/item-{index}",
                "source": "reuters.com",
                "source_quality": "mainstream",
                "source_type": "media",
                "published_at": "2026-07-01",
                "snippet": "News",
            }
            for index in range(30)
        ]
        raw = [{"url": item["url"], "title": item["title"]} for item in search_results]

        evidence = llm_analysis.normalize_evidence(raw, search_results)

        self.assertEqual(len(evidence), 24)

    def test_parse_json_strips_think_blocks(self) -> None:
        result = llm_analysis.parse_json_text('<think>推理过程</think>```json\n{"ok": true}\n```')

        self.assertEqual(result, {"ok": True})

    @patch("llm_analysis.call_chat_model")
    def test_parse_or_repair_json_uses_chat_repair(self, call_chat_model) -> None:
        call_chat_model.return_value = ('{"fixed": true}', "deepseek", "deepseek-chat")

        result, repaired = llm_analysis.parse_or_repair_json_text('{"fixed": tru', timeout=10)

        self.assertTrue(repaired)
        self.assertEqual(result, {"fixed": True})
        self.assertEqual(call_chat_model.call_args.args[1], llm_analysis.DEFAULT_DEEPSEEK_MODEL)

    def test_report_quality_flags_short_or_missing_sections(self) -> None:
        issues = llm_analysis.report_quality_issues("## 核心结论\n太短")

        self.assertTrue(any(item.startswith("full_report_too_short") for item in issues))
        self.assertTrue(any(item.startswith("missing_sections") for item in issues))

    def test_normalize_executive_points_limits_and_falls_back(self) -> None:
        raw = {
            "executive_points": [
                {"text": f"核心结论 {index}", "rationale": "来自研报", "evidence_ids": [index], "priority": 7 - index}
                for index in range(8)
            ]
        }

        points = llm_analysis.normalize_executive_points(raw, sample_brief())
        fallback = llm_analysis.normalize_executive_points([], sample_brief())

        self.assertEqual(len(points), 6)
        self.assertEqual(points[0]["priority"], 1)
        self.assertEqual(points[0]["evidence_ids"], ["6"])
        self.assertEqual(fallback[0]["text"], "榜单换手较高。")

    @patch("llm_analysis.tavily_search")
    @patch("llm_analysis.call_chat_model")
    def test_generate_model_interpretation_returns_full_schema(self, call_chat_model, tavily_search) -> None:
        call_chat_model.side_effect = [
            (json.dumps({"research_questions": ["why APP"], "search_tasks": [{"query": f"APP stock news {i}", "target": "APP", "reason": "mover", "priority": 1} for i in range(12)]}), "deepseek", "deepseek-v4-pro"),
            (json.dumps({"evidence": [{"id": "1", "title": "APP update", "title_zh": "APP 股价异动更新", "summary_zh": "该来源用于解释 APP 当日异动。", "url": "https://www.reuters.com/app", "source": "reuters.com", "published_at": "2026-07-01", "snippet": "APP news", "relevance": "解释异动", "used_by": ["APP"]}]}), "deepseek", "deepseek-chat"),
            (json.dumps({"summary": "摘要：APP 异动值得关注 [1]", "full_report": complete_markdown_report()}), "deepseek", "deepseek-v4-pro"),
            (json.dumps({"status": "ok", "issues": [], "final_notes": "审计通过"}), "deepseek", "deepseek-chat"),
            (json.dumps({"executive_points": [{"text": "APP 异动是今日最重要观察。", "rationale": "研报把 APP 列为关键对象。", "evidence_ids": ["1"], "priority": 1}]}), "deepseek", "deepseek-chat"),
        ]
        tavily_search.return_value = [
            {"title": "APP update", "url": "https://www.reuters.com/app", "published_date": "2026-07-01", "content": "APP news", "score": 0.9}
        ]

        result = llm_analysis.generate_model_interpretation(sample_brief(), timeout=10)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["text"], result["summary"])
        self.assertIn("full_report", result)
        self.assertIn("report", result)
        self.assertIn("research_context", result)
        self.assertEqual(len(result["research_plan"]["search_tasks"]), 8)
        self.assertEqual(result["evidence"][0]["id"], "1")
        self.assertEqual(result["evidence"][0]["title_zh"], "APP 股价异动更新")
        self.assertEqual(result["evidence"][0]["summary_zh"], "该来源用于解释 APP 当日异动。")
        self.assertIn("causality_strength", result["evidence"][0])
        self.assertEqual(result["audit"]["status"], "ok")
        self.assertEqual(result["executive_points"][0]["text"], "APP 异动是今日最重要观察。")
        self.assertEqual(result["executive_points"][0]["evidence_ids"], ["1"])
        self.assertTrue(result["pipeline"]["stages"])
        self.assertEqual(call_chat_model.call_args_list[0].args[1], llm_analysis.DEFAULT_DEEPSEEK_PRO_MODEL)
        self.assertEqual(call_chat_model.call_args_list[1].args[1], llm_analysis.DEFAULT_DEEPSEEK_PRO_MODEL)
        self.assertEqual(call_chat_model.call_args_list[2].args[1], llm_analysis.DEFAULT_DEEPSEEK_PRO_MODEL)
        self.assertEqual(call_chat_model.call_args_list[3].args[1], llm_analysis.DEFAULT_DEEPSEEK_MODEL)
        self.assertEqual(call_chat_model.call_args_list[4].args[1], llm_analysis.DEFAULT_DEEPSEEK_MODEL)

    @patch("llm_analysis.tavily_search", side_effect=RuntimeError("network blocked"))
    @patch("llm_analysis.call_chat_model")
    def test_generate_model_interpretation_partial_when_search_fails(self, call_chat_model, _tavily_search) -> None:
        call_chat_model.side_effect = [
            (json.dumps({"research_questions": [], "search_tasks": [{"query": "APP stock news", "target": "APP"}]}), "deepseek", "deepseek-chat"),
            (json.dumps({"summary": "量化摘要", "full_report": complete_markdown_report()}), "deepseek", "deepseek-chat"),
            (json.dumps({"status": "warning", "issues": [{"type": "source_quality", "severity": "medium", "message": "缺少联网证据"}], "final_notes": "需人工复核"}), "deepseek", "deepseek-chat"),
            (json.dumps({"executive_points": [{"text": "缺少联网证据，结论仅供观察。", "rationale": "搜索失败。", "priority": 1}]}), "deepseek", "deepseek-chat"),
        ]

        result = llm_analysis.generate_model_interpretation(sample_brief(), timeout=10)

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["summary"], "量化摘要")
        self.assertEqual(result["executive_points"][0]["text"], "缺少联网证据，结论仅供观察。")
        self.assertTrue(result["pipeline"]["errors"])

    @patch("llm_analysis.tavily_search")
    @patch("llm_analysis.call_chat_model")
    def test_generate_model_interpretation_falls_back_when_executive_points_fail(self, call_chat_model, tavily_search) -> None:
        call_chat_model.side_effect = [
            (json.dumps({"research_questions": [], "search_tasks": []}), "deepseek", "deepseek-v4-pro"),
            (json.dumps({"summary": "量化摘要", "full_report": complete_markdown_report()}), "deepseek", "deepseek-v4-pro"),
            (json.dumps({"status": "ok", "issues": [], "final_notes": "审计通过"}), "deepseek", "deepseek-chat"),
            RuntimeError("executive unavailable"),
        ]
        tavily_search.return_value = []

        result = llm_analysis.generate_model_interpretation(sample_brief(), timeout=10)

        self.assertNotEqual(result["status"], "error")
        self.assertEqual(result["executive_points"][0]["text"], "榜单换手较高。")
        self.assertTrue(any(stage.get("stage") == "executive_points" and stage.get("status") == "error" for stage in result["pipeline"]["stages"]))

    def test_html_template_contains_citation_popover_and_executive_points_logic(self) -> None:
        brief = sample_brief()
        brief["model_interpretation"] = {
            "summary": "摘要",
            "text": "摘要",
            "full_report": "## 核心结论\nAPP 值得观察 [1]",
            "executive_points": [{"text": "模型结论优先展示", "rationale": "来自研报", "evidence_ids": ["1"], "priority": 1}],
            "evidence": [{"id": "1", "title_zh": "APP 新闻", "url": "https://www.reuters.com/app", "summary_zh": "APP 摘要"}],
            "audit": {"status": "warning", "issues": [{"type": "source_quality", "severity": "medium", "message": "关注 [1] 来源质量"}], "final_notes": "需复核"},
        }

        html = interactive_daily_brief.generate_html(brief, "light")

        self.assertIn('id="citationPopover"', html)
        self.assertIn("data-citation-id", html)
        self.assertIn("executive_points", html)
        self.assertIn("定位引用卡", html)


if __name__ == "__main__":
    unittest.main()
