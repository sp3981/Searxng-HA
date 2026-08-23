"""Home Assistant / voluptuous 最小桩与假 aiohttp 会话，供本地单元测试使用。

真实环境由 Home Assistant 提供这些模块；本地测试时用本文件代替，
因此可以在没有安装 Home Assistant 的机器上验证集成逻辑。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

# 把仓库根目录加入 sys.path，使 custom_components 可导入
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------- voluptuous 桩 ----------
_vol = types.ModuleType("voluptuous")


class _Schema:
    """只保存 schema、不做校验的桩。"""

    def __init__(self, schema: Any) -> None:
        self.schema = schema

    def __call__(self, value: Any) -> Any:
        return value


def _marker(key: Any, default: Any = None, **_: Any) -> Any:
    del default
    return key


_vol.Schema = _Schema
_vol.Required = _marker
_vol.Optional = _marker
_vol.All = lambda *args: args[0] if args else None
_vol.Any = lambda *args: args[0] if args else None
_vol.Length = lambda **kwargs: (lambda value: value)
_vol.Coerce = lambda fn: fn
_vol.Range = lambda **kwargs: (lambda value: value)
sys.modules["voluptuous"] = _vol


# ---------- homeassistant 桩 ----------
_ha = types.ModuleType("homeassistant")
_ha.__path__ = []
sys.modules["homeassistant"] = _ha

_exceptions = types.ModuleType("homeassistant.exceptions")


class HomeAssistantError(Exception):
    """HomeAssistantError 桩。"""


_exceptions.HomeAssistantError = HomeAssistantError
sys.modules["homeassistant.exceptions"] = _exceptions

_core = types.ModuleType("homeassistant.core")


class HomeAssistant:
    """HomeAssistant 桩。"""


def _callback(fn: Any) -> Any:
    """callback 装饰器桩：原样返回函数。"""
    return fn


class ServiceCall:
    """homeassistant.core.ServiceCall 桩。"""

    def __init__(self, hass: Any = None, data: dict[str, Any] | None = None) -> None:
        self.hass = hass
        self.data = data or {}
        self.context = None
        self.return_response = False


ServiceResponse = dict


class SupportsResponse:
    """homeassistant.core.SupportsResponse 桩。"""

    NONE = 0
    OPTIONAL = 1
    ONLY = 2


_core.HomeAssistant = HomeAssistant
_core.callback = _callback
_core.ServiceCall = ServiceCall
_core.ServiceResponse = ServiceResponse
_core.SupportsResponse = SupportsResponse
sys.modules["homeassistant.core"] = _core

_config_entries = types.ModuleType("homeassistant.config_entries")


class ConfigEntry:
    """ConfigEntry 桩。"""

    def __init__(self) -> None:
        self.entry_id = "test_entry"
        self.data: dict[str, Any] = {}
        self.options: dict[str, Any] = {}
        self.title = "SearXNG"


_config_entries.ConfigEntry = ConfigEntry
sys.modules["homeassistant.config_entries"] = _config_entries

_helpers = types.ModuleType("homeassistant.helpers")
_helpers.__path__ = []
sys.modules["homeassistant.helpers"] = _helpers

# HA 2026.8+ 把 LLM 基类搬到 helpers.llm，新架构分支需要这些桩
_helpers_llm = types.ModuleType("homeassistant.helpers.llm")


class NewStyleTool:
    """helpers.llm.Tool 桩：子类以类属性声明 name/description/parameters。"""


class NewStyleToolInput:
    """helpers.llm.ToolInput 桩。"""

    def __init__(self, tool_name: str, tool_args: dict[str, Any], tool_id: str = "") -> None:
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.id = tool_id


class NewStyleLLMContext:
    """helpers.llm.LLMContext 桩。"""


_helpers_llm.Tool = NewStyleTool
_helpers_llm.ToolInput = NewStyleToolInput
_helpers_llm.LLMContext = NewStyleLLMContext
sys.modules["homeassistant.helpers.llm"] = _helpers_llm

_aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
_current_session: Any = None


def set_session(session: Any) -> None:
    """供测试注入假 aiohttp 会话。"""
    global _current_session
    _current_session = session


def async_get_clientsession(hass: Any) -> Any:
    """返回测试注入的会话。"""
    del hass
    if _current_session is None:
        raise RuntimeError("测试未注入会话：请先调用 set_session()")
    return _current_session


_aiohttp_client.set_session = set_session
_aiohttp_client.async_get_clientsession = async_get_clientsession
sys.modules["homeassistant.helpers.aiohttp_client"] = _aiohttp_client

_components = types.ModuleType("homeassistant.components")
_components.__path__ = []
sys.modules["homeassistant.components"] = _components

_llm = types.ModuleType("homeassistant.components.llm")


class LLMContext:
    """llm.LLMContext 桩。"""


class API:
    """llm.API 桩。"""


class APIInstance:
    """llm.APIInstance 桩。"""


class Tool:
    """llm.Tool 桩。"""

    def __init__(self, name, description, parameters, llm_func) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.llm_func = llm_func

    async def async_call(self, tool_input):
        """按新版本调用约定执行工具。"""
        return await self.llm_func(tool_input)


class ToolResult:
    """llm.ToolResult 桩。"""

    def __init__(self, serialized_result, user_prompt=None) -> None:
        self.serialized_result = serialized_result
        self.user_prompt = user_prompt


class ToolError(HomeAssistantError):
    """llm.ToolError 桩。"""


ToolInput = dict

_registered: dict[str, API] = {}


def async_register_api(hass, api):
    """注册桩：返回注销回调。"""
    del hass
    _registered[api.id] = api

    def _unregister() -> None:
        _registered.pop(api.id, None)

    return _unregister


def async_get_apis(hass):
    """返回已注册的 API 列表。"""
    del hass
    return list(_registered.values())


_llm.LLMContext = LLMContext
_llm.API = API
_llm.APIInstance = APIInstance
_llm.Tool = Tool
_llm.ToolResult = ToolResult
_llm.ToolError = ToolError
_llm.ToolInput = ToolInput
_llm.async_register_api = async_register_api
_llm.async_get_apis = async_get_apis
sys.modules["homeassistant.components.llm"] = _llm


# ---------- 假 aiohttp 会话 / 响应 ----------
import aiohttp  # noqa: E402


class FakeResponse:
    """模拟 aiohttp 响应。"""

    def __init__(
        self,
        status: int = 200,
        payload: Any = None,
        content_type: str = "application/json",
        enter_error: Exception | None = None,
    ) -> None:
        self.status = status
        self._payload = {"results": []} if payload is None else payload
        self._enter_error = enter_error
        self.headers = {"Content-Type": content_type}

    async def __aenter__(self) -> "FakeResponse":
        if self._enter_error is not None:
            raise self._enter_error
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def json(self, content_type: str | None = None) -> Any:
        """返回 payload；字符串/字节按非法 JSON 处理。"""
        del content_type
        if isinstance(self._payload, (str, bytes)):
            raise ValueError("响应不是合法的 JSON")
        return self._payload

    async def text(self, errors: str | None = None) -> str:
        """返回 payload 的文本形式。"""
        del errors
        return str(self._payload)


class FakeSession:
    """记录请求参数的假会话；可给多个响应按顺序回放。"""

    def __init__(self, response: FakeResponse | list[FakeResponse]) -> None:
        self._queue: list[FakeResponse] = (
            list(response) if isinstance(response, list) else [response]
        )
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        """记录调用并返回队列中下一个响应（耗尽后复用最后一个）。"""
        self.calls.append((url, kwargs))
        if len(self._queue) > 1:
            return self._queue.pop(0)
        return self._queue[0]


class BrokenSession:
    """get() 直接抛连接错误的会话。"""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error or aiohttp.ClientConnectionError("连接失败")

    def get(self, url: str, **kwargs: Any) -> None:
        """抛出连接错误。"""
        del url, kwargs
        raise self.error
