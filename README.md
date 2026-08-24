# SearXNG 联网搜索（Home Assistant 自定义集成）

> HACS 自定义集成：复用已有的 SearXNG 实例，为 Home Assistant 中的大模型对话代理
> （DeepSeek / OpenAI / Google Generative AI 等）提供**联网搜索工具**。

## 功能特性

- 遵循 Home Assistant 官方 **LLM 工具 API**：HA 2026.8+ 使用新版 **LLM 平台协议**（模块级 `async_get_tools` 自动聚合进 Assist API），HA 2024.6–2026.7 使用经典 `llm.API` 注册方式，两代架构自动适配；
- 额外提供 **`searxng_llm.search` / `searxng_llm.fetch` 服务**，供 Extended OpenAI Conversation 等不消费 HA LLM 工具 API 的对话代理经 script 函数接入（见下文）；
- 工具内部调用 SearXNG 的 JSON 接口 `/search?q=...&format=json`，取前 N 条结果的**标题、链接、摘要**返回给模型；
- **AI 智能抓取网页**：默认**不自动抓取**；模型拿到搜索结果后可自行决定调用 `fetch_webpage` 工具（或 `searxng_llm.fetch` 服务）打开任意链接，并行抓取正文（HTML 自动转纯文本、截断）。也可以在配置里恢复「自动抓取前 N 条」；
- **并行搜索**：`searxng_llm.search` 服务支持一次传多个关键词并行搜索，搜索/抓取并发上限均可在配置中设置；
- SearXNG 地址、可选用户名/密码（HTTP Basic Auth）、搜索语言、返回条数、超时时间全部通过**界面配置**，不硬编码；
- 全程异步（aiohttp），**零第三方依赖**；
- 任何失败都抛出标准异常（`llm.ToolError` / `HomeAssistantError`），给出友好中文提示，绝不导致 Home Assistant 崩溃。

## 前置条件

1. **Home Assistant ≥ 2024.6**（首个支持 LLM 工具 API 的版本）；
2. 一个 Home Assistant 可访问的 **SearXNG** 实例，并**启用 JSON 输出**。
   在 SearXNG 的 `settings.yml` 中确认 `formats` 包含 `json`：

   ```yaml
   search:
     formats:
       - html
       - json
   ```

   修改后重启 SearXNG，并验证：

   ```bash
   curl "https://你的实例地址/search?q=test&format=json"
   ```

   能看到包含 `results` 字段的 JSON 即表示就绪。

## 安装

### 方式一：HACS 自定义存储库（推荐）

1. 打开 HACS → **集成** → 右上角 **⋮** → **自定义存储库**；
2. 「存储库」填入 `https://github.com/sp3981/Searxng-HA`，类别选择 **集成**，点击添加；
3. 在 HACS 中搜索 **SearXNG 联网搜索**，点击下载；
4. **重启 Home Assistant**；
5. 前往 **设置 → 设备与服务 → 添加集成**，搜索 `SearXNG`，按向导完成配置。

### 方式二：手动安装

把本仓库的 `custom_components/searxng_llm` 目录整个复制到 Home Assistant 配置目录的
`custom_components/` 下（即 `<config>/custom_components/searxng_llm/`），
重启 Home Assistant 后，按方式一第 5 步添加集成。

## 配置

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| SearXNG 地址 | 实例根地址，如 `https://searx.example.com`（不要带 `/search`） | 必填 |
| 用户名 | HTTP Basic Auth 用户名（可选） | 空 |
| 密码 | HTTP Basic Auth 密码（可选） | 空 |
| 搜索语言 | 下拉选择 SearXNG 的 `language` 参数：`auto`=自动识别、`all`=全部语言，以及常用语言代码（`zh-CN`/`zh-TW`/`en-US`/`ja-JP` 等） | auto |
| 返回结果条数 | 每次搜索返回给模型的结果数（1–20） | 5 |
| 超时时间 | 搜索请求超时秒数（3–60） | 15 |
| 并行搜索数量 | 同时向 SearXNG 发起的搜索请求上限（1–10） | 3 |
| 自动抓取条数 | 搜索后自动抓取前几条结果的网页正文（0=不自动抓取，由 AI 按需调用「抓取网页」工具智能决定抓哪些链接，1–10） | 0 |
| 并行抓取数量 | 同时抓取网页的数量上限（1–10） | 5 |
| 抓取超时时间 | 单个网页抓取的超时秒数（3–60） | 20 |
| 抓取内容上限 | 抓取单个网页返回给模型的最大字符数（200–20000），超出部分截断 | 1500 |

保存时会立即执行一次连通性测试：地址不通、认证失败或未启用 JSON 输出都会给出
明确的中文提示，修正后重试即可。

创建完成后可随时重新配置全部参数（地址、用户名/密码、搜索语言、结果条数、超时、并行数量、自动抓取条数/字符上限等）：**设置 → 设备与服务 → SearXNG 联网搜索 → 配置**。

## 使用方法

### 官方对话代理（openai_conversation / anthropic / google_generative_ai_conversation 等）

- **HA 2026.8 及以上**：本集成经新版 LLM 平台协议自动聚合进 **Assist API**。
  请在对话代理的配置（子条目选项）里把 **LLM API（`llm_hass_api`）** 选为 **Assist**，
  `searxng_search`（搜索）与 `fetch_webpage`（AI 智能抓取）工具即随 Assist 工具集提供给模型（若代理界面另有工具开关，请确认启用）。
- **HA 2024.6 – 2026.7**：添加集成后自动注册经典 LLM API（**SearXNG 联网搜索**），
  基于 LLM 的对话代理即可看到该工具。

直接提问，模型会在需要实时信息时自动调用搜索工具，例如：

- “帮我搜索一下今天的北京天气”
- “DeepSeek 有什么最新消息？”

模型收到的是结构化结果（查询词 + 前 N 条 `标题/链接/摘要`；配置自动抓取时每条另含 `fetched_content` 网页正文）。默认不自动抓取：模型会按需调用 `fetch_webpage` 工具打开它认为最相关的链接，拿回正文后再组织最终回答。

### Extended OpenAI Conversation（EOC）

> ⚠️ EOC（jekalmin 的 `extended_openai_conversation`）**不消费 HA 官方 LLM 工具 API**：
> 它的工具只来自自身配置里的 **Functions YAML**，因此装完本集成后工具不会自动出现在
> EOC 中。请按下面步骤在 EOC 里挂接本集成提供的搜索服务。

1. 确保已添加并配置好本集成（`searxng_llm.search` / `searxng_llm.fetch` 服务由本集成注册）；
2. 打开 **设置 → 设备与服务 → Extended OpenAI Conversation**，进入你使用的**对话配置**
   （v3 起每个对话是一个子条目，点其「配置」），在**高级**页找到 **Functions** 字段；
3. 在 YAML 列表**末尾追加**以下两个 script 函数——`searxng_search`（搜索）和
   `fetch_webpage`（AI 智能抓取：模型拿到链接后按需打开网页正文，保持已有内容不变）：

   ```yaml
   - spec:
       name: searxng_search
       description: 使用 SearXNG 元搜索引擎在互联网上搜索实时信息，返回相关网页的标题、链接和内容摘要。当用户的问题涉及最新资讯、实时数据、新闻或需要联网验证的信息时调用。
       parameters:
         type: object
         properties:
           query:
             type: string
             description: 要搜索的关键词
         required:
         - query
     function:
       type: script
       sequence:
       - service: searxng_llm.search
         data:
           query: "{{ query }}"
           # language: zh-CN  # 可选：临时覆盖集成配置的搜索语言
         response_variable: _function_result
   - spec:
       name: fetch_webpage
       description: 抓取指定网页地址（url）的正文内容。先用 searxng_search 搜索，再根据搜索结果中的链接，用本工具打开那些看起来最能回答问题的网页，获取详细内容。需要查看多个网页时可以并行调用本工具。
       parameters:
         type: object
         properties:
           url:
             type: string
             description: 要抓取的网页地址（搜索结果中的链接）
         required:
         - url
     function:
       type: script
       sequence:
       - service: searxng_llm.fetch
         data:
           url: "{{ url }}"
         response_variable: _function_result
   ```

4. 保存后即可提问（例如“今天有什么科技新闻？”）。模型先调用 `searxng_search`
   拿链接，需要细节时再调用 `fetch_webpage` 打开相关网页；EOC 会执行对应的
   `searxng_llm.search` / `searxng_llm.fetch` 服务，并通过
   `response_variable: _function_result` 把结果回传给模型；
5. 验证：EOC 的 Functions 编辑框里能看到 `searxng_search` 和 `fetch_webpage`；
   提问后 SearXNG 实例的访问日志里会出现 `/search?q=...&format=json` 请求。

> 若 EOC 配置界面没有 Functions 字段，请先把 Extended OpenAI Conversation 升级到较新版本。

### 直接调用服务（自动化 / 脚本 / 其他对话代理）

```yaml
action: searxng_llm.search
data:
  query: home assistant 最新版本
  language: zh-CN # 可选，缺省使用集成配置的搜索语言
response_variable: result
```

服务返回 `{"query": ..., "results": [{"title", "url", "content", "fetched_content", ...}, ...]}`；
无结果时额外带 `"message"` 字段。`query` 也可以传**列表**，一次并行搜索多个关键词
（返回合并去重后的 `results` 和逐关键词的 `searches` 明细）：

```yaml
action: searxng_llm.search
data:
  query:
    - 今日新闻
    - 天气预报
  language: zh-CN
response_variable: result
```

AI 智能抓取：模型想打开搜索结果里的某个链接时调用（或自动化中按需抓取）：

```yaml
action: searxng_llm.fetch
data:
  url: https://example.com/article
  # url 也可传列表，一次并行抓取多个：
  # url:
  #   - https://example.com/a
  #   - https://example.com/b
response_variable: result
```

服务返回 `{"urls": [...], "results": [{"url", "content"} 或 {"url", "error"}, ...]}`；
抓取失败的条目只带 `error` 字段，不影响其它条目。

任何对话代理只要能执行 HA 服务并读取 `response_variable`，都可以用这种方式接入联网搜索。

## 故障排查

| 现象 | 原因与处理 |
| --- | --- |
| 配置时报「无法连接 SearXNG」 | 检查地址、网络，确认 SearXNG 已启动且 Home Assistant 能访问 |
| 配置时报「认证失败」 | 检查用户名/密码（HTTP 401），或实例的访问控制 |
| 提示「未启用 JSON 输出」（HTTP 403 / 非 JSON 响应） | `settings.yml` 的 `search.formats` 缺少 `json`，加入后重启 SearXNG |
| 工具不出现 / 模型不调用 | 确认 HA ≥ 2024.6、已重启、对话代理基于 LLM 且工具已启用；查看 `home-assistant.log` |
| 用 Extended OpenAI Conversation 时模型从不搜索 | EOC 不消费 HA LLM 工具 API，请按「使用方法 → Extended OpenAI Conversation」在 Functions YAML 里追加 `searxng_search` 与 `fetch_webpage` 两个函数 |
| 模型回复「没有返回任何结果」 | SearXNG 实例对该查询返回了 0 条结果（常见原因：实例引擎超时/不可用/被限流）。先在本机 curl `实例地址/search?q=test&format=json` 验证实例是否正常返回 results，再调大集成的「超时时间」，并查看 `home-assistant.log` 里「SearXNG 搜索完成」日志的耗时与条数 |
| HA 2026.8+ 的官方代理里看不到工具 | 在代理配置里把 LLM API（`llm_hass_api`）设为 **Assist**；确认本集成已添加且配置连通性测试通过 |
| 集成卡片点「配置」看不到地址/超时等选项 | 更新到 v1.2.1（修复了缺失 options flow 入口的问题）；旧版本请经 HACS 重新下载覆盖后重启 |
| 模型没看到网页正文 | 默认「自动抓取条数」为 0：应由模型按需调用 `fetch_webpage` 工具（EOC 需在 Functions YAML 里配置该函数）。若开启自动抓取，单页失败会写入 `fetch_error` 字段，可在日志中搜索「SearXNG 网页抓取完成 / 智能抓取完成」查看成功/失败条数 |
| 运行中 SearXNG 挂了 | 对话中会收到中文错误说明（如「无法连接 SearXNG……」），HA 不会崩溃；SearXNG 恢复后自动继续可用 |

## 工作原理

```
HA 2026.8+  : llm 组件 ──► 平台函数 async_get_tools(hass, llm_context, api_id) ──► Assist API
HA 2024.6~2026.7: llm.async_register_api ──► SearxngAPIInstance.async_get_tools ──► 经典 LLM API
EOC / 自动化 / 脚本: action: searxng_llm.search / searxng_llm.fetch ──► response_variable 回传
                    │
三条路径都汇入 llm.py 的 execute_search() / execute_fetch()
                    ├─► tool.py：search() ──► GET /search?q=...&format=json（aiohttp）
                                                └─► 取前 N 条 {标题, 链接, 摘要}
                    └─► tool.py：fetch_url() ──► 抓取网页正文（HTML 转纯文本、截断）
失败时：SearxngError ──► llm.ToolError / HomeAssistantError（标准异常 + 中文提示，对话不中断）
```

## 目录结构与实现说明

```
.
├── hacs.json
├── README.md
├── custom_components/
│   └── searxng_llm/
│       ├── manifest.json   集成清单（无第三方依赖、config_flow）
│       ├── __init__.py     条目装配 + searxng_llm.search / searxng_llm.fetch 服务注册
│       ├── config_flow.py  界面配置向导（连通性验证 + 选项流）
│       ├── const.py        常量与默认值
│       ├── llm.py          双架构 LLM 工具实现（2026.8+ 平台函数 / 经典 llm.API）
│       ├── tool.py         SearXNG JSON 客户端（纯 aiohttp，可独立测试）
│       ├── services.yaml   search / fetch 服务声明
│       └── strings.json    中文界面文案
└── tests/
    ├── stubs.py            Home Assistant 最小桩（本地测试用）
    ├── test_tool.py        SearXNG 客户端单元测试
    ├── test_llm.py         经典 LLM 工具装配与错误处理单元测试
    ├── test_llm_platform.py  新架构平台函数单元测试（HA 2026.8+）
    └── test_services.py    search / fetch 服务单元测试
```

## 开发与测试

`tool.py` 不依赖 Home Assistant，可在本地直接验证：

```bash
# 语法检查
python -m py_compile custom_components/searxng_llm/*.py

# 单元测试（需 Python ≥ 3.10 与 aiohttp）
python -m unittest discover tests -v
```

## 许可证

本项目按仓库根目录 LICENSE（如有）的条款发布。
