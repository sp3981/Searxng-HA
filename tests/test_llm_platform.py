"""llm.py 新架构（HA 2026.8+ LLM 平台协议）的单元测试。

通过向 components.llm 桩临时注入 LLMTools 并重载模块，验证平台函数
async_get_tools 与新形态 SearxngSearchTool.async_call 的行为；
测试结束后恢复经典架构，避免影响其他用例。
"""

from __future__ import annotations

import importlib
import sys
import types
import unittest

import stubs  # noqa: F401  在导入组件前安装 Home Assistant 桩
from stubs import (
    BrokenSession,
    ConfigEntry,
    FakeResponse,
    FakeSession,
    NewStyleLLMContext,
    NewStyleToolInput,
    set_session,
)

from custom_components.searxng_llm.const import (
    CONF_BASE_URL,
    CONF_LANGUAGE,
    CONF_RESULTS,
    CONF_TIMEOUT,
    DOMAIN,
    TOOL_NAME,
)


class _LLMTools:
    """homeassistant.components.llm.LLMTools 桩。"""

    def __init__(self, tools, prompt=None) -> None:
        self.tools = tools
        self.prompt = prompt


class _FakeHass:
    """带 config_entries 的最小 hass 桩。"""

    def __init__(self, entries=None) -> None:
        self._entries = entries or []
        self.config_entries = types.SimpleNamespace(
            async_entries=lambda domain: [e for e in self._entries if domain == DOMAIN]
        )


def _entry_with_base_url(base_url: str) -> ConfigEntry:
    """构造带默认配置的 ConfigEntry。"""
    entry = ConfigEntry()
    entry.data = {
        CONF_BASE_URL: base_url,
        CONF_RESULTS: 3,
        CONF_TIMEOUT: 10,
        CONF_LANGUAGE: "auto",
        "username": "",
        "password": "",
    }
    return entry


class SearxngPlatformTests(unittest.IsolatedAsyncioTestCase):
    """新架构 LLM 平台函数与工具行为。"""

    @classmethod
    def setUpClass(cls) -> None:
        """注入 LLMTools 标记并重载组件模块，切换到新架构分支。"""
        cls._llm_stub = sys.modules["homeassistant.components.llm"]
        cls._llm_stub.LLMTools = _LLMTools
        cls.module = importlib.reload(
            importlib.import_module("custom_components.searxng_llm.llm")
        )

    @classmethod
    def tearDownClass(cls) -> None:
        """移除标记并重载，恢复经典架构供其他用例使用。"""
        del cls._llm_stub.LLMTools
        importlib.reload(importlib.import_module("custom_components.searxng_llm.llm"))
        restored = importlib.import_module("custom_components.searxng_llm.llm")
        assert not restored.NEW_STYLE
        assert hasattr(restored, "SearxngAPI")

    def test_platform_returns_none_when_unconfigured(self):
        """没有配置条目时平台不暴露工具。"""
        self.assertIsNone(self.module.async_get_tools(_FakeHass(), None, "assist"))

    def test_platform_returns_none_when_base_url_missing(self):
        """条目未填写地址时平台不暴露工具。"""
        entry = _entry_with_base_url("")
        self.assertIsNone(
            self.module.async_get_tools(_FakeHass([entry]), None, "assist")
        )

    def test_platform_exposes_tool_when_configured(self):
        """配置完成后平台返回带搜索工具的 LLMTools。"""
        entry = _entry_with_base_url("https://searx.example.com")
        tools = self.module.async_get_tools(_FakeHass([entry]), None, "assist")
        self.assertIsNotNone(tools)
        self.assertEqual(len(tools.tools), 1)
        tool = tools.tools[0]
        self.assertEqual(tool.name, TOOL_NAME)
        self.assertIn("SearXNG", tool.description)
        self.assertIn("query", tool.parameters.schema)

    async def test_tool_call_returns_results(self):
        """async_call 执行搜索并返回结构化结果。"""
        payload = {"results": [{"title": "结果", "url": "https://x", "content": "摘要"}]}
        set_session(FakeSession(FakeResponse(200, payload)))
        entry = _entry_with_base_url("https://searx.example.com")
        tool = self.module.SearxngSearchTool()
        result = await tool.async_call(
            _FakeHass([entry]),
            NewStyleToolInput(TOOL_NAME, {"query": "今天的天气"}),
            NewStyleLLMContext(),
        )
        self.assertEqual(result["query"], "今天的天气")
        self.assertEqual(result["results"][0]["title"], "结果")

    async def test_tool_call_passes_configured_language(self):
        """配置的语言随请求发送给 SearXNG。"""
        session = FakeSession(FakeResponse(200, {"results": []}))
        set_session(session)
        entry = _entry_with_base_url("https://searx.example.com")
        entry.data[CONF_LANGUAGE] = "zh"
        tool = self.module.SearxngSearchTool()
        result = await tool.async_call(
            _FakeHass([entry]),
            NewStyleToolInput(TOOL_NAME, {"query": "新闻"}),
            NewStyleLLMContext(),
        )
        self.assertEqual(result["results"], [])
        self.assertEqual(session.calls[0][1]["params"]["language"], "zh")

    async def test_tool_call_connection_failure_raises_chinese_error(self):
        """SearXNG 不可用时抛中文 HomeAssistantError。"""
        from homeassistant.exceptions import HomeAssistantError

        set_session(BrokenSession())
        entry = _entry_with_base_url("https://searx.example.com")
        tool = self.module.SearxngSearchTool()
        with self.assertRaises(HomeAssistantError) as ctx:
            await tool.async_call(
                _FakeHass([entry]),
                NewStyleToolInput(TOOL_NAME, {"query": "新闻"}),
                NewStyleLLMContext(),
            )
        self.assertIn("无法连接", str(ctx.exception))

    async def test_tool_call_empty_query_raises_chinese_error(self):
        """空关键词抛中文错误。"""
        from homeassistant.exceptions import HomeAssistantError

        entry = _entry_with_base_url("https://searx.example.com")
        tool = self.module.SearxngSearchTool()
        with self.assertRaises(HomeAssistantError) as ctx:
            await tool.async_call(
                _FakeHass([entry]),
                NewStyleToolInput(TOOL_NAME, {"query": "   "}),
                NewStyleLLMContext(),
            )
        self.assertIn("关键词", str(ctx.exception))

    async def test_tool_call_missing_config_raises_chinese_error(self):
        """未配置任何实例时抛中文错误（而不是崩溃）。"""
        from homeassistant.exceptions import HomeAssistantError

        tool = self.module.SearxngSearchTool()
        with self.assertRaises(HomeAssistantError) as ctx:
            await tool.async_call(
                _FakeHass(),
                NewStyleToolInput(TOOL_NAME, {"query": "新闻"}),
                NewStyleLLMContext(),
            )
        self.assertIn("尚未配置", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
