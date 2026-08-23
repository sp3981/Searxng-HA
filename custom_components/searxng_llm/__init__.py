"""SearXNG 联网搜索：把 SearXNG 变成 Home Assistant 大模型的搜索工具。

提供两条使用路径：

* LLM 工具：HA 2026.8+ 经 LLM 平台协议自动聚合进 Assist API；
  HA 2026.8 之前注册经典 llm.API（见 :mod:`custom_components.searxng_llm.llm`）。
* 服务 ``searxng_llm.search``：任意自动化/脚本/对话代理都可调用，
  特别为 Extended OpenAI Conversation 这类不消费 HA LLM 工具 API 的
  对话代理提供接入方式（在 EOC 的 Functions YAML 中配置 script 函数，
  用 ``response_variable: _function_result`` 把结果回传给模型）。
"""

from __future__ import annotations

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

from .const import CONF_QUERY, DOMAIN, EMPTY_RESULTS_MESSAGE, SERVICE_SEARCH
from .llm import execute_search, setup_api

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """集成仅支持界面配置（config flow），此处注册搜索服务并忽略 YAML 配置。"""
    del config
    hass.data.setdefault(DOMAIN, {})
    if not hass.services.has_service(DOMAIN, SERVICE_SEARCH):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SEARCH,
            _handle_search,
            schema=vol.Schema({vol.Required(CONF_QUERY): str}),
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

    返回 ``{"query", "results"[, "message"]}``；需要响应时（如 EOC 的
    ``response_variable: _function_result``）调用方会拿到该字典，
    否则返回 None。失败抛中文 HomeAssistantError，不崩溃。
    """
    query = str(call.data.get(CONF_QUERY, "")).strip()
    if not query:
        raise HomeAssistantError("请提供要搜索的内容（query 参数不能为空）。")
    items = await execute_search(call.hass, query)
    if not call.return_response:
        return None
    if not items:
        return {
            "query": query,
            "results": [],
            "message": EMPTY_RESULTS_MESSAGE,
        }
    return {"query": query, "results": items}
