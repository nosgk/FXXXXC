# -*- coding: utf-8 -*-
"""Chapter queue, worker pool and per-job dispatch."""

from __future__ import annotations

import enum
import threading
import time
from dataclasses import dataclass
from queue import Empty, PriorityQueue
from typing import Any, Callable

from loguru import logger

from api.base import Chaoxing, StudyResult
from api.exceptions import InputFormatError
from api.live import Live
from api.live_process import LiveProcessor

try:
    from queue import ShutDown
except ImportError:  # Python < 3.13

    class ShutDown(Exception):
        pass


class ChapterResult(enum.Enum):
    SUCCESS = 0
    ERROR = 1
    NOT_OPEN = 2
    PENDING = 3


@dataclass
class ChapterTask:
    index: int
    point: dict[str, Any]
    course: dict[str, Any]
    result: ChapterResult = ChapterResult.PENDING
    tries: int = 0

    def __lt__(self, other):
        if not isinstance(other, ChapterTask):
            return NotImplemented
        return self.index < other.index


def _emit(chaoxing, data: dict) -> None:
    """Best-effort progress emission; CLI runs have no hook installed."""
    emit = getattr(chaoxing, "emit_progress", None)
    if callable(emit):
        try:
            emit(data)
        except Exception:  # noqa: BLE001 - listeners must never break workers
            pass


def process_job(
    chaoxing: Chaoxing,
    course: dict,
    job: dict,
    job_info: dict,
    speed: float,
) -> StudyResult:
    """Dispatch one task point to the appropriate study implementation."""
    job_type = job.get("type")
    task_name = str(job.get("name") or job.get("jobid") or job_type or "unknown")
    _emit(
        chaoxing,
        {"kind": str(job_type or "unknown"), "phase": "start", "name": task_name, "course": course.get("title", "")},
    )

    if job_type == "video":
        logger.trace(f"识别到视频任务, 任务章节: {course.get('title', '')} 任务ID: {job.get('jobid', '')}")
        video_result = chaoxing.study_video(course, job, job_info, _speed=speed, _type="Video")
        if video_result.is_failure():
            logger.warning("当前任务非视频任务, 正在尝试音频任务解码")
            video_result = chaoxing.study_video(course, job, job_info, _speed=speed, _type="Audio")
        if video_result.is_failure():
            logger.warning(
                f"出现异常任务 -> 任务章节: {course.get('title', '')} 任务ID: {job.get('jobid', '')}, 已跳过"
            )
        _emit_job_result(chaoxing, job_type, task_name, course, video_result)
        return video_result

    if job_type == "document":
        logger.trace(f"识别到文档任务, 任务章节: {course.get('title', '')} 任务ID: {job.get('jobid', '')}")
        result = chaoxing.study_document(course, job)
        _emit_job_result(chaoxing, job_type, task_name, course, result)
        return result

    if job_type == "workid":
        logger.trace(f"识别到章节检测任务, 任务章节: {course.get('title', '')}")
        result = chaoxing.study_work(course, job, job_info)
        _emit_job_result(chaoxing, job_type, task_name, course, result)
        return result

    if job_type == "read":
        logger.trace(f"识别到阅读任务, 任务章节: {course.get('title', '')}")
        result = chaoxing.study_read(course, job, job_info)
        _emit_job_result(chaoxing, job_type, task_name, course, result)
        return result

    if job_type == "live":
        logger.trace(f"识别到直播任务, 任务章节: {course.get('title', '')} 任务ID: {job.get('jobid', '')}")
        try:
            defaults = {
                "userid": chaoxing.get_uid(),
                "clazzId": course.get("clazzId"),
                "knowledgeid": job_info.get("knowledgeid"),
            }
            live = Live(attachment=job, defaults=defaults, course_id=course.get("courseId"))
            result_holder: dict[str, object] = {}

            def _run_live() -> None:
                try:
                    result_holder["ok"] = LiveProcessor.run_live(live, speed)
                except Exception as exc:  # noqa: BLE001 - thread boundary
                    logger.error(f"直播任务异常: {exc}")
                    result_holder["ok"] = False

            thread = threading.Thread(target=_run_live, daemon=True)
            thread.start()
            thread.join()
            live_result = StudyResult.SUCCESS if result_holder.get("ok") else StudyResult.ERROR
            _emit_job_result(chaoxing, job_type, task_name, course, live_result)
            return live_result
        except Exception as exc:  # noqa: BLE001 - a live task must not kill the worker
            logger.error(f"处理直播任务时出错: {exc}")
            _emit(chaoxing, {"kind": "live", "phase": "error", "name": task_name, "course": course.get("title", ""), "message": str(exc)})
            return StudyResult.ERROR

    logger.error(f"未知任务类型: {job_type}")
    _emit(chaoxing, {"kind": "unknown", "phase": "error", "name": task_name, "course": course.get("title", ""), "message": f"未知任务类型: {job_type}"})
    return StudyResult.ERROR


def _emit_job_result(chaoxing, job_type, task_name, course, result) -> None:
    _emit(
        chaoxing,
        {
            "kind": str(job_type or "unknown"),
            "phase": "error" if result.is_failure() else "done",
            "name": task_name,
            "course": course.get("title", ""),
            "result": result.name.lower(),
        },
    )


class JobProcessor:
    """Priority-queue based chapter worker pool.

    A task that is requeued for retry keeps its ``unfinished_tasks`` slot until
    it finally succeeds or is abandoned. This keeps ``join()`` correct and
    makes ``stop()`` safe from another thread.
    """

    def __init__(self, chaoxing: Chaoxing, tasks: list[ChapterTask], config: dict[str, Any]):
        jobs = int(config.get("jobs") or 4)
        if jobs < 1:
            raise ValueError("jobs must be >= 1")

        self.chaoxing = chaoxing
        self.speed = float(config.get("speed") or 1.0)
        self.max_tries = max(1, int(config.get("chapter_max_tries") or 5))
        self.tasks = tasks
        self.failed_tasks: list[ChapterTask] = []
        self.task_queue: PriorityQueue[ChapterTask] = PriorityQueue()
        self.retry_queue: PriorityQueue[ChapterTask] = PriorityQueue()
        self.threads: list[threading.Thread] = []
        self.worker_num = jobs
        self.config = config
        self.retry_interval = max(0.0, float(config.get("retry_interval", 1.0)))
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()  # set means paused
        self._retry_thread: threading.Thread | None = None
        self._started = False
        self._finished = False

    def should_stop(self) -> bool:
        return self.stop_event.is_set()

    def pause(self) -> None:
        self.pause_event.set()

    def resume(self) -> None:
        self.pause_event.clear()

    def stop(self) -> None:
        self.stop_event.set()
        self.pause_event.clear()
        if hasattr(self.chaoxing, "cancel"):
            self.chaoxing.cancel()

        for queue in (self.task_queue, self.retry_queue):
            while True:
                try:
                    queue.get_nowait()
                except (Empty, ShutDown):
                    break
                else:
                    try:
                        self.task_queue.task_done()
                    except ValueError:
                        pass

    def _sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        while not self.stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.2, remaining))

    def _wait_if_paused(self) -> None:
        while self.pause_event.is_set() and not self.stop_event.is_set():
            time.sleep(0.1)

    def run(self) -> None:
        if self._started:
            raise RuntimeError("JobProcessor.run() can only be called once")
        self._started = True
        if self.stop_event.is_set():
            self._finished = True
            return

        for task in self.tasks:
            self.task_queue.put(task)

        for _ in range(self.worker_num):
            thread = threading.Thread(target=self.worker_thread, daemon=True)
            self.threads.append(thread)
            thread.start()

        self._retry_thread = threading.Thread(target=self.retry_thread, daemon=True)
        self._retry_thread.start()

        try:
            self.task_queue.join()
        finally:
            self.stop_event.set()
            self.pause_event.clear()
            if self._retry_thread is not None:
                self._retry_thread.join(timeout=2.0)
            for thread in self.threads:
                thread.join(timeout=2.0)
            if hasattr(self.task_queue, "shutdown"):
                self.task_queue.shutdown()
            self._finished = True

    def _handle_result(self, task: ChapterTask) -> bool:
        match task.result:
            case ChapterResult.SUCCESS:
                logger.debug("Task success: {} - {}", task.course.get("title", ""), task.point.get("title", ""))
                return False

            case ChapterResult.NOT_OPEN:
                if self.config.get("notopen_action") == "continue":
                    logger.warning(
                        "章节未开启: {} - {}, 正在跳过",
                        task.course.get("title", ""),
                        task.point.get("title", ""),
                    )
                    return False

                task.tries += 1
                if task.tries >= self.max_tries:
                    logger.error(
                        "章节未开启: {} - {} 可能由于上一章节的章节检测未完成, 也可能由于该章节因为时效已关闭，"
                        "请手动检查完成并提交再重试。或者在配置中配置(自动跳过关闭章节/开启题库并启用提交)",
                        task.course.get("title", ""),
                        task.point.get("title", ""),
                    )
                    return False

                self.retry_queue.put(task)
                return True

            case ChapterResult.ERROR:
                task.tries += 1
                logger.warning(
                    "重试任务 {} - {} ({}/{} 次尝试)",
                    task.course.get("title", ""),
                    task.point.get("title", ""),
                    task.tries,
                    self.max_tries,
                )
                if task.tries >= self.max_tries:
                    logger.error(
                        "任务重试次数达到上限: {} - {}",
                        task.course.get("title", ""),
                        task.point.get("title", ""),
                    )
                    self.failed_tasks.append(task)
                    return False
                self.retry_queue.put(task)
                return True

            case _:
                logger.error("任务 {} 的状态无效 {}", task.result, task.point.get("title", ""))
                self.failed_tasks.append(task)
                return False

    def worker_thread(self) -> None:
        while not self.stop_event.is_set():
            self._wait_if_paused()
            if self.stop_event.is_set():
                return

            try:
                task = self.task_queue.get(timeout=0.2)
            except Empty:
                continue
            except ShutDown:
                logger.info("Queue shut down")
                return

            requeued = False
            try:
                task.result = process_chapter(
                    self.chaoxing,
                    task.course,
                    task.point,
                    self.speed,
                    should_stop=self.should_stop,
                )
                requeued = self._handle_result(task)
                if requeued:
                    _emit(
                        self.chaoxing,
                        {
                            "kind": "chapter",
                            "phase": "retry",
                            "course": task.course.get("title", ""),
                            "chapter": task.point.get("title", ""),
                            "result": task.result.name.lower(),
                            "tries": task.tries,
                        },
                    )
            except Exception as exc:  # noqa: BLE001 - a worker must never die silently
                logger.error(
                    "处理章节异常: {} - {}: {}",
                    task.course.get("title"),
                    task.point.get("title"),
                    exc,
                )
                logger.opt(exception=True).debug("章节异常堆栈")
                task.result = ChapterResult.ERROR
                try:
                    requeued = self._handle_result(task)
                except Exception as inner:  # noqa: BLE001
                    logger.error("处理失败结果时再次异常: {}", inner)
                    requeued = False
            finally:
                if not requeued:
                    try:
                        self.task_queue.task_done()
                    except ValueError:
                        pass

    def retry_thread(self) -> None:
        while not self.stop_event.is_set():
            try:
                task = self.retry_queue.get(timeout=0.2)
            except Empty:
                continue
            except ShutDown:
                return

            if self.stop_event.is_set():
                try:
                    self.task_queue.task_done()
                except ValueError:
                    pass
                return

            self._sleep(self.retry_interval)
            if self.stop_event.is_set():
                try:
                    self.task_queue.task_done()
                except ValueError:
                    pass
                return

            try:
                self.task_queue.put(task)
                self.task_queue.task_done()
            except ShutDown:
                return


def process_chapter(
    chaoxing: Chaoxing,
    course: dict[str, Any],
    point: dict[str, Any],
    speed: float,
    should_stop: Callable[[], bool] | None = None,
) -> ChapterResult:
    """Process one chapter and all of its task points."""
    if should_stop is not None and should_stop():
        return ChapterResult.ERROR

    logger.info(f'当前章节: {point.get("title", "")}')
    _emit(
        chaoxing,
        {
            "kind": "chapter",
            "phase": "start",
            "course": course.get("title", ""),
            "chapter": point.get("title", ""),
        },
    )
    if point.get("has_finished"):
        logger.info(f'章节：{point.get("title", "")} 已完成所有任务点')
        _emit(
            chaoxing,
            {
                "kind": "chapter",
                "phase": "done",
                "course": course.get("title", ""),
                "chapter": point.get("title", ""),
                "result": "success",
            },
        )
        return ChapterResult.SUCCESS

    chaoxing.rate_limiter.limit_rate(random_time=True, random_min=0, random_max=0.2)

    jobs, job_info = chaoxing.get_job_list(course, point)
    job_info = job_info or {}

    if job_info.get("notOpen", False):
        _emit(
            chaoxing,
            {
                "kind": "chapter",
                "phase": "done",
                "course": course.get("title", ""),
                "chapter": point.get("title", ""),
                "result": "not_open",
            },
        )
        return ChapterResult.NOT_OPEN

    job_results: list[StudyResult] = []
    for job in jobs:
        if should_stop is not None and should_stop():
            logger.info("收到停止请求, 中断章节: {}", point.get("title", ""))
            _emit(
                chaoxing,
                {
                    "kind": "chapter",
                    "phase": "error",
                    "course": course.get("title", ""),
                    "chapter": point.get("title", ""),
                    "result": "stopped",
                },
            )
            return ChapterResult.ERROR
        job_results.append(process_job(chaoxing, course, job, job_info, speed))

    failed = any(result.is_failure() for result in job_results)
    _emit(
        chaoxing,
        {
            "kind": "chapter",
            "phase": "done" if not failed else "error",
            "course": course.get("title", ""),
            "chapter": point.get("title", ""),
            "result": "error" if failed else "success",
            "tasks": len(job_results),
        },
    )
    return ChapterResult.ERROR if failed else ChapterResult.SUCCESS


def filter_courses(all_course, course_list):
    """Filter courses; an explicit list with no match is an error."""
    if isinstance(course_list, str):
        course_list = [item.strip() for item in course_list.split(",") if item.strip()]
    explicit_list = bool(course_list)

    if not course_list:
        print("*" * 10 + "课程列表" + "*" * 10)
        for course in all_course:
            print(f"ID: {course['courseId']} 班级ID: {course['clazzId']} 课程名: {course['title']}")
        print("*" * 28)
        print("提示: 同一 courseId 下若存在多个班级, 将分别完成。")
        try:
            raw = input("请输入想要学习的课程列表,以逗号分隔,例: 2151141,189191,198198\n")
        except Exception as exc:
            raise InputFormatError("输入格式错误") from exc
        course_list = [item.strip() for item in raw.split(",") if item.strip()]
        explicit_list = bool(course_list)

    course_task = []
    seen_keys = set()
    for course in all_course:
        key = (course["courseId"], course["clazzId"])
        if course["courseId"] in course_list and key not in seen_keys:
            course_task.append(course)
            seen_keys.add(key)

    if not course_task:
        if explicit_list:
            available = ", ".join(
                f"{course['courseId']}({course['title']})" for course in all_course[:20]
            )
            raise InputFormatError(
                "指定的课程ID未匹配到任何课程，请检查 course_list。"
                f"可用课程: {available or '无'}"
            )
        course_task = all_course

    matched_ids = {course["courseId"] for course in course_task}
    unknown_ids = [course_id for course_id in course_list if course_id not in matched_ids]
    if unknown_ids:
        logger.warning("以下课程ID未匹配到课程，已忽略: {}", ", ".join(unknown_ids))

    return course_task
