# -*- coding: utf-8 -*-
"""JSON-RPC protocol helpers for the desktop engine."""

from __future__ import annotations

from typing import Any


class RpcError(Exception):
    """An error that is reported to the client as a JSON-RPC error object."""

    def __init__(self, code: int, message: str, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data:
            payload["data"] = self.data
        return payload


METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
ENGINE_ERROR = -32000
NOT_LOGGED_IN = 1001
STUDY_ALREADY_RUNNING = 1002
STUDY_NOT_RUNNING = 1003
CONFIG_ERROR = 1004
