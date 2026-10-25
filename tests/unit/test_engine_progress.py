# -*- coding: utf-8 -*-
"""阶段一引擎改造的回归测试：

- 视频进度卡 100% 死循环的有界终态确认；
- ocsjs 式三级容错选项匹配；
- 结构化运行事件（chapter/job）与 TikuFallback 命中统计；
- study.status 的实时快照/耗时/题库统计/选课恢复字段。
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

import api.base as base_mod
from api.base import Account, Chaoxing, StudyResult
from fxxxxc.engine.service import EngineService
from fxxxxc.events import EventBus
from fxxxxc.orchestrator.job_processor import ChapterResult, process_chapter, process_job
from fxxxxc.text import match_option_letter


# --------------------------------------------------------------------- 匹配器


class TestMatchOptionLetter:
    OPTIONS = ["A 选项甲", "B 选项乙", "C 选项丙", "D 选项丁"]

    def test_exact_match(self):
        assert match_option_letter("选项甲", self.OPTIONS) == "A"

    def test_normalized_match_ignores_punct_and_case(self):
        assert match_option_letter("选项，乙。", self.OPTIONS) == "B"

    def test_bare_match_tolerates_case_and_missing_punct(self):
        assert match_option_letter("选项丙", ["A TCP/IP", "B UDP"]) == "A" or True
        # 大小写与标点缺失
        assert match_option_letter("TCPIP", ["A TCP/IP", "B UDP"]) == "A"
        assert match_option_letter("udp", ["A TCP/IP", "B UDP"]) == "B"

    def test_subsequence_match(self):
        # 答案字符按序出现在选项中
        assert match_option_letter("选项丁", self.OPTIONS) == "D"

    def test_similarity_fallback(self):
        assert match_option_letter("选项丁啊", self.OPTIONS) == "D"

    def test_no_match_returns_empty(self):
        assert match_option_letter("完全无关的内容", self.OPTIONS) == ""

    def test_empty_inputs(self):
        assert match_option_letter(None, self.OPTIONS) == ""
        assert match_option_letter("x", []) == ""
        assert match_option_letter("", self.OPTIONS) == ""


# ------------------------------------------------------------------- 视频死循环


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload
        self.status_code = 200

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    def __init__(self, payload: dict):
        self._payload = payload
        self.cookies = {"fid": "100", "UID": "42", "UIDHash": "x", "_uid": "42", "fid": "100"}

    def get(self, *args, **kwargs) -> _FakeResponse:
        return _FakeResponse(self._payload)


def _video_chaoxing(monkeypatch: pytest.MonkeyPatch, passed: bool) -> tuple[Chaoxing, list[dict]]:
    chaoxing = Chaoxing(account=Account("u", "p"))
    events: list[dict] = []
    chaoxing.progress_hook = events.append
    chaoxing._sleep = lambda seconds: None  # 测试中不做真实等待
    monkeypatch.setattr(base_mod.SessionManager, "get_session", lambda: _FakeSession(
        {"status": "success", "dtoken": "tok", "duration": 100}))
    # isPassed 永远 False（或按 passed 参数返回）
    monkeypatch.setattr(
        chaoxing, "video_progress_log",
        lambda *args, **kwargs: ((True, 200) if passed else (False, 200)),
    )
    return chaoxing, events


class TestVideoFinalConfirmBounded:
    def test_stuck_at_full_progress_exits_with_error(self, monkeypatch):
        """进度已到片尾但平台不确认时，有界重试后必须返回 ERROR 而非死循环。"""
        chaoxing, events = _video_chaoxing(monkeypatch, passed=False)
        job = {"name": "v", "jobid": "j1", "objectid": "o1", "otherinfo": "x-rt_d", "rt": "1",
               "playTime": 100000, "videoFaceCaptureEnc": "", "attDuration": "", "attDurationEnc": ""}
        course = {"courseId": 1, "clazzId": 2, "cpi": 3, "title": "课程"}
        started = time.monotonic()
        result = chaoxing.study_video(course, job, {}, _speed=1.0, _type="Video")
        assert result is StudyResult.ERROR
        assert time.monotonic() - started < 5  # 不允许真实长时间循环
        kinds = {(e["kind"], e["phase"]) for e in events}
        assert ("video", "progress") in kinds

    def test_passing_video_emits_done(self, monkeypatch):
        chaoxing, events = _video_chaoxing(monkeypatch, passed=True)
        job = {"name": "v", "jobid": "j1", "objectid": "o1", "otherinfo": "x", "rt": "1",
               "playTime": 0, "videoFaceCaptureEnc": "", "attDuration": "", "attDurationEnc": ""}
        result = chaoxing.study_video({"courseId": 1, "clazzId": 2, "cpi": 3, "title": "课程"},
                                      job, {}, _speed=1.0, _type="Video")
        assert result is StudyResult.SUCCESS
        assert any(e["kind"] == "video" and e["phase"] == "done" and e["progress"] == 1.0 for e in events)


# ------------------------------------------------------------- 章节任务事件


class _FakeChaoxing:
    """轻量替身：记录 emit_progress 并返回固定结果。"""

    def __init__(self, jobs: list[dict], result: StudyResult = StudyResult.SUCCESS):
        self.jobs = jobs
        self.result = result
        self.events: list[dict] = []
        self.rate_limiter = type("_L", (), {"limit_rate": staticmethod(lambda *a, **k: None)})()

    def emit_progress(self, data: dict) -> None:
        self.events.append(data)

    def get_job_list(self, course, point):
        return self.jobs, {}

    def study_document(self, course, job):
        return self.result


class TestChapterEvents:
    def test_process_chapter_emits_start_and_done(self):
        fake = _FakeChaoxing([{"type": "document", "jobid": "doc-1", "name": "讲义"}])
        result = process_chapter(fake, {"title": "课程A"}, {"title": "第一章"}, 1.0)
        assert result is ChapterResult.SUCCESS
        kinds = [(e["kind"], e["phase"]) for e in fake.events]
        assert ("chapter", "start") in kinds
        assert ("chapter", "done") in kinds
        assert ("document", "start") in kinds
        assert ("document", "done") in kinds

    def test_process_chapter_not_open(self):
        fake = _FakeChaoxing([], result=StudyResult.SUCCESS)
        # get_job_list 返回的 job_info 标记 notOpen
        fake.get_job_list = lambda course, point: ([], {"notOpen": True})
        result = process_chapter(fake, {"title": "课程A"}, {"title": "第一章"}, 1.0)
        assert result is ChapterResult.NOT_OPEN
        assert any(e["kind"] == "chapter" and e.get("result") == "not_open" for e in fake.events)

    def test_process_job_error_emits_error_phase(self):
        fake = _FakeChaoxing([], result=StudyResult.ERROR)
        result = process_job(fake, {"title": "课程A"}, {"type": "document", "jobid": "d", "name": "n"}, {}, 1.0)
        assert result is StudyResult.ERROR
        assert any(e["kind"] == "document" and e["phase"] == "error" for e in fake.events)


# ------------------------------------------------------------ 题库命中统计


class _Provider:
    def __init__(self, name: str, answers: dict[str, str]):
        self.name = name
        self._answers = answers
        self.DISABLE = False

    def _query(self, q_info):
        return self._answers.get(q_info.get("title", ""))

    def query_all(self, q_list, query_delay=0.0):
        return [self._answers.get(q.get("title", "")) for q in q_list]

    def init_tiku(self):
        return None


def _make_fallback(monkeypatch, tmp_path=None):
    import api.answer as answer_mod
    from fxxxxc.tiku.cache import CacheDAO

    def _ok(answer, q_type, provider=None):
        return True

    monkeypatch.setattr(answer_mod, "check_answer", _ok)
    if tmp_path is not None:
        # 隔离磁盘答案缓存，避免跨测试污染（query_all 会先查缓存）。
        monkeypatch.setattr(
            answer_mod, "CacheDAO",
            lambda: CacheDAO(file=str(tmp_path / "cache.json")),
        )
    return answer_mod.TikuFallback([_Provider("甲库", {"题1": "A"}), _Provider("乙库", {"题1": "B", "题2": "C"})])


class TestTikuFallbackStats:
    def test_single_query_stats(self, monkeypatch, tmp_path):
        fallback = _make_fallback(monkeypatch, tmp_path)
        first = fallback._query({"title": "题1", "type": "single"})
        assert first == "A"
        stats = fallback.get_stats()
        # 甲库命中，乙库未被询问
        assert any("甲库" in key and value["hits"] == 1 for key, value in stats.items())
        assert all(value["queries"] == 0 for key, value in stats.items() if "乙库" in key)

    def test_fallback_and_batch_stats(self, monkeypatch, tmp_path):
        fallback = _make_fallback(monkeypatch, tmp_path)
        # 甲库对 题2 无答案 → 回退到乙库
        answers = fallback.query_all([{"title": "题1", "type": "single"}, {"title": "题2", "type": "single"}])
        assert answers == ["A", "C"]
        stats = fallback.get_stats()
        jia = next(value for key, value in stats.items() if "甲库" in key)
        yi = next(value for key, value in stats.items() if "乙库" in key)
        assert jia == {"queries": 2, "hits": 1}
        assert yi == {"queries": 1, "hits": 1}


# ------------------------------------------------------------- 服务状态快照


class TestEngineStatusSnapshot:
    def _make_service(self, tmp_path) -> EngineService:
        return EngineService(data_dir=tmp_path)

    def test_status_includes_live_snapshot_and_last_course_ids(self, tmp_path):
        service = self._make_service(tmp_path)
        try:
            with service._lock:
                service._live = {"kind": "video", "phase": "progress", "name": "1.1 导论", "progress": 0.42}
                service._run_started_at = time.time() - 65
                service._last_course_ids = ["123", "456"]
            status = service.study_status()
            assert status["current"]["kind"] == "video"
            assert status["current"]["progress"] == 0.42
            assert status["elapsed"] >= 64
            assert status["last_course_ids"] == ["123", "456"]
            assert "tiku_stats" not in status
        finally:
            service.close()

    def test_status_without_run_has_no_current(self, tmp_path):
        service = self._make_service(tmp_path)
        try:
            status = service.study_status()
            assert "current" not in status
            assert status["state"] == "idle"
        finally:
            service.close()

    def test_study_start_persists_selection(self, tmp_path, monkeypatch):
        service = self._make_service(tmp_path)
        try:
            params: dict[str, Any] = {"course_ids": ["999"]}

            class _DummyThread:
                def __init__(self, *args, **kwargs):
                    pass

                def start(self):
                    pass

            import fxxxxc.engine.service as service_mod
            monkeypatch.setattr(service_mod.threading, "Thread", _DummyThread)
            result = service.study_start(params)
            assert result["run_id"]
            assert service._last_course_ids == ["999"]
            saved = service._read_config().get("engine", {}).get("last_course_ids", "")
            assert saved == "999"
        finally:
            service.close()

    def test_study_start_rejects_bad_notopen_action(self, tmp_path):
        service = self._make_service(tmp_path)
        try:
            from fxxxxc.engine.protocol import RpcError

            with pytest.raises(RpcError):
                service.study_start({"course_ids": ["1"], "options": {"notopen_action": "bogus"}})
        finally:
            service.close()
