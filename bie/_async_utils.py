"""
Internal helpers for running async code from synchronous entry points,
safely whether or not the caller is already inside an event loop.

This module exists because BIE's public sync API (``Crawler.crawl``,
``BIE.crawl``, etc.) wraps async crawl logic with ``asyncio.run()`` —
which works fine in plain scripts, CLI commands, and server request
handlers, but **raises** ``RuntimeError: asyncio.run() cannot be called
from a running event loop`` when called from Jupyter/Colab notebooks
(which run their own persistent event loop).

:func:`run_sync` detects this and falls back automatically:

1. **No running loop** (plain script/CLI/server) — use ``asyncio.run()``
   directly. This is the common case and has zero overhead.
2. **Running loop + nest_asyncio installed** — patch the running loop
   with `nest_asyncio <https://pypi.org/project/nest_asyncio/>`_ so
   ``asyncio.run()`` can be called from within it. Cheap, same-thread.
3. **Running loop, no nest_asyncio** — run the coroutine to completion in
   a fresh event loop on a separate worker thread, and block until it
   finishes. Always works, no extra dependencies required, slightly more
   overhead (one thread per call).

Callers (``Crawler.crawl``, ``BIE.crawl``, etc.) don't need to know which
path was taken — :func:`run_sync` always returns the coroutine's result
or raises its exception, as if it were called from a script with no
running loop.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Coroutine, TypeVar

_T = TypeVar("_T")

logger = logging.getLogger("bie.async_utils")

_nest_asyncio_applied = False


def run_sync(coro: Coroutine[None, None, _T]) -> _T:
    """Run ``coro`` to completion and return its result, working correctly
    whether or not the calling thread already has a running event loop.

    See module docstring for the fallback strategy.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop in this thread — the normal case for scripts,
        # CLI commands, and most server request handlers.
        return asyncio.run(coro)

    # We're inside a running event loop (e.g. a Jupyter/Colab cell).
    # First choice: nest_asyncio, if available — patches the loop so
    # asyncio.run() works from within it. Cheapest option, same thread.
    if _try_apply_nest_asyncio():
        return asyncio.run(coro)

    # Fallback: run the coroutine in a brand-new event loop on a separate
    # thread, and block the calling (notebook) thread until it's done.
    # This always works and requires no extra dependencies.
    logger.debug(
        "Running coroutine in a separate thread (already inside an event "
        "loop and nest_asyncio is not installed). Install nest_asyncio for "
        "lower overhead: pip install nest_asyncio"
    )
    return _run_in_new_thread(coro)


def _try_apply_nest_asyncio() -> bool:
    global _nest_asyncio_applied
    if _nest_asyncio_applied:
        return True
    try:
        import nest_asyncio
    except ImportError:
        return False
    nest_asyncio.apply()
    _nest_asyncio_applied = True
    return True


def _run_in_new_thread(coro: Coroutine[None, None, _T]) -> _T:
    def _runner() -> _T:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_runner)
        return future.result()
