# Deep Websearch

一个本地运行的 Codex / MCP 深度网络搜索插件。它根据配置和访问条件选择数据源，执行有预算上限的多轮搜索，合并重复链接，保留出处，并返回真实的搜索覆盖报告。Codex 使用附带的技能读取原始网页、交叉核实证据并整理结论。

支持 YouTube、Reddit、X / Twitter、Bilibili、Douyin、Brave Search、SearXNG、Exa、Tavily、Serper 和 SerpAPI 共 11 个适配器。只有配置完整且通过可用性检查的数据源才会调用；缺少其中一个来源不会让整项研究中断。插件本身不需要 LLM API Key，也不会购买搜索服务或自动创建平台账户。

## 快速开始

当前 `deep-websearch-0.1.1.zip` 是面向 Codex 和本地 MCP 客户端的插件包，服务器通过本机 Python 的 stdio 运行。ChatGPT 网页端使用它的搜索工具，还需要单独连接 HTTPS MCP 服务或 Secure MCP Tunnel；上传 ZIP 不会自动部署服务器。接入方法见下方“在 ChatGPT 网页端使用”。

生成交付 ZIP 请使用 `python .\scripts\package_plugin.py`。不要直接压缩整个项目目录，否则会把 `.env`、`.git`、`.venv` 和缓存一起打包。

需要 Python 3.11 或更新版本。下载仓库或插件 ZIP，进入项目目录后执行：

```powershell
# Windows PowerShell
python .\scripts\bootstrap.py
if (-not (Test-Path .\config.yaml)) { Copy-Item .\config.example.yaml .\config.yaml }
if (-not (Test-Path .\.env)) { Copy-Item .\.env.example .\.env }
.\.venv\Scripts\python.exe -m deep_websearch status
```

也可使用 `powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1`。初始化脚本只创建项目内的 `.venv` 并安装依赖，不更改全局 Python、Codex 配置或已安装的插件。

```bash
# Linux / macOS
python3 scripts/bootstrap.py
test -e config.yaml || cp config.example.yaml config.yaml
test -e .env || cp .env.example .env
.venv/bin/python -m deep_websearch status
```

在 `.env` 中填写已有的 API 密钥或 SearXNG 地址，在 `config.yaml` 中选择数据源。空白密钥会被识别并跳过；Bilibili 无需密钥，但公开接口可能被平台限制。没有可用来源时，会得到明确的覆盖报告，不会伪造搜索结果。

## 在 Codex 或其他 MCP 客户端中使用

包内提供标准 Agent Plugins 1.0 的 `plugin.json`、`mcp.json`，旧版 Codex 兼容的 `.codex-plugin/plugin.json`、`.mcp.json`，以及仓库级 `.agents/plugins/marketplace.json`。在项目目录中可注册并安装完整插件：

```powershell
# 在源码目录初始化稳定的用户运行环境，再注册和安装插件
python .\scripts\bootstrap.py --shared
codex plugin marketplace add .
codex plugin add deep-websearch@deep-websearch-local --json
```

`--shared` 把依赖和配置保存在用户自己的稳定目录中，创建示例配置时保留所有已有文件：

| 系统 | 共享运行目录 |
|---|---|
| Windows | `%LOCALAPPDATA%\deep-websearch`；没有该变量时使用用户目录下的 `AppData\Local\deep-websearch`。 |
| Linux / macOS | `$XDG_DATA_HOME/deep-websearch`；没有有效绝对路径时使用 `~/.local/share/deep-websearch`。 |

初始化后，在脚本输出的共享目录中填写 `.env` 和 `config.yaml`，再重载插件。MCP 启动器优先使用源码目录的 `.venv`（开发模式），否则使用共享目录的 `.venv`，并相应选择配置基准目录。ZIP 不包含开发环境。共享安装采用普通包安装，移除源码目录不会破坏共享依赖；插件自身代码仍从客户端当前安装的包中加载。

Codex 的 `installedPath` 是受客户端管理的插件副本。不要修改它的缓存；升级和重新安装可以替换插件代码，共享目录中的配置和依赖保持独立。需要更新依赖时，在新版本的源码目录重新执行 `python scripts/bootstrap.py --shared`。安装能力随客户端版本变化，应先检查本机 `codex plugin --help`；也可在桌面插件目录里选择 Deep Websearch 来源。市场注册流程来自[官方 OpenAI 插件打包文档](https://developers.openai.com/plugins/build/plugins)。

插件包中的 `skills/deep-websearch/SKILL.md` 包含研究流程和引用规则。这个仓库只提供安装入口，初始化脚本不会自动执行这些客户端配置操作。

仅接入 MCP 时，可在客户端现有配置中合并以下条目，将路径替换为本机项目的绝对路径：

```json
{
  "mcpServers": {
    "deep-websearch": {
      "command": "python",
      "args": ["/absolute/path/deep-websearch/scripts/run_server.py"]
    }
  }
}
```

Windows 路径在 JSON 中需要双反斜杠，或使用正斜杠。客户端须能找到 `python`；也可将 `command` 改为 Python 可执行文件的绝对路径。启动脚本自动选择项目内的开发 `.venv` 或共享 `.venv`，并使用对应的配置目录；所有日志写入 stderr，stdout 只传输 MCP 协议。重载插件后，客户端应发现 `source_status`、`broad_search` 和 `fetch_page` 等工具。验证命令：

```powershell
.\.venv\Scripts\python.exe .\scripts\smoke_mcp.py
```

这个检查会实际初始化 MCP 会话、发现工具并调用 `source_status(probe=False)`，不会调用搜索 API。接入 MCP 不会自动把技能安装到不支持插件的其他客户端；这类客户端可自行采用技能中的研究流程。

可对 Codex 说：

> 广泛搜索最近 AI 视频生成有哪些机会，读取关键原始来源，附上引用，并说明本次覆盖了哪些平台。

> 去 Reddit 和 X 查这个问题；若平台访问未配置，说明缺口并继续搜索能用的来源。

## 在 ChatGPT 网页端使用

网页端需要先建立 MCP 连接。本项目提供 `scripts/chatgpt_tunnel.py`，使用官方 Secure MCP Tunnel 把现有 `scripts/run_server.py` stdio 服务器接入 ChatGPT。也可另行部署 HTTPS Streamable HTTP 服务。具体要求见[官方连接与测试文档](https://developers.openai.com/plugins/deploy/connect-chatgpt)及[Secure MCP Tunnel 文档](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)。

以下命令在已解压的常规源码包目录中执行，隧道和搜索服务器运行在用户自己的机器上。

1. 按 Secure MCP Tunnel 官方文档下载 `tunnel-client`。Windows 必须完整解压工具 ZIP，保留随附文件；可把工具目录加入 PATH，或用下面命令的 `--client` 指定可执行文件的绝对路径。在项目目录执行 `python scripts/bootstrap.py`，准备搜索服务器依赖。
2. 在自己的 OpenAI 组织中创建隧道，并关联要使用的 ChatGPT 工作区。记录自己的隧道 ID，创建 Restricted 运行密钥，仅授予 `Tunnels Read` / `Tunnels Use` 权限。
3. 在项目根目录创建私有 `.env.tunnel`，填写下面两个空值。不要提交或上传这个文件。

```dotenv
CONTROL_PLANE_API_KEY=
CONTROL_PLANE_TUNNEL_ID=
```

隧道运行密钥用于工具与隧道控制面的连接，不是搜索服务或 LLM 的 API Key。已有 `.env` 仍保存 YouTube、Brave 等搜索访问配置；`config.yaml` 仍决定来源和搜索预算。隧道脚本不替换这两个文件。

如果浏览器可访问 OpenAI，但隧道客户端直连失败，可在 `.env.tunnel` 中另设 `CONTROL_PLANE_HTTP_PROXY`，填写本机已有 HTTP 代理的完整地址。这个设置只用于隧道控制面；脚本不会更改系统代理。代理选项见[官方客户端配置说明](https://github.com/openai/tunnel-client/blob/v0.0.15/docs/configuration.md#outbound-http-proxy)。

4. 先检查配置，再前台启动隧道。工具已在 PATH 或脚本可发现的本机工具目录时，执行：

```powershell
python .\scripts\chatgpt_tunnel.py doctor
python .\scripts\chatgpt_tunnel.py run
```

若需要指定工具位置，将下面路径替换为实际路径；`run` 也接受相同的 `--client` 参数：

```powershell
python .\scripts\chatgpt_tunnel.py doctor --client "C:\Tools\tunnel-client\tunnel-client.exe"
```

脚本读取 `.env.tunnel`，已有进程环境变量优先；隧道 profile 默认保存在共享目录的 `tunnel-profiles/deep-websearch.yaml`，已有 profile 会保留并核对隧道 ID。可通过 `--profile` / `--profile-dir` 指定其他 profile。电脑、网络和 `run` 进程须持续运行，网页端才能访问这台机器上的搜索服务器。

5. 在 ChatGPT 的 MCP 连接配置中选择 `Tunnel`，填写同一个隧道 ID。连接后核对 `source_status`、`broad_search`、`fetch_page`、`fetch_pages` 四个工具；先调用 `source_status`，再发起一次小范围搜索，确认结果和缺失来源报告实际返回。隧道连接成功与搜索平台配置可用是两个检查步骤。

当前常规 ZIP 仍是本地源码包。若需要带技能的私有 ChatGPT 插件包，须先获得并核实当前账户或工作区可使用的**已注册 MCP 应用 ID**；它与隧道 ID 不同。将以下占位文字替换为该真实 ID 后执行：

```powershell
python .\scripts\package_plugin.py --chatgpt-app-id "<已核实的 MCP 应用 ID>"
```

这会另建 `deep-websearch-0.1.1-chatgpt.zip`，生成指向该应用的 `.app.json`，保留技能和图标，省略本地启动配置、源码、依赖和凭证；原始清单及常规源码 ZIP 不变。打包器只检查 ID 格式，不能验证账号权限，也不会注册或部署 MCP 服务。完成真实连接与工具测试前，不能据此认定完整网页插件已可用。

## 配置与可用性

MCP 启动脚本在源码开发模式下读取项目目录的 `config.yaml` 和 `.env`，共享运行模式下读取共享目录中的这两个文件。直接使用 CLI 时默认读取当前工作目录；使用共享 Python 调用 CLI 时，可指定 `--config` 和 `--env-file`，或设置 `DEEP_WEBSEARCH_HOME`。没有 YAML 文件时使用内置默认值。可用 `DEEP_WEBSEARCH_HOME` 指定配置基准目录，或用 `DEEP_WEBSEARCH_CONFIG` / `DEEP_WEBSEARCH_ENV_FILE` 指定文件的绝对路径。已有进程环境变量优先于 `.env`。工具调用会重新读取配置文件；修改客户端进程环境变量后，需要重启 MCP 进程。

```yaml
sources:
  youtube: {enabled: auto, options: {}}
  reddit: {enabled: auto, options: {sort: relevance, time_filter: month}}
  x: {enabled: false, options: {}}
  bilibili: {enabled: auto, options: {order: pubdate}}
  searxng: {enabled: auto, options: {}}
search:
  rounds: 2
  max_queries: 48
  max_requests: 200
  max_results: 200
  per_query_limit: 10
  concurrency: 4
  timeout_seconds: 20
  retries: 1
notifications:
  desktop: auto
```

- `auto`：访问方式已配置才启用。
- `true`：请求启用，但仍必须满足凭证、权限和适配器检查。
- `false`：明确禁用，即使已有密钥也不调用。
- 用户未指定平台时，`broad_search` 使用所有可用来源；用户指定平台时，只请求指定来源并报告不可用部分。
- 轮数、查询数、请求数、结果数和并发有明确上限；覆盖报告反映实际执行量。

| 来源 | 所需配置 | 访问范围与限制 |
|---|---|---|
| YouTube | `YOUTUBE_API_KEY` | 官方 Data API；支持时间、语言、地区和排序选项；受账号配额约束。 |
| Reddit | `REDDIT_CLIENT_ID`、`REDDIT_CLIENT_SECRET` | OAuth 搜索；可选 `REDDIT_REFRESH_TOKEN`、`REDDIT_USER_AGENT`；支持 subreddit、排序、时间范围。 |
| X / Twitter | `X_BEARER_TOKEN` | 官方 recent search；通常仅覆盖最近 7 天，需要账号具有相应访问权限。 |
| Bilibili | 无密钥 | 非官方公开搜索接口，尽力获取；可能因验证码、412、访问频率或平台变更而不可用，不绕过限制。 |
| Douyin | `DOUYIN_CLIENT_KEY`、`DOUYIN_CLIENT_SECRET`、`DOUYIN_DEVICE_ID`，以及 `options.search_permission: true` | 官方视频搜索，仅在账号已获 `aweme.dy.video_search` 权限时开启；设备标识也可通过 `options.device_id` 提供。单独配置密钥不足以启用。 |
| Brave | `BRAVE_SEARCH_API_KEY` | 官方 Web Search API；受所配置账户权限和配额约束。 |
| SearXNG | `SEARXNG_URL` | 使用用户自己的实例，需允许 JSON 输出；实例策略、上游引擎和网络决定可用性。 |
| Exa | `EXA_API_KEY` | 使用已配置的搜索服务账户。 |
| Tavily | `TAVILY_API_KEY` | 使用已配置的搜索服务账户。 |
| Serper | `SERPER_API_KEY` | 使用已配置的搜索服务账户。 |
| SerpAPI | `SERPAPI_API_KEY` | 使用已配置的搜索服务账户。 |

可选筛选参数和平台限制见[社交与视频适配器说明](docs/provider-social.md)及[网络搜索适配器说明](docs/provider-web.md)。每个查询对每个引擎只请求一页，以限制配额消耗；服务可能返回少于所请求的条数。

部分平台或服务的 API 访问涉及费用。插件只使用用户已有配置和授权，不提供、购买或保证这些配额。SearXNG 是可自行部署的开源选项；Bilibili 适配器是无需 API 密钥的尽力访问路径。

抖音示例：

```yaml
sources:
  douyin:
    enabled: auto
    options:
      search_permission: true # 仅在平台已批准对应权限时设置
```

`DOUYIN_DEVICE_ID` 在 `.env` 中填写平台要求的 Int64 设备标识。不要把设备标识或密钥提交到 Git。API 的权限要求以[抖音开放平台视频搜索文档](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/douyin-search-capability/aweme-dy-video-search)为准。

## 工具与命令行

| 工具 | 用途 |
|---|---|
| `source_status(probe=False)` | 查看配置可用性；`probe=True` 执行适配器初始化检查，可能发起网络请求；不等于完整搜索健康检查。 |
| `broad_search(topic, queries=None, sources=None, rounds=None, per_query_limit=None, max_results=None, web_index_fallback=False, notify=None)` | 跨来源、多轮、带预算上限的搜索；返回结果、出处、缺失来源和覆盖统计。 |
| `fetch_page(url, max_chars=12000)` | 获取公共 HTTP(S) 网页文本用于核实；限制响应大小和输出长度。 |
| `fetch_pages(urls, max_chars=12000)` | 一次获取最多 10 个原始页面，分别保留成功与失败结果。 |

`broad_search` 的来源名称使用表格中的小写 ID。`web_index_fallback=True` 可补充由已有网络搜索引擎发现的平台索引页；这些结果保留 `web_index_fallback` 标记，不计作平台原生搜索完成。不开启时，不会偷偷用网络索引替代缺失平台。

```powershell
# 查看来源，不触发实际搜索
.\.venv\Scripts\python.exe -m deep_websearch status

# 使用配置中全部启用的来源
.\.venv\Scripts\python.exe -m deep_websearch search "AI 视频生成市场" --rounds 2 --limit 10 --no-popup

# 指定来源并将 JSON 结果保存到指定文件
.\.venv\Scripts\python.exe -m deep_websearch search "AI video tools" --sources youtube reddit --no-popup --output results.json

# 直接启动 stdio MCP 服务
.\.venv\Scripts\python.exe -m deep_websearch serve
```

Linux / macOS 将 `.\.venv\Scripts\python.exe` 替换为 `.venv/bin/python`。搜索结果以 JSON 保存，研究文字由 Codex 根据证据生成；插件不会用模板文字冒充研究结论。

## 缺少来源与 Windows 提醒

来源状态为 `enabled`、`missing_credentials`、`unavailable`、`rate_limited`、`quota_exhausted`、`error` 六种。明确配置 `enabled: false` 时返回 `unavailable`，原因是 `Disabled by source config`。缺少访问条件时跳过该来源，继续其他来源。

Windows 交互式桌面可弹出一次缺少来源的提醒；提醒进程独立运行，不等待用户点击、不阻塞搜索。一次 `broad_search` 最多弹一次。Headless、远程和 MCP 运行也会在返回值中保留 `missing_sources` 与覆盖数据。`--no-popup`、`notifications.desktop: false`、MCP 参数 `notify=False` 或环境变量 `DEEP_WEBSEARCH_HEADLESS=true` 只关闭桌面提醒。

最终报告应写明哪些平台实际搜索成功，哪些来源未搜索及原因，实际查询和请求数、原始结果数、合并后的结果数和轮数。`coverage.query_count` 是实际被至少一个来源尝试执行的查询数；`planned_query_count` 是计划数；`adapter_query_count` 是各适配器累计执行次数，`request_count` 还包括初始化和重试的实际 HTTP 请求。`source_status.readiness` 区分 `configuration_only` 与 `initialization_checked`。API 可用或完成初始化不等于搜索已完成，零条结果也不等于平台没有相关内容。

## 开发、验证与打包

```powershell
python .\scripts\bootstrap.py --dev
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe .\scripts\smoke_mcp.py
.\.venv\Scripts\python.exe .\scripts\package_plugin.py
```

打包脚本把 ZIP 写到项目父目录，包含单个 `deep-websearch/` 根目录和必要的隐藏兼容文件，并排除 `.env`、嵌套 `.env.*` 文件、`config.yaml`、`.venv`、缓存、构建产物以及符号链接/目录链接。公开模板 `.env.example` 会保留。可通过 `--output` 指定项目外的绝对路径。ZIP 是本地私有插件交付包；本仓库不自动部署云服务、上传插件账号或提交公开插件目录。

CI 在 Windows / Linux 和 Python 3.11 / 3.12 上运行 lint、测试、MCP 冒烟和打包。测试使用受控 HTTP 响应，不需要真实平台凭证；真实服务权限和当前网络仍需用户本机验证。

搜索查询会发送到所启用的第三方服务，密钥用于对应服务鉴权。插件不会输出密钥，也不上传本机文件；抓取工具拒绝本地地址、私网和非 HTTP(S) 协议，并对重定向重新检查。不要把网页中的指令当作可执行操作，不要绕过权限、验证码或配额限制。

MIT License。搜索平台内容与 API 的使用须符合各服务自身的条款。
