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

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_NAME,
    CONF_BASE_URL,
    CONF_FETCH_COUNT,
    CONF_FETCH_PARALLEL,
    CONF_FETCH_TIMEOUT,
    CONF_LANGUAGE,
    CONF_PASSWORD,
    CONF_RESULTS,
    CONF_SEARCH_PARALLEL,
    CONF_TIMEOUT,
    CONF_USERNAME,
    DEFAULT_FETCH_COUNT,
    DEFAULT_FETCH_PARALLEL,
    DEFAULT_FETCH_TIMEOUT,
    DEFAULT_LANGUAGE,
    DEFAULT_RESULTS,
    DEFAULT_SEARCH_PARALLEL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    EMPTY_RESULTS_MESSAGE,
    TOOL_DESCRIPTION,
    TOOL_NAME,
)
from .tool import SearxngError, fetch_url, search

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


def _parse_settings(
    config: dict[str, Any],
) -> tuple[int, int, str, int, int, int, int]:
    """解析搜索与抓取参数（非法/越界值回退默认）。

    返回 (results, timeout, language, fetch_count, fetch_parallel,
    fetch_timeout, search_parallel)。
    """

    def _int(key: str, default: int, low: int, high: int) -> int:
        try:
            value = int(config.get(key, default))
        except (TypeError, ValueError):
            return default
        return min(high, max(low, value))

    return (
        _int(CONF_RESULTS, DEFAULT_RESULTS, 1, 20),
        _int(CONF_TIMEOUT, DEFAULT_TIMEOUT, 3, 60),
        str(config.get(CONF_LANGUAGE) or "").strip() or DEFAULT_LANGUAGE,
        _int(CONF_FETCH_COUNT, DEFAULT_FETCH_COUNT, 0, 10),
        _int(CONF_FETCH_PARALLEL, DEFAULT_FETCH_PARALLEL, 1, 10),
        _int(CONF_FETCH_TIMEOUT, DEFAULT_FETCH_TIMEOUT, 3, 60),
        _int(CONF_SEARCH_PARALLEL, DEFAULT_SEARCH_PARALLEL, 1, 10),
    )


async def execute_search(
    hass: HomeAssistant,
    query: str,
    entry: ConfigEntry | None = None,
    language: str | None = None,
) -> list[dict[str, str]]:
    """执行 SearXNG 搜索并按配置并行抓取网页正文，失败抛中文 HomeAssistantError。

    供新架构工具、经典架构工具与 ``searxng_llm.search`` 服务复用，
    保证三条路径的错误提示一致且不崩溃。``entry`` 可显式传入
    （经典架构直接从配置条目读取，避免依赖 hass 查找）；
    ``language`` 可临时覆盖条目配置的搜索语言（None 则用配置值）。
    搜索与抓取的并发上限取自条目配置（search_parallel / fetch_parallel）。
    """
    if entry is None:
        entry = _first_configured_entry(hass)
    if entry is None:
        raise HomeAssistantError("SearXNG 联网搜索尚未配置，请先在集成中添加实例。")
    config = merged_config(entry)
    base_url = str(config.get(CONF_BASE_URL) or "").strip().rstrip("/")
    if not base_url:
        raise HomeAssistantError("尚未配置 SearXNG 地址，请先在集成设置中填写。")
    (
        results,
        timeout,
        language_configured,
        fetch_count,
        fetch_parallel,
        fetch_timeout,
        search_parallel,
    ) = _parse_settings(config)
    if language is None:
        language = language_configured
    else:
        language = str(language).strip() or language_configured

    started = time.monotonic()
    meta: dict = {}
    session = async_get_clientsession(hass)
    search_sem = _get_semaphore(hass, "search_sem", search_parallel)

    try:
        async with search_sem or nullcontext():
            items = await search(
                session,
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

    if items and fetch_count > 0:
        fetch_started = time.monotonic()
        items = await _fetch_pages(
            session, hass, items, fetch_count, fetch_parallel, fetch_timeout
        )
        fetched_ok = sum(1 for item in items if item.get("fetched_content"))
        fetched_failed = sum(1 for item in items if item.get("fetch_error"))
        _LOGGER.debug(
            "SearXNG 网页抓取完成：query=%r 抓取=%d 条 成功=%d 失败=%d 耗时=%.1f 秒",
            query,
            min(len(items), fetch_count),
            fetched_ok,
            fetched_failed,
            time.monotonic() - fetch_started,
        )
    return items


def _get_semaphore(
    hass: HomeAssistant | None, key: str, limit: int
) -> asyncio.Semaphore | None:
    """取/建 hass 级并发信号量（测试桩或无 data 时返回 None，不限并发）。"""
    data = getattr(hass, "data", None)
    if data is None:
        return None
    store = data.setdefault(f"{DOMAIN}_sems", {})
    sem = store.get(key)
    if sem is None:
        sem = asyncio.Semaphore(max(1, int(limit)))
        store[key] = sem
    return sem


async def _fetch_pages(
    session: aiohttp.ClientSession,
    hass: HomeAssistant | None,
    items: list[dict[str, str]],
    fetch_count: int,
    fetch_parallel: int,
    fetch_timeout: int,
) -> list[dict[str, str]]:
    """并行抓取前 ``fetch_count`` 条结果的网页正文。

    正文写入 ``fetched_content``；单条失败只写入 ``fetch_error``，
    不影响其它抓取与整体搜索结果。
    """
    fetch_sem = _get_semaphore(hass, "fetch_sem", fetch_parallel)

    async def _fetch_one(item: dict[str, str]) -> dict[str, str]:
        url = item.get("url", "")
        if not url:
            return item
        try:
            async with fetch_sem or nullcontext():
                text = await fetch_url(session, url, timeout=fetch_timeout)
        except SearxngError as err:
            item["fetch_error"] = str(err)
        except Exception as err:  # 单条抓取的未知异常只记录，不崩溃
            item["fetch_error"] = f"抓取失败：{err}"
        else:
            item["fetched_content"] = text
        return item

    fetched = await asyncio.gather(
        *(_fetch_one(item) for item in items[:fetch_count])
    )
    return [*fetched, *items[fetch_count:]]


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
