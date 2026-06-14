"""
Internal helper for calling async BIE internals from synchronous code.

Plain scripts have no running event loop, so ``asyncio.run()`` works fine.
Jupyter/Colab/IPython kernels, however, *already* run an event loop, and
``asyncio.run()`` raises::

    RuntimeError: asyncio.run() cannot be called from a running event loop

:func:`run_sync` detects this and transparently falls back to:

1. ``nest_asyncio`` (if installed) — patches the running loop so it can be
   re-entered, then runs the coroutine on it directly.
2. A dedicated background thread with its own fresh event loop — works
   everywhere, with zero extra dependencies, at the cost of a thread
   spin-up per call.

This means the same sync call (e.g. ``engine.crawl(urls)``) works
unchanged in plain scripts, notebooks, and servers.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")


def run_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run ``coro`` to completion and return its result, regardless of
    whether a thread already has an asyncio event loop running.

    Args:
        coro: An awaitable coroutine object (not yet awaited/started).

    Returns:
        The coroutine's return value.

    Raises:
        Whatever exception the coroutine itself raises.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No loop running in this thread — the normal case for scripts,
        # CLI commands, and server request handlers.
        return asyncio.run(coro)

    # A loop is already running in this thread (e.g. Jupyter/Colab/IPython,
    # or an async framework that called into sync BIE code).
    try:
        import nest_asyncio  # type: ignore[import-not-found]
    except ImportError:
        return _run_in_new_thread(coro)

    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(coro)


def _run_in_new_thread(coro: Coroutine[Any, Any, T]) -> T:
    """Run ``coro`` to completion on a fresh event loop in a new thread.

    Used as the dependency-free fallback when a loop is already running in
    the calling thread and ``nest_asyncio`` isn't installed.
    """
    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread
            error["value"] = exc

    thread = threading.Thread(target=_runner, name="bie-async-runner", daemon=True)
    thread.start()
    thread.join()

    if "value" in error:
        raise error["value"]
    return result["value"]  # type: ignore[return-value]
