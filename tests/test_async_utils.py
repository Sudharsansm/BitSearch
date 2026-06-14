"""Tests for bie._async_utils.run_sync — notebook-safe sync wrapper."""

import asyncio
import sys
from unittest.mock import patch

import pytest

from bie import _async_utils
from bie._async_utils import run_sync


async def _coro_return(value):
    await asyncio.sleep(0)
    return value


async def _coro_raise():
    await asyncio.sleep(0)
    raise ValueError("boom")


def test_run_sync_no_running_loop_uses_asyncio_run():
    result = run_sync(_coro_return("ok"))
    assert result == "ok"


def test_run_sync_propagates_exceptions_no_running_loop():
    with pytest.raises(ValueError, match="boom"):
        run_sync(_coro_raise())


def test_run_sync_inside_running_loop_uses_thread_fallback_without_nest_asyncio():
    """Simulates Jupyter/Colab: a coroutine calls run_sync() while the
    calling thread already has a running event loop, and nest_asyncio is
    not available."""
    _async_utils._nest_asyncio_applied = False

    async def outer():
        # We are now inside a running loop.
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()  # sanity: this does NOT raise...
        return None

    async def inner_main():
        # Confirm we're inside a running loop
        asyncio.get_running_loop()

        with patch.object(_async_utils, "_try_apply_nest_asyncio", return_value=False):
            return run_sync(_coro_return("from-thread"))

    result = asyncio.run(inner_main())
    assert result == "from-thread"


def test_run_sync_inside_running_loop_propagates_exception_via_thread():
    _async_utils._nest_asyncio_applied = False

    async def inner_main():
        asyncio.get_running_loop()
        with patch.object(_async_utils, "_try_apply_nest_asyncio", return_value=False):
            return run_sync(_coro_raise())

    with pytest.raises(ValueError, match="boom"):
        asyncio.run(inner_main())


def test_run_sync_inside_running_loop_uses_nest_asyncio_if_available():
    """If nest_asyncio is importable and successfully patches the loop
    (simulated here), run_sync should call asyncio.run() directly rather
    than falling back to a thread."""
    fake_nest_asyncio = type(sys)("nest_asyncio")
    fake_nest_asyncio.apply = lambda: None

    _async_utils._nest_asyncio_applied = False

    async def inner_main():
        asyncio.get_running_loop()
        coro = _coro_return("unused")
        try:
            with patch.dict(sys.modules, {"nest_asyncio": fake_nest_asyncio}), \
                 patch.object(_async_utils, "_run_in_new_thread") as mock_thread, \
                 patch("asyncio.run", return_value="via-nest-asyncio") as mock_run:
                result = run_sync(coro)
        finally:
            coro.close()

        mock_run.assert_called_once()
        mock_thread.assert_not_called()
        return result

    result = asyncio.run(inner_main())
    assert result == "via-nest-asyncio"
    _async_utils._nest_asyncio_applied = False


def test_run_sync_caches_nest_asyncio_applied_flag():
    fake_nest_asyncio = type(sys)("nest_asyncio")
    apply_calls = []
    fake_nest_asyncio.apply = lambda: apply_calls.append(True)

    _async_utils._nest_asyncio_applied = False

    async def inner_main():
        asyncio.get_running_loop()
        coro1, coro2 = _coro_return("unused"), _coro_return("unused")
        try:
            with patch.dict(sys.modules, {"nest_asyncio": fake_nest_asyncio}), \
                 patch("asyncio.run", return_value="ok"):
                run_sync(coro1)
                run_sync(coro2)
        finally:
            coro1.close()
            coro2.close()

    asyncio.run(inner_main())
    assert len(apply_calls) == 1  # applied only once, even across multiple calls
    _async_utils._nest_asyncio_applied = False
