"""SearXNG 联网搜索集成的常量定义。"""

from __future__ import annotations

DOMAIN = "searxng_llm"
NAME = "SearXNG 联网搜索"
API_NAME = "SearXNG 联网搜索"

CONF_BASE_URL = "base_url"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_RESULTS = "results"
CONF_TIMEOUT = "timeout"
CONF_LANGUAGE = "language"
CONF_SEARCH_PARALLEL = "search_parallel"
CONF_FETCH_CHARS = "fetch_chars"
CONF_FETCH_COUNT = "fetch_count"
CONF_FETCH_PARALLEL = "fetch_parallel"
CONF_FETCH_TIMEOUT = "fetch_timeout"
CONF_QUERY = "query"
CONF_URL = "url"

# 服务名：searxng_llm.search / searxng_llm.fetch，供 Extended OpenAI
# Conversation 等不消费 HA LLM 工具 API 的对话代理通过 script 函数调用
SERVICE_SEARCH = "search"
SERVICE_FETCH = "fetch"

DEFAULT_RESULTS = 5
DEFAULT_TIMEOUT = 15

# SearXNG /search 接口的 language 参数：auto=自动识别查询语言，
# all=全部语言，也可以填具体语言代码，如 zh-CN、zh、en-US、en
DEFAULT_LANGUAGE = "auto"
DEFAULT_SEARCH_PARALLEL = 3

# 搜索后自动抓取前几条结果：0=不自动抓取（默认），由 AI 按需调用
# 「抓取网页」工具，根据搜索结果智能决定要打开哪些链接
DEFAULT_FETCH_COUNT = 0
DEFAULT_FETCH_PARALLEL = 5
DEFAULT_FETCH_TIMEOUT = 20

# 抓取网页正文返回给模型的单页最大字符数（超出截断）
DEFAULT_FETCH_CHARS = 1500

# LLM 工具的名称与描述（描述会直接交给大模型，引导模型在需要实时信息时调用）
TOOL_NAME = "searxng_search"
TOOL_DESCRIPTION = (
    "使用 SearXNG 元搜索引擎在互联网上搜索实时信息，"
    "返回与关键词相关网页的标题、链接和内容摘要。"
    "当用户的问题涉及最新资讯、实时数据、新闻或需要联网验证的信息时，"
    "应调用此工具获取最新资料。"
)
TOOL_FETCH_NAME = "fetch_webpage"
TOOL_FETCH_DESCRIPTION = (
    "抓取指定网页地址（url）的正文内容。"
    "先用 searxng_search 搜索，再根据搜索结果中的链接，"
    "用本工具打开那些看起来最能回答问题的网页，获取详细内容。"
    "需要查看多个网页时可以并行调用本工具。"
)

# SearxngError 错误码，与 strings.json 中 error 段落的键名一一对应
ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_INVALID_AUTH = "invalid_auth"
ERROR_JSON_DISABLED = "json_format_disabled"
ERROR_INVALID_RESPONSE = "invalid_response"

KNOWN_ERROR_CODES = frozenset(
    {
        ERROR_CANNOT_CONNECT,
        ERROR_INVALID_AUTH,
        ERROR_JSON_DISABLED,
        ERROR_INVALID_RESPONSE,
    }
)

# 配置向导连通性测试使用的关键词（允许零结果，只用于验证协议可用）
TEST_QUERY = "home assistant connectivity test"


# SearXNG 返回 0 条结果时给模型/用户的提示（三种调用路径共用）
EMPTY_RESULTS_MESSAGE = (
    "SearXNG 没有返回任何结果。可能原因：实例引擎超时或不可用、查询无匹配或被限流；"
    "可尝试调大集成的「超时时间」、更换关键词，或直接在浏览器打开实例的 "
    "/search?q=test&format=json 地址检查实例是否正常。"
)
