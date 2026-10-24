# -*- coding: utf-8 -*-
"""Characterization tests for the on-disk answer cache."""

from __future__ import annotations

import json
from pathlib import Path

from api.answer import CacheDAO


def test_cache_round_trip(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    dao = CacheDAO(str(cache_file))

    assert dao.get_cache("题目") is None
    dao.add_cache("题目", "A")
    assert dao.get_cache("题目") == "A"
    assert json.loads(cache_file.read_text(encoding="utf-8")) == {"题目": "A"}


def test_cache_recovers_from_truncated_json(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    cache_file.write_text('{"题目": "A"', encoding="utf-8")

    dao = CacheDAO(str(cache_file))
    assert dao.get_cache("题目") is None
    assert list(tmp_path.glob("cache.json.bak.*"))


def test_cache_creates_parent_directory(tmp_path: Path):
    cache_file = tmp_path / "nested" / "cache.json"
    dao = CacheDAO(str(cache_file))
    dao.add_cache("q", "B")

    assert cache_file.exists()
    assert dao.get_cache("q") == "B"
