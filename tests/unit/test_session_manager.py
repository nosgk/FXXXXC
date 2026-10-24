# -*- coding: utf-8 -*-
"""Regression tests for BUG-001: SessionManager must initialize once."""

from __future__ import annotations

from api.base import SessionManager


def test_session_is_not_recreated_on_each_access():
    SessionManager.reset()
    first = SessionManager.get_session()
    first.headers["X-Test"] = "kept"

    second = SessionManager.get_session()

    assert first is second
    assert second.headers["X-Test"] == "kept"
    SessionManager.reset()


def test_reset_creates_a_new_session():
    SessionManager.reset()
    first = SessionManager.get_session()
    SessionManager.reset()
    second = SessionManager.get_session()

    assert first is not second
    SessionManager.reset()
