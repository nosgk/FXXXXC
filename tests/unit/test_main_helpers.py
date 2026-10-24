# -*- coding: utf-8 -*-
"""Regression tests for course filtering, live results and helpers."""

from __future__ import annotations

import pytest

import main
from api.base import StudyResult
from api.exceptions import InputFormatError
from fxxxxc.orchestrator import job_processor


COURSES = [
    {"courseId": "c1", "clazzId": "k1", "title": "课程一"},
    {"courseId": "c2", "clazzId": "k2", "title": "课程二"},
]


def test_filter_courses_explicit_unknown_list_raises():
    with pytest.raises(InputFormatError):
        main.filter_courses(COURSES, ["missing"])


def test_filter_courses_explicit_valid_list_selects_matches():
    result = main.filter_courses(COURSES, ["c2"])
    assert [course["courseId"] for course in result] == ["c2"]


def test_filter_courses_ignores_unknown_ids_when_some_match():
    result = main.filter_courses(COURSES, ["c1", "missing"])
    assert [course["courseId"] for course in result] == ["c1"]


def test_process_job_live_propagates_failure(monkeypatch):
    class _DummyLive:
        def __init__(self, attachment, defaults, course_id):
            self.attachment = attachment
            self.defaults = defaults
            self.course_id = course_id

    class _Chaoxing:
        def get_uid(self):
            return "uid"

    monkeypatch.setattr(job_processor, "Live", _DummyLive)
    monkeypatch.setattr(job_processor.LiveProcessor, "run_live", staticmethod(lambda live, speed: False))

    result = main.process_job(
        _Chaoxing(),
        {"courseId": "c1", "clazzId": "k1"},
        {"type": "live", "jobid": "j1"},
        {"knowledgeid": "k1"},
        1.0,
    )
    assert result is StudyResult.ERROR


def test_process_job_live_propagates_success(monkeypatch):
    class _DummyLive:
        def __init__(self, attachment, defaults, course_id):
            pass

    class _Chaoxing:
        def get_uid(self):
            return "uid"

    monkeypatch.setattr(job_processor, "Live", _DummyLive)
    monkeypatch.setattr(job_processor.LiveProcessor, "run_live", staticmethod(lambda live, speed: True))

    result = main.process_job(
        _Chaoxing(),
        {"courseId": "c1", "clazzId": "k1"},
        {"type": "live", "jobid": "j1"},
        {"knowledgeid": "k1"},
        1.0,
    )
    assert result is StudyResult.SUCCESS
