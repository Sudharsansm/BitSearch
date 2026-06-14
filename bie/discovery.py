"""
Free, no-API-key, real-time web search discovery for BIE.

This module answers the question: *"given a query, what URLs on the
internet are relevant right now?"* — without requiring any paid API,
subscription, or API key.

It tries multiple lightweight, no-JS public search endpoints **in order**,
falling back automatically if one is blocked, rate-limited, or returns
no results:

  1. DuckDuckGo HTML  (``https://html.duckduckgo.com/html/``)
  2. DuckDuckGo Lite  (``https://lite.duckduckgo.com/lite/``)
  3. Bing HTML        (``https://www.bing.com/search``)

A fourth backend, ``searxng``, can be enabled to query a self-hosted
`SearXNG <https://github.com/searxng/searxng>`_ instance — this is the
most reliable no-API-key option, since it isn't subject to the same
rate-limiting / bot-detection / HTML-layout churn as scraping DDG/Bing
directly.

The set and order of backends is configurable via the ``BIE_DISCOVERY_BACKENDS``
environment variable (or the ``backends=`` argument), e.g.::

    export BIE_DISCOVERY_BACKENDS=searxng,ddg_html,ddg_lite,bing_html
    export BIE_SEARXNG_URL=http://localhost:8080

This is the **discovery** step. BIE then crawls the discovered URLs with
Bitscrape and ranks the extracted content with its hybrid BM25+vector
index — giving a genuine "type a query, get a real-time answer from the
internet" experience with zero configuration and zero cost.

Diagnostics
-----------
If every configured backend fails, :func:`discover_urls` still returns
``[]`` (callers should treat this as "try again", not "no results exist"
— see :func:`bie.quicksearch.websearch`'s fallback behaviour). However,
it logs a single, actionable ``warning``-level message that distinguishes:

* **network-blocked** — every backend failed at the connection level
  (``httpx.RequestError``: connection refused, DNS failure, proxy
  denial such as an ``x-deny-reason: host_not_allowed`` header from an
  egress proxy, timeouts, etc.). This means *this process* cannot reach
  the public internet (or these specific hosts) at all — check the
  environment's network/proxy configuration.
* **blocked / rate-limited** — backends responded with an error status
  (commonly ``403``/``429``/``503``), suggesting the search engine is
  rate-limiting or bot-blocking this IP. Retrying later, lowering query
  volume, or switching to ``searxng`` usually helps.
* **empty response** — backends returned ``200 OK`` but the page
  contained no parseable results (e.g. a CAPTCHA/consent page, or the
  result page's HTML structure changed). This can indicate the scraper's
  selectors are out of date.

Call :func:`get_last_discovery_diagnostics` after a failed
:func:`discover_urls` call to inspect the per-backend failure details
programmatically (e.g. to surface a more specific error to end users).
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx

logger = logging.getLogger("bie.discovery")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# DuckDuckGo wraps result links as //duckduckgo.com/l/?uddg=<encoded-url>&...
_DDG_REDIRECT_RE = re.compile(r"^(?:https?:)?//duckduckgo\.com/l/\?")

# Tracking/redirector domains we never want to treat as a "real" result
_BLOCKED_HOST_FRAGMENTS = (
    "duckduckgo.com",
    "bing.com/search",
    "go.microsoft.com",
    "r.search.yahoo.com",
)

_DEFAULT_BACKENDS = ("ddg_html", "ddg_lite", "bing_html")

# Categories used in BackendFailure.category — see module docstring.
NETWORK_BLOCKED = "network_blocked"
BLOCKED_OR_RATE_LIMITED = "blocked_or_rate_limited"
EMPTY_RESPONSE = "empty_response"
UNKNOWN_BACKEND = "unknown_backend"
NOT_CONFIGURED = "not_configured"
OTHER_ERROR = "other_error"


@dataclass(frozen=True)
class BackendFailure:
    """Diagnostic record for why a single discovery backend failed."""

    backend: str
    category: str
    detail: str


@dataclass
class DiscoveryDiagnostics:
    """Per-call diagnostics from the most recent :func:`discover_urls`."""

    query: str = ""
    failures: list[BackendFailure] = field(default_factory=list)
    succeeded_backend: str | None = None

    @property
    def all_failed(self) -> bool:
        return self.succeeded_backend is None

    def category_counts(self) -> Counter:
        return Counter(f.category for f in self.failures)

    def summary(self) -> str:
        """A short, human-readable diagnosis of why discovery failed."""
        if not self.all_failed:
            return f"backend '{self.succeeded_backend}' returned results"
        if not self.failures:
            return "no backends were attempted"

        counts = self.category_counts()
        total = len(self.failures)
        details = "; ".join(f"{f.backend}={f.category} ({f.detail})" for f in self.failures)

        if counts.get(NETWORK_BLOCKED, 0) == total:
            return (
                "All discovery backends failed at the network/connection level "
                f"({details}). This process cannot reach these search endpoints "
                "at all — check outbound network/proxy/firewall configuration "
                "for this environment (sandboxes often allowlist only specific "
                "domains). This is an environment issue, not a BIE bug."
            )
        if counts.get(BLOCKED_OR_RATE_LIMITED, 0) == total:
            return (
                "All discovery backends responded but refused the request "
                f"({details}). This usually means the search engine is "
                "rate-limiting or bot-blocking this IP. Try again later, "
                "reduce request volume, or configure a 'searxng' backend "
                "via BIE_DISCOVERY_BACKENDS / BIE_SEARXNG_URL."
            )
        if counts.get(EMPTY_RESPONSE, 0) == total:
            return (
                "All discovery backends returned 200 OK but no parseable "
                f"results ({details}). This often means a CAPTCHA/consent "
                "page was served instead of results, or the result page's "
                "HTML structure changed."
            )
        return f"All discovery backends failed with mixed errors: {details}"


_diagnostics_lock = threading.Lock()
_last_diagnostics = DiscoveryDiagnostics()


def get_last_discovery_diagnostics() -> DiscoveryDiagnostics:
    """Return diagnostics for the most recent :func:`discover_urls` call.

    Useful after ``discover_urls(...)`` returns ``[]`` to find out *why*
    (network-blocked vs. rate-limited vs. empty/CAPTCHA response) without
    needing to enable debug logging.

    Note: not safe to rely on across concurrent calls from multiple
    threads — for concurrent use, parse :func:`discover_urls`'s log
    output, or call discovery from a single thread/queue.
    """
    with _diagnostics_lock:
        return _last_diagnostics


def _get_configured_backends() -> list[str]:
    """Read the ordered backend list from ``BIE_DISCOVERY_BACKENDS``
    (comma-separated), falling back to the built-in default order.
    Unknown names are kept (and reported as ``unknown_backend`` failures
    at call time) rather than silently dropped, so misconfiguration is
    visible.
    """
    raw = os.environ.get("BIE_DISCOVERY_BACKENDS", "")
    names = [n.strip() for n in raw.split(",") if n.strip()]
    return names or list(_DEFAULT_BACKENDS)


# Alias kept for backwards compatibility with callers/tests that use the
# shorter name.
_configured_backends = _get_configured_backends


def discover_urls(
    query: str,
    max_results: int = 5,
    timeout: float = 15.0,
    backends: list[str] | None = None,
) -> list[str]:
    """Return up to ``max_results`` candidate URLs for ``query`` from the
    live web — no API key required.

    Tries each backend in ``backends`` (default: the
    ``BIE_DISCOVERY_BACKENDS`` env var, or ``ddg_html,ddg_lite,bing_html``)
    in order, stopping at the first one that returns usable results.

    Args:
        query: The natural-language search query.
        max_results: Maximum number of URLs to return.
        timeout: HTTP request timeout in seconds (per attempt).
        backends: Optional explicit ordered list of backend names,
            overriding ``BIE_DISCOVERY_BACKENDS``. Built-in names:
            ``"ddg_html"``, ``"ddg_lite"``, ``"bing_html"``, ``"searxng"``
            (the latter requires ``BIE_SEARXNG_URL`` to be set).

    Returns:
        A list of absolute, deduplicated URLs in result order. Returns an
        empty list only if every backend fails — callers should treat this
        as "try again" rather than "no results exist". Call
        :func:`get_last_discovery_diagnostics` to find out why.
    """
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
    }

    backend_names = backends if backends is not None else _get_configured_backends()
    diagnostics = DiscoveryDiagnostics(query=query)

    for name in backend_names:
        fetch_name = _BACKEND_FETCHER_NAMES.get(name)
        if fetch_name is None:
            logger.warning(
                "Discovery backend %r is not recognized — skipping. "
                "Known backends: %s",
                name,
                ", ".join(_BACKEND_FETCHER_NAMES),
            )
            diagnostics.failures.append(
                BackendFailure(name, UNKNOWN_BACKEND, "not a recognized backend name")
            )
            continue

        if name == "searxng" and not os.environ.get("BIE_SEARXNG_URL"):
            logger.warning(
                "Discovery backend 'searxng' is configured but BIE_SEARXNG_URL "
                "is not set — skipping. Set it to your SearXNG instance's base "
                "URL, e.g. BIE_SEARXNG_URL=http://localhost:8080"
            )
            diagnostics.failures.append(
                BackendFailure(name, NOT_CONFIGURED, "BIE_SEARXNG_URL is not set")
            )
            continue

        try:
            fetch = globals()[fetch_name]
            with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
                html = fetch(client, query)
        except httpx.HTTPStatusError as exc:
            category, detail = _categorize_status_error(exc)
            logger.warning("Discovery backend %s failed: %s (%s)", name, detail, category)
            diagnostics.failures.append(BackendFailure(name, category, detail))
            continue
        except httpx.RequestError as exc:
            detail = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Discovery backend %s failed at the connection level: %s. "
                "If this is unexpected, check outbound network/proxy access "
                "to this host from this environment.",
                name,
                detail,
            )
            diagnostics.failures.append(BackendFailure(name, NETWORK_BLOCKED, detail))
            continue
        except Exception as exc:  # noqa: BLE001 - never let one backend crash discovery
            detail = f"{type(exc).__name__}: {exc}"
            logger.warning("Discovery backend %s raised an unexpected error: %s", name, detail)
            diagnostics.failures.append(BackendFailure(name, OTHER_ERROR, detail))
            continue

        if not html:
            diagnostics.failures.append(
                BackendFailure(name, EMPTY_RESPONSE, "response body was empty")
            )
            continue

        urls = _parse_result_urls(html, max_results)
        if urls:
            logger.debug("Discovery backend %s returned %d url(s)", name, len(urls))
            diagnostics.succeeded_backend = name
            _set_last_diagnostics(diagnostics)
            return urls

        diagnostics.failures.append(
            BackendFailure(
                name,
                EMPTY_RESPONSE,
                "got a 200 OK response but no results could be parsed "
                "(possibly a CAPTCHA/consent page or changed HTML layout)",
            )
        )

    _set_last_diagnostics(diagnostics)
    logger.warning(
        "All discovery backends failed or returned no results for query=%r. %s",
        query,
        diagnostics.summary(),
    )
    return []


def _set_last_diagnostics(diagnostics: DiscoveryDiagnostics) -> None:
    global _last_diagnostics
    with _diagnostics_lock:
        _last_diagnostics = diagnostics


def _categorize_status_error(exc: httpx.HTTPStatusError) -> tuple[str, str]:
    """Distinguish an egress-proxy denial (e.g. a sandbox's
    ``x-deny-reason: host_not_allowed`` header) from a genuine
    rate-limit/bot-block response from the search engine itself.
    """
    response = exc.response
    deny_reason = response.headers.get("x-deny-reason")
    if deny_reason:
        return (
            NETWORK_BLOCKED,
            f"HTTP {response.status_code}, x-deny-reason={deny_reason!r} "
            "(this environment's egress proxy blocked the request)",
        )
    return (BLOCKED_OR_RATE_LIMITED, f"HTTP {response.status_code}")


def discover_urls_multi(
    queries: list[str],
    max_results_per_query: int = 5,
    max_total: int = 15,
    timeout: float = 15.0,
    backends: list[str] | None = None,
) -> list[str]:
    """Run :func:`discover_urls` for several query variants and merge the
    results, ranked by how many variants surfaced each URL.

    This implements simple **query fan-out**: searching multiple phrasings
    of the same question (e.g. the original query plus a couple of
    rewordings) surfaces a broader, more relevant set of candidate pages
    than a single query alone — particularly for ambiguous or
    multi-faceted questions.

    Args:
        queries: Query variants to search, in priority order. The first
            is treated as the primary query.
        max_results_per_query: How many URLs to fetch per query variant.
        max_total: Maximum number of URLs to return overall.
        timeout: Per-request timeout in seconds.
        backends: Optional explicit ordered list of backend names, passed
            through to each :func:`discover_urls` call.

    Returns:
        Deduplicated URLs, ordered by (number of variants that returned
        them, then first-seen order). URLs found by multiple query
        variants are considered more likely relevant.
    """
    url_votes: dict[str, int] = {}
    url_order: dict[str, int] = {}
    order_counter = 0

    for query in queries:
        for url in discover_urls(
            query, max_results=max_results_per_query, timeout=timeout, backends=backends
        ):
            if url not in url_votes:
                url_votes[url] = 0
                url_order[url] = order_counter
                order_counter += 1
            url_votes[url] += 1

    ranked = sorted(url_votes.keys(), key=lambda u: (-url_votes[u], url_order[u]))
    return ranked[:max_total]


def _fetch_ddg_html(client: httpx.Client, query: str) -> str:
    resp = client.post("https://html.duckduckgo.com/html/", data={"q": query})
    resp.raise_for_status()
    return resp.text


def _fetch_ddg_lite(client: httpx.Client, query: str) -> str:
    resp = client.post("https://lite.duckduckgo.com/lite/", data={"q": query})
    resp.raise_for_status()
    return resp.text


def _fetch_bing_html(client: httpx.Client, query: str) -> str:
    resp = client.get("https://www.bing.com/search", params={"q": query, "form": "QBLH"})
    resp.raise_for_status()
    return resp.text


def _fetch_searxng_html(client: httpx.Client, query: str) -> str:
    """Query a self-hosted SearXNG instance's HTML results page.

    Requires ``BIE_SEARXNG_URL`` to be set to the instance's base URL
    (e.g. ``http://localhost:8080``). SearXNG aggregates multiple search
    engines server-side and exposes a stable HTML/JSON API, making it the
    most reliable no-API-key discovery option when self-hosted.
    """
    base_url = os.environ["BIE_SEARXNG_URL"]  # presence checked by caller
    search_url = urljoin(base_url.rstrip("/") + "/", "search")
    resp = client.get(search_url, params={"q": query, "format": "html"})
    resp.raise_for_status()
    return resp.text


_BACKEND_FETCHER_NAMES = {
    "ddg_html": "_fetch_ddg_html",
    "ddg_lite": "_fetch_ddg_lite",
    "bing_html": "_fetch_bing_html",
    "searxng": "_fetch_searxng_html",
}


def _parse_result_urls(html: str, max_results: int) -> list[str]:
    """Extract organic result URLs from a search results page.

    Handles:
      - DuckDuckGo HTML:  ``<a class="result__a" href="...">``
      - DuckDuckGo Lite:  ``<a class="result-link" href="...">``
      - Bing:             ``<li class="b_algo">...<a href="...">``
      - SearXNG HTML:     ``<a class="url_header" href="...">`` /
                          ``<h3><a href="...">`` result articles
    """
    hrefs = re.findall(r'class="result__a"[^>]*href="([^"]+)"', html)
    if not hrefs:
        hrefs = re.findall(r'class="result-link"[^>]*href="([^"]+)"', html)
    if not hrefs:
        hrefs = _extract_bing_hrefs(html)
    if not hrefs:
        hrefs = _extract_searxng_hrefs(html)

    urls: list[str] = []
    seen: set[str] = set()
    for href in hrefs:
        url = _resolve_redirect(href)
        if not url or not url.startswith("http"):
            continue
        if _is_blocked_host(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= max_results:
            break

    return urls


def _extract_bing_hrefs(html: str) -> list[str]:
    """Extract result links from Bing's organic result blocks
    (``<li class="b_algo">``)."""
    hrefs: list[str] = []
    for block in re.findall(r'<li class="b_algo".*?</li>', html, flags=re.S):
        m = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"', block)
        if m:
            hrefs.append(m.group(1))
    return hrefs


def _extract_searxng_hrefs(html: str) -> list[str]:
    """Extract result links from a SearXNG HTML results page
    (``<a class="url_header" href="...">`` within ``<article class="result">``)."""
    hrefs: list[str] = []
    for block in re.findall(r'<article class="result[^"]*".*?</article>', html, flags=re.S):
        m = re.search(r'<a[^>]*class="url_header"[^>]*href="([^"]+)"', block)
        if not m:
            m = re.search(r'<a[^>]*href="([^"]+)"', block)
        if m:
            hrefs.append(m.group(1))
    return hrefs


def _resolve_redirect(href: str) -> str | None:
    """Unwrap DuckDuckGo's ``//duckduckgo.com/l/?uddg=<url-encoded-target>``
    redirect links to get the real target URL. Other links pass through
    unchanged."""
    href = href.strip().replace("&amp;", "&")

    if _DDG_REDIRECT_RE.match(href):
        parsed = urlparse(href if href.startswith("http") else f"https:{href}")
        qs = parse_qs(parsed.query)
        target = qs.get("uddg", [None])[0]
        return unquote(target) if target else None

    return href


def _is_blocked_host(url: str) -> bool:
    return any(fragment in url for fragment in _BLOCKED_HOST_FRAGMENTS)
