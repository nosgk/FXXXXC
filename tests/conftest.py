# -*- coding: utf-8 -*-
"""Shared pytest configuration and helpers."""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def fixture_text(name: str) -> str:
    """Read a UTF-8 fixture from tests/fixtures."""
    return (FIXTURES / name).read_text(encoding="utf-8")
