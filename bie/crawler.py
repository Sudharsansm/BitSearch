"""
BIE Crawler — thin orchestration layer over Bitscrape's Engine.

Implements PRD Module 1 (Crawler) for the OSS edition: runs the
:class:`bie.spiders.generic.BIESpider` against one or more seed URLs,
collects extracted pages in-memory as :class:`bie.models.Document`
objects, ready for chunking + indexing.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import bitscrape
from bitscrape.pipeline.pipelines import BasePipeline

from bie._asyncutil import run_sync
from bie.config import BIESettings
from bie.models import Document
from bie.spiders.generic import BIESpider

logger = logging.getLogger("bie.crawler")


def _patch_request_ordering() -> None:
    """Work around a Bitscrape bug where its scheduler's
    ``asyncio.PriorityQueue[tuple[int, Request]]`` compares ``Request``
    objects directly whenever two requests share the same priority
    (the common case -- most requests are ``RequestPriority.NORMAL``),
    raising::

        TypeError: '<' not supported between instances of 'Request' and 'Request'

    ``Request`` is a pydantic model with no ``__lt__``/etc., so tuple
    comparison falls through to comparing the ``Request`` instances
    themselves once priorities tie.

    This patches ``bitscrape.Request`` (a pydantic ``BaseModel``) with an
    identity-based ordering at import time, so equal-priority ties are
    broken deterministically instead of crashing. This does not change
    crawl semantics -- priority still determines order; only the
    previously-crashing tie-break becomes well-defined.

    The patch is idempotent and a no-op if a future Bitscrape release
    already defines ``__lt__`` on ``Request``.
    """
    request_cls = getattr(bitscrape, "Request", None)
    if request_cls is None:
        logger.debug("bitscrape.Request not found -- skipping ordering patch")
        return
    if "__lt__" in request_cls.__dict__:
        return  # already orderable (newer bitscrape version fixed it upstream)

    request_cls.__lt__ = lambda self, other: id(self) < id(other)
    request_cls.__le__ = lambda self, other: id(self) <= id(other)
    request_cls.__gt__ = lambda self, other: id(self) > id(other)
    request_cls.__ge__ = lambda self, other: id(self) >= id(other)
    logger.debug("Patched bitscrape.Request with identity-based ordering")


_patch_request_ordering()


class _CollectorPipeline(BasePipeline):
    """Collects every scraped item into an in-memory list."""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    async def process_item(self, item: Any, spider: Any) -> Any:
        self.items.append(item)
        return item


class Crawler:
    """Crawls a list of seed URLs using Bitscrape and returns Documents."""

    def __init__(self, settings: BIESettings | None = None) -> None:
        self.settings = settings or BIESettings()

    def crawl(
        self, urls: list[str], allowed_domains: list[str] | None = None, instruction: str = ""
    ) -> list[Document]:
        """Synchronous convenience wrapper around :meth:`acrawl`.

        Safe to call from plain scripts, CLI commands, server request
        handlers, *and* Jupyter/Colab/IPython notebooks (which already run
        an event loop, where a plain ``asyncio.run()`` would raise
        ``RuntimeError: asyncio.run() cannot be called from a running
        event loop``). See :func:`bie._asyncutil.run_sync`.
        """
        return run_sync(self.acrawl(urls, allowed_domains, instruction))

    async def acrawl(
        self,
        urls: list[str],
        allowed_domains: list[str] | None = None,
        instruction: str = "",
    ) -> list[Document]:
        if not urls:
            return []

        if allowed_domains is None:
            allowed_domains = sorted({urlparse(u).netloc for u in urls if urlparse(u).netloc})

        bs_settings = bitscrape.Settings(
            concurrent_requests=self.settings.concurrent_requests,
            download_delay=self.settings.download_delay,
            user_agent=self.settings.user_agent,
            robotstxt_obey=self.settings.robotstxt_obey,
            download_timeout=self.settings.request_timeout,
            max_depth=self.settings.max_depth,
        )

        spider = BIESpider(settings=bs_settings)
        spider.start_urls = list(urls)
        spider.allowed_domains = allowed_domains
        spider.max_pages = self.settings.max_pages
        spider.max_depth = self.settings.max_depth
        spider.instruction = instruction

        collector = _CollectorPipeline()

        middlewares = [
            bitscrape.UserAgentMiddleware(),
            bitscrape.CookieMiddleware(),
        ]
        if bs_settings.robotstxt_obey:
            middlewares.insert(0, bitscrape.RobotsMiddleware())

        engine = bitscrape.Engine(
            spider=spider,
            settings=bs_settings,
            pipelines=[collector],
            middlewares=middlewares,
        )

        stats = await engine.run()
        logger.info(
            "Crawled %d page(s) from %d seed URL(s) — %d failed",
            stats.items_scraped,
            len(urls),
            stats.requests_failed,
        )

        documents: list[Document] = []
        for item in collector.items:
            if not item.get("text"):
                continue
            documents.append(
                Document(
                    url=item["url"],
                    title=item.get("title", item["url"]),
                    text=item["text"],
                    site=urlparse(item["url"]).netloc,
                    metadata={"depth": item.get("depth", 0)},
                )
            )
        return documents
