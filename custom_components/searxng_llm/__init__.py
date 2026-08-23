"""SearXNG 联网搜索：把 SearXNG 变成 Home Assistant 大模型的搜索工具。

提供两条使用路径：

* LLM 工具：搜索 searxng_search + AI 智能抓取 fetch_webpage（由模型按需
  打开搜索结果中的链接，默认不再强制自动抓取）；HA 2026.8+ 经 LLM 平台
  协议自动聚合进 Assist API；HA 2026.8 之前注册经典 llm.API
  （见 :mod:`custom_components.searxng_llm.llm`）。
* 服务 ``searxng_llm.search`` / ``searxng_llm.fetch``：任意自动化/脚本/
  对话代理都可调用，特别为 Extended OpenAI Conversation 这类不消费
  HA LLM 工具 API 的对话代理提供接入方式（在 EOC 的 Functions YAML 中
  配置 script 函数，用 ``response_variable: _function_result`` 把结果回传给模型）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_LANGUAGE,
    CONF_QUERY,
    CONF_URL,
    DOMAIN,
    EMPTY_RESULTS_MESSAGE,
    SERVICE_FETCH,
    SERVICE_SEARCH,
)
from .llm import execute_fetch, execute_search, setup_api

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """集成仅支持界面配置（config flow），此处注册搜索/抓取服务并忽略 YAML 配置。"""
    del config
    hass.data.setdefault(DOMAIN, {})
    if not hass.services.has_service(DOMAIN, SERVICE_SEARCH):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SEARCH,
            _handle_search,
            schema=vol.Schema(
                {
                    vol.Required(CONF_QUERY): vol.Any(
                        str,
                        vol.All(vol.Coerce(list), vol.Length(min=1, max=10), [str]),
                    ),
                    vol.Optional(CONF_LANGUAGE): str,
                }
            ),
            supports_response=SupportsResponse.OPTIONAL,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_FETCH):
        hass.services.async_register(
            DOMAIN,
            SERVICE_FETCH,
            _handle_fetch,
            schema=vol.Schema(
                {
                    vol.Required(CONF_URL): vol.Any(
                        str,
                        vol.All(vol.Coerce(list), vol.Length(min=1, max=10), [str]),
                    ),
                }
            ),
            supports_response=SupportsResponse.OPTIONAL,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """装配配置条目：按当前 HA 架构注册 LLM 搜索工具。"""
    api = setup_api(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry
    if api is not None:
        entry.async_on_unload(api.async_unregister)
        _LOGGER.debug("SearXNG 联网搜索已注册：%s", api.id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载配置条目。"""
    hass.data.setdefault(DOMAIN, {}).pop(entry.entry_id, None)
    return True


async def _handle_search(call: ServiceCall) -> ServiceResponse | None:
    """处理 ``searxng_llm.search`` 服务：返回 JSON 格式搜索结果。

    返回 ``{"query", "results"[, "message"]}``；``query`` 传列表时并行搜索
    多个关键词（并发受集成「并行搜索数量」限制），返回合并去重后的
    results 与逐关键词的 ``searches``。需要响应时（如 EOC 的
    ``response_variable: _function_result``）调用方会拿到该字典，
    否则返回 None。可选传入 ``language`` 临时覆盖集成的搜索语言。
    失败抛中文 HomeAssistantError，不崩溃。
    """
    raw = call.data.get(CONF_QUERY)
    if isinstance(raw, list):
        queries = [str(q).strip() for q in raw]
    else:
        queries = [str(raw or "").strip()]
    queries = [q for q in queries if q]
    if not queries:
        raise HomeAssistantError("请提供要搜索的内容（query 参数不能为空）。")
    language = call.data.get(CONF_LANGUAGE)
    groups = await asyncio.gather(
        *(execute_search(call.hass, q, language=language) for q in queries)
    )
    if len(queries) == 1:
        query: str | list[str] = queries[0]
        items = groups[0]
    else:
        merged: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in (item for group in groups for item in group):
            url = item.get("url", "")
            if not url or url not in seen:
                merged.append(item)
                if url:
                    seen.add(url)
        query = queries
        items = merged
    if not call.return_response:
        return None
    result: dict[str, Any] = {"query": query, "results": items}
    if isinstance(query, list):
        result["searches"] = [
            {"query": q, "results": group} for q, group in zip(queries, groups)
        ]
    if not items:
        result["message"] = EMPTY_RESULTS_MESSAGE
    return result


async def _handle_fetch(call: ServiceCall) -> ServiceResponse | None:
    """处理 ``searxng_llm.fetch`` 服务：抓取指定网页的正文内容。

    返回 ``{"urls", "results"}``，每条结果为 ``{"url", "content"}`` 或
    ``{"url", "error"}``；``url`` 传列表时并行抓取（并发受集成
    「并行抓取数量」限制）。需要响应时（如 EOC 的
    ``response_variable: _function_result``）调用方会拿到该字典，
    否则返回 None。失败抛中文 HomeAssistantError，不崩溃。
    """
    raw = call.data.get(CONF_URL)
    if isinstance(raw, list):
        urls = [str(u).strip() for u in raw]
    else:
        urls = [str(raw or "").strip()]
    urls = [u for u in urls if u]
    if not urls:
        raise HomeAssistantError("请提供要抓取的网页地址（url 参数不能为空）。")
    results = await execute_fetch(call.hass, urls)
    if not call.return_response:
        return None
    return {"urls": urls, "results": results}
