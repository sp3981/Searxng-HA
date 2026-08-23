"""tool.py：SearXNG JSON 客户端单元测试。"""

import asyncio
import base64
import unittest

import stubs  # noqa: F401  在导入组件前安装 Home Assistant 桩
from stubs import BrokenSession, FakeResponse, FakeSession

from custom_components.searxng_llm.const import (
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_AUTH,
    ERROR_INVALID_RESPONSE,
    ERROR_JSON_DISABLED,
)
from custom_components.searxng_llm.tool import SearxngError, search


class ToolSearchTests(unittest.IsolatedAsyncioTestCase):
    """search() 的成功与错误路径。"""

    async def test_search_returns_mapped_and_sliced_results(self):
        """成功：取前 N 条并映射为 title/url/content。"""
        payload = {
            "results": [
                {"title": "甲", "url": "https://a.example", "content": "内容1"},
                {"title": "乙", "url": "https://b.example", "content": "内容2"},
                {"title": "丙", "url": "https://c.example", "content": "内容3"},
            ]
        }
        session = FakeSession(FakeResponse(200, payload))
        items = await search(session, "https://searx.example.com/", "天气", results=2)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0], {"title": "甲", "url": "https://a.example", "content": "内容1"})
        url, kwargs = session.calls[0]
        self.assertEqual(url, "https://searx.example.com/search")
        self.assertEqual(kwargs["params"], {"q": "天气", "format": "json"})

    async def test_basic_auth_when_credentials_given(self):
        """提供了用户名/密码时发送 HTTP Basic 认证头。"""
        session = FakeSession(FakeResponse())
        await search(session, "https://s.example", "q", username="user", password="pw")
        auth = session.calls[0][1]["headers"]["Authorization"]
        self.assertTrue(auth.startswith("Basic "))
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        self.assertEqual(decoded, "user:pw")

    async def test_no_auth_without_credentials(self):
        """未提供凭据时不发送认证头。"""
        session = FakeSession(FakeResponse())
        await search(session, "https://s.example", "q")
        self.assertNotIn("Authorization", session.calls[0][1]["headers"])

    async def test_empty_results(self):
        """零结果返回空列表。"""
        session = FakeSession(FakeResponse(200, {"results": []}))
        self.assertEqual(await search(session, "https://s.example", "q"), [])

    async def test_search_captures_unresponsive_engines_in_meta(self):
        """meta 字典接收 unresponsive_engines 等诊断信息。"""
        payload = {
            "results": [],
            "unresponsive_engines": [["google", "验证码"], ["baidu", "超时"]],
            "number_of_results": 0,
        }
        session = FakeSession(FakeResponse(200, payload))
        meta: dict = {}
        items = await search(session, "https://s.example", "q", meta=meta)
        self.assertEqual(items, [])
        self.assertEqual(meta["unresponsive_engines"], payload["unresponsive_engines"])
        self.assertEqual(meta["number_of_results"], 0)

    async def test_401_maps_to_invalid_auth(self):
        """HTTP 401 → invalid_auth，中文提示。"""
        session = FakeSession(FakeResponse(401, "Unauthorized", "text/html"))
        with self.assertRaises(SearxngError) as ctx:
            await search(session, "https://s.example", "q")
        self.assertEqual(ctx.exception.code, ERROR_INVALID_AUTH)
        self.assertIn("认证失败", str(ctx.exception))

    async def test_403_html_means_json_disabled(self):
        """HTTP 403 + HTML（SearXNG 未启用 JSON 的典型表现）→ json_format_disabled。"""
        session = FakeSession(FakeResponse(403, "Search format not supported", "text/html"))
        with self.assertRaises(SearxngError) as ctx:
            await search(session, "https://s.example", "q")
        self.assertEqual(ctx.exception.code, ERROR_JSON_DISABLED)
        self.assertIn("json", str(ctx.exception))

    async def test_404_maps_to_invalid_response(self):
        """其它 4xx/5xx → invalid_response。"""
        session = FakeSession(FakeResponse(404, "Not Found", "text/html"))
        with self.assertRaises(SearxngError) as ctx:
            await search(session, "https://s.example", "q")
        self.assertEqual(ctx.exception.code, ERROR_INVALID_RESPONSE)

    async def test_connection_error(self):
        """连接错误 → cannot_connect。"""
        with self.assertRaises(SearxngError) as ctx:
            await search(BrokenSession(), "https://s.example", "q")
        self.assertEqual(ctx.exception.code, ERROR_CANNOT_CONNECT)
        self.assertIn("无法连接", str(ctx.exception))

    async def test_timeout(self):
        """超时 → cannot_connect。"""
        session = FakeSession(FakeResponse(enter_error=asyncio.TimeoutError()))
        with self.assertRaises(SearxngError) as ctx:
            await search(session, "https://s.example", "q")
        self.assertEqual(ctx.exception.code, ERROR_CANNOT_CONNECT)
        self.assertIn("超时", str(ctx.exception))

    async def test_non_json_response(self):
        """返回 HTML → json_format_disabled。"""
        session = FakeSession(FakeResponse(200, "<html>...</html>", "text/html"))
        with self.assertRaises(SearxngError) as ctx:
            await search(session, "https://s.example", "q")
        self.assertEqual(ctx.exception.code, ERROR_JSON_DISABLED)

    async def test_missing_results_field(self):
        """缺少 results 字段 → invalid_response。"""
        session = FakeSession(FakeResponse(200, {"foo": "bar"}))
        with self.assertRaises(SearxngError) as ctx:
            await search(session, "https://s.example", "q")
        self.assertEqual(ctx.exception.code, ERROR_INVALID_RESPONSE)


if __name__ == "__main__":
    unittest.main()
