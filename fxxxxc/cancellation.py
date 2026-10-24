# -*- coding: utf-8 -*-
"""Cooperative cancellation and pause primitives."""

from __future__ import annotations

import threading
import time


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, seconds: float) -> bool:
        """Sleep in slices; return True if cancelled during the wait."""
        deadline = time.monotonic() + max(0.0, seconds)
        while not self._event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.2, remaining))
        return True


class PauseToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def pause(self) -> None:
        self._event.set()

    def resume(self) -> None:
        self._event.clear()

    def is_paused(self) -> bool:
        return self._event.is_set()

    def wait_if_paused(self, cancellation: CancellationToken | None = None) -> None:
        while self._event.is_set():
            if cancellation is not None and cancellation.is_cancelled():
                return
            time.sleep(0.1)
