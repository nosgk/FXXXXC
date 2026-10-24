# -*- coding: utf-8 -*-
"""Engine service: command implementations shared by CLI, GUI and tests."""

from __future__ import annotations

import os
import platform
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

import fxxxxc
from api.answer import Tiku, TikuManual
from api.base import Account, Chaoxing
from api.logger import logger
from api.notification import Notification
from fxxxxc.engine.protocol import (
    CONFIG_ERROR,
    NOT_LOGGED_IN,
    RpcError,
    STUDY_ALREADY_RUNNING,
    STUDY_NOT_RUNNING,
)
from fxxxxc.config import load_ini, save_ini
from fxxxxc.events import EventBus
from fxxxxc.orchestrator import ChapterTask, JobProcessor, process_job  # noqa: F401 (re-export)

_BOOL_TRUE = {"1", "true", "yes", "y", "on"}

# 配置 schema：section.key -> 校验/归一化规则。GUI 与引擎共用这一份定义，
# 非法入参在写入前被拒绝（fail-closed），合法值归一化后落盘。
_NOTOPEN_ACTIONS = {"retry", "ask", "continue"}
_MANUAL_MODES = {"batch", "single"}
_SEPARATORS = {";", ",", " ", "tab", "\\n", "；", "，"}
_BOOL_KEYS = {
    ("common", "use_cookies"),
    ("common", "work_redo_enabled"),
    ("common", "add_learning_count"),
    ("tiku", "check_llm_connection"),
    ("tiku", "submit"),
    ("tiku", "likeapi_search"),
    ("tiku", "likeapi_vision"),
    ("tiku", "likeapi_retry"),
    ("tiku", "insecure_skip_verify"),
}
_FLOAT_RANGE = {
    ("common", "speed"): (1.0, 2.0),
    ("common", "retry_interval"): (0.0, 60.0),
    ("common", "learning_count_interval"): (0.0, 3600.0),
    ("tiku", "cover_rate"): (0.0, 1.0),
    ("tiku", "delay"): (0.0, 60.0),
    ("tiku", "go_min_interval"): (0.0, 60.0),
    ("tiku", "go_retry_backoff"): (1.0, 10.0),
}
_INT_RANGE = {
    ("common", "jobs"): (1, 16),
    ("common", "chapter_max_tries"): (1, 20),
    ("common", "work_max_retries"): (0, 10),
    ("common", "target_count"): (1, 10000),
    ("tiku", "min_interval_seconds"): (0, 600),
    ("tiku", "likeapi_retry_times"): (1, 10),
    ("tiku", "go_retry_times"): (1, 10),
}
_ENUMS = {
    ("common", "notopen_action"): _NOTOPEN_ACTIONS,
    ("tiku", "manual_mode_default"): _MANUAL_MODES,
}
_PROVIDER_NAMES = None  # lazily imported from api.answer


def _provider_registry_names() -> set[str]:
    global _PROVIDER_NAMES
    if _PROVIDER_NAMES is None:
        try:
            from api.answer import PROVIDER_REGISTRY
            _PROVIDER_NAMES = set(PROVIDER_REGISTRY)
        except Exception:  # noqa: BLE001 - validation must not crash the server
            _PROVIDER_NAMES = set()
    return _PROVIDER_NAMES


def _normalize_bool(value: str) -> str:
    return "true" if _as_bool(value, False) else "false"


def _parseable_float(value: str) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _parseable_int(value: str) -> bool:
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False


def validate_config_value(section: str, key: str, raw: str) -> tuple[str, str | None]:
    """Return ``(normalized, error)`` for one config value."""
    pair = (section, key)
    value = str(raw)
    if pair in _BOOL_KEYS:
        return _normalize_bool(value), None
    if pair in _FLOAT_RANGE:
        low, high = _FLOAT_RANGE[pair]
        if value.strip() == "" or not _parseable_float(value):
            return str(low), f"{section}.{key} 需为数字（{low}~{high}）"
        number = min(high, max(low, float(value)))
        return f"{number:g}", None
    if pair in _INT_RANGE:
        low, high = _INT_RANGE[pair]
        if value.strip() == "" or not _parseable_int(value):
            return str(low), f"{section}.{key} 需为整数（{low}~{high}）"
        return str(min(high, max(low, int(value)))), None
    if pair in _ENUMS:
        text = value.strip().lower()
        allowed = _ENUMS[pair]
        if text not in allowed:
            return next(iter(sorted(allowed))), f"{section}.{key} 仅允许 {'/'.join(sorted(allowed))}"
        return text, None
    if pair == ("tiku", "provider"):
        names = [part.strip() for part in value.split(",") if part.strip()]
        if not names:
            return "", None  # 未配置题库是合法状态
        registry = _provider_registry_names()
        invalid = [name for name in names if name not in registry]
        if invalid:
            return value, f"tiku.provider 未知题库: {', '.join(invalid)}"
        return ", ".join(names), None
    if pair == ("tiku", "manual_mode_separator"):
        if value in _SEPARATORS:
            return value, None
        return ";", "tiku.manual_mode_separator 仅允许 ; , space tab \\n"
    return value.strip(), None


def normalize_config_patch(patch: dict[str, dict[str, Any]]) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Validate a patch; return ``(normalized_patch, errors)`` (fail-closed)."""
    normalized: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for section, items in patch.items():
        if not isinstance(section, str) or not isinstance(items, dict):
            errors.append("config 节必须是 {section: {key: value}}")
            continue
        for key, value in items.items():
            if not isinstance(key, str) or isinstance(value, (dict, list)):
                errors.append(f"{section}.{key} 的值类型不合法")
                continue
            normalized_value, error = validate_config_value(section, key, str(value))
            if error:
                errors.append(error)
                continue
            normalized.setdefault(section, {})[key] = normalized_value
    return normalized, errors


def _as_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _BOOL_TRUE


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class EngineManualTiku(TikuManual):
    """Manual provider that routes questions through the engine event bus."""

    def __init__(self, service, config_path: str | None = None):
        super().__init__(config_path)
        self._service = service

    def _query(self, q_info: dict):
        return self._service.ask_manual([q_info])[0]

    def _query_all(self, q_list: list[dict], query_delay: float = 0.0):
        return self._service.ask_manual(q_list)


class EngineService:
    """Owns configuration, login state and the study worker."""

    def __init__(self, data_dir: str | os.PathLike[str] | None = None):
        from fxxxxc.paths import get_data_dir

        self.data_dir = Path(data_dir).expanduser().resolve() if data_dir else get_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.data_dir / "config.ini"
        self.bus = EventBus(replay=500)
        self.started_at = time.time()

        self._lock = threading.RLock()
        self._state = "idle"
        self._state_detail = ""
        self._chaoxing: Chaoxing | None = None
        self._tiku: Tiku | None = None
        self._login_name = ""
        self._courses: list[dict] = []
        self._processor: JobProcessor | None = None
        self._worker: threading.Thread | None = None
        self._run_id = ""
        self._manual_batches: dict[str, dict] = {}
        self._log_lines: deque[dict] = deque(maxlen=1000)
        self._log_sink_handle = None
        self._install_log_sink()

    # ------------------------------------------------------------------ meta

    def version(self) -> str:
        return fxxxxc.__version__

    def pid(self) -> int:
        return os.getpid()

    def state(self) -> str:
        with self._lock:
            return self._state

    def _set_state(self, state: str, detail: str = "") -> None:
        with self._lock:
            self._state = state
            self._state_detail = detail
        self.bus.emit("state.changed", {"state": state, "detail": detail})

    def _install_log_sink(self) -> None:
        def sink(message) -> None:
            record = message.record
            text = message.rstrip("\n")
            entry = {
                "ts": record["time"].strftime("%H:%M:%S"),
                "level": record["level"].name,
                "logger": record["name"],
                "message": text,
            }
            self._log_lines.append(entry)
            self.bus.emit("log", entry)

        self._log_sink_handle = logger.add(sink, level=os.environ.get("FXXXXC_LOG_LEVEL", "INFO"))

    def close(self) -> None:
        if self._log_sink_handle is not None:
            try:
                logger.remove(self._log_sink_handle)
            except Exception:
                pass
            self._log_sink_handle = None

    # -------------------------------------------------------------- dispatch

    def dispatch(self, method: str, params: dict[str, Any]) -> Any:
        handlers = {
            "app.info": lambda p: self.app_info(),
            "config.get": self.config_get,
            "config.set": self.config_set,
            "config.validate": self.config_validate,
            "auth.login": self.auth_login,
            "auth.status": lambda p: self.auth_status(),
            "auth.logout": lambda p: self.auth_logout(),
            "courses.list": self.courses_list,
            "study.start": self.study_start,
            "study.pause": lambda p: self.study_pause(),
            "study.resume": lambda p: self.study_resume(),
            "study.stop": lambda p: self.study_stop(),
            "study.status": lambda p: self.study_status(),
            "logs.tail": self.logs_tail,
            "manual.answer": self.manual_answer,
            "manual.skip": self.manual_skip,
            "tiku.test": lambda p: self.tiku_test(),
            "notification.test": lambda p: self.notification_test(),
        }
        handler = handlers.get(method)
        if handler is None:
            raise RpcError(-32601, f"unknown method: {method}")
        return handler(params)

    def app_info(self) -> dict:
        return {
            "version": self.version(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "data_dir": str(self.data_dir),
            "state": self.state(),
        }

    # ---------------------------------------------------------------- config

    def _read_config(self) -> dict[str, dict[str, str]]:
        return load_ini(self.config_path)

    def _write_config(self, data: dict[str, dict[str, Any]]) -> None:
        save_ini(self.config_path, data)

    def config_get(self, params: dict) -> dict:
        return {
            "config": self._read_config(),
            "config_path": str(self.config_path),
            "data_dir": str(self.data_dir),
        }

    def config_set(self, params: dict) -> dict:
        patch = params.get("config") or params.get("patch")
        if not isinstance(patch, dict):
            raise RpcError(-32602, "config.set requires {config: {section: {key: value}}}")
        normalized, errors = normalize_config_patch(patch)
        if errors:
            raise RpcError(-32602, "；".join(errors), {"errors": errors})
        with self._lock:
            data = self._read_config()
            for section, items in normalized.items():
                data.setdefault(section, {}).update(items)
            self._write_config(data)
        self.bus.emit("config.changed", {})
        return {"ok": True, "config_path": str(self.config_path), "normalized": normalized}

    def config_validate(self, params: dict) -> dict:
        patch = params.get("config") or {}
        if not isinstance(patch, dict):
            raise RpcError(-32602, "config.validate requires {config: {...}}")
        normalized, errors = normalize_config_patch(patch)
        return {"ok": not errors, "errors": errors, "normalized": normalized}

    def _common_config(self) -> dict[str, Any]:
        raw = self._read_config().get("common", {})
        common: dict[str, Any] = dict(raw)
        if common.get("course_list"):
            common["course_list"] = [
                item.strip() for item in str(common["course_list"]).split(",") if item.strip()
            ]
        else:
            common["course_list"] = []
        common["speed"] = min(2.0, max(1.0, _as_float(raw.get("speed"), 1.0)))
        common["jobs"] = max(1, _as_int(raw.get("jobs"), 4))
        common["notopen_action"] = raw.get("notopen_action", "retry")
        common["retry_interval"] = max(0.0, _as_float(raw.get("retry_interval"), 1.0))
        common["work_max_retries"] = max(0, _as_int(raw.get("work_max_retries"), 3))
        common["work_redo_enabled"] = _as_bool(raw.get("work_redo_enabled"), False)
        common["chapter_max_tries"] = max(1, _as_int(raw.get("chapter_max_tries"), 5))
        common["learning_count_interval"] = max(0.0, _as_float(raw.get("learning_count_interval"), 30.0))
        common["add_learning_count"] = _as_bool(raw.get("add_learning_count"), False)
        common["target_count"] = max(1, _as_int(raw.get("target_count"), 100))
        common["use_cookies"] = _as_bool(raw.get("use_cookies"), False)
        common["username"] = str(raw.get("username", "") or "").strip()
        common["password"] = str(raw.get("password", "") or "").strip()
        return common

    def _tiku_config(self) -> dict[str, str]:
        return self._read_config().get("tiku", {})

    # ------------------------------------------------------------------ auth

    def _build_tiku(self) -> Tiku:
        tiku_conf = self._tiku_config()
        tiku = Tiku.get_tiku_from_config(dict(tiku_conf), config_path=str(self.config_path))
        tiku.init_tiku()
        if isinstance(tiku, TikuManual):
            manual = EngineManualTiku(self, config_path=str(self.config_path))
            manual.config_set(dict(tiku_conf))
            manual.init_tiku()
            tiku = manual
        return tiku

    def _build_chaoxing(self, common: dict[str, Any], tiku: Tiku) -> Chaoxing:
        username = common.get("username", "")
        password = common.get("password", "")
        use_cookies = bool(common.get("use_cookies", False))
        if not (username and password) and not use_cookies:
            raise RpcError(CONFIG_ERROR, "缺少账号密码或 cookies，请先在设置中填写")

        tiku_conf = self._tiku_config()
        account = Account(username, password)
        return Chaoxing(
            account=account,
            tiku=tiku,
            query_delay=_as_float(tiku_conf.get("delay"), 0.0),
            work_max_retries=common.get("work_max_retries", 3),
            work_redo_enabled=common.get("work_redo_enabled", False),
            learning_count_interval=common.get("learning_count_interval", 30.0),
        )

    def auth_login(self, params: dict) -> dict:
        username = str(params.get("username") or "").strip()
        password = str(params.get("password") or "").strip()
        use_cookies = _as_bool(params.get("use_cookies"), False)
        if username or password:
            self.config_set({"config": {"common": {"username": username, "password": password}}})
        elif use_cookies:
            self.config_set({"config": {"common": {"use_cookies": "true"}}})

        with self._lock:
            common = self._common_config()
            tiku = self._build_tiku()
            chaoxing = self._build_chaoxing(common, tiku)
            result = chaoxing.login(login_with_cookies=common.get("use_cookies", False))
            if not result.get("status"):
                raise RpcError(NOT_LOGGED_IN, str(result.get("msg", "登录失败")))
            self._chaoxing = chaoxing
            self._tiku = tiku
            try:
                self._login_name = Chaoxing.get_name()
            except Exception:
                self._login_name = ""
        self.bus.emit("auth.changed", {"logged_in": True, "name": self._login_name})
        return {"status": True, "name": self._login_name}

    def _ensure_chaoxing(self, login: bool = True) -> Chaoxing:
        if self._chaoxing is None:
            common = self._common_config()
            tiku = self._build_tiku()
            chaoxing = self._build_chaoxing(common, tiku)
            if login:
                result = chaoxing.login(login_with_cookies=common.get("use_cookies", False))
                if not result.get("status"):
                    raise RpcError(NOT_LOGGED_IN, str(result.get("msg", "登录失败")))
            self._chaoxing = chaoxing
            self._tiku = tiku
        return self._chaoxing

    def auth_status(self) -> dict:
        return {"logged_in": self._chaoxing is not None, "name": self._login_name}

    def auth_logout(self) -> None:
        self.study_stop()
        from api.base import SessionManager
        from api.config import GlobalConst as gc
        from api.cookies import cookie_lock

        with self._lock:
            self._chaoxing = None
            self._tiku = None
            self._login_name = ""
            self._courses = []
        SessionManager.reset()
        try:
            with cookie_lock:
                if gc.COOKIES_PATH and os.path.exists(gc.COOKIES_PATH):
                    os.remove(gc.COOKIES_PATH)
        except OSError:
            pass
        self.bus.emit("auth.changed", {"logged_in": False})
        return {"ok": True}

    # --------------------------------------------------------------- courses

    def courses_list(self, params: dict) -> dict:
        chaoxing = self._ensure_chaoxing()
        courses = chaoxing.get_course_list()
        with self._lock:
            self._courses = courses
        self.bus.emit("course.list", {"count": len(courses)})
        return {"courses": courses}

    # ----------------------------------------------------------------- study

    def study_start(self, params: dict) -> dict:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                raise RpcError(STUDY_ALREADY_RUNNING, "已有学习任务在运行")
            course_ids = [str(item) for item in (params.get("course_ids") or [])]
            if not course_ids:
                raise RpcError(-32602, "study.start requires course_ids")
            options = params.get("options") or {}
            if not isinstance(options, dict):
                raise RpcError(-32602, "study.start options must be an object")

            self._run_id = f"run-{int(time.time())}-{uuid.uuid4().hex[:6]}"
            run_id = self._run_id
            worker = threading.Thread(
                target=self._study_worker,
                args=(run_id, course_ids, options),
                daemon=True,
            )
            self._worker = worker
        worker.start()
        return {"run_id": run_id}

    def _options_for_run(self, options: dict) -> dict[str, Any]:
        common = self._common_config()
        overrides: dict[str, Any] = {}
        for key in ("speed", "jobs", "notopen_action", "retry_interval", "chapter_max_tries"):
            if key in options:
                overrides[key] = options[key]
        merged = {**common, **overrides}
        merged["speed"] = min(2.0, max(1.0, _as_float(merged.get("speed"), 1.0)))
        merged["jobs"] = max(1, _as_int(merged.get("jobs"), 4))
        merged["retry_interval"] = max(0.0, _as_float(merged.get("retry_interval"), 1.0))
        merged["chapter_max_tries"] = max(1, _as_int(merged.get("chapter_max_tries"), 5))
        return merged

    def _study_worker(self, run_id: str, course_ids: list[str], options: dict) -> None:
        processor: JobProcessor | None = None
        try:
            self._set_state("loading", "正在准备学习任务")
            chaoxing = self._ensure_chaoxing()
            config = self._options_for_run(options)

            with self._lock:
                courses = list(self._courses)
            if not courses:
                courses = chaoxing.get_course_list()
                with self._lock:
                    self._courses = courses

            selected = [course for course in courses if str(course.get("courseId")) in course_ids]
            if not selected:
                raise RpcError(-32602, "课程列表为空或课程ID未匹配，请先刷新课程列表")

            tasks: list[ChapterTask] = []
            for course in selected:
                if chaoxing.should_stop():
                    break
                self.bus.emit(
                    "study.progress",
                    {
                        "run_id": run_id,
                        "phase": "loading_course",
                        "course_id": course.get("courseId"),
                        "course_title": course.get("title"),
                    },
                )
                points = chaoxing.get_course_point(course["courseId"], course["clazzId"], course["cpi"])
                for index, point in enumerate(points.get("points", [])):
                    tasks.append(ChapterTask(index=len(tasks), point=point, course=course))

            processor = JobProcessor(chaoxing, tasks, config)
            with self._lock:
                self._processor = processor
            self._set_state("running", f"共 {len(tasks)} 个章节")
            self.bus.emit(
                "study.progress",
                {"run_id": run_id, "phase": "running", "total": len(tasks), "done": 0},
            )
            processor.run()

            failed = len(processor.failed_tasks)
            detail = f"完成，失败章节 {failed}"
            self._set_state("idle", detail)
            self.bus.emit(
                "study.progress",
                {
                    "run_id": run_id,
                    "phase": "finished",
                    "total": len(tasks),
                    "failed": failed,
                },
            )

            if config.get("add_learning_count"):
                self._increase_learning_count(chaoxing, selected, config)
        except RpcError as exc:
            self._set_state("error", exc.message)
            self.bus.emit("study.progress", {"run_id": run_id, "phase": "error", "message": exc.message})
        except Exception as exc:  # noqa: BLE001 - worker boundary
            logger.error("学习任务异常: {}", exc)
            self._set_state("error", f"{type(exc).__name__}: {exc}")
            self.bus.emit(
                "study.progress",
                {"run_id": run_id, "phase": "error", "message": str(exc)},
            )
        finally:
            with self._lock:
                self._processor = None
                if self._worker is threading.current_thread():
                    self._worker = None

    def _increase_learning_count(self, chaoxing: Chaoxing, courses: list[dict], config: dict) -> None:
        from api.process import increase_learning_count_for_course

        self._set_state("running", "增加章节学习次数")
        for course in courses:
            if chaoxing.should_stop():
                break
            increase_learning_count_for_course(chaoxing, course, config)

    def study_pause(self) -> dict:
        processor = self._processor
        if processor is None:
            raise RpcError(STUDY_NOT_RUNNING, "没有正在运行的学习任务")
        processor.pause()
        self._set_state("paused", "已暂停")
        return {"state": "paused"}

    def study_resume(self) -> dict:
        processor = self._processor
        if processor is None:
            raise RpcError(STUDY_NOT_RUNNING, "没有正在运行的学习任务")
        processor.resume()
        self._set_state("running", "已恢复")
        return {"state": "running"}

    def study_stop(self) -> dict:
        processor = self._processor
        if processor is None:
            return {"state": self.state()}
        self._set_state("stopping", "正在停止")
        processor.stop()
        return {"state": "stopping"}

    def study_status(self) -> dict:
        processor = self._processor
        payload: dict[str, Any] = {"state": self.state(), "detail": self._state_detail}
        if processor is not None:
            total = len(processor.tasks)
            unfinished = processor.task_queue.unfinished_tasks
            payload.update(
                {
                    "run_id": self._run_id,
                    "total": total,
                    "done": max(0, total - unfinished),
                    "failed": len(processor.failed_tasks),
                }
            )
        elif self._chaoxing is not None:
            payload.update({"courses": len(self._courses)})
        return payload

    # ------------------------------------------------------------------ logs

    def logs_tail(self, params: dict) -> dict:
        limit = max(1, min(1000, int(params.get("limit", 200))))
        level = str(params.get("level", "")).upper()
        lines = list(self._log_lines)[-limit:]
        if level:
            lines = [line for line in lines if line.get("level") == level]
        return {"lines": lines}

    # ---------------------------------------------------------------- manual

    def ask_manual(self, q_list: list[dict]) -> list[str | None]:
        """Ask the GUI to answer questions and wait for the user."""
        if not q_list:
            return []
        batch_id = uuid.uuid4().hex
        questions = [
            {
                "id": f"{batch_id}-{index}",
                "title": q.get("title", ""),
                "type": q.get("type", ""),
                "options": q.get("options", ""),
            }
            for index, q in enumerate(q_list)
        ]
        batch = {
            "questions": q_list,
            "results": [None] * len(q_list),
            "received": [False] * len(q_list),
            "done": threading.Event(),
        }
        with self._lock:
            self._manual_batches[batch_id] = batch
        try:
            self.bus.emit("manual.question", {"batch_id": batch_id, "questions": questions})
            while not batch["done"].wait(0.2):
                chaoxing = self._chaoxing
                if chaoxing is not None and chaoxing.should_stop():
                    logger.info("手动答题被取消")
                    break
        finally:
            with self._lock:
                self._manual_batches.pop(batch_id, None)
        return list(batch["results"])

    def _manual_batch(self, batch_id: str) -> dict:
        batch = self._manual_batches.get(batch_id)
        if batch is None:
            raise RpcError(-32602, f"未知的手动答题批次: {batch_id}")
        return batch

    def manual_answer(self, params: dict) -> dict:
        batch_id = str(params.get("batch_id") or "")
        index = params.get("index")
        answer = params.get("answer")
        if not batch_id or not isinstance(index, int):
            raise RpcError(-32602, "manual.answer requires batch_id and index")
        batch = self._manual_batch(batch_id)
        questions = batch["questions"]
        if index < 0 or index >= len(questions):
            raise RpcError(-32602, "index out of range")
        if answer is None or str(answer).strip() == "":
            return self.manual_skip({"batch_id": batch_id, "index": index})

        question = questions[index]
        manual = self._tiku if isinstance(self._tiku, TikuManual) else None
        normalized = str(answer).strip()
        if manual is not None:
            ok, message = manual._validate_user_input(
                normalized, {"type": question.get("type"), "options": question.get("options")}
            )
            if not ok:
                raise RpcError(-32602, f"答案不合规: {message}")
            normalized = manual._normalize_user_input(
                normalized, {"type": question.get("type"), "options": question.get("options")}
            ) or normalized

        batch["results"][index] = normalized
        batch["received"][index] = True
        self.bus.emit(
            "manual.answered",
            {"batch_id": batch_id, "index": index, "answer": normalized},
        )
        if all(batch["received"]):
            batch["done"].set()
        return {"ok": True, "answer": normalized}

    def manual_skip(self, params: dict) -> dict:
        batch_id = str(params.get("batch_id") or "")
        index = params.get("index")
        if not batch_id or not isinstance(index, int):
            raise RpcError(-32602, "manual.skip requires batch_id and index")
        batch = self._manual_batch(batch_id)
        questions = batch["questions"]
        if index < 0 or index >= len(questions):
            raise RpcError(-32602, "index out of range")
        batch["results"][index] = None
        batch["received"][index] = True
        self.bus.emit("manual.answered", {"batch_id": batch_id, "index": index, "answer": None})
        if all(batch["received"]):
            batch["done"].set()
        return {"ok": True}

    # -------------------------------------------------------------- testing

    def tiku_test(self) -> dict:
        try:
            tiku = self._build_tiku()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": str(exc)}
        if getattr(tiku, "DISABLE", False):
            return {"ok": False, "message": "题库未启用或配置无效"}
        if hasattr(tiku, "check_llm_connection"):
            try:
                ok = bool(tiku.check_llm_connection())
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "message": str(exc)}
            return {"ok": ok, "message": "连接正常" if ok else "连接失败"}
        return {"ok": True, "message": "题库已启用"}

    def notification_test(self) -> dict:
        try:
            notification = Notification()
            notification.config_set(self._read_config().get("notification", {}))
            service = notification.get_notification_from_config()
            service.init_notification()
            service.send("FXXXXC 测试通知")
            return {"ok": not service.disabled, "message": "已发送" if not service.disabled else "通知未配置"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": str(exc)}
