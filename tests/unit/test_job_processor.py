# -*- coding: utf-8 -*-
"""Regression tests for BUG-002: worker errors must not hang the pool."""

from __future__ import annotations

import threading
import time

import main
from main import ChapterResult, ChapterTask, JobProcessor


class _NoopRateLimiter:
    def limit_rate(self, *args, **kwargs):
        return None


class _ExplodingChaoxing:
    def __init__(self):
        self.rate_limiter = _NoopRateLimiter()
        self.cancelled = False

    def get_job_list(self, course, point):
        raise RuntimeError("boom")

    def cancel(self):
        self.cancelled = True


class _SuccessChaoxing:
    def __init__(self):
        self.rate_limiter = _NoopRateLimiter()
        self.cancelled = False

    def get_job_list(self, course, point):
        return [], {}

    def cancel(self):
        self.cancelled = True


def _make_processor(chaoxing, tasks, **config):
    base_config = {
        "speed": 1.0,
        "jobs": 2,
        "notopen_action": "retry",
        "retry_interval": 0.01,
        "chapter_max_tries": 2,
    }
    base_config.update(config)
    return JobProcessor(chaoxing, tasks, base_config)


def _run_with_timeout(processor, timeout=5.0):
    thread = threading.Thread(target=processor.run, daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), "JobProcessor.run() hung"


def _task(index=0):
    return ChapterTask(index=index, point={"title": "章节", "has_finished": False}, course={"title": "课程"})


def test_worker_exception_is_retried_and_does_not_hang():
    task = _task()
    processor = _make_processor(_ExplodingChaoxing(), [task])

    _run_with_timeout(processor)

    assert task.tries == 2
    assert task in processor.failed_tasks
    assert processor.task_queue.unfinished_tasks == 0


def test_stop_before_run_returns_immediately():
    processor = _make_processor(_SuccessChaoxing(), [_task()])
    processor.stop()

    _run_with_timeout(processor)

    assert processor.task_queue.unfinished_tasks == 0


def test_stop_cancels_chaoxing():
    chaoxing = _SuccessChaoxing()
    processor = _make_processor(chaoxing, [_task()])
    processor.stop()

    assert chaoxing.cancelled is True


def test_chapter_result_values_are_integers():
    assert ChapterResult.SUCCESS.value == 0
    assert ChapterResult.ERROR.value == 1
    assert ChapterResult.NOT_OPEN.value == 2
    assert ChapterResult.PENDING.value == 3


def test_successful_empty_chapter_does_not_retry():
    task = _task()
    processor = _make_processor(_SuccessChaoxing(), [task])

    _run_with_timeout(processor)

    assert task.tries == 0
    assert processor.failed_tasks == []


def test_retry_interval_is_respected_without_blocking_stop():
    task = _task()
    processor = _make_processor(
        _ExplodingChaoxing(),
        [task],
        retry_interval=5.0,
        chapter_max_tries=5,
    )

    thread = threading.Thread(target=processor.run, daemon=True)
    thread.start()
    time.sleep(0.1)
    processor.stop()
    thread.join(2.0)

    assert not thread.is_alive()
    assert processor.task_queue.unfinished_tasks == 0
