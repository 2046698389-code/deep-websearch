# TikOmni / TikHub 平台搜索

这两个服务与官方平台密钥是不同的访问方式。插件识别 `TIKOMNI_API_KEY` 和 `TIKHUB_API_KEY`，兼容用户原字段 `Itkomni_key`、`TikOmni_key`、`TikHub_key`。密钥只通过 Authorization Bearer 发送至对应的固定 API 域名，不进入查询参数、日志、结果或归档。

`sources.<platform>.options.provider` 支持 auto / official / tikomni / tikhub。auto 优先已经配置好的官方或公开来源，否则 TikOmni、TikHub。一次查询只调用选定的服务；接口错误和余额不足会报告，不自动切换另一个计费账户。显式配置和禁用开关均优先。

| 平台 | 方法 | 服务内路径 |
|---|---|---|
| YouTube | GET | youtube/web_v2/get_general_search_v2 |
| Reddit | GET | reddit/app/fetch_dynamic_search |
| X | GET | twitter/web/fetch_search_timeline |
| 抖音 | POST | douyin/search/fetch_video_search_v2 |
| Bilibili（显式选择服务） | GET | bilibili/app/fetch_search_by_type |

TikOmni 基址为 `https://api.tikomni.com/api/u1/v1/`，TikHub 基址为 `https://api.tikhub.io/api/v1/`。只取首批结果并按调用限制截断，不自动翻页。Bilibili 默认保留无需密钥的公开接口。

`source_status.providers` 列出服务是否已配置；平台状态说明选中的服务。配置完整不等于已验证接口。真实 `broad_search` 的结果、来源与覆盖记录携带 `provider`、`method=provider_api`。`native_search_completed` 只计官方/公开适配器，`provider_successful_queries` 计第三方服务，`platform_search_completed` 计两者。网页索引回退另算。

HTTP 402 对应 quota_exhausted，429 对应 rate_limited，401/403 对应凭据或权限拒绝，HTTP 200 下的非成功业务 code 也会报错。不会原样回显上游错误文本。TikOmni 返回的 Reddit `children[].post.postTitle`、Markdown 内容、原帖链接，YouTube 结构化视频结果，Twitter GraphQL Tweet 与抖音 aweme 都有对应解析和测试。

瞬时限流、账户额度和上游平台变化按实际调用结果报告。一般网页搜索需另配已支持的搜索引擎；这两个服务不会自动变成 Google/全网搜索。

接口契约来源：

- [TikHub 官方 API](https://api.tikhub.io/)
- [TikHub 官方 Python SDK](https://github.com/TikHub/TikHub-API-Python-SDK)
- [TikOmni YouTube 结构化搜索](https://docs.tikomni.com/432245131e0)
- [TikOmni Reddit 搜索](https://docs.tikomni.com/418753253e0)
- [TikOmni X 搜索](https://docs.tikomni.com/418753218e0)
- [TikOmni Bilibili 搜索](https://docs.tikomni.com/418753192e0)
