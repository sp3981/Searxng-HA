"""SearXNG JSON 接口客户端（纯 aiohttp，零第三方依赖）。"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

import aiohttp

from .const import (
    DEFAULT_RESULTS,
    DEFAULT_TIMEOUT,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_AUTH,
    ERROR_INVALID_RESPONSE,
    ERROR_JSON_DISABLED,
)

_LOGGER = logging.getLogger(__name__)

USER_AGENT = "homeassistant-searxng-llm/1.0"


def _basic_auth_header(username: str, password: str) -> str:
    """构造 HTTP Basic 认证头（不依赖已弃用的 aiohttp.BasicAuth）。"""
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


class SearxngError(Exception):
    """SearXNG 请求失败。

    ``message`` 是面向用户的中文提示；``code`` 对应 strings.json 中的错误键。
    """

    def __init__(self, message: str, code: str = ERROR_CANNOT_CONNECT) -> None:
        """初始化。"""
        super().__init__(message)
        self.message = message
        self.code = code

    def __str__(self) -> str:
        """返回用户可读的中文提示。"""
        return self.message


async def search(
    session: aiohttp.ClientSession,
    base_url: str,
    query: str,
    *,
    results: int = DEFAULT_RESULTS,
    username: str | None = None,
    password: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[dict[str, str]]:
    """调用 SearXNG 的 JSON 接口搜索，返回前 ``results`` 条结果。

    每条结果为 ``{"title", "url", "content"}`` 字典；
    连接失败、认证失败、未启用 JSON 输出等情况抛出 :class:`SearxngError`。
    """
    url = f"{base_url.rstrip('/')}/search"
    params: dict[str, str] = {"q": query, "format": "json"}
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if username and password:
        headers["Authorization"] = _basic_auth_header(username, password)

    try:
        async with session.get(
            url,
            params=params,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as response:
            if response.status == 401:
                raise SearxngError(
                    "认证失败：SearXNG 返回 HTTP 401，请检查用户名和密码。",
                    code=ERROR_INVALID_AUTH,
                )
            if response.status == 403:
                content_type = (response.headers or {}).get("Content-Type", "")
                if "json" in content_type.lower():
                    raise SearxngError(
                        "访问被拒绝：SearXNG 返回 HTTP 403，"
                        "请检查认证信息或实例的访问控制。",
                        code=ERROR_INVALID_AUTH,
                    )
                raise SearxngError(
                    "SearXNG 返回 HTTP 403：通常是实例未启用 JSON 输出"
                    "（settings.yml 的 search.formats 需包含 json）；"
                    "若实例部署在反向代理之后，也可能是认证失败。",
                    code=ERROR_JSON_DISABLED,
                )
            if response.status >= 400:
                raise SearxngError(
                    f"SearXNG 返回 HTTP {response.status}，"
                    "请确认地址是 SearXNG 实例的根地址（例如 https://searx.example.com）。",
                    code=ERROR_INVALID_RESPONSE,
                )
            try:
                data = await response.json(content_type=None)
            except (ValueError, aiohttp.ClientResponseError) as err:
                raise SearxngError(
                    "SearXNG 未返回 JSON 数据：请在 settings.yml 的 "
                    "search.formats 中加入 json 并重启 SearXNG。",
                    code=ERROR_JSON_DISABLED,
                ) from err
    except SearxngError:
        raise
    except asyncio.TimeoutError as err:
        raise SearxngError(
            "连接 SearXNG 超时，请检查网络或调大超时时间。",
            code=ERROR_CANNOT_CONNECT,
        ) from err
    except aiohttp.ClientError as err:
        raise SearxngError(
            "无法连接 SearXNG，请检查地址、网络以及服务是否正常运行。",
            code=ERROR_CANNOT_CONNECT,
        ) from err

    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise SearxngError(
            "SearXNG 返回的数据缺少 results 字段，请确认已启用 format=json 输出。",
            code=ERROR_INVALID_RESPONSE,
        )

    items: list[dict[str, str]] = []
    for item in data["results"][:results]:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "title": str(item.get("title") or "").strip(),
                "url": str(item.get("url") or ""),
                "content": str(item.get("content") or "").strip(),
            }
        )
    return items
