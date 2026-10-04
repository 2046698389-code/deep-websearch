# Social and video source capabilities

All five adapters perform read-only search. `status` without probing inspects local
configuration only. An `enabled` status means the configured adapter can be
attempted; the actual API may still deny permissions, apply quotas, or have an
outage. Provider failures are reported separately from successful empty results.
Each query returns one page with a bounded number of results. Multi-round research
issues multiple planned queries; it does not retrieve a platform's complete index.

## YouTube

Set `YOUTUBE_API_KEY` for a Google project with YouTube Data API v3 enabled.
The adapter uses official `search.list`, restricts results to videos, and returns
titles, descriptions, channel names, timestamps, and watch links. It does not
download video, request caption transcripts, or search video speech.

Options: `order` (default `relevance`), `relevance_language`, `region_code`,
`published_after`, `published_before`. One request returns at most 50 results.
The API applies search quotas; check the project's console for its current
allowance. `quotaExceeded` and `dailyLimitExceeded` are reported as
`quota_exhausted`. [Official search.list reference](https://developers.google.com/youtube/v3/docs/search/list).

## Reddit

Set `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET`. This adapter uses OAuth
`client_credentials` for a confidential web/script application, or a preexisting
`REDDIT_REFRESH_TOKEN` if supplied. It caches access tokens in process memory.
Use `REDDIT_USER_AGENT` to identify your application and contact details.

The adapter searches posts, returning Reddit permalinks, post text, authors,
timestamps, score, and comment count. It does not retrieve comment bodies.
Options: `sort` (default `relevance`), `time_filter` (default `all`), and an optional
single `subreddit`. One request returns at most 100 posts. Credentials do not
override Reddit access approval or commercial-use requirements. Follow current
platform policies before connecting an application.
[Official API reference](https://www.reddit.com/dev/api/#GET_search),
[Reddit-owned OAuth documentation](https://github.com/reddit-archive/reddit/wiki/OAuth2#application-only-oauth).

Reddit's documented `q` limit is 512 characters. Longer simple keyword queries
are reduced while retaining explicit exclusions and field operators. Each result
records the actual request in `metadata.effective_query` and flags reductions
with `metadata.query_reduced`. Overlong quoted, grouped, or Boolean queries fail
locally because cutting their syntax could change their meaning.

## X

Set `X_BEARER_TOKEN` for an approved developer application. The official recent
search endpoint searches the preceding seven days; this adapter does not provide
full archive access. Results include post text, author when returned, timestamps,
permalinks, and public metrics. The API's minimum request size is 10; output is
trimmed to the caller's limit. Maximum request size is 100.

Options: `include_retweets` (default `false`), `start_time`, and `end_time` within
the recent-search window. Requests may require paid platform access or consume
billable allowance. Keep X disabled until its access and spend are authorized;
the plugin does not purchase access. Tokens alone do not guarantee endpoint
entitlement. [X-owned recent search quickstart](https://github.com/xdevplatform/docs/blob/main/x-api/posts/search/quickstart/recent-search.mdx).

The adapter targets the documented standard recent-search limit of 512
characters, including operators. It reserves room for `-is:retweet` when that
exclusion is enabled and preserves existing exclusions and field operators when
reducing long simple keyword queries. It never duplicates an existing
`-is:retweet`. Overlong quoted, grouped, or Boolean syntax fails locally with a
request to shorten the query. `metadata.effective_query` contains the actual API
query; `metadata.query_reduced` reports a reduction. Research provenance records
the actual query and retains `planned_query` when provider adaptation changed it.
[X-owned search limits](https://github.com/xdevplatform/docs/blob/main/x-api/posts/search/introduction.mdx).

## Bilibili

No credentials are needed for this best-effort public website adapter. It first
requests the public homepage and keeps only cookies returned by that website in
the HTTP client's memory. It then tries the unsigned legacy web search endpoint
`https://api.bilibili.com/x/web-interface/search/type`, with `search_type=video`.
This is an **unofficial public web interface**, not a documented Bilibili OpenAPI
contract, and can stop working at any time. The public endpoint behavior has
offline contract tests but has not been certified with a live production query.

Option: `order` (default `totalrank`). Only the first page is requested, capped at
20 videos. Results include watch links, cleaned titles/descriptions, authors,
timestamps, and view counts when available. The implementation does not calculate
WBI signatures, synthesize device cookies, import browser login sessions, solve
CAPTCHA, or bypass anti-bot challenges. A blocked public homepage or rejected web
API yields a source failure; the plugin proceeds with other configured sources.
[Bilibili public website](https://www.bilibili.com/),
[Bilibili official Open Platform](https://open.bilibili.com/) (separate product).

## Douyin

This adapter uses the documented official video search capability:
`GET https://open.douyin.com/dy_open_api/v1/search/video/`. Set
`DOUYIN_CLIENT_KEY` and `DOUYIN_CLIENT_SECRET`, obtain approval for
`aweme.dy.video_search`, then explicitly set `options.search_permission: true`.
Also provide the required valid Int64 device identifier through `options.device_id`
or `DOUYIN_DEVICE_ID`. The plugin does not invent a device identifier.
**Keys alone leave this source unavailable.** The config flag records the
operator's approval assertion; the server verifies actual entitlement.

The adapter obtains and caches `client_token` using official
`POST https://open.douyin.com/oauth/client_token/` with
`grant_type=client_credential`. Search uses the documented `access-token` header
and `data.data.video_list` response. Options: `sort_type` (0 relevance, 1 likes,
2 latest), `publish_time` (0 unrestricted, 1 day, 7 days, 180 days). One first-page
request is capped at 20 results. It returns provided high quality text when
available; it does not independently transcribe video.

Platform errors for unapproved capability, invalid tokens, exhausted quota, and
server failures produce explicit source statuses. No undocumented scraping or
gateway is attempted. Different application types may have different permission
availability, so verify access in the application's console.
[Official video search reference](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/douyin-search-capability/aweme-dy-video-search),
[Official client_token reference](https://partner.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/account-permission/client-token/).

## Verification

`tests/test_social_adapters.py` uses HTTPX MockTransport with dummy credentials.
It checks provider request shapes, token caching, disabled-source behavior,
metadata mapping, explicit permission gates, quota/rate-limit separation,
HTML cleaning, and rejection of challenge responses. Tests send no external
queries and do not prove a particular operator's live platform entitlement.
