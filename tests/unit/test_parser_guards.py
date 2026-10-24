# -*- coding: utf-8 -*-
"""Regression tests for BUG-011/BUG-013/BUG-014 parser hardening."""

from __future__ import annotations

import json

from api.decode import (
    _extract_marg_json,
    decode_course_card,
    decode_course_list,
    decode_questions_info,
)


def test_course_list_with_missing_fields_is_skipped():
    assert decode_course_list('<div class="course" id="broken"></div>') == []


def test_questions_without_form_returns_empty_shape():
    data = decode_questions_info("<html><body>no form</body></html>")
    assert data["questions"] == []
    assert data["answerwqbid"] == ""


def test_marg_scanner_handles_braces_inside_strings():
    html = 'mArg={"text":"a};b","value":1};'
    raw = _extract_marg_json(html)
    assert raw is not None
    assert json.loads(raw) == {"text": "a};b", "value": 1}


def test_course_card_with_broken_json_returns_empty():
    jobs, info = decode_course_card("mArg={not json};")
    assert jobs == []
    assert info == {}
