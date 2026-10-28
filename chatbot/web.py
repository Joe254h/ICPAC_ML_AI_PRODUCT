"""Wikipedia and the open web for the Copilot: read-only, small and public.

Three lookups: a Wikipedia summary (in any Wikipedia language), a web search, and the text
of one public web page. Only http(s) pages on public internet addresses are read: every
address a host name resolves to is checked, and the connection goes to the checked address,
so a name cannot be pointed at the service's own network afterwards. Redirects are followed
by hand and checked the same way. Pages are cut to a few thousand characters of text.

What a page says is information for the answer, never an instruction to the Copilot.
COPILOT_WEB=false switches all three off. BRAVE_SEARCH_API_KEY, when set, uses the Brave
Search API; otherwise the search reads DuckDuckGo's HTML results page.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote, urljoin, urlsplit

import httpcore
import httpx

#: Wikipedia editions of the member states' languages, and the region's other languages.
WIKIPEDIAS = {
    "en": "English",
    "sw": "Kiswahili",
    "am": "Amharic",
    "so": "Somali",
    "ar": "Arabic",
    "fr": "French",
    "ti": "Tigrinya",
    "om": "Afaan Oromo",
    "rw": "Kinyarwanda",
    "rn": "Kirundi",
    "lg": "Luganda",
}
MAX_BYTES = 1_500_000
MAX_TEXT = 6000
TIMEOUT = httpx.Timeout(20, connect=8)
AGENT = "ICPAC-Week2-Copilot/1.0 (https://www.icpac.net; forecast service assistant)"


class WebUnavailable(Exception):
    """The lookup could not be made; the message says why, in words."""


def enabled() -> bool:
    return os.getenv("COPILOT_WEB", "true") != "false"


def _public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global and not ip.is_multicast


def public_addresses(host: str, port: int) -> list[str]:
    """The host's addresses, if every one of them is a public internet address."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise WebUnavailable(f"{host} could not be found") from exc
    addresses = sorted({str(info[4][0]) for info in infos})
    if not addresses or not all(_public(a) for a in addresses):
        raise WebUnavailable("Only public web pages can be read")
    return addresses


class _PublicOnly(httpcore.SyncBackend):
    """Connects only to checked public addresses (the one checked, not a fresh lookup)."""

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            addresses = public_addresses(host, port)
        except WebUnavailable as exc:
            raise httpcore.ConnectError(str(exc)) from exc
        last: Exception | None = None
        for address in addresses:
            try:
                return super().connect_tcp(address, port, timeout, local_address, socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last = exc
        assert last is not None
        raise last


def client() -> httpx.Client:
    transport = httpx.HTTPTransport()
    transport._pool = httpcore.ConnectionPool(
        ssl_context=httpx.create_ssl_context(), network_backend=_PublicOnly()
    )
    # trust_env=False: a proxy from the environment would bypass the address checks.
    return httpx.Client(
        transport=transport,
        timeout=TIMEOUT,
        trust_env=False,
        headers={"User-Agent": AGENT, "Accept-Language": "en"},
    )


def check_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise WebUnavailable("Only http and https web pages can be read")
    if parts.username or parts.password:
        raise WebUnavailable("Web addresses with passwords are not read")
    try:
        ipaddress.ip_address(parts.hostname)
    except ValueError:
        pass
    else:
        if not _public(parts.hostname):
            raise WebUnavailable("Only public web pages can be read")
    return parts.geturl()


def get(url: str, session: httpx.Client | None = None, params=None) -> httpx.Response:
    """GET a public page, following up to three redirects, each checked; at most
    MAX_BYTES are read."""
    own = session is None
    session = session or client()
    try:
        for _ in range(4):
            url = check_url(url)
            with session.stream("GET", url, params=params) as response:
                if response.is_redirect and "location" in response.headers:
                    url, params = urljoin(url, response.headers["location"]), None
                    continue
                body = b""
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        break
                return httpx.Response(
                    response.status_code,
                    headers=response.headers,
                    content=body[:MAX_BYTES],
                    request=response.request,
                )
        raise WebUnavailable("The page redirects too many times")
    except httpx.HTTPError as exc:
        raise WebUnavailable(f"The page could not be reached ({type(exc).__name__})") from exc
    finally:
        if own:
            session.close()


class _Text(HTMLParser):
    """A page's title and readable text, without scripts, styles and navigation."""

    SKIP = {"script", "style", "noscript", "nav", "footer", "header", "svg", "form", "aside"}
    BREAK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BREAK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        joined = re.sub(r"[ \t\r\f\v]+", " ", "".join(self.parts))
        return re.sub(r"\n\s*\n+", "\n\n", joined).strip()


def read_page(url: str) -> dict[str, Any]:
    response = get(url)
    if response.status_code >= 400:
        raise WebUnavailable(f"The page answered with an error ({response.status_code})")
    kind = response.headers.get("content-type", "")
    if "html" in kind:
        parser = _Text()
        parser.feed(response.text)
        title, text = parser.title.strip(), parser.text()
    elif kind.startswith("text/"):
        title, text = "", response.text.strip()
    else:
        raise WebUnavailable("Only web pages and plain text can be read")
    return {
        "url": str(response.request.url),
        "title": unescape(title)[:200] or str(response.request.url),
        "text": text[:MAX_TEXT],
        "truncated": len(text) > MAX_TEXT,
    }


def wikipedia(query: str, language: str = "en") -> dict[str, Any]:
    """The best-matching Wikipedia article's summary, in the language's edition."""
    if language not in WIKIPEDIAS:
        raise WebUnavailable("That Wikipedia language is not available here")
    base = f"https://{language}.wikipedia.org"
    with client() as session:
        found = get(f"{base}/w/rest.php/v1/search/page", session, params={"q": query, "limit": 3})
        if found.status_code >= 400:
            raise WebUnavailable("Wikipedia did not answer the search")
        pages = found.json().get("pages") or []
        if not pages:
            return {"language": WIKIPEDIAS[language], "articles": []}
        articles = []
        for page in pages[:2]:
            summary = get(f"{base}/api/rest_v1/page/summary/{quote(page['key'], safe='')}", session)
            if summary.status_code >= 400:
                continue
            data = summary.json()
            articles.append(
                {
                    "title": data.get("title") or page.get("title"),
                    "summary": (data.get("extract") or "")[:1800],
                    "url": (data.get("content_urls") or {}).get("desktop", {}).get("page")
                    or f"{base}/wiki/{quote(page['key'])}",
                }
            )
    return {"language": WIKIPEDIAS[language], "articles": articles}


_RESULT = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>'
    r'.*?class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
    re.S,
)


def _plain(fragment: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _target(href: str) -> str:
    """DuckDuckGo's redirect link's real address."""
    href = unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    parts = urlsplit(href)
    if parts.path.startswith("/l/"):
        return parse_qs(parts.query).get("uddg", [href])[0]
    return href


def search(query: str, count: int = 5) -> list[dict[str, str]]:
    """Web results: title, address and snippet."""
    key = os.getenv("BRAVE_SEARCH_API_KEY")
    if key:
        response = _brave(query, key, count)
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": _plain(r.get("description", "")),
            }
            for r in (response.get("web") or {}).get("results", [])[:count]
        ]
    response = get("https://html.duckduckgo.com/html/", params={"q": query})
    if response.status_code >= 400:
        raise WebUnavailable("The web search did not answer")
    results = []
    for match in _RESULT.finditer(response.text):
        url = _target(match.group("href"))
        if not url.startswith(("http://", "https://")):
            continue
        results.append(
            {
                "title": _plain(match.group("title")),
                "url": url,
                "snippet": _plain(match.group("snippet")),
            }
        )
        if len(results) == count:
            break
    return results


def _brave(query: str, key: str, count: int) -> dict[str, Any]:
    with client() as session:
        try:
            response = session.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": count},
                headers={"X-Subscription-Token": key, "Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise WebUnavailable("The web search did not answer") from exc
    if response.status_code >= 400:
        raise WebUnavailable(f"The web search refused the request ({response.status_code})")
    return response.json()
