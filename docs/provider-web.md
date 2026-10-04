# General web search providers

Each adapter performs one structured API request for each planned query. The
research engine owns concurrency and the global request budget. A `limit` is an
upper bound, not a guarantee: provider pagination and result availability can
produce fewer rows. No adapter signs up for a service, obtains keys, or enables a
subscription. Configure only credentials and sources you want to use; provider
charges and quotas are controlled by your own account.

| Source | Credential | API and response mapping | Supported `options` |
| --- | --- | --- | --- |
| `brave` | `BRAVE_SEARCH_API_KEY` | `GET https://api.search.brave.com/res/v1/web/search`; `web.results`, `description`, `page_age`; `count` capped at 20 | `country`, `search_lang`, `ui_lang`, `safesearch`, `freshness` |
| `searxng` | `SEARXNG_URL` | `GET <instance>/search?q=…&format=json`; `results`, `content`, `publishedDate` | `engines`, `categories`, `language`, `safesearch`, `time_range` |
| `exa` | `EXA_API_KEY` | `POST https://api.exa.ai/search`; `results`, `publishedDate`, `author`; `numResults` capped at 100 | `type`, `category`, `includeDomains`, `excludeDomains`, `startPublishedDate`, `endPublishedDate`, `include_highlights` |
| `tavily` | `TAVILY_API_KEY` | `POST https://api.tavily.com/search`; Bearer header; `results`, `content`, `published_date`; `max_results` capped at 20 | `search_depth`, `topic`, `time_range`, `include_domains`, `exclude_domains`, `country`, `language` |
| `serper` | `SERPER_API_KEY` | `POST https://google.serper.dev/search`; `X-API-KEY` header; `organic`, `link`, `snippet`, `date` | `gl`, `hl`, `location`, `tbs` |
| `serpapi` | `SERPAPI_API_KEY` | `GET https://serpapi.com/search.json?engine=google`; `organic_results`, `link`, `snippet`, `date` | `gl`, `hl`, `location`, `safe`, `tbs`, `google_domain` |

`SEARXNG_URL` is a trusted, explicitly configured search backend and supports a
self-hosted instance such as `http://localhost:8080`. Its configured path prefix
is preserved. JSON must be enabled in the instance's `search.formats` setting;
public instances commonly disable it or rate-limit clients. Embedded credentials
in URLs are rejected; the other five providers use fixed HTTPS API endpoints.

Exa defaults to `type: auto` and does not request additional extracted content.
Set `include_highlights: true` explicitly if you accept the provider's additional
content operation. A search without content may have an empty snippet. Tavily
defaults to `search_depth: basic`, disables automatic parameter upgrades, and
does not request generated answers or raw content. `search_depth: advanced` is an
explicit user configuration and may consume more credits.

SerpAPI's current Google endpoint documentation does not advertise the old `num`
parameter. The adapter requests one page and truncates locally rather than
relying on an obsolete result-count option. Serper also returns one page; its
result count is capped at 100. Date strings are preserved as reported by the
provider, including relative or uncertain dates; they are not presented as
verified publication timestamps.

Only rows with a usable HTTP(S) URL and a nonempty title enter the evidence list.
Malformed rows are skipped. Markup is stripped from titles and snippets, and
provenance records the source, query, and result URL. Provider request metadata
and raw error messages are not included, so a query-string API key cannot leak
through SerpAPI's `search_parameters` field.

Primary API documentation checked on 2026-10-04:

- [Brave Web Search API](https://api-dashboard.search.brave.com/api-reference/web/search/get)
- [SearXNG Search API](https://docs.searxng.org/dev/search_api.html)
- [Exa Search API](https://exa.ai/docs/reference/search)
- [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)
- [Serper's public API response examples](https://serper.dev/) and [official playground](https://serper.dev/playground). The public playground's code generator confirms the fixed Google endpoint, POST JSON requests, and `X-API-KEY` header; interactive use requires sign-in. No account was created or credentialed request made during verification.
- [SerpAPI Google Search API](https://serpapi.com/search-api)
