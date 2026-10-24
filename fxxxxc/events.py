# -*- coding: utf-8 -*-
"""Thread-safe event bus used by the engine and future GUI adapters."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

Listener = Callable[["Event"], None]


@dataclass(frozen=True)
class Event:
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    seq: int = 0

    def to_json(self) -> str:
        return json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "event",
                "params": {
                    "type": self.type,
                    "seq": self.seq,
                    "ts": self.ts,
                    "data": self.data,
                },
            },
            ensure_ascii=False,
        )


class EventBus:
    """Fan-out bus with a bounded replay buffer for late subscribers."""

    def __init__(self, replay: int = 200):
        self._lock = threading.RLock()
        self._listeners: list[Listener] = []
        self._buffer: list[Event] = []
        self._replay = max(0, replay)
        self._seq = 0

    def subscribe(self, listener: Listener, replay: bool = True) -> None:
        with self._lock:
            self._listeners.append(listener)
            buffered = list(self._buffer) if replay else []
        for event in buffered:
            self._safe_call(listener, event)

    def unsubscribe(self, listener: Listener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def emit(self, event_type: str, data: dict[str, Any] | None = None) -> Event:
        with self._lock:
            self._seq += 1
            event = Event(type=event_type, data=data or {}, seq=self._seq)
            self._buffer.append(event)
            if self._replay and len(self._buffer) > self._replay:
                self._buffer = self._buffer[-self._replay :]
            listeners = list(self._listeners)
        for listener in listeners:
            self._safe_call(listener, event)
        return event

    def recent(self, limit: int = 200) -> list[Event]:
        with self._lock:
            return list(self._buffer[-max(0, limit) :])

    @staticmethod
    def _safe_call(listener: Listener, event: Event) -> None:
        try:
            listener(event)
        except Exception:
            # A broken listener must not break the study worker.
            pass


class NullEventBus(EventBus):
    def emit(self, event_type: str, data: dict[str, Any] | None = None) -> Event:
        return Event(type=event_type, data=data or {})
