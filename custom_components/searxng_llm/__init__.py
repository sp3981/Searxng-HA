"""SearXNG 联网搜索：把 SearXNG 变成 Home Assistant 大模型的搜索工具。"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .llm import SearxngAPI

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """集成仅支持界面配置（config flow），此处忽略 YAML 配置。"""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """装配配置条目：把搜索工具注册到 LLM 工具 API。"""
    api = SearxngAPI(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = api
    entry.async_on_unload(api.async_unregister)
    api.async_register()
    _LOGGER.debug("SearXNG 联网搜索已注册：%s", api.id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载配置条目（LLM 注销由 async_on_unload 自动完成）。"""
    hass.data.setdefault(DOMAIN, {}).pop(entry.entry_id, None)
    return True
