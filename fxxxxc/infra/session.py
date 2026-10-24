# -*- coding: utf-8 -*-
"""Process-wide requests session with a one-time initializer."""

from __future__ import annotations

import functools
import threading

import requests
from requests.adapters import HTTPAdapter
from typing_extensions import Self

from api.config import GlobalConst as gc
from api.cookies import use_cookies


class SessionManager:
    """Process-wide requests session.

    ``__init__`` is guarded so obtaining the singleton never recreates the
    session, headers or cookies. Call ``reset()`` when switching accounts or
    in tests.
    """

    _instance = None
    _init_lock = threading.Lock()
    _login_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        with self._init_lock:
            if getattr(self, "_initialized", False):
                return
            self._session = requests.Session()
            self._session.mount("https://", HTTPAdapter(max_retries=10))
            self._session.mount("http://", HTTPAdapter(max_retries=10))
            self._session.request = functools.partial(self._session.request, timeout=5)
            self._session.headers.clear()
            self._session.headers.update(gc.HEADERS)
            self._session.cookies.update(use_cookies())
            self._initialized = True

    @classmethod
    def get_instance(cls) -> Self:
        return cls()

    @classmethod
    def get_session(cls) -> requests.Session:
        return cls.get_instance()._session

    @classmethod
    def update_cookies(cls):
        cls.get_instance()._session.cookies.update(use_cookies())

    @classmethod
    def reset(cls) -> None:
        """Drop the current session so the next access starts clean."""
        with cls._init_lock:
            instance = cls._instance
            if instance is not None:
                try:
                    instance._session.close()
                except Exception:
                    pass
                instance._initialized = False
                cls._instance = None
