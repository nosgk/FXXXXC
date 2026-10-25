# -*- coding: utf-8 -*-
"""OCS 兼容答题源（TikuOcs）与学习次数阶段事件的回归测试。"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from api.answer import TikuOcs
from api.base import Chaoxing, StudyResult


def _make_tiku(wrappers, **extra) -> TikuOcs:
    tiku = TikuOcs()
    conf = {'ocs_wrappers': json.dumps(wrappers, ensure_ascii=False)}
    conf.update(extra)
    tiku.config_set(conf)
    tiku._init_tiku()
    return tiku


class _FakeResponse:
    def __init__(self, payload, status_code=200, text=None):
        self._payload = payload
        self.status_code = status_code
        self.text = text if text is not None else json.dumps(payload, ensure_ascii=False)

    def json(self):
        if self._payload is None:
            raise ValueError('no json')
        return self._payload


Q_INFO = {'title': '测试题', 'type': 'single', 'options': 'A. 甲\nB. 乙'}


class TestOcsExtraction:
    def test_default_shape_data_answer(self):
        tiku = _make_tiku([{'name': 't', 'url': 'https://x/q'}])
        assert tiku._extract_answer(
            {'code': 1, 'data': {'answer': '正确'}}, tiku._wrappers[0]) == '正确'

    def test_answers_list_joined_with_hash(self):
        tiku = _make_tiku([{'name': 't', 'url': 'https://x/q'}])
        assert tiku._extract_answer(
            {'code': 1, 'data': {'answers': ['选项一', '选项二']}}, tiku._wrappers[0]) == '选项一#选项二'

    def test_top_level_answer_field(self):
        tiku = _make_tiku([{'name': 't', 'url': 'https://x/q'}])
        assert tiku._extract_answer({'answer': 'B'}, tiku._wrappers[0]) == 'B'

    def test_code_zero_is_miss(self):
        tiku = _make_tiku([{'name': 't', 'url': 'https://x/q'}])
        assert tiku._extract_answer(
            {'code': 0, 'msg': '题目不存在'}, tiku._wrappers[0]) is None

    def test_answer_path_override(self):
        tiku = _make_tiku([{'name': 't', 'url': 'https://x/q', 'answer_path': 'result.list'}],
                          ocs_answer_path='result.list')
        payload = {'result': {'list': ['甲', '乙']}}
        assert tiku._extract_answer(payload, tiku._wrappers[0]) == '甲#乙'

    def test_plain_text_body(self):
        tiku = _make_tiku([{'name': 't', 'url': 'https://x/q', 'contentType': 'text'}])
        assert tiku._extract_answer(' 正确答案 ', tiku._wrappers[0]) == '正确答案'


class TestOcsRequest:
    def test_get_query_template_and_encoding(self):
        tiku = _make_tiku([{'name': 't', 'url': 'https://x/q?kw=${title}',
                            'data': {'type': '${type}'}}])
        with patch.object(requests, 'get',
                          return_value=_FakeResponse({'code': 1, 'answer': 'A'})) as mock_get:
            answer = tiku._query(Q_INFO)
        assert answer == 'A'
        args, kwargs = mock_get.call_args
        assert args[0] == 'https://x/q?kw=%E6%B5%8B%E8%AF%95%E9%A2%98'
        assert kwargs['params'] == {'type': 'single'}

    def test_post_json_body(self):
        tiku = _make_tiku([{'name': 't', 'url': 'https://x/q', 'method': 'post',
                            'contentType': 'json', 'data': {'question': '${title}'}}])
        with patch.object(requests, 'post',
                          return_value=_FakeResponse({'code': 1, 'data': {'answer': '乙'}})) as mock_post:
            answer = tiku._query(Q_INFO)
        assert answer == '乙'
        assert mock_post.call_args.kwargs['json'] == {'question': '测试题'}

    def test_network_failure_falls_through_to_next_wrapper(self):
        wrappers = [
            {'name': '坏源', 'url': 'https://bad/q'},
            {'name': '好源', 'url': 'https://good/q', 'data': {'question': '${title}'}},
        ]
        tiku = _make_tiku(wrappers)

        def fake_get(url, **kwargs):
            if url.startswith('https://bad'):
                raise requests.exceptions.ConnectTimeout('down')
            return _FakeResponse({'code': 1, 'answer': '兜底'})

        with patch.object(requests, 'get', side_effect=fake_get):
            assert tiku._query(Q_INFO) == '兜底'

    def test_invalid_config_disables_tiku(self):
        tiku = TikuOcs()
        tiku.config_set({'ocs_wrappers': 'not-json'})
        tiku.init_tiku()
        assert tiku.DISABLE is True

    def test_empty_config_disables_tiku(self):
        tiku = TikuOcs()
        tiku.config_set({'ocs_wrappers': ''})
        tiku.init_tiku()
        assert tiku.DISABLE is True

    def test_handler_warning_but_still_parsed(self):
        tiku = _make_tiku([{'name': 't', 'url': 'https://x/q',
                            'handler': 'return (res)=> [res.answer, undefined]'}])
        assert len(tiku._wrappers) == 1


# ------------------------------------------------------------- 学习次数事件

def _make_chaoxing_for_count():
    cx = Chaoxing.__new__(Chaoxing)
    cx._cancel_event = threading.Event()
    cx.kwargs = {'learning_count_interval': 0}
    cx.rate_limiter = SimpleNamespace(limit_rate=lambda *a, **k: None)
    cx._access_chapter_for_count = lambda course, point: '<html>ok</html>'
    cx._extract_and_send_setlog = lambda html: None
    cx._send_monitor_heartbeat = lambda course, point: None
    cx._sleep = lambda seconds: None
    return cx


class TestLearnCountEvents:
    def test_progress_events_emitted(self):
        cx = _make_chaoxing_for_count()
        events = []
        cx.emit_progress = events.append
        points = [{'title': '第一章'}, {'title': '第二章'}]
        result = cx.increase_chapter_learning_count({'title': '课程A'}, points, 2)
        assert result is StudyResult.SUCCESS
        kinds = [(event['kind'], event['phase']) for event in events]
        assert ('learn', 'start') in kinds
        assert ('learn', 'done') in kinds
        progress = [event for event in events if event.get('phase') == 'progress']
        assert [event['count'] for event in progress] == [1, 2]
        assert progress[0]['target'] == 2
        assert progress[0]['course'] == '课程A'

    def test_cancel_emits_error_event(self):
        cx = _make_chaoxing_for_count()
        cx._cancel_event.set()
        events = []
        cx.emit_progress = events.append
        result = cx.increase_chapter_learning_count(
            {'title': '课程A'}, [{'title': '第一章'}], 5)
        assert result is StudyResult.ERROR
        assert any(
            event['kind'] == 'learn' and event['phase'] == 'error'
            and event.get('message') == '已停止'
            for event in events
        )

    def test_empty_points_emits_error_event(self):
        cx = _make_chaoxing_for_count()
        events = []
        cx.emit_progress = events.append
        result = cx.increase_chapter_learning_count({'title': '课程A'}, [], 5)
        assert result is StudyResult.SUCCESS
        assert any(
            event['kind'] == 'learn' and event['phase'] == 'error'
            and '没有章节' in event.get('message', '')
            for event in events
        )
