# -*- coding: utf-8 -*-
"""言溪题库瞬时故障重试与视频续播位置规则的回归测试（上游 PR #635/#646）。"""

from __future__ import annotations

import pytest
import requests

from api.answer import TikuYanxi
from api.base import Chaoxing


def _make_tiku() -> TikuYanxi:
    tiku = TikuYanxi.__new__(TikuYanxi)
    tiku.name = '言溪题库'
    tiku.api = 'https://tk.enncy.cn/query'
    tiku._token = 'TEST_TOKEN'
    tiku._token_index = 0
    tiku._times = 100
    tiku._last_failure_transient = False
    tiku.RETRY_TIMES = 3
    tiku.RETRY_BACKOFF = 0.0  # 测试不等待
    tiku._conf = {'tokens': 'TEST_TOKEN'}
    return tiku


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text='{}'):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError('no json')
        return self._payload


def test_transient_failure_retries_then_succeeds(monkeypatch):
    tiku = _make_tiku()
    responses = [
        requests.exceptions.ConnectTimeout('timeout'),
        _FakeResponse(payload={'code': 1, 'data': {'answer': '正确', 'times': 88}, 'message': 'ok'}),
    ]
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(requests, 'get', fake_get)
    assert tiku._query({'title': '某题'}) == '正确'
    assert len(calls) == 2
    assert tiku._times == 88


def test_non_transient_failure_does_not_retry(monkeypatch):
    tiku = _make_tiku()
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        return _FakeResponse(payload={'code': 0, 'data': {'answer': '', 'times': 9}, 'message': '请求失败'})

    monkeypatch.setattr(requests, 'get', fake_get)
    assert tiku._query({'title': '某题'}) is None
    assert len(calls) == 1


def test_bad_json_retries_and_gives_up(monkeypatch):
    tiku = _make_tiku()
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        return _FakeResponse(status_code=200, text='<html>bad</html>')

    monkeypatch.setattr(requests, 'get', fake_get)
    assert tiku._query({'title': '某题'}) is None
    assert len(calls) == 3


def test_success_empty_answer_treated_as_miss(monkeypatch):
    tiku = _make_tiku()

    def fake_get(*args, **kwargs):
        return _FakeResponse(payload={'code': 1, 'data': {'answer': '', 'times': 50}, 'message': '未找到'})

    monkeypatch.setattr(requests, 'get', fake_get)
    assert tiku._query({'title': '某题'}) is None


def test_code_zero_with_none_data_no_exception(monkeypatch):
    tiku = _make_tiku()

    def fake_get(*args, **kwargs):
        return _FakeResponse(payload={'code': 0, 'data': None, 'message': '请求失败'})

    monkeypatch.setattr(requests, 'get', fake_get)
    assert tiku._query({'title': '某题'}) is None


# ---------------------------------------------------------------------------
# 视频续播位置（官方播放器规则：到达片尾重置为 0）

class TestVideoResumeSeconds:
    helper = staticmethod(Chaoxing._get_video_resume_time_seconds)

    @pytest.mark.parametrize('position_ms,expected', [
        (0, 0),
        (120000, 120),
        (662999, 662),
        (663000, 0),   # 到达片尾 → 重置 0
        (800000, 0),   # 超出片尾 → 重置 0
        ('663000', 0), # 字符串毫秒
        ('bad', 0),    # 非法输入
        (None, 0),
    ])
    def test_official_end_rule(self, position_ms, expected):
        assert self.helper(position_ms, 663) == expected
