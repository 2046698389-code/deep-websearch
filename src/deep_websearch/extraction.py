"""Bounded public-page extraction; DNS addresses are validated and pinned."""
import asyncio
from datetime import datetime, timezone
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
import httpx


async def resolve_public(host, port):
    try:
        rows = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(row[4][0] for row in rows))
    except OSError:
        raise ValueError("Page hostname could not be resolved") from None
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Only public Internet addresses may be fetched")
    return addresses[0]


class PageFetcher:
    def __init__(self, timeout=20, *, transport=None, resolver=resolve_public):
        self.timeout = timeout
        self.transport = transport
        self.resolver = resolver

    async def fetch(self, url, max_chars=12000):
        if not isinstance(max_chars, int) or not 200 <= max_chars <= 30000:
            raise ValueError("max_chars must be 200–30000")
        if not isinstance(url, str) or len(url) > 4096:
            raise ValueError("url must be an HTTP(S) URL of at most 4096 characters")
        original = url
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport,
                                     follow_redirects=False, trust_env=False) as client:
            for _ in range(6):
                parsed = urlsplit(url)
                if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError("Only HTTP(S) URLs without embedded credentials may be fetched")
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                if port not in (80, 443):
                    raise ValueError("Only public HTTP(S) ports 80 and 443 may be fetched")
                host = parsed.hostname.encode("idna").decode("ascii")
                address = await self.resolver(host, port)
                # DNS cannot be resolved a second time by the transport: connect to validated IP.
                pinned = httpx.URL(url).copy_with(host=address)
                authority = f"[{host}]" if ":" in host else host
                host_header = authority if parsed.port is None else f"{authority}:{port}"
                try:
                    async with client.stream("GET", pinned, headers={"Host": host_header,
                            "User-Agent": "deep-websearch/0.1", "Accept": "text/html,text/plain"},
                            extensions={"sni_hostname": host}) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location:
                                raise ValueError("Redirect response had no destination")
                            url = urljoin(url, location)
                            continue
                        if response.is_error:
                            raise ValueError(f"Page returned HTTP {response.status_code}")
                        mime = response.headers.get("content-type", "").lower().split(";")[0]
                        if mime not in ("text/html", "application/xhtml+xml", "text/plain"):
                            raise ValueError("Page is not HTML or plain text; binary/PDF extraction is unsupported")
                        chunks = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > 2 * 1024 * 1024:
                                raise ValueError("Page exceeds the 2 MiB extraction limit")
                            chunks.append(chunk)
                        raw = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
                except (httpx.HTTPError, UnicodeError):
                    raise ValueError("Page could not be fetched within the network limits") from None
                title = ""
                if mime in ("text/html", "application/xhtml+xml"):
                    soup = BeautifulSoup(raw, "html.parser")
                    title = soup.title.get_text(" ", strip=True) if soup.title else ""
                    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "form"]):
                        tag.decompose()
                    main = soup.find("main") or soup.find("article") or soup.body or soup
                    content = main.get_text("\n", strip=True)
                else:
                    content = raw.strip()
                return {"url": original, "final_url": url, "title": title,
                        "text": content[:max_chars], "truncated": len(content) > max_chars,
                        "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        "content_type": mime, "untrusted_content": True,
                        "limitation": "No JavaScript, login, paywall bypass, video transcription, or PDF parsing."}
        raise ValueError("Page exceeded the redirect limit")
