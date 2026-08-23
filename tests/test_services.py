"""__init__.py：searxng_llm.search / searxng_llm.fetch 服务单元测试。"""

from __future__ import annotations

import types
import unittest

import importlib

import stubs  # noqa: F401  在导入组件前安装 Home Assistant 桩
from stubs import ConfigEntry, FakeResponse, FakeSession, ServiceCall, set_session

component_init = importlib.import_module("custom_components.searxng_llm")
from custom_components.searxng_llm.const import (
    CONF_BASE_URL,
    CONF_FETCH_COUNT,
    CONF_RESULTS,
    CONF_TIMEOUT,
    DOMAIN,
)

from homeassistant.exceptions import HomeAssistantError


class _FakeHass:
    """带 config_entries 与 data 的最小 hass 桩。"""

    def __init__(self, entries=None) -> None:
        self._entries = entries or []
        self.data: dict = {}
        self.config_entries = types.SimpleNamespace(
            async_entries=lambda domain: [e for e in self._entries if domain == DOMAIN]
        )


def _entry() -> ConfigEntry:
    """构造带默认配置（不抓取）的 ConfigEntry。"""
    entry = ConfigEntry()
    entry.data = {
        CONF_BASE_URL: "https://searx.example.com",
        CONF_RESULTS: 3,
        CONF_TIMEOUT: 10,
        "language": "auto",
        CONF_FETCH_COUNT: 0,
    }
    return entry


class SearchServiceTests(unittest.IsolatedAsyncioTestCase):
    """_handle_search 服务行为。"""

    async def test_single_query_returns_results(self):
        """单个 query：保持与既有调用方兼容的返回结构。"""
        session = FakeSession(
            FakeResponse(200, {"results": [{"title": "甲", "url": "https://a", "content": "c"}]})
        )
        set_session(session)
        call = ServiceCall(_FakeHass([_entry()]), {"query": "天气"})
        call.return_response = True
        result = await component_init._handle_search(call)
        self.assertEqual(result["query"], "天气")
        self.assertEqual(result["results"][0]["title"], "甲")

    async def test_parallel_queries_merged_and_grouped(self):
        """query 列表：并行搜索并按 URL 合并去重，附 searches 明细。"""
        session = FakeSession(
            [
                FakeResponse(200, {"results": [{"title": "甲", "url": "https://a", "content": "1"}]}),
                FakeResponse(200, {"results": [{"title": "乙", "url": "https://b", "content": "2"}]}),
            ]
        )
        set_session(session)
        call = ServiceCall(_FakeHass([_entry()]), {"query": ["天气", "新闻"]})
        call.return_response = True
        result = await component_init._handle_search(call)
        self.assertEqual(result["query"], ["天气", "新闻"])
        self.assertEqual(len(result["searches"]), 2)
        self.assertEqual([i["url"] for i in result["results"]], ["https://a", "https://b"])
        self.assertEqual(len(session.calls), 2)

    async def test_parallel_queries_deduplicates_by_url(self):
        """相同 URL 的结果合并后只保留一条。"""
        payload = {"results": [{"title": "甲", "url": "https://a", "content": "1"}]}
        session = FakeSession([FakeResponse(200, payload), FakeResponse(200, payload)])
        set_session(session)
        call = ServiceCall(_FakeHass([_entry()]), {"query": ["天气", "新闻"]})
        call.return_response = True
        result = await component_init._handle_search(call)
        self.assertEqual(len(result["results"]), 1)

    async def test_empty_query_raises(self):
        """空关键词抛中文 HomeAssistantError。"""
        call = ServiceCall(_FakeHass(), {"query": "   "})
        call.return_response = True
        with self.assertRaises(HomeAssistantError) as ctx:
            await component_init._handle_search(call)
        self.assertIn("query", str(ctx.exception))

    async def test_language_override_passed_through(self):
        """服务级 language 覆盖集成配置。"""
        session = FakeSession(FakeResponse(200, {"results": []}))
        set_session(session)
        call = ServiceCall(_FakeHass([_entry()]), {"query": "天气", "language": "zh"})
        call.return_response = True
        result = await component_init._handle_search(call)
        self.assertEqual(session.calls[0][1]["params"]["language"], "zh")
        self.assertEqual(result["results"], [])
        self.assertIn("message", result)

    async def test_no_response_requested_returns_none(self):
        """未要求响应时返回 None。"""
        set_session(FakeSession(FakeResponse(200, {"results": []})))
        call = ServiceCall(_FakeHass([_entry()]), {"query": "天气"})
        call.return_response = False
        self.assertIsNone(await component_init._handle_search(call))


class FetchServiceTests(unittest.IsolatedAsyncioTestCase):
    """_handle_fetch 服务行为（AI 智能抓取）。"""

    async def test_single_url_returns_content(self):
        """单个 url：返回抓取后的正文。"""
        session = FakeSession(
            FakeResponse(
                200,
                "<html><body><p>正文内容。</p></body></html>",
                "text/html",
            )
        )
        set_session(session)
        call = ServiceCall(_FakeHass([_entry()]), {"url": "https://a.example/article"})
        call.return_response = True
        result = await component_init._handle_fetch(call)
        self.assertEqual(result["urls"], ["https://a.example/article"])
        self.assertEqual(result["results"][0]["content"], "正文内容。")

    async def test_parallel_urls_fetched(self):
        """url 列表：并行抓取多个网页。"""
        session = FakeSession(
            [
                FakeResponse(200, "<html><body><p>甲。</p></body></html>", "text/html"),
                FakeResponse(200, "<html><body><p>乙。</p></body></html>", "text/html"),
            ]
        )
        set_session(session)
        call = ServiceCall(
            _FakeHass([_entry()]), {"url": ["https://a.example/1", "https://b.example/2"]}
        )
        call.return_response = True
        result = await component_init._handle_fetch(call)
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(
            {i["url"] for i in result["results"]},
            {"https://a.example/1", "https://b.example/2"},
        )
        self.assertEqual(len(session.calls), 2)

    async def test_fetch_failure_returns_error_field(self):
        """抓取失败返回 error 字段，不抛异常。"""
        set_session(FakeSession(FakeResponse(403, "Forbidden", "text/html")))
        call = ServiceCall(_FakeHass([_entry()]), {"url": "https://a.example/1"})
        call.return_response = True
        result = await component_init._handle_fetch(call)
        self.assertIn("error", result["results"][0])

    async def test_empty_url_raises(self):
        """空地址抛中文 HomeAssistantError。"""
        call = ServiceCall(_FakeHass(), {"url": "   "})
        call.return_response = True
        with self.assertRaises(HomeAssistantError) as ctx:
            await component_init._handle_fetch(call)
        self.assertIn("网页地址", str(ctx.exception))

    async def test_no_response_requested_returns_none(self):
        """未要求响应时返回 None。"""
        set_session(
            FakeSession(
                FakeResponse(
                    200,
                    "<html><body><p>正文。</p></body></html>",
                    "text/html",
                )
            )
        )
        call = ServiceCall(_FakeHass([_entry()]), {"url": "https://a.example/1"})
        call.return_response = False
        self.assertIsNone(await component_init._handle_fetch(call))


if __name__ == "__main__":
    unittest.main()
