# -*- coding: utf-8 -*-
"""Regression tests for BUG-003/BUG-004/BUG-009."""

from __future__ import annotations

import json
from pathlib import Path

import api.answer as answer_module
from api.answer import CacheDAO, Tiku


class _FakeTiku(Tiku):
    def __init__(self):
        super().__init__()
        self.name = "fake"
        self.DISABLE = False
        self._conf = {
            "submit": "true",
            "cover_rate": "0.8",
            "true_list": "正确",
            "false_list": "错误",
        }
        self.true_list = ["正确"]
        self.false_list = ["错误"]
        self.calls = 0
        self.work_feedback = None

    def set_work_feedback(self, feedback):
        self.work_feedback = feedback

    def _query(self, q_info):
        self.calls += 1
        return "A"


def _question(title: str, q_type: str = "single") -> dict:
    return {"title": title, "type": q_type, "options": "A. 甲\nB. 乙"}


def _patch_cache(monkeypatch, cache_file: Path) -> None:
    monkeypatch.setattr(answer_module, "CacheDAO", lambda: CacheDAO(str(cache_file)))


def test_query_cache_miss_returns_and_caches_answer(monkeypatch, tmp_path):
    cache_file = tmp_path / "cache.json"
    _patch_cache(monkeypatch, cache_file)
    tiku = _FakeTiku()

    assert tiku.query(_question("题目一")) == "A"
    assert tiku.calls == 1
    assert json.loads(cache_file.read_text(encoding="utf-8"))["题目一"] == "A"

    assert tiku.query(_question("题目一")) == "A"
    assert tiku.calls == 1


def test_query_feedback_mode_does_not_use_or_write_cache(monkeypatch, tmp_path):
    cache_file = tmp_path / "cache.json"
    _patch_cache(monkeypatch, cache_file)
    tiku = _FakeTiku()
    tiku.set_work_feedback(["上次答错"])

    assert tiku.query(_question("题目二")) == "A"
    assert tiku.calls == 1
    assert not cache_file.exists() or "题目二" not in json.loads(cache_file.read_text(encoding="utf-8"))


def test_query_all_uses_one_cache_write(monkeypatch, tmp_path):
    cache_file = tmp_path / "cache.json"
    _patch_cache(monkeypatch, cache_file)
    tiku = _FakeTiku()

    results = tiku.query_all([_question("一"), _question("二")])
    assert results == ["A", "A"]
    assert tiku.calls == 2
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert data == {"一": "A", "二": "A"}

    assert tiku.query_all([_question("一"), _question("二")]) == ["A", "A"]
    assert tiku.calls == 2


def test_init_tiku_uses_defaults_for_missing_or_invalid_keys():
    tiku = _FakeTiku()
    tiku._conf = {"submit": "maybe", "cover_rate": "bad"}
    tiku.init_tiku()

    assert tiku.SUBMIT is False
    assert tiku.COVER_RATE == 0.8
    assert "正确" in tiku.true_list
    assert "错误" in tiku.false_list


def test_tls_verification_is_on_by_default_and_can_be_disabled():
    tiku = _FakeTiku()
    assert tiku._tls_verify() is True
    tiku._conf = {"insecure_skip_verify": "true"}
    assert tiku._tls_verify() is False
