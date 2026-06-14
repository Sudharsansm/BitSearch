"""Tests for the bitscrape.Request ordering patch (bie/crawler.py)."""

import bitscrape

# Importing bie.crawler applies the patch as a side effect.
import bie.crawler  # noqa: F401


def test_request_objects_are_orderable():
    r1 = bitscrape.Request(url="https://a.example.com")
    r2 = bitscrape.Request(url="https://b.example.com")

    # Should not raise TypeError
    result = r1 < r2
    assert isinstance(result, bool)
    # Ordering should be consistent (anti-symmetric)
    assert (r1 < r2) != (r2 < r1) or r1 is r2


def test_request_ordering_is_stable_for_same_object():
    r1 = bitscrape.Request(url="https://a.example.com")
    assert (r1 < r1) is False


def test_priority_queue_with_equal_priority_requests_does_not_raise():
    """Reproduces the original crash: two Requests with the same priority
    pushed into an asyncio.PriorityQueue must not raise TypeError on
    tie-break comparison."""
    import asyncio

    from bitscrape.core.models import RequestPriority

    async def _run():
        q: asyncio.PriorityQueue = asyncio.PriorityQueue()
        r1 = bitscrape.Request(url="https://a.example.com")
        r2 = bitscrape.Request(url="https://b.example.com")

        # Same priority value -> heapq must compare the Request objects
        await q.put((RequestPriority.NORMAL.value, r1))
        await q.put((RequestPriority.NORMAL.value, r2))

        _, first = q.get_nowait()
        _, second = q.get_nowait()
        return first, second

    first, second = asyncio.run(_run())
    assert {first.url, second.url} == {"https://a.example.com", "https://b.example.com"}


def test_patch_is_noop_if_lt_already_defined():
    """If a future Bitscrape version already defines __lt__, re-running
    the patch function must not override it."""
    from bie.crawler import _patch_request_ordering

    sentinel_called = []

    def custom_lt(self, other):
        sentinel_called.append(True)
        return id(self) < id(other)

    original = bitscrape.Request.__lt__
    try:
        bitscrape.Request.__lt__ = custom_lt
        _patch_request_ordering()  # should be a no-op now
        assert bitscrape.Request.__lt__ is custom_lt
    finally:
        bitscrape.Request.__lt__ = original
