# -*- coding: utf-8 -*-
"""course.detail RPC（章节状态明细+TTL 缓存）与 study.status 分课程进度的契约测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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


class TestLearnPhaseProgress:
    def _service_with_processor(self, tmp_path, learn):
        svc = EngineService(data_dir=tmp_path)
        svc._learn_active, svc._learn_done, svc._learn_total = learn
        course = {"courseId": "a", "title": "课程A"}
        tasks = [
            ChapterTask(index=0, point={"title": "一"}, course=course,
                        result=ChapterResult.SUCCESS),
            ChapterTask(index=1, point={"title": "二"}, course=course,
                        result=ChapterResult.PENDING),
        ]
        processor = _FakeProcessor(tasks=tasks, failed_tasks=[])
        processor.task_queue.unfinished_tasks = 0  # 章节全部完成
        svc._processor = processor
        svc._run_id = "run-1"
        return svc

    def test_learn_counts_into_total(self, tmp_path):
        """学习次数阶段进行中：total/done 折入课程门数，进度不再停在 100%。"""
        svc = self._service_with_processor(tmp_path, (True, 1, 2))
        payload = svc.study_status()
        assert payload["total"] == 2 + 2
        assert payload["done"] == 2 + 1
        assert payload["learn"] == {"active": True, "done": 1, "total": 2}
        assert payload["done"] < payload["total"]

    def test_learn_inactive_keeps_chapter_totals(self, tmp_path):
        svc = self._service_with_processor(tmp_path, (False, 2, 2))
        payload = svc.study_status()
        assert payload["total"] == 2
        assert payload["done"] == 2
        assert payload["learn"]["active"] is False


class TestCourseExtras:
    def _patch_session(self, responses):
        """拦截 SessionManager.get_session().get（extras 的真实请求路径）。"""
        session = MagicMock()
        session.get.side_effect = responses
        return patch("api.base.SessionManager.get_session", return_value=session)

    def test_extras_learn_count_with_target(self, tmp_path):
        svc = EngineService(data_dir=tmp_path)
        html = "<div>学习次数： 12/100</div>"
        # 第 1 个响应=章节学习页，第 2 个=门户页（404 即可短路成绩提取）
        with self._patch_session([
            MagicMock(status_code=200, text=html),
            MagicMock(status_code=404, text=""),
        ]) as sess:
            extras = svc._fetch_course_extras("c1", "k1", "p1", "pt1")
        assert extras["learn_count"] == 12
        assert extras["learn_target"] == 100
        assert extras["score"] is None
        # 首个请求是章节学习页（studentstudyAjax）
        assert "studentstudyAjax" in sess.return_value.get.call_args_list[0].args[0]

    def test_extras_learn_count_without_target(self, tmp_path):
        svc = EngineService(data_dir=tmp_path)
        with self._patch_session([
            MagicMock(status_code=200, text="学习次数 7 次"),
            MagicMock(status_code=404, text=""),
        ]):
            extras = svc._fetch_course_extras("c1", "k1", "p1", "pt1")
        assert extras["learn_count"] == 7
        assert extras["learn_target"] is None

    def test_extras_score_follows_platform_link(self, tmp_path):
        svc = EngineService(data_dir=tmp_path)
        portal = '<a href="https://x.chaoxing.com/assessment?i=1">成绩</a>'
        score_page = "本课程综合成绩： 86.5 分"
        # 无首章节 → 第 1 个请求即门户页，门户带成绩链接 → 第 2 个请求是成绩页
        with self._patch_session([
            MagicMock(status_code=200, text=portal, url="https://portal/"),
            MagicMock(status_code=200, text=score_page),
        ]):
            extras = svc._fetch_course_extras("c1", "k1", "p1", "")
        assert extras["score"] == 86.5

    def test_extras_fail_open_on_errors(self, tmp_path):
        import requests as requests_mod

        svc = EngineService(data_dir=tmp_path)
        with self._patch_session(
                requests_mod.exceptions.ConnectTimeout("down")):
            extras = svc._fetch_course_extras("c1", "k1", "p1", "pt1")
        assert extras == {
            "learn_count": None, "learn_target": None, "score": None}


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
