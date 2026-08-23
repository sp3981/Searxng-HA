"""llm.py：LLM 工具装配、调用约定兼容与错误处理单元测试。"""

import unittest

import stubs  # noqa: F401  在导入组件前安装 Home Assistant 桩
from stubs import (
    BrokenSession,
    ConfigEntry,
    FakeResponse,
    FakeSession,
    LLMContext,
    ToolError,
    set_session,
)

from custom_components.searxng_llm import llm as component_llm
from custom_components.searxng_llm.const import (
    CONF_BASE_URL,
    CONF_FETCH_COUNT,
    CONF_FETCH_PARALLEL,
    CONF_FETCH_TIMEOUT,
    CONF_LANGUAGE,
    CONF_RESULTS,
    CONF_TIMEOUT,
    TOOL_NAME,
)


def _make_api(data=None):
    """构造一个带默认配置的 SearxngAPI 并注册。"""
    entry = ConfigEntry()
    entry.data = {
        CONF_BASE_URL: "https://searx.example.com",
        CONF_RESULTS: 3,
        CONF_TIMEOUT: 10,
        CONF_LANGUAGE: "auto",
        CONF_FETCH_COUNT: 0,
        "username": "",
        "password": "",
    }
    if data:
        entry.data.update(data)
    api = component_llm.SearxngAPI(None, entry)
    api.async_register()
    return api


class SearxngLLMTests(unittest.IsolatedAsyncioTestCase):
    """SearxngAPI / SearxngAPIInstance 的行为。"""

    async def test_registers_and_exposes_tool(self):
        """注册后能通过 async_get_tools 拿到「搜索」工具。"""
        api = _make_api()
        instance = await api.async_get_api_instance(LLMContext())
        tools = await instance.async_get_tools()
        self.assertEqual(len(tools), 1)
        tool = tools[0]
        self.assertEqual(tool.name, TOOL_NAME)
        self.assertIn("SearXNG", tool.description)
        self.assertIn("query", tool.parameters.schema)

    async def test_new_style_call_returns_results(self):
        """新调用约定 llm_func(tool_input) 返回结构化结果。"""
        payload = {"results": [{"title": "结果", "url": "https://x", "content": "摘要"}]}
        set_session(FakeSession(FakeResponse(200, payload)))
        api = _make_api()
        instance = await api.async_get_api_instance(LLMContext())
        tool = (await instance.async_get_tools())[0]
        result = await tool.llm_func({"query": "今天的天气"})
        self.assertEqual(result.serialized_result["query"], "今天的天气")
        self.assertEqual(result.serialized_result["results"][0]["title"], "结果")

    async def test_legacy_style_call_ignores_call_id(self):
        """旧调用约定 llm_func(call_id, tool_input) 同样可用。"""
        set_session(FakeSession(FakeResponse(200, {"results": []})))
        api = _make_api()
        instance = await api.async_get_api_instance(LLMContext())
        tool = (await instance.async_get_tools())[0]
        result = await tool.llm_func("call-id-123", {"query": "新闻"})
        self.assertEqual(result.serialized_result["query"], "新闻")
        self.assertEqual(result.serialized_result["results"], [])
        self.assertIn("没有返回", result.serialized_result["message"])

    async def test_configured_language_passed_to_search(self):
        """集成配置的搜索语言传给 SearXNG language 参数。"""
        session = FakeSession(FakeResponse(200, {"results": []}))
        set_session(session)
        api = _make_api({CONF_LANGUAGE: "zh-CN"})
        instance = await api.async_get_api_instance(LLMContext())
        tool = (await instance.async_get_tools())[0]
        await tool.llm_func({"query": "天气"})
        self.assertEqual(session.calls[0][1]["params"]["language"], "zh-CN")

    async def test_fetch_content_attached_when_enabled(self):
        """fetch_count>0 时并行抓取前 N 条网页正文。"""
        html_page = "<html><body><p>网页正文内容。</p></body></html>"
        session = FakeSession(
            [
                FakeResponse(
                    200,
                    {
                        "results": [
                            {"title": "甲", "url": "https://a.example", "content": "摘要1"},
                            {"title": "乙", "url": "https://b.example", "content": "摘要2"},
                        ]
                    },
                ),
                FakeResponse(200, html_page, "text/html"),
                FakeResponse(200, html_page, "text/html"),
            ]
        )
        set_session(session)
        api = _make_api(
            {
                CONF_FETCH_COUNT: 2,
                CONF_FETCH_PARALLEL: 2,
                CONF_FETCH_TIMEOUT: 10,
            }
        )
        instance = await api.async_get_api_instance(LLMContext())
        tool = (await instance.async_get_tools())[0]
        result = await tool.llm_func({"query": "天气"})
        items = result.serialized_result["results"]
        self.assertEqual(items[0]["fetched_content"], "网页正文内容。")
        self.assertEqual(items[1]["fetched_content"], "网页正文内容。")
        self.assertEqual(len(session.calls), 3)

    async def test_fetch_failure_attaches_error_without_crashing(self):
        """单条抓取失败写入 fetch_error，搜索本身不失败。"""
        session = FakeSession(
            [
                FakeResponse(
                    200,
                    {"results": [{"title": "甲", "url": "https://a.example", "content": "x"}]},
                ),
                FakeResponse(403, "Forbidden", "text/html"),
            ]
        )
        set_session(session)
        api = _make_api({CONF_FETCH_COUNT: 1, CONF_FETCH_PARALLEL: 1, CONF_FETCH_TIMEOUT: 10})
        instance = await api.async_get_api_instance(LLMContext())
        tool = (await instance.async_get_tools())[0]
        result = await tool.llm_func({"query": "天气"})
        self.assertIn("fetch_error", result.serialized_result["results"][0])

    async def test_connection_failure_raises_tool_error_in_chinese(self):
        """SearXNG 不可用时抛 ToolError，给出中文提示（系统不崩溃）。"""
        set_session(BrokenSession())
        api = _make_api()
        instance = await api.async_get_api_instance(LLMContext())
        tool = (await instance.async_get_tools())[0]
        with self.assertRaises(ToolError) as ctx:
            await tool.llm_func({"query": "新闻"})
        self.assertIn("无法连接", str(ctx.exception))

    async def test_json_disabled_raises_tool_error(self):
        """未启用 JSON 输出时给出针对性中文提示。"""
        set_session(FakeSession(FakeResponse(403, "Search format not supported", "text/html")))
        api = _make_api()
        instance = await api.async_get_api_instance(LLMContext())
        tool = (await instance.async_get_tools())[0]
        with self.assertRaises(ToolError) as ctx:
            await tool.llm_func({"query": "新闻"})
        self.assertIn("json", str(ctx.exception).lower())

    async def test_empty_query_raises_tool_error(self):
        """空关键词抛出友好错误。"""
        set_session(FakeSession(FakeResponse()))
        api = _make_api()
        instance = await api.async_get_api_instance(LLMContext())
        tool = (await instance.async_get_tools())[0]
        with self.assertRaises(ToolError) as ctx:
            await tool.llm_func({"query": "   "})
        self.assertIn("关键词", str(ctx.exception))

    async def test_missing_base_url_raises_tool_error(self):
        """未配置地址时抛出友好错误。"""
        set_session(FakeSession(FakeResponse()))
        api = _make_api({CONF_BASE_URL: ""})
        instance = await api.async_get_api_instance(LLMContext())
        tool = (await instance.async_get_tools())[0]
        with self.assertRaises(ToolError) as ctx:
            await tool.llm_func({"query": "新闻"})
        self.assertIn("地址", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
