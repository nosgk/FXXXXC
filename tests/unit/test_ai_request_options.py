# -*- coding: utf-8 -*-
"""AI 题库请求选项与响应解析的回归测试（对齐上游 PR #643/#633）。"""

from __future__ import annotations

import json
from types import SimpleNamespace

from api.answer import AI, message_answer_text

ANSWER_JSON = json.dumps({"Answer": ["光合作用"]}, ensure_ascii=False)


class TestMessageAnswerText:
    def test_prefers_content(self):
        msg = SimpleNamespace(content=ANSWER_JSON, reasoning_content='思考过程')
        assert message_answer_text(msg) == ANSWER_JSON

    def test_falls_back_to_reasoning_content(self):
        msg = SimpleNamespace(content=None, reasoning_content=ANSWER_JSON)
        assert message_answer_text(msg) == ANSWER_JSON

    def test_blank_content_falls_back(self):
        msg = SimpleNamespace(content='   \n', reasoning_content=ANSWER_JSON)
        assert message_answer_text(msg) == ANSWER_JSON

    def test_missing_attributes(self):
        assert message_answer_text(SimpleNamespace()) == ''


def _make_ai(**conf_overrides) -> AI:
    conf = {
        'endpoint': 'https://example.com/v1',
        'key': 'test-key',
        'model': 'test-model',
        'http_proxy': '',
        'min_interval_seconds': '0',
    }
    conf.update(conf_overrides)
    ai = AI()
    ai.config_set(conf)
    ai._init_tiku()
    return ai


class TestExtraBody:
    def test_missing_uses_default_thinking_disabled(self):
        assert _make_ai().extra_body == {'thinking': {'type': 'disabled'}}

    def test_empty_object_kept(self):
        assert _make_ai(extra_body='{}').extra_body == {}

    def test_valid_json_parsed(self):
        assert _make_ai(extra_body='{"enable_thinking": false}').extra_body == {
            'enable_thinking': False
        }

    def test_invalid_json_ignored(self):
        assert _make_ai(extra_body='not-json').extra_body == {}

    def test_non_object_ignored(self):
        assert _make_ai(extra_body='[1, 2]').extra_body == {}

    def test_merged_into_completion_kwargs(self):
        kwargs = _make_ai(extra_body='{"a": 1}')._completion_kwargs(model='m')
        assert kwargs['extra_body'] == {'a': 1}

    def test_no_extra_body_no_key(self):
        kwargs = _make_ai(extra_body='{}')._completion_kwargs(model='m')
        assert 'extra_body' not in kwargs


class TestJsonMode:
    def test_missing_is_false(self):
        assert _make_ai().json_mode is False

    def test_true_parsed(self):
        assert _make_ai(json_mode='true').json_mode is True
        assert _make_ai(json_mode='True').json_mode is True

    def test_invalid_is_false(self):
        assert _make_ai(json_mode='yes').json_mode is False

    def test_response_format_injected_when_enabled(self):
        kwargs = _make_ai(json_mode='true')._completion_kwargs(model='m')
        assert kwargs['response_format'] == {'type': 'json_object'}

    def test_no_response_format_when_disabled(self):
        kwargs = _make_ai()._completion_kwargs(model='m')
        assert 'response_format' not in kwargs


class TestQueryParse:
    Q_INFO = {'type': 'single', 'title': '植物吸收光能转化为什么?',
              'options': 'A. 光合作用\nB. 呼吸作用'}

    def _run(self, message):
        class _FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        class _FakeClient:
            def __init__(self):
                self.chat = SimpleNamespace(completions=_FakeCompletions())

        client = _FakeClient()
        ai = _make_ai()
        ai._client = client
        ai._client_key = (ai.endpoint, ai.key, ai.http_proxy)
        return ai._query(self.Q_INFO), client

    def test_reasoning_only_response_is_parsed(self):
        """思考模式正文为空时，答案在 reasoning_content 里也要能取到。"""
        msg = SimpleNamespace(content=None, reasoning_content=ANSWER_JSON)
        answer, _ = self._run(msg)
        assert answer == '光合作用'

    def test_markdown_wrapped_response(self):
        msg = SimpleNamespace(content='```json\n' + ANSWER_JSON + '\n```')
        answer, _ = self._run(msg)
        assert answer == '光合作用'

    def test_unparsable_response_returns_none(self):
        msg = SimpleNamespace(content='抱歉，我无法回答')
        answer, _ = self._run(msg)
        assert answer is None
