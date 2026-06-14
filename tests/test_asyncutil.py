"""Tests for bie._asyncutil.run_sync — the notebook-safe async wrapper.

These cover the three execution contexts run_sync needs to handle:

1. No event loop running (plain scripts, CLI) -> asyncio.run().
2. A loop already running (Jupyter/Colab) + nest_asyncio installed
   -> nest_asyncio.apply() + loop.run_until_complete().
3. A loop already running + nest_asyncio NOT installed
   -> dependency-free background-thread fallback.
"""

from __future__ import annotations

import asyncio
import builtins
import sys
from unittest.mock import MagicMock

import pytest

from bie._asyncutil import run_sync


async def _add(a: int, b: int) -> int:
    await asyncio.sleep(0)
    return a + b


async def _boom() -> None:
    await asyncio.sleep(0)
    raise ValueError("boom")


def test_run_sync_no_running_loop_uses_asyncio_run():
    """The common case: a plain script with no event loop yet."""
    result = run_sync(_add(2, 3))
    assert result == 5


def test_run_sync_propagates_exceptions_without_running_loop():
    with pytest.raises(ValueError, match="boom"):
        run_sync(_boom())


def test_run_sync_with_running_loop_and_nest_asyncio(monkeypatch):
    """Simulates Jupyter/Colab: a loop is already running in this thread,
    and nest_asyncio is importable. Verifies run_sync takes the
    nest_asyncio path: apply() then loop.run_until_complete()."""

    fake_nest_asyncio = MagicMock()
    monkeypatch.setitem(sys.modules, "nest_asyncio", fake_nest_asyncio)

    fake_loop = MagicMock()
    fake_loop.run_until_complete.return_value = 30

    # Simulate "a loop is already running" without needing a real
    # re-entrant loop (that's nest_asyncio's job, which we've mocked out).
    monkeypatch.setattr(
        "bie._asyncutil.asyncio.get_running_loop", MagicMock(return_value=MagicMock())
    )
    monkeypatch.setattr(
        "bie._asyncutil.asyncio.get_event_loop", MagicMock(return_value=fake_loop)
    )

    coro = _add(10, 20)
    result = run_sync(coro)

    assert result == 30
    fake_nest_asyncio.apply.assert_called_once()
    fake_loop.run_until_complete.assert_called_once_with(coro)
    coro.close()


def test_run_sync_with_running_loop_no_nest_asyncio_uses_thread(monkeypatch):
    """Simulates Jupyter/Colab without nest_asyncio installed: falls back
    to running the coroutine in a separate thread with its own loop."""

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "nest_asyncio":
            raise ImportError("No module named 'nest_asyncio'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delitem(sys.modules, "nest_asyncio", raising=False)

    async def runner():
        return run_sync(_add(1, 2))

    result = asyncio.run(runner())
    assert result == 3


def test_run_sync_with_running_loop_no_nest_asyncio_propagates_exception(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "nest_asyncio":
            raise ImportError("No module named 'nest_asyncio'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delitem(sys.modules, "nest_asyncio", raising=False)

    async def runner():
        return run_sync(_boom())

    with pytest.raises(ValueError, match="boom"):
        asyncio.run(runner())
