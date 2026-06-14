"""Tests that Crawler.crawl()/BIE.crawl() are safe to call from inside a
running event loop (simulating Jupyter/Colab)."""

import asyncio
from unittest.mock import patch

from bie import _async_utils
from bie.crawler import Crawler
from bie.models import Document


def test_crawler_crawl_works_with_no_running_loop():
    crawler = Crawler()

    async def fake_acrawl(self, urls, allowed_domains=None, instruction=""):
        return [Document(url=urls[0], title="t", text="hello world")]

    with patch.object(Crawler, "acrawl", side_effect=fake_acrawl, autospec=True):
        docs = crawler.crawl(["https://example.com"])

    assert len(docs) == 1
    assert docs[0].url == "https://example.com"


def test_crawler_crawl_works_inside_running_loop_via_thread_fallback():
    """Simulates calling engine.crawl(...) from a Jupyter/Colab cell:
    the calling code is already inside asyncio.run(), and nest_asyncio is
    not installed."""
    _async_utils._nest_asyncio_applied = False

    crawler = Crawler()

    async def fake_acrawl(self, urls, allowed_domains=None, instruction=""):
        await asyncio.sleep(0)
        return [Document(url=urls[0], title="t", text="hello world")]

    async def inner_main():
        asyncio.get_running_loop()  # confirm we're inside a loop
        with patch.object(Crawler, "acrawl", side_effect=fake_acrawl, autospec=True), \
             patch.object(_async_utils, "_try_apply_nest_asyncio", return_value=False):
            return crawler.crawl(["https://example.com"])

    docs = asyncio.run(inner_main())
    assert len(docs) == 1
    assert docs[0].url == "https://example.com"


def test_crawler_crawl_inside_running_loop_uses_nest_asyncio_when_available():
    _async_utils._nest_asyncio_applied = False

    crawler = Crawler()

    async def fake_acrawl(self, urls, allowed_domains=None, instruction=""):
        return [Document(url=urls[0], title="t", text="hello world")]

    async def inner_main():
        asyncio.get_running_loop()
        coro_holder = {}

        def capturing_acrawl(self, urls, allowed_domains=None, instruction=""):
            coro = fake_acrawl(self, urls, allowed_domains, instruction)
            coro_holder["coro"] = coro
            return coro

        try:
            with patch.object(Crawler, "acrawl", new=capturing_acrawl), \
                 patch.object(_async_utils, "_try_apply_nest_asyncio", return_value=True), \
                 patch("asyncio.run") as mock_run:
                mock_run.return_value = [Document(url="https://example.com", title="t", text="hi")]
                docs = crawler.crawl(["https://example.com"])
        finally:
            coro_holder["coro"].close()

        mock_run.assert_called_once()
        return docs

    docs = asyncio.run(inner_main())
    assert len(docs) == 1
    _async_utils._nest_asyncio_applied = False
