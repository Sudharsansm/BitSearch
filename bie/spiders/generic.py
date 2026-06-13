"""
BIE's default spider — built directly on the Bitscrape Spider class.

This implements PRD Module 1 (Crawler) at OSS scope: generic article/page
extraction with link-following, using Bitscrape's selector API and
RobotsMiddleware for politeness.

Note: Bitscrape's Engine calls ``parse(self, parsed)`` where ``parsed`` is
already a :class:`bitscrape.ParsedResponse` (a CSS/XPath-selectable wrapper
around the raw Response) — see ``bitscrape/engine.py::_parse_response``.
"""

from __future__ import annotations

import re
from typing import AsyncGenerator
from urllib.parse import urljoin, urlparse

import bitscrape

_WS_RE = re.compile(r"\s+")
_SKIP_EXT = re.compile(r"\.(jpg|jpeg|png|gif|svg|css|js|ico|pdf|zip|mp4|mp3|woff2?)$", re.I)
_WORD_RE = re.compile(r"[a-z0-9]+")


def _clean(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


class BIESpider(bitscrape.Spider):
    """Generic article-extraction spider with bounded, optionally
    instruction-guided link-following.

    Configured dynamically per-crawl via instance attributes
    ``start_urls``, ``allowed_domains``, ``max_pages``, ``max_depth``, and
    ``instruction`` (set by :class:`bie.crawler.Crawler`).

    When ``instruction`` is set (a short natural-language description of
    what to look for, e.g. "pricing and plans pages"), outgoing links are
    scored by keyword overlap between the instruction and the link's
    anchor text + URL path, and only the highest-scoring links are
    followed. This is a **keyword-relevance heuristic**, not semantic
    understanding of the instruction — it biases the crawl toward
    plausibly-relevant pages without requiring an LLM call per page.
    """

    name = "bie_spider"

    # When instruction-guided, only follow the top N scoring links per page.
    _MAX_GUIDED_LINKS = 10

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.allowed_domains: list[str] = []
        self.max_pages: int = 40
        self.max_depth: int = 2
        self.instruction: str = ""
        self._instruction_keywords: set[str] = set()
        self._seen_pages: int = 0

    def _keywords(self) -> set[str]:
        if not self.instruction:
            return set()
        if not self._instruction_keywords:
            self._instruction_keywords = set(_WORD_RE.findall(self.instruction.lower()))
        return self._instruction_keywords

    async def parse(self, parsed: "bitscrape.ParsedResponse") -> AsyncGenerator:
        if parsed.status >= 400:
            return

        self._seen_pages += 1

        title_sel = parsed.css("title::text").get() or parsed.css("h1::text").get() or ""
        title = _clean(title_sel)

        candidate_selectors = [
            "article ::text",
            "main ::text",
            "[role=main] ::text",
            ".content ::text",
            ".post ::text",
            "p::text",
            "h1::text",
            "h2::text",
            "h3::text",
        ]
        candidates: list[str] = []
        for sel in candidate_selectors:
            try:
                candidates.extend(parsed.css(sel).getall())
            except Exception:
                continue

        if not candidates:
            try:
                candidates = parsed.css("body ::text").getall()
            except Exception:
                candidates = []

        blocks = [_clean(c) for c in candidates]
        blocks = [b for b in blocks if len(b) > 1]
        text = "\n\n".join(_dedupe_consecutive(blocks))

        depth = parsed.request.depth
        meta = parsed.request.meta

        yield {
            "url": parsed.url,
            "title": title or parsed.url,
            "text": text,
            "depth": depth,
        }

        # Link-following (bounded by depth + page budget)
        if depth < self.max_depth and self._seen_pages < self.max_pages:
            for next_url in self._select_links(parsed):
                yield self.follow(next_url, meta={**meta, "depth": depth + 1})

    def _select_links(self, parsed: "bitscrape.ParsedResponse") -> list[str]:
        """Return the outgoing links to follow from this page, optionally
        ranked by relevance to ``self.instruction``."""
        anchors = parsed.css("a")
        candidates: list[tuple[str, str]] = []  # (url, anchor_text)

        try:
            hrefs = parsed.css("a::attr(href)").getall()
            texts = [a.text(strip=True) for a in anchors] if anchors else []
        except Exception:
            hrefs, texts = [], []

        for i, href in enumerate(hrefs[:200]):
            if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            next_url = urljoin(parsed.url, href)
            if _SKIP_EXT.search(next_url):
                continue
            if self.allowed_domains and not _same_site(next_url, self.allowed_domains):
                continue
            anchor_text = texts[i] if i < len(texts) else ""
            candidates.append((next_url, anchor_text))

        if not candidates:
            return []

        keywords = self._keywords()
        if not keywords:
            # No instruction: preserve original behaviour (first N links).
            return [url for url, _ in candidates[:50]]

        scored = sorted(
            candidates,
            key=lambda c: _relevance_score(c[0], c[1], keywords),
            reverse=True,
        )
        return [url for url, _ in scored[: self._MAX_GUIDED_LINKS]]


def _relevance_score(url: str, anchor_text: str, keywords: set[str]) -> int:
    """Count overlapping keyword tokens between ``keywords`` and the
    link's anchor text + URL path. Higher = more likely relevant to the
    crawl instruction."""
    haystack = f"{anchor_text} {urlparse(url).path}".lower()
    tokens = set(_WORD_RE.findall(haystack))
    return len(tokens & keywords)


def _dedupe_consecutive(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if not out or out[-1] != item:
            out.append(item)
    return out


def _same_site(url: str, allowed_domains: list[str]) -> bool:
    host = urlparse(url).netloc.lower()
    return any(host == d or host.endswith(f".{d}") for d in allowed_domains)
