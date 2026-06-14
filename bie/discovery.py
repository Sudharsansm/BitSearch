"""
Free, no-API-key, real-time web search discovery for BIE.

This module answers the question: *"given a query, what URLs on the
internet are relevant right now?"* — without requiring any paid API,
subscription, or API key.

It tries multiple lightweight, no-JS public search endpoints in order,
falling back automatically if one is blocked, rate-limited, or returns
no results. The default order is:

  1. DuckDuckGo HTML  (``https://html.duckduckgo.com/html/``)
  2. DuckDuckGo Lite  (``https://lite.duckduckgo.com/lite/``)
  3. Bing HTML        (``https://www.bing.com/search``)

This is the **discovery** step. BIE then crawls the discovered URLs with
Bitscrape and ranks the extracted content with its hybrid BM25+vector
index — giving a genuine "type a query, get a real-time answer from the
internet" experience with zero configuration and zero cost.

Configuring backends
---------------------

Scraping search-engine HTML pages is inherently fragile: result markup
changes, and shared/cloud IPs (CI runners, sandboxes, some notebook
hosts) are sometimes rate-limited or blocked outright. The set and order
of backends tried can be overridden with the ``BIE_DISCOVERY_BACKENDS``
environment variable — a comma-separated list of backend names::

    export BIE_DISCOVERY_BACKENDS=ddg_html,ddg_lite,bing_html,searxng

Built-in backend names: ``ddg_html``, ``ddg_lite``, ``bing_html``.

To add a self-hosted `SearXNG <https://docs.searxng.org/>`_ instance (the
realistic long-term fix for persistent rate-limiting), set
``BIE_SEARXNG_URL`` to its base URL (e.g. ``http://localhost:8080``) and
include ``searxng`` in ``BIE_DISCOVERY_BACKENDS``.
"""

from __future__ import annotations

import logging
import os
import re
from urllib.parse import parse_qs, unquote, urlparse

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

_ENV_BACKENDS = "BIE_DISCOVERY_BACKENDS"
_ENV_SEARXNG_URL = "BIE_SEARXNG_URL"


class DiscoveryError(RuntimeError):
    """Raised by :func:`discover_urls` callers that opt into strict mode
    (not raised by :func:`discover_urls` itself, which always returns a
    list — see its docstring). Exposed for callers that want to
    distinguish failure categories programmatically; see
    :class:`BackendFailure`.
    """


class BackendFailure:
    """Records why a single discovery backend attempt did not produce URLs.

    Attributes:
        backend: Backend name (e.g. ``"ddg_html"``).
        category: One of:
            - ``"network_blocked"`` — the request itself failed before a
              response was received (connection error, timeout, DNS
              failure, or a proxy/firewall denial). This usually means
              the *environment* can't reach the backend at all (e.g. a
              sandboxed proxy with an `x-deny-reason: host_not_allowed`
              style policy, or no internet access).
            - ``"http_error"`` — a response was received but with an
              error status code (403, 429, 5xx). Often rate-limiting or
              IP-based blocking.
            - ``"empty_response"`` — a 2xx response was received, but it
              contained no parseable results (e.g. a CAPTCHA/consent page,
              or a markup change this parser doesn't handle).
        detail: Human-readable detail (exception message or status code).
    """

    __slots__ = ("backend", "category", "detail")

    def __init__(self, backend: str, category: str, detail: str) -> None:
        self.backend = backend
        self.category = category
        self.detail = detail

    def __repr__(self) -> str:  # pragma: no cover - convenience only
        return f"BackendFailure(backend={self.backend!r}, category={self.category!r}, detail={self.detail!r})"


def _configured_backends() -> list[str]:
    raw = os.environ.get(_ENV_BACKENDS, "")
    if not raw.strip():
        return list(_DEFAULT_BACKENDS)
    names = [n.strip() for n in raw.split(",") if n.strip()]
    return names or list(_DEFAULT_BACKENDS)


def discover_urls(
    query: str, max_results: int = 5, timeout: float = 15.0
) -> list[str]:
    """Return up to ``max_results`` candidate URLs for ``query`` from the
    live web — no API key required.

    Tries each backend in :func:`_configured_backends` order (default:
    DuckDuckGo HTML, DuckDuckGo Lite, Bing HTML — see module docstring for
    how to configure this via ``BIE_DISCOVERY_BACKENDS``).

    Args:
        query: The natural-language search query.
        max_results: Maximum number of URLs to return.
        timeout: HTTP request timeout in seconds (per attempt).

    Returns:
        A list of absolute, deduplicated URLs in result order. Returns an
        empty list only if every configured backend fails — callers
        should treat this as "try again, or check connectivity" rather
        than "no results exist for this query". When this happens, a
        ``WARNING``-level log message summarizes *why* each backend
        failed (see :func:`discover_urls_detailed` for the structured
        version of this information).
    """
    urls, _failures = discover_urls_detailed(query, max_results=max_results, timeout=timeout)
    return urls


def discover_urls_detailed(
    query: str, max_results: int = 5, timeout: float = 15.0
) -> tuple[list[str], list[BackendFailure]]:
    """Like :func:`discover_urls`, but also returns structured
    :class:`BackendFailure` records for every backend that didn't produce
    results — useful for diagnostics (e.g. distinguishing "network
    blocked" from "got a CAPTCHA page").

    Returns:
        ``(urls, failures)``. ``urls`` is empty only if every backend
        failed; ``failures`` has one entry per attempted backend that
        didn't return usable results (it's empty if the first backend
        tried succeeded).
    """
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
    }

    backend_fns: dict[str, tuple] = {
        "ddg_html": (_fetch_ddg_html, "POST https://html.duckduckgo.com/html/"),
        "ddg_lite": (_fetch_ddg_lite, "POST https://lite.duckduckgo.com/lite/"),
        "bing_html": (_fetch_bing_html, "GET https://www.bing.com/search"),
        "searxng": (_fetch_searxng, "GET <BIE_SEARXNG_URL>/search"),
    }

    failures: list[BackendFailure] = []

    for name in _configured_backends():
        entry = backend_fns.get(name)
        if entry is None:
            logger.warning(
                "Unknown discovery backend %r in %s — skipping. Known backends: %s",
                name,
                _ENV_BACKENDS,
                ", ".join(backend_fns),
            )
            continue

        fetch, description = entry

        try:
            with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
                html = fetch(client, query)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            failure = BackendFailure(
                backend=name,
                category="http_error",
                detail=f"{description} -> HTTP {status}",
            )
            failures.append(failure)
            logger.warning(
                "Discovery backend %s returned HTTP %s (likely rate-limiting or "
                "IP-based blocking): %s",
                name,
                status,
                exc,
            )
            continue
        except httpx.HTTPError as exc:
            # Connection-level failure: DNS error, connection refused/reset,
            # TLS error, timeout, or — in sandboxed environments — a proxy
            # denial (e.g. `x-deny-reason: host_not_allowed`) that httpx
            # surfaces as a connection error before any HTTP response.
            failure = BackendFailure(
                backend=name,
                category="network_blocked",
                detail=f"{description} -> {type(exc).__name__}: {exc}",
            )
            failures.append(failure)
            logger.warning(
                "Discovery backend %s could not be reached at all "
                "(%s: %s). This usually means the network/proxy in this "
                "environment blocks access to this host, not that the "
                "backend itself is down.",
                name,
                type(exc).__name__,
                exc,
            )
            continue
        except ValueError as exc:
            # e.g. searxng misconfigured (no BIE_SEARXNG_URL)
            failure = BackendFailure(backend=name, category="config_error", detail=str(exc))
            failures.append(failure)
            logger.warning("Discovery backend %s is misconfigured: %s", name, exc)
            continue

        if not html:
            failures.append(
                BackendFailure(backend=name, category="empty_response", detail="empty body")
            )
            continue

        urls = _parse_result_urls(html, max_results)
        if urls:
            logger.debug("Discovery backend %s returned %d url(s)", name, len(urls))
            return urls, failures

        # Got a 2xx response, but no results parsed out of it — most
        # likely a CAPTCHA/consent page, or a markup change.
        failures.append(
            BackendFailure(
                backend=name,
                category="empty_response",
                detail=(
                    f"{description} returned HTTP 200 but no results could be "
                    f"parsed (possible CAPTCHA/consent page or markup change)"
                ),
            )
        )
        logger.warning(
            "Discovery backend %s returned a response but no results could be "
            "parsed from it (possible CAPTCHA/consent page, or the result "
            "markup has changed).",
            name,
        )

    if failures:
        _log_all_failed_summary(query, failures)

    return [], failures


def _log_all_failed_summary(query: str, failures: list[BackendFailure]) -> None:
    network_blocked = [f for f in failures if f.category == "network_blocked"]
    empty_or_http = [f for f in failures if f.category in ("empty_response", "http_error")]

    if network_blocked and not empty_or_http:
        logger.warning(
            "All discovery backends failed for query=%r, and every failure was a "
            "connection-level error (%s). This strongly suggests network access "
            "to search backends is blocked in this environment (e.g. a sandboxed "
            "proxy, firewall, or no internet access) rather than the backends "
            "being down. If you're in a restricted sandbox, try running this in "
            "an environment with normal internet access (e.g. Colab, a local "
            "machine, or a server). If this persists on a normal connection, "
            "configure BIE_DISCOVERY_BACKENDS with a self-hosted SearXNG "
            "instance (see bie.discovery module docs).",
            query,
            ", ".join(f"{f.backend}: {f.detail}" for f in network_blocked),
        )
    elif empty_or_http and not network_blocked:
        logger.warning(
            "All discovery backends failed for query=%r, but connections "
            "succeeded — responses were empty, blocked (CAPTCHA/consent "
            "pages), or rate-limited (%s). This usually means the backends "
            "are reachable but the IP is being rate-limited, or their result "
            "markup has changed. Try again later, reduce request frequency, "
            "or configure a self-hosted SearXNG backend via "
            "BIE_DISCOVERY_BACKENDS / BIE_SEARXNG_URL (see bie.discovery "
            "module docs).",
            query,
            ", ".join(f"{f.backend}: {f.detail}" for f in empty_or_http),
        )
    else:
        logger.warning(
            "All discovery backends failed or returned no results for "
            "query=%r (%s).",
            query,
            ", ".join(f"{f.backend} [{f.category}]: {f.detail}" for f in failures),
        )


def discover_urls_multi(
    queries: list[str], max_results_per_query: int = 5, max_total: int = 15, timeout: float = 15.0
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

    Returns:
        Deduplicated URLs, ordered by (number of variants that returned
        them, then first-seen order). URLs found by multiple query
        variants are considered more likely relevant.
    """
    url_votes: dict[str, int] = {}
    url_order: dict[str, int] = {}
    order_counter = 0

    for query in queries:
        for url in discover_urls(query, max_results=max_results_per_query, timeout=timeout):
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


def _fetch_searxng(client: httpx.Client, query: str) -> str:
    base_url = os.environ.get(_ENV_SEARXNG_URL, "").rstrip("/")
    if not base_url:
        raise ValueError(
            f"backend 'searxng' is configured in {_ENV_BACKENDS} but "
            f"{_ENV_SEARXNG_URL} is not set"
        )
    resp = client.get(f"{base_url}/search", params={"q": query, "format": "json"})
    resp.raise_for_status()
    return resp.text


def _parse_result_urls(html: str, max_results: int) -> list[str]:
    """Extract organic result URLs from a search results page.

    Handles:
      - DuckDuckGo HTML:  ``<a class="result__a" href="...">``
      - DuckDuckGo Lite:  ``<a class="result-link" href="...">``
      - Bing:             ``<li class="b_algo">...<a href="...">``
      - SearXNG JSON:     ``{"results": [{"url": "..."}, ...]}``
    """
    urls_from_json = _parse_searxng_json(html)
    if urls_from_json is not None:
        hrefs = urls_from_json
    else:
        hrefs = re.findall(r'class="result__a"[^>]*href="([^"]+)"', html)
        if not hrefs:
            hrefs = re.findall(r'class="result-link"[^>]*href="([^"]+)"', html)
        if not hrefs:
            hrefs = _extract_bing_hrefs(html)

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


def _parse_searxng_json(text: str) -> list[str] | None:
    """If ``text`` is a SearXNG JSON results payload, return the result
    URLs in order; otherwise return ``None`` (not JSON / not this shape)
    so the caller falls back to HTML parsing."""
    import json

    stripped = text.lstrip()
    if not stripped.startswith("{"):
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    results = data.get("results")
    if not isinstance(results, list):
        return None
    return [r.get("url", "") for r in results if isinstance(r, dict) and r.get("url")]


def _extract_bing_hrefs(html: str) -> list[str]:
    """Extract result links from Bing's organic result blocks
    (``<li class="b_algo">``)."""
    hrefs: list[str] = []
    for block in re.findall(r'<li class="b_algo".*?</li>', html, flags=re.S):
        m = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"', block)
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
