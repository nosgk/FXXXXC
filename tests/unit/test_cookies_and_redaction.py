# -*- coding: utf-8 -*-
"""Regression tests for cookie persistence and log redaction."""

from __future__ import annotations

import requests

import api.cookies as cookies_module
from api.redact import redact_mapping, redact_url


def test_cookies_round_trip_with_utf8(monkeypatch, tmp_path):
    cookie_path = tmp_path / "cookies.txt"
    monkeypatch.setattr(cookies_module.gc, "COOKIES_PATH", str(cookie_path))

    session = requests.Session()
    session.cookies.set("_uid", "12345")
    session.cookies.set("fid", "1024")
    cookies_module.save_cookies(session)

    assert cookies_module.use_cookies() == {"_uid": "12345", "fid": "1024"}
    assert cookie_path.read_text(encoding="utf-8") == "_uid=12345;fid=1024"


def test_cookie_save_is_atomic_and_leaves_no_temp_file(monkeypatch, tmp_path):
    cookie_path = tmp_path / "cookies.txt"
    monkeypatch.setattr(cookies_module.gc, "COOKIES_PATH", str(cookie_path))

    session = requests.Session()
    session.cookies.set("a", "b")
    cookies_module.save_cookies(session)

    assert [path.name for path in tmp_path.iterdir()] == ["cookies.txt"]


def test_redact_mapping_hides_sensitive_keys():
    result = redact_mapping(
        {
            "Cookie": "uid=123; token=abcdef",
            "Authorization": "Bearer abcdef",
            "User-Agent": "test-agent",
            "X-Trace": "visible",
        }
    )
    assert "abcdef" not in str(result)
    assert result["User-Agent"] == "test-agent"
    assert result["X-Trace"] == "visible"


def test_redact_url_masks_query_values():
    result = redact_url("https://example.com/path?token=abcdef&name=visible&chat_id=123456")
    assert "abcdef" not in result
    assert "123456" not in result
    assert "name=visible" in result
