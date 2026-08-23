"""SearXNG 联网搜索的配置向导（含连通性验证）。"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
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
    ERROR_CANNOT_CONNECT,
    KNOWN_ERROR_CODES,
    TEST_QUERY,
)
from .tool import SearxngError, search

_LOGGER = logging.getLogger(__name__)

INVALID_URL = "invalid_url"


def _normalize_base_url(value: str) -> str:
    """去除首尾空白与结尾斜杠。"""
    return value.strip().rstrip("/")


def _check_base_url(value: str) -> str | None:
    """校验地址格式：合法返回 None，否则返回错误键。"""
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return INVALID_URL
    return None


def _build_schema(defaults: Mapping[str, Any] | None = None) -> vol.Schema:
    """构造配置表单。"""
    values: Mapping[str, Any] = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_BASE_URL, default=values.get(CONF_BASE_URL, "https://")
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
            ),
            vol.Optional(
                CONF_USERNAME, default=values.get(CONF_USERNAME, "")
            ): str,
            vol.Optional(
                CONF_PASSWORD, default=values.get(CONF_PASSWORD, "")
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(
                CONF_LANGUAGE, default=values.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            vol.Required(
                CONF_RESULTS, default=values.get(CONF_RESULTS, DEFAULT_RESULTS)
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
            vol.Required(
                CONF_TIMEOUT, default=values.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
            ): vol.All(vol.Coerce(int), vol.Range(min=3, max=60)),
            vol.Required(
                CONF_SEARCH_PARALLEL,
                default=values.get(CONF_SEARCH_PARALLEL, DEFAULT_SEARCH_PARALLEL),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
            vol.Required(
                CONF_FETCH_COUNT,
                default=values.get(CONF_FETCH_COUNT, DEFAULT_FETCH_COUNT),
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=10)),
            vol.Required(
                CONF_FETCH_PARALLEL,
                default=values.get(CONF_FETCH_PARALLEL, DEFAULT_FETCH_PARALLEL),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
            vol.Required(
                CONF_FETCH_TIMEOUT,
                default=values.get(CONF_FETCH_TIMEOUT, DEFAULT_FETCH_TIMEOUT),
            ): vol.All(vol.Coerce(int), vol.Range(min=3, max=60)),
        }
    )


async def _test_search(hass: HomeAssistant, data: Mapping[str, Any]) -> None:
    """用测试关键词验证连通性与 JSON 输出，失败时抛出 SearxngError。"""
    session = async_get_clientsession(hass)
    timeout = min(int(data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)), 10)
    await search(
        session,
        _normalize_base_url(str(data[CONF_BASE_URL])),
        TEST_QUERY,
        results=1,
        username=str(data.get(CONF_USERNAME) or "") or None,
        password=str(data.get(CONF_PASSWORD) or "") or None,
        timeout=timeout,
        language=str(data.get(CONF_LANGUAGE) or DEFAULT_LANGUAGE),
    )


def _map_error(err: SearxngError) -> str:
    """把 SearxngError 映射为 strings.json 中的错误键。"""
    return err.code if err.code in KNOWN_ERROR_CODES else ERROR_CANNOT_CONNECT


class SearxngConfigFlow(ConfigFlow, domain=DOMAIN):
    """处理首次配置。"""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """第一步：填写并验证 SearXNG 连接信息。"""
        errors: dict[str, str] = {}
        if user_input is not None:
            base_url = _normalize_base_url(str(user_input[CONF_BASE_URL]))
            user_input[CONF_BASE_URL] = base_url
            if error := _check_base_url(base_url):
                errors[CONF_BASE_URL] = error
            else:
                await self.async_set_unique_id(base_url)
                self._abort_if_unique_id_configured()
                try:
                    await _test_search(self.hass, user_input)
                except SearxngError as err:
                    _LOGGER.info("SearXNG 连通性测试失败：%s", err)
                    errors["base"] = _map_error(err)
                except Exception:
                    _LOGGER.exception("SearXNG 连通性测试发生未知错误")
                    errors["base"] = ERROR_CANNOT_CONNECT
                else:
                    return self.async_create_entry(
                        title=f"SearXNG（{urlparse(base_url).netloc}）",
                        data={
                            CONF_BASE_URL: base_url,
                            CONF_USERNAME: str(
                                user_input.get(CONF_USERNAME) or ""
                            ).strip(),
                            CONF_PASSWORD: str(user_input.get(CONF_PASSWORD) or ""),
                            CONF_RESULTS: int(user_input[CONF_RESULTS]),
                            CONF_TIMEOUT: int(user_input[CONF_TIMEOUT]),
                            CONF_LANGUAGE: str(
                                user_input.get(CONF_LANGUAGE) or ""
                            ).strip()
                            or DEFAULT_LANGUAGE,
                            CONF_SEARCH_PARALLEL: int(
                                user_input.get(
                                    CONF_SEARCH_PARALLEL, DEFAULT_SEARCH_PARALLEL
                                )
                            ),
                            CONF_FETCH_COUNT: int(
                                user_input.get(CONF_FETCH_COUNT, DEFAULT_FETCH_COUNT)
                            ),
                            CONF_FETCH_PARALLEL: int(
                                user_input.get(
                                    CONF_FETCH_PARALLEL, DEFAULT_FETCH_PARALLEL
                                )
                            ),
                            CONF_FETCH_TIMEOUT: int(
                                user_input.get(
                                    CONF_FETCH_TIMEOUT, DEFAULT_FETCH_TIMEOUT
                                )
                            ),
                        },
                    )
        return self.async_show_form(
            step_id="user", data_schema=_build_schema(), errors=errors
        )


class SearxngOptionsFlow(OptionsFlow):
    """处理参数修改。"""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """修改 SearXNG 连接信息。"""
        errors: dict[str, str] = {}
        if user_input is not None:
            base_url = _normalize_base_url(str(user_input[CONF_BASE_URL]))
            user_input[CONF_BASE_URL] = base_url
            if error := _check_base_url(base_url):
                errors[CONF_BASE_URL] = error
            else:
                try:
                    await _test_search(self.hass, user_input)
                except SearxngError as err:
                    errors["base"] = _map_error(err)
                except Exception:
                    _LOGGER.exception("SearXNG 连通性测试发生未知错误")
                    errors["base"] = ERROR_CANNOT_CONNECT
            if not errors:
                return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(
                {**self.config_entry.data, **self.config_entry.options}
            ),
            errors=errors,
        )


async def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
    """返回选项流：让「集成 → 配置」能打开可修改的连接参数表单。

    没有该入口时，HA 点「配置」拿不到 options flow，
    地址/超时/语言等参数只有首次添加时才能填。
    """
    return SearxngOptionsFlow(config_entry)
