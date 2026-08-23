"""把 SearXNG 搜索暴露为 Home Assistant 大模型的 LLM 工具。

兼容两代 LLM 工具架构：

* HA 2026.8 起（``homeassistant.helpers.llm`` + LLM 平台协议）：本模块会被
  llm 组件当作「llm 平台」自动导入，通过模块级
  ``async_get_tools(hass, llm_context, api_id)`` 提供工具，聚合进 Assist API，
  供所有使用该 API 的对话代理调用。
* HA 2026.8 之前（经典 ``llm.API`` 注册方式）：注册专属 API，由
  ``SearxngAPIInstance.async_get_tools`` 暴露工具。

两代架构复用同一个搜索实现 :func:`execute_search`。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_NAME,
    CONF_BASE_URL,
    CONF_LANGUAGE,
    CONF_PASSWORD,
    CONF_RESULTS,
    CONF_TIMEOUT,
    CONF_USERNAME,
    DEFAULT_LANGUAGE,
    DEFAULT_RESULTS,
    DEFAULT_TIMEOUT,
    DOMAIN,
    EMPTY_RESULTS_MESSAGE,
    TOOL_DESCRIPTION,
    TOOL_NAME,
)
from .tool import SearxngError, search

_LOGGER = logging.getLogger(__name__)

# HA 2026.8 起 homeassistant.components.llm 导出 LLMTools 平台协议标记，
# 据此在运行时选择新架构（模块级平台函数）或经典架构（注册 llm.API）。
try:
    from homeassistant.components.llm import LLMTools

    NEW_STYLE = True
except ImportError:  # pragma: no cover - 老版本走经典架构
    NEW_STYLE = False

if NEW_STYLE:
    from homeassistant.helpers import llm as llm
else:
    from homeassistant.components import llm

    try:
        from homeassistant.components.llm import ToolError
    except ImportError:  # pragma: no cover - 极老版本回退到标准异常基类
        from homeassistant.exceptions import HomeAssistantError as ToolError


def merged_config(entry: ConfigEntry) -> dict[str, Any]:
    """合并条目数据与选项（选项优先），得到当前生效配置。"""
    return {**entry.data, **entry.options}


def _first_configured_entry(hass: HomeAssistant) -> ConfigEntry | None:
    """返回第一个已填写 SearXNG 地址的配置条目（平台函数与服务共用）。"""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if str(merged_config(entry).get(CONF_BASE_URL) or "").strip():
            return entry
    return None


def _parse_settings(config: dict[str, Any]) -> tuple[int, int, str]:
    """解析结果条数、超时与搜索语言（非法值回退默认）。"""
    try:
        results = int(config.get(CONF_RESULTS, DEFAULT_RESULTS))
    except (TypeError, ValueError):
        results = DEFAULT_RESULTS
    try:
        timeout = int(config.get(CONF_TIMEOUT, DEFAULT_TIMEOUT))
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    language = str(config.get(CONF_LANGUAGE) or "").strip() or DEFAULT_LANGUAGE
    return results, timeout, language


async def execute_search(
    hass: HomeAssistant,
    query: str,
    entry: ConfigEntry | None = None,
    language: str | None = None,
) -> list[dict[str, str]]:
    """执行 SearXNG 搜索，返回结果列表；失败抛中文 HomeAssistantError。

    供新架构工具、经典架构工具与 ``searxng_llm.search`` 服务复用，
    保证三条路径的错误提示一致且不崩溃。``entry`` 可显式传入
    （经典架构直接从配置条目读取，避免依赖 hass 查找）；
    ``language`` 可临时覆盖条目配置的搜索语言（None 则用配置值）。
    """
    if entry is None:
        entry = _first_configured_entry(hass)
    if entry is None:
        raise HomeAssistantError("SearXNG 联网搜索尚未配置，请先在集成中添加实例。")
    config = merged_config(entry)
    base_url = str(config.get(CONF_BASE_URL) or "").strip().rstrip("/")
    if not base_url:
        raise HomeAssistantError("尚未配置 SearXNG 地址，请先在集成设置中填写。")
    results, timeout, configured_language = _parse_settings(config)
    if language is None:
        language = configured_language
    else:
        language = str(language).strip() or configured_language
    started = time.monotonic()
    meta: dict = {}

    try:
        items = await search(
            async_get_clientsession(hass),
            base_url,
            query,
            results=results,
            username=str(config.get(CONF_USERNAME) or "") or None,
            password=str(config.get(CONF_PASSWORD) or "") or None,
            timeout=timeout,
            language=language,
            meta=meta,
        )
    except SearxngError as err:
        _LOGGER.warning(
            "SearXNG 搜索失败（耗时 %.1f 秒）：%s",
            time.monotonic() - started,
            err,
        )
        raise HomeAssistantError(str(err)) from err
    except Exception as err:  # 兜底：未知异常也转为友好提示，保证不崩溃
        _LOGGER.exception(
            "SearXNG 搜索发生未知错误（耗时 %.1f 秒）",
            time.monotonic() - started,
        )
        raise HomeAssistantError(f"搜索时发生内部错误：{err}") from err

    _LOGGER.debug(
        "SearXNG 搜索完成：query=%r 地址=%r 语言=%r 耗时=%.1f 秒 结果=%d 条 "
        "unresponsive_engines=%r number_of_results=%r",
        query,
        base_url,
        language,
        time.monotonic() - started,
        len(items),
        meta.get("unresponsive_engines"),
        meta.get("number_of_results"),
    )
    return items


if NEW_STYLE:

    class SearxngSearchTool(llm.Tool):
        """SearXNG 搜索工具（HA 2026.8+ 的 Tool 子类形态）。"""

        name = TOOL_NAME
        description = TOOL_DESCRIPTION
        parameters = vol.Schema({vol.Required("query"): str})

        async def async_call(
            self,
            hass: HomeAssistant,
            tool_input: llm.ToolInput,
            llm_context: llm.LLMContext,
        ) -> dict[str, Any]:
            """执行搜索并返回给模型的结果对象。"""
            del llm_context
            args = getattr(tool_input, "tool_args", None)
            query = str(args.get("query", "")).strip() if isinstance(args, dict) else ""
            if not query:
                raise HomeAssistantError("搜索关键词不能为空，请先确定要搜索的内容。")
            items = await execute_search(hass, query)
            if not items:
                return {
                    "query": query,
                    "results": [],
                    "message": EMPTY_RESULTS_MESSAGE,
                }
            return {"query": query, "results": items}

    @callback
    def async_get_tools(
        hass: HomeAssistant, llm_context: Any, api_id: str
    ) -> LLMTools | None:
        """LLM 平台入口（须为同步函数），由 llm 组件聚合进 Assist API。

        未配置任何实例时返回 None，不向模型暴露工具。
        """
        del llm_context, api_id
        if _first_configured_entry(hass) is None:
            return None
        return LLMTools(tools=[SearxngSearchTool()])

else:  # 经典架构（HA 2026.8 之前）

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
            try:
                items = await execute_search(self.api.hass, query, self.api.entry)
            except HomeAssistantError as err:
                raise ToolError(str(err)) from err
            if not items:
                return llm.ToolResult(
                    {
                        "query": query,
                        "results": [],
                        "message": EMPTY_RESULTS_MESSAGE,
                    }
                )
            return llm.ToolResult({"query": query, "results": items})


def setup_api(
    hass: HomeAssistant, entry: ConfigEntry
) -> Any:
    """按当前 HA 架构注册 LLM 工具，返回 API 对象（新架构返回 None）。

    新架构下无需注册：llm 组件会自动导入本模块并调用平台函数。
    """
    if NEW_STYLE:
        return None
    api = SearxngAPI(hass, entry)
    api.async_register()
    return api
