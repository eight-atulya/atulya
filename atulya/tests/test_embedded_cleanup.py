"""
Regression tests for Group 7 of the hindsight bugfix backport: bounded
``AtulyaEmbedded._cleanup``.

Before the fix ``_cleanup`` did ``with self._lock:`` unconditionally, so any
thread holding the lock would wedge interpreter shutdown forever (it is also
called from ``__exit__`` / ``__del__`` paths). After the fix we use a
``Lock.acquire(timeout=...)``, mark the client closed even on timeout, and
swallow ``client.close()`` / ``manager.stop()`` exceptions so the cleanup
path is reentrancy-safe.

These tests don't need a running daemon — we construct the object via
``__new__`` and inject minimal fakes for ``_client``, ``_manager`` and
``_lock``.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from atulya.embedded import AtulyaEmbedded


def _make_client(lock: Any | None = None) -> AtulyaEmbedded:
    """Construct an AtulyaEmbedded without spinning up a daemon."""
    obj = AtulyaEmbedded.__new__(AtulyaEmbedded)
    obj.profile = "test"
    obj.config = {}
    obj._client = MagicMock()
    obj._lock = lock if lock is not None else threading.Lock()
    obj._started = True
    obj._closed = False
    obj._manager = MagicMock()
    obj._banks_api = None
    obj._mental_models_api = None
    obj._directives_api = None
    obj._memories_api = None
    return obj


class TestCleanupBoundedAcquire:
    def test_returns_within_timeout_when_lock_held(self) -> None:
        """If another thread holds the lock, _cleanup must NOT block forever."""
        client = _make_client()
        # Drop timeout to keep the test fast but still observable.
        client._CLEANUP_LOCK_TIMEOUT_SECONDS = 0.5

        holder_started = threading.Event()
        holder_release = threading.Event()

        def _hold_lock() -> None:
            with client._lock:
                holder_started.set()
                # Hold the lock well beyond the cleanup timeout
                holder_release.wait(timeout=5.0)

        t = threading.Thread(target=_hold_lock, daemon=True)
        t.start()
        try:
            assert holder_started.wait(timeout=2.0), "holder thread never grabbed the lock"

            start = time.monotonic()
            client._cleanup()
            elapsed = time.monotonic() - start

            assert elapsed < client._CLEANUP_LOCK_TIMEOUT_SECONDS + 1.0, (
                f"_cleanup blocked for {elapsed:.2f}s > "
                f"{client._CLEANUP_LOCK_TIMEOUT_SECONDS + 1.0:.2f}s; the bounded "
                "acquire regressed to an unbounded ``with self._lock:``"
            )
            assert client._closed, "Client must be marked closed even on timeout"
            # ``client.close()`` must NOT have been called when we timed out —
            # we never owned the lock that protects it.
            assert not client._client.close.called
        finally:
            holder_release.set()
            t.join(timeout=2.0)

    def test_releases_lock_on_client_close_exception(self) -> None:
        """If ``client.close()`` raises, the lock must still be released
        and ``_closed`` must still be set so subsequent calls fast-fail."""
        client = _make_client()
        client._client.close.side_effect = RuntimeError("boom")

        client._cleanup()

        assert client._closed is True
        # The lock should be free for re-acquisition; if the broad-except
        # path forgot the ``finally: release()`` this acquire would block.
        assert client._lock.acquire(timeout=0.5), (
            "Lock was not released after client.close() raised; the "
            "bounded-cleanup contract was broken."
        )
        client._lock.release()

    def test_idempotent_on_already_closed(self) -> None:
        client = _make_client()
        client._closed = True
        client._cleanup()
        # Should not have touched the (mock) client.
        assert not client._client.close.called

    def test_happy_path_stops_daemon_when_requested(self) -> None:
        client = _make_client()
        client._cleanup(stop_daemon_on_close=True)
        assert client._closed is True
        assert client._client is None  # cleared
        client._manager.stop.assert_called_once_with("test")

    def test_swallows_manager_stop_exception(self) -> None:
        client = _make_client()
        client._manager.stop.side_effect = RuntimeError("daemon already gone")
        # Must not propagate; cleanup path is reachable from finalizers.
        client._cleanup(stop_daemon_on_close=True)
        assert client._closed is True


class TestCleanupTimeoutConstant:
    def test_default_timeout_is_finite_and_short(self) -> None:
        # Five seconds is the documented default; this guards against future
        # drift back toward an unbounded acquire.
        assert 0 < AtulyaEmbedded._CLEANUP_LOCK_TIMEOUT_SECONDS <= 30.0
