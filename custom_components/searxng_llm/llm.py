"""把 SearXNG 搜索暴露为 Home Assistant 大模型的 LLM 工具。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import voluptuous as vol

from homeassistant.components import llm
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_NAME,
    CONF_BASE_URL,
    CONF_PASSWORD,
    CONF_RESULTS,
    CONF_TIMEOUT,
    CONF_USERNAME,
    DEFAULT_RESULTS,
    DEFAULT_TIMEOUT,
    DOMAIN,
    TOOL_DESCRIPTION,
    TOOL_NAME,
)
from .tool import SearxngError, search

_LOGGER = logging.getLogger(__name__)

try:
    from homeassistant.components.llm import ToolError
except ImportError:  # pragma: no cover - 极老版本回退到标准异常基类
    from homeassistant.exceptions import HomeAssistantError as ToolError


def merged_config(entry: ConfigEntry) -> dict[str, Any]:
    """合并条目数据与选项（选项优先），得到当前生效配置。"""
    return {**entry.data, **entry.options}


class SearxngAPI(llm.API):
    """向 LLM 暴露 SearXNG 搜索工具的 API。"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """初始化。"""
        self.hass = hass
        self.entry = entry
        self.id = f"{DOMAIN}_{entry.entry_id}"
        self.name = API_NAME
        self._unregister: Callable[[], None] | None = None

    def async_register(self) -> None:
        """把 API 注册到 LLM 工具注册表（命名与官方示例保持一致）。"""
        self._unregister = llm.async_register_api(self.hass, self)

    def async_unregister(self) -> None:
        """从 LLM 工具注册表注销，供配置条目卸载时调用。"""
        if self._unregister is not None:
            self._unregister()
            self._unregister = None

    async def async_get_api_instance(
        self, llm_context: llm.LLMContext
    ) -> SearxngAPIInstance:
        """返回当前 LLM 会话上下文的 API 实例。"""
        return SearxngAPIInstance(self, llm_context)


class SearxngAPIInstance(llm.APIInstance):
    """LLM 工具实例：在一次会话中向模型提供「搜索」工具。"""

    def __init__(self, api: SearxngAPI, llm_context: llm.LLMContext) -> None:
        """初始化。"""
        self.api = api
        self.llm_context = llm_context

    async def async_get_tools(self) -> list[llm.Tool]:
        """返回可被模型调用的工具列表。"""
        return [
            llm.Tool(
                name=TOOL_NAME,
                description=TOOL_DESCRIPTION,
                parameters=vol.Schema({vol.Required("query"): str}),
                llm_func=self._tool_search,
            )
        ]

    async def _tool_search(self, *args: Any) -> llm.ToolResult:
        """执行 SearXNG 搜索并返回结果。

        不同 HA 版本对 llm_func 的调用约定略有差异：新版本为
        ``llm_func(tool_input)``，早期版本为 ``llm_func(call_id, tool_input)``。
        这里统一取最后一个参数作为 tool_input，兼容两种调用约定。
        """
        tool_input: llm.ToolInput = args[-1] if args else {}
        query = (
            str(tool_input.get("query", "")).strip()
            if isinstance(tool_input, dict)
            else ""
        )
        if not query:
            raise ToolError("搜索关键词不能为空，请先确定要搜索的内容。")

        config = merged_config(self.api.entry)
        base_url = str(config.get(CONF_BASE_URL) or "").strip().rstrip("/")
        if not base_url:
            raise ToolError("尚未配置 SearXNG 地址，请先在集成设置中填写。")

        try:
            results = int(config.get(CONF_RESULTS, DEFAULT_RESULTS))
        except (TypeError, ValueError):
            results = DEFAULT_RESULTS
        try:
            timeout = int(config.get(CONF_TIMEOUT, DEFAULT_TIMEOUT))
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT

        try:
            items = await search(
                async_get_clientsession(self.api.hass),
                base_url,
                query,
                results=results,
                username=str(config.get(CONF_USERNAME) or "") or None,
                password=str(config.get(CONF_PASSWORD) or "") or None,
                timeout=timeout,
            )
        except SearxngError as err:
            _LOGGER.warning("SearXNG 搜索失败：%s", err)
            raise ToolError(str(err)) from err
        except Exception as err:  # 兜底：未知异常也转为友好提示，保证不崩溃
            _LOGGER.exception("SearXNG 搜索发生未知错误")
            raise ToolError(f"搜索时发生内部错误：{err}") from err

        if not items:
            return llm.ToolResult(
                {
                    "query": query,
                    "results": [],
                    "message": "SearXNG 没有返回相关结果。",
                }
            )
        return llm.ToolResult({"query": query, "results": items})
