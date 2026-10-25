# -*- coding: utf-8 -*-
"""course.detail RPC（章节状态明细+TTL 缓存）与 study.status 分课程进度的契约测试。"""

from __future__ import annotations

import pytest

from fxxxxc.engine.protocol import RpcError
from fxxxxc.engine.service import EngineService
from fxxxxc.orchestrator import ChapterResult, ChapterTask


class _StubChaoxing:
    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []

    def get_course_point(self, course_id, clazz_id, cpi):
        self.calls.append((course_id, clazz_id, cpi))
        return {
            "hasLocked": False,
            "points": [
                {"id": "1", "title": "第一章", "jobCount": "2",
                 "has_finished": True, "need_unlock": False},
                {"id": "2", "title": "第二章", "jobCount": "1",
                 "has_finished": False, "need_unlock": True},
                {"id": "3", "title": "第三章", "jobCount": "1",
                 "has_finished": False, "need_unlock": False},
            ],
        }


@pytest.fixture
def service(tmp_path):
    svc = EngineService(data_dir=tmp_path)
    stub = _StubChaoxing()
    svc._ensure_chaoxing = lambda: stub  # type: ignore[method-assign]
    svc._chaoxing = stub  # type: ignore[assignment]
    return svc


class TestCourseDetail:
    def test_shape_and_counts(self, service):
        detail = service.course_detail({"course_id": "c1", "clazz_id": "k1", "cpi": "p"})
        assert detail["total"] == 3
        assert detail["finished"] == 1
        assert detail["locked"] == 1
        assert detail["has_locked"] is False
        assert [chapter["title"] for chapter in detail["chapters"]] == [
            "第一章", "第二章", "第三章"]
        assert detail["chapters"][1]["need_unlock"] is True

    def test_requires_course_and_clazz_id(self, service):
        with pytest.raises(RpcError):
            service.course_detail({"course_id": "", "clazz_id": "k1"})

    def test_ttl_cache_avoids_refetch(self, service):
        service.course_detail({"course_id": "c1", "clazz_id": "k1"})
        service.course_detail({"course_id": "c1", "clazz_id": "k1"})
        stub = service._ensure_chaoxing()
        assert len(stub.calls) == 1  # 命中缓存
        service.course_detail({"course_id": "c1", "clazz_id": "k1", "refresh": True})
        assert len(stub.calls) == 2  # 强制回源

    def test_different_courses_cached_separately(self, service):
        service.course_detail({"course_id": "c1", "clazz_id": "k1"})
        service.course_detail({"course_id": "c2", "clazz_id": "k2"})
        stub = service._ensure_chaoxing()
        assert len(stub.calls) == 2


class _FakeProcessor:
    """最小化 JobProcessor 替身：只暴露 study_status 需要的属性。"""

    def __init__(self, tasks, failed_tasks):
        self.tasks = tasks
        self.failed_tasks = failed_tasks

    class _Queue:
        unfinished_tasks = 1

    task_queue = _Queue()


class TestCoursesProgress:
    def test_study_status_reports_per_course_progress(self, service):
        course_a = {"courseId": "a", "title": "课程A"}
        course_b = {"courseId": "b", "title": "课程B"}
        tasks = [
            ChapterTask(index=0, point={"title": "一"}, course=course_a,
                        result=ChapterResult.SUCCESS),
            ChapterTask(index=1, point={"title": "二"}, course=course_a,
                        result=ChapterResult.PENDING),
            ChapterTask(index=2, point={"title": "三"}, course=course_b,
                        result=ChapterResult.PENDING),
        ]
        service._processor = _FakeProcessor(
            tasks=tasks, failed_tasks=[ChapterTask(index=2, point={}, course=course_b)])
        service._run_id = "run-1"

        payload = service.study_status()
        progress = payload["courses_progress"]
        assert [(item["course_id"], item["total"], item["done"], item["failed"])
                for item in progress] == [("a", 2, 1, 0), ("b", 1, 0, 1)]
        assert progress[0]["title"] == "课程A"

    def test_no_processor_no_progress_key(self, service):
        payload = service.study_status()
        assert "courses_progress" not in payload
