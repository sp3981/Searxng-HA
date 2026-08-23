# SearXNG 联网搜索（Home Assistant 自定义集成）

> HACS 自定义集成：复用已有的 SearXNG 实例，为 Home Assistant 中的大模型对话代理
> （DeepSeek / OpenAI / Google Generative AI 等）提供**联网搜索工具**。

## 功能特性

- 遵循 Home Assistant 官方 **LLM 工具 API**（`llm.py` 暴露 `async_get_tools`），把「搜索」注册为对话模型可调用的工具；
- 工具内部调用 SearXNG 的 JSON 接口 `/search?q=...&format=json`，取前 N 条结果的**标题、链接、摘要**返回给模型；
- SearXNG 地址、可选用户名/密码（HTTP Basic Auth）、返回条数、超时时间全部通过**界面配置**，不硬编码；
- 全程异步（aiohttp），**零第三方依赖**；
- 任何失败都抛出标准 `llm.ToolError`，给出友好中文提示，绝不导致 Home Assistant 崩溃。

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

1. 把本仓库推送到 GitHub；
2. 打开 HACS → **集成** → 右上角 **⋮** → **自定义存储库**；
3. 「存储库」填入本仓库的 Git 地址，类别选择 **集成**，点击添加；
4. 在 HACS 中搜索 **SearXNG 联网搜索**，点击下载；
5. **重启 Home Assistant**；
6. 前往 **设置 → 设备与服务 → 添加集成**，搜索 `SearXNG`，按向导完成配置。

### 方式二：手动安装

把本仓库的 `custom_components/searxng_llm` 目录整个复制到 Home Assistant 配置目录的
`custom_components/` 下（即 `<config>/custom_components/searxng_llm/`），
重启 Home Assistant 后，按方式一第 6 步添加集成。

## 配置

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| SearXNG 地址 | 实例根地址，如 `https://searx.example.com`（不要带 `/search`） | 必填 |
| 用户名 | HTTP Basic Auth 用户名（可选） | 空 |
| 密码 | HTTP Basic Auth 密码（可选） | 空 |
| 返回结果条数 | 每次搜索返回给模型的结果数（1–20） | 5 |
| 超时时间 | 请求超时秒数（3–60） | 15 |

保存时会立即执行一次连通性测试：地址不通、认证失败或未启用 JSON 输出都会给出
明确的中文提示，修正后重试即可。

后续修改参数：**设置 → 设备与服务 → SearXNG 联网搜索 → 配置**。

## 使用方法

1. 先配置好一个基于大模型的对话代理，例如 DeepSeek Conversation、
   OpenAI Conversation、Google Generative AI 等；
2. **设置 → 语音助手**，选择该对话代理。集成注册的 **SearXNG 联网搜索**
   工具会自动提供给基于 LLM 的对话代理（若对话代理的配置界面提供工具开关，请确认已勾选）；
3. 直接提问，模型会在需要实时信息时自动调用搜索工具，例如：
   - “帮我搜索一下今天的北京天气”
   - “DeepSeek-V3 有什么最新消息？”

模型收到的是结构化结果（查询词 + 前 N 条 `标题/链接/摘要`），会自然融入最终回答。

## 故障排查

| 现象 | 原因与处理 |
| --- | --- |
| 配置时报「无法连接 SearXNG」 | 检查地址、网络，确认 SearXNG 已启动且 Home Assistant 能访问 |
| 配置时报「认证失败」 | 检查用户名/密码（HTTP 401），或实例的访问控制 |
| 提示「未启用 JSON 输出」（HTTP 403 / 非 JSON 响应） | `settings.yml` 的 `search.formats` 缺少 `json`，加入后重启 SearXNG |
| 工具不出现 / 模型不调用 | 确认 HA ≥ 2024.6、已重启、对话代理基于 LLM 且工具已启用；查看 `home-assistant.log` |
| 运行中 SearXNG 挂了 | 对话中会收到中文错误说明（如「无法连接 SearXNG……」），HA 不会崩溃；SearXNG 恢复后自动继续可用 |

## 工作原理

```
对话代理 ──► LLM 工具 API（llm.py：SearxngAPIInstance.async_get_tools）
                └─► tool.py：search() ──► GET /search?q=...&format=json（aiohttp）
                                            └─► 取前 N 条 {标题, 链接, 摘要}
失败时：SearxngError ──► llm.ToolError（标准异常 + 中文提示，对话不中断）
```

## 目录结构与实现说明

```
.
├── hacs.json
├── README.md
├── custom_components/
│   └── searxng_llm/
│       ├── manifest.json   集成清单（无第三方依赖、config_flow）
│       ├── __init__.py     条目装配：注册 / 注销 LLM API
│       ├── config_flow.py  界面配置向导（连通性验证 + 选项流）
│       ├── const.py        常量与默认值
│       ├── llm.py          HA 官方 LLM 工具 API 实现（async_get_tools）
│       ├── tool.py         SearXNG JSON 客户端（纯 aiohttp，可独立测试）
│       └── strings.json    中文界面文案
└── tests/
    ├── stubs.py            Home Assistant 最小桩（本地测试用）
    ├── test_tool.py        SearXNG 客户端单元测试
    └── test_llm.py         LLM 工具装配与错误处理单元测试
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
