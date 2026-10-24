# -*- coding: utf-8 -*-
"""Small helpers for keeping credentials out of logs."""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SENSITIVE_MARKERS = (
    "cookie",
    "authorization",
    "token",
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "access_key",
    "chat_id",
)


def redact_value(value: Any, keep: int = 2) -> str:
    text = str(value)
    if not text:
        return ""
    if len(text) <= keep * 2:
        return "***"
    return f"{text[:keep]}***{text[-keep:]}"


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SENSITIVE_MARKERS)


def redact_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in mapping.items():
        result[key] = redact_value(value) if is_sensitive_key(str(key)) else value
    return result


def redact_url(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    query = [
        (key, redact_value(value) if is_sensitive_key(key) else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
