"""
``bie.extract()`` — retrieve clean, readable Markdown from a single URL.

This is BIE's "give me this page as clean text" primitive: fetch a URL,
strip navigation/ads/scripts/styling noise, and convert the main content
to Markdown — the format LLMs work with best.

For static HTML pages, this uses a direct HTTP fetch (fast, no browser).
For JavaScript-rendered pages (SPAs, sites that return a near-empty
``<body>`` until JS runs), pass ``render_js=True`` to fall back to a
headless Playwright browser — requires the optional ``bie[render]``
extra (``pip install "bits-bie[render]"`` plus ``playwright install
chromium`` once).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx
from markdownify import markdownify

from bie._async_utils import run_sync
from bie.security import scan_for_prompt_injection

if TYPE_CHECKING:
    from bie.security import SecurityReport

logger = logging.getLogger("bie.extract")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 BIE/0.5"
)

# Tags whose content is never useful for an LLM and should be stripped
# before markdown conversion.
_STRIP_TAGS = (
    "script",
    "style",
    "noscript",
    "nav",
    "footer",
    "header",
    "form",
    "iframe",
    "svg",
    "button",
    "aside",
)

# A page is considered "JS-required" if, after stripping noise tags, the
# remaining visible text is suspiciously short.
_JS_REQUIRED_TEXT_THRESHOLD = 80


class ExtractError(RuntimeError):
    """Raised when a page can't be fetched or extracted."""


@dataclass
class ExtractResult:
    """Result of :func:`bie.extract.extract`."""

    url: str
    title: str
    markdown: str
    text: str
    word_count: int
    rendered_with_js: bool = False
    security: "SecurityReport | None" = field(default=None)

    def __str__(self) -> str:  # pragma: no cover - convenience only
        flag = " [JS-rendered]" if self.rendered_with_js else ""
        return f"<ExtractResult {self.url!r} title={self.title!r} words={self.word_count}{flag}>"


def extract(
    url: str,
    render_js: bool = False,
    timeout: float = 20.0,
    scan_security: bool = True,
) -> ExtractResult:
    """Fetch ``url`` and return its content as clean Markdown.

    Args:
        url: The page to fetch.
        render_js: If True, render the page with a headless browser
            (requires ``pip install "bits-bie[render]"`` and
            ``playwright install chromium``). If False (default), BIE
            still auto-detects JS-only pages and raises a helpful
            :class:`ExtractError` suggesting ``render_js=True`` rather
            than silently returning near-empty content.
        timeout: Request timeout in seconds.
        scan_security: If True (default), scan the extracted text for
            prompt-injection patterns and attach a
            :class:`bie.security.SecurityReport` to ``result.security``.
            This does **not** remove or alter content, only flags it.

    Returns:
        An :class:`ExtractResult` with ``markdown``, plain ``text``,
        ``title``, and ``word_count``.

    Raises:
        ExtractError: if the page can't be fetched, or appears to require
            JavaScript and ``render_js=False``.
    """
    if render_js:
        html = _fetch_with_playwright(url, timeout)
        rendered_with_js = True
    else:
        html = _fetch_static(url, timeout)
        rendered_with_js = False

        if _looks_js_only(html):
            raise ExtractError(
                f"{url} appears to require JavaScript to render its content "
                f"(static fetch returned very little text). Retry with "
                f"extract(url, render_js=True) — requires "
                f'\'pip install "bits-bie[render]"\' and '
                f"'playwright install chromium' once."
            )

    title, markdown, text = _to_markdown(html)

    result = ExtractResult(
        url=url,
        title=title,
        markdown=markdown,
        text=text,
        word_count=len(text.split()),
        rendered_with_js=rendered_with_js,
    )

    if scan_security:
        result.security = scan_for_prompt_injection(text)

    return result


def _fetch_static(url: str, timeout: float) -> str:
    headers = {"User-Agent": _USER_AGENT}
    try:
        with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text
    except httpx.HTTPError as exc:
        raise ExtractError(f"Failed to fetch {url}: {exc}") from exc


def _fetch_with_playwright(url: str, timeout: float) -> str:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise ExtractError(
            "render_js=True requires the 'playwright' package. Install with: "
            'pip install "bits-bie[render]" && playwright install chromium'
        ) from exc

    async def _run() -> str:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page(user_agent=_USER_AGENT)
                await page.goto(url, timeout=timeout * 1000, wait_until="networkidle")
                return await page.content()
            finally:
                await browser.close()

    try:
        return run_sync(_run())
    except Exception as exc:
        raise ExtractError(f"Failed to render {url} with Playwright: {exc}") from exc


def _looks_js_only(html: str) -> bool:
    """Heuristic: after stripping script/style/nav/etc, is there
    suspiciously little visible text? Typical of SPA shells that render
    everything client-side (e.g. ``<div id="root"></div>``)."""
    _, _, text = _to_markdown(html)
    return len(text.strip()) < _JS_REQUIRED_TEXT_THRESHOLD


def _to_markdown(html: str) -> tuple[str, str, str]:
    """Strip noise tags and convert to (title, markdown, plain_text)."""
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)

    title_node = tree.css_first("title")
    title = _clean_text(title_node.text()) if title_node else ""

    for tag in _STRIP_TAGS:
        for node in tree.css(tag):
            node.decompose()

    body = tree.css_first("body") or tree
    body_html = body.html or ""

    markdown = markdownify(body_html, heading_style="ATX", strip=["a"]).strip()
    markdown = _collapse_blank_lines(markdown)

    text_node = tree.css_first("body") or tree
    text = _clean_text(text_node.text(separator=" ", deep=True))

    return title, markdown, text


def _collapse_blank_lines(markdown: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", markdown)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()
