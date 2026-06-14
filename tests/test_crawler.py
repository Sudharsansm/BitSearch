"""Tests for bie.crawler:

- _patch_request_ordering(): fixes Bitscrape's
  ``TypeError: '<' not supported between instances of 'Request' and 'Request'``
  by making ``bitscrape.Request`` orderable.
- Crawler.crawl(): notebook-safe sync wrapper around acrawl() via run_sync.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import bitscrape

from bie.crawler import Crawler, _patch_request_ordering
from bie.models import Document


def test_bitscrape_request_is_orderable_after_import():
    """bie.crawler patches bitscrape.Request with __lt__ etc. at import
    time. Two Request instances should now be comparable instead of
    raising TypeError."""
    r1 = bitscrape.Request(url="https://a.example.com")
    r2 = bitscrape.Request(url="https://b.example.com")

    # Should not raise TypeError: '<' not supported between instances ...
    assert isinstance(r1 < r2, bool)
    assert isinstance(r1 <= r2, bool)


def test_priority_queue_with_equal_priority_requests_does_not_crash():
    """Reproduces the exact failure mode: an asyncio.PriorityQueue of
    (priority, Request) tuples where two requests share the same
    priority. Before the patch this raised TypeError on comparison."""

    async def _run():
        queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        r1 = bitscrape.Request(url="https://a.example.com")
        r2 = bitscrape.Request(url="https://b.example.com")
        await queue.put((5, r1))
        await queue.put((5, r2))  # same priority -> tuple tie-break compares Requests
        first = await queue.get()
        second = await queue.get()
        return first, second

    first, second = asyncio.run(_run())
    assert {first[1].url, second[1].url} == {"https://a.example.com", "https://b.example.com"}


def test_patch_request_ordering_is_idempotent():
    """Calling the patch function multiple times should not error and
    should not stomp on an ordering already defined elsewhere."""
    _patch_request_ordering()
    _patch_request_ordering()
    assert "__lt__" in bitscrape.Request.__dict__


def test_patch_request_ordering_does_not_override_existing_lt():
    """If Request already defines __lt__ (e.g. a future Bitscrape release
    fixes this upstream), the patch must be a no-op."""

    class FakeRequest:
        def __lt__(self, other):
            return "custom"

    original = bitscrape.Request
    try:
        bitscrape.Request = FakeRequest
        _patch_request_ordering()
        # Our identity-based lambda must NOT have replaced the custom one.
        assert FakeRequest.__dict__["__lt__"] is FakeRequest.__lt__
        assert FakeRequest().__lt__(None) == "custom"
    finally:
        bitscrape.Request = original


def test_patch_request_ordering_handles_missing_request_attr():
    """If bitscrape doesn't expose Request at all, the patch is a silent
    no-op rather than raising."""
    original = bitscrape.Request
    try:
        del bitscrape.Request
        _patch_request_ordering()  # should not raise
    finally:
        bitscrape.Request = original


# ---------------------------------------------------------------------------
# Crawler.crawl() notebook-safety
# ---------------------------------------------------------------------------


def test_crawl_uses_run_sync():
    """Crawler.crawl() must delegate to run_sync(acrawl(...)) rather than
    calling asyncio.run() directly, so it works inside notebooks too."""
    crawler = Crawler()
    sentinel_docs = [Document(url="https://example.com", title="T", text="hello")]

    crawler.acrawl = AsyncMock(return_value=sentinel_docs)  # type: ignore[method-assign]

    with patch("bie.crawler.run_sync") as mock_run_sync:
        mock_run_sync.return_value = sentinel_docs
        result = crawler.crawl(["https://example.com"])

    assert result == sentinel_docs
    mock_run_sync.assert_called_once()
    # The coroutine passed to run_sync should be the one from acrawl()
    awaited_coro = mock_run_sync.call_args[0][0]
    assert asyncio.iscoroutine(awaited_coro)
    awaited_coro.close()  # avoid "coroutine was never awaited" warning


def test_crawl_works_when_called_from_a_running_event_loop():
    """End-to-end notebook simulation: Crawler.crawl() (sync) is called
    from inside code that's already running an event loop. Before the
    run_sync fix this raised:
        RuntimeError: asyncio.run() cannot be called from a running event loop
    """
    crawler = Crawler()
    crawler.acrawl = AsyncMock(return_value=[])  # type: ignore[method-assign]

    async def notebook_cell():
        # asyncio.get_running_loop() succeeds here, simulating Jupyter/Colab.
        return crawler.crawl([])

    result = asyncio.run(notebook_cell())
    assert result == []


def test_acrawl_returns_empty_list_for_no_urls():
    crawler = Crawler()
    result = asyncio.run(crawler.acrawl([]))
    assert result == []
