# -*- coding: utf-8 -*-
"""Engine service: command implementations shared by CLI, GUI and tests."""

from __future__ import annotations

import json
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
from fxxxxc.orchestrator import ChapterResult, ChapterTask, JobProcessor, process_job  # noqa: F401 (re-export)

_BOOL_TRUE = {"1", "true", "yes", "y", "on"}

# 题库实例段前缀：每个 [tiku_bank.<id>] 是一个独立的题库源配置（含自己的
# provider 与专属键），按 priority 升序组成梯度回退链，天然支持多题库并行启用。
BANK_SECTION_PREFIX = "tiku_bank."

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
    if section.startswith(BANK_SECTION_PREFIX):
        # 题库实例段：enabled/priority 为实例自身键，其余键复用 tiku 段的校验规则
        if key == "enabled":
            return _normalize_bool(value), None
        if key == "priority":
            if value.strip() == "" or not _parseable_int(value):
                return "0", "题库实例 priority 需为整数"
            return str(int(value)), None
        if key == "name":
            return value.strip(), None
        return validate_config_value("tiku", key, raw)
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
        if text == "":
            return "", None  # 留空 = 使用默认/不启用（GUI 提供空白选项）
        allowed = _ENUMS[pair]
        if text not in allowed:
            return next(iter(sorted(allowed))), f"{section}.{key} 仅允许 {'/'.join(sorted(allowed))}（可留空）"
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
        if value == "":
            return ";", None  # 留空使用默认分隔符
        if value in _SEPARATORS:
            return value, None
        return ";", "tiku.manual_mode_separator 仅允许 ; , space tab \\n（可留空）"
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

    # 课程章节详情缓存 TTL（秒）：章节状态在两次学习之间基本不变，
    # GUI 展开/预取都会打到这里，短缓存避免重复请求平台。
    COURSE_DETAIL_TTL = 120.0
    COURSE_DETAIL_CACHE_MAX = 200

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
        self._run_started_at = 0.0
        self._live: dict[str, Any] = {}
        self._last_course_ids: list[str] = []
        self._manual_batches: dict[str, dict] = {}
        self._log_lines: deque[dict] = deque(maxlen=1000)
        self._log_sink_handle = None
        self._course_details: dict[tuple[str, str], tuple[float, dict]] = {}
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

        # GUI 总线固定 INFO 起（流水账 DEBUG 不进 GUI）；需要细粒度时用
        # FXXXXC_BUS_LOG_LEVEL 覆盖，与文件等级 FXXXXC_LOG_LEVEL 互不影响。
        self._log_sink_handle = logger.add(
            sink, level=os.environ.get("FXXXXC_BUS_LOG_LEVEL", "INFO"))

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
            "config.remove": self.config_remove,
            "auth.login": self.auth_login,
            "auth.status": lambda p: self.auth_status(),
            "auth.logout": lambda p: self.auth_logout(),
            "courses.list": self.courses_list,
            "course.detail": self.course_detail,
            "study.start": self.study_start,
            "study.pause": lambda p: self.study_pause(),
            "study.resume": lambda p: self.study_resume(),
            "study.stop": lambda p: self.study_stop(),
            "study.status": lambda p: self.study_status(),
            "logs.tail": self.logs_tail,
            "manual.answer": self.manual_answer,
            "manual.skip": self.manual_skip,
            "tiku.test": lambda p: self.tiku_test(),
            "tiku.ocs.fetch": self.tiku_ocs_fetch,
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

    def config_remove(self, params: dict) -> dict:
        """删除整个配置节（目前仅允许题库实例段，避免误删账号等关键配置）。"""
        sections = params.get("sections") or []
        if not isinstance(sections, list) or not all(isinstance(item, str) for item in sections):
            raise RpcError(-32602, "config.remove requires {sections: [name]}")
        invalid = [name for name in sections if not name.startswith(BANK_SECTION_PREFIX)]
        if invalid:
            raise RpcError(-32602, f"仅允许删除题库实例配置节: {', '.join(invalid)}")
        removed = []
        with self._lock:
            data = self._read_config()
            for name in sections:
                if name in data:
                    data.pop(name)
                    removed.append(name)
            if removed:
                self._write_config(data)
        if removed:
            self.bus.emit("config.changed", {})
        return {"ok": True, "removed": removed}

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
        common["notopen_action"] = raw.get("notopen_action") or "retry"
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

    def _bank_instances(self, data: dict[str, dict[str, str]] | None = None) -> list[tuple[str, dict[str, str]]]:
        """收集已启用的题库实例，按 priority 升序（同值按段名字典序）返回。

        每个实例是 ``(段名, 配置)``；priority 缺省按 0 处理，段名自带稳定排序。
        """
        if data is None:
            data = self._read_config()
        banks: list[tuple[str, dict[str, str]]] = []
        for section, items in data.items():
            if not section.startswith(BANK_SECTION_PREFIX):
                continue
            conf = dict(items)
            enabled = str(conf.get("enabled", "true")).strip().lower() in _BOOL_TRUE
            if not enabled:
                continue
            try:
                priority = int(str(conf.get("priority", "0")).strip() or "0")
            except (TypeError, ValueError):
                priority = 0
            banks.append((section, conf))
        banks.sort(key=lambda item: (
            _as_int(item[1].get("priority"), 0),
            item[0],
        ))
        return banks

    def _build_tiku(self) -> Tiku:
        data = self._read_config()
        tiku_conf = data.get("tiku", {})
        has_bank_sections = any(
            section.startswith(BANK_SECTION_PREFIX) for section in data
        )
        banks = self._bank_instances(data)
        if banks:
            # 实例链：全局键（submit/cover_rate/delay/判断词列表等）作为兜底，
            # 实例自己的键优先 —— 每个题库源一份独立配置，互不串线。
            merged_banks = [
                (name, {**tiku_conf, **conf}) for name, conf in banks
            ]
            from api.answer import build_tiku_from_banks

            tiku = build_tiku_from_banks(merged_banks, config_path=str(self.config_path))
            if tiku is None:
                raise RpcError(CONFIG_ERROR, "题库实例均已停用或配置无效，请先在设置中启用至少一个题库源")
        elif has_bank_sections:
            # 配置过实例但全部停用：明确报错而不是静默按“无题库”运行，
            # 否则章节检测会被整体跳过且难以察觉。
            raise RpcError(CONFIG_ERROR, "所有题库源均已停用，请至少启用一个题库源")
        else:
            # 兼容旧配置：单个 [tiku] provider（可逗号分隔多实现，共享一份配置）
            tiku = Tiku.get_tiku_from_config(dict(tiku_conf), config_path=str(self.config_path))
        tiku.init_tiku()
        if isinstance(tiku, TikuManual):
            manual = EngineManualTiku(self, config_path=str(self.config_path))
            manual.config_set(dict(tiku_conf))
            manual.init_tiku()
            tiku = manual
        return tiku

    # ------------------------------------------------------------------ auth

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

    def course_detail(self, params: dict) -> dict:
        """单门课程的章节状态明细（供 GUI 课程卡展开/预取）。

        带 TTL 缓存；``refresh=true`` 强制回源。返回结构化的章节列表与
        汇总计数，GUI 不需要再解析平台 HTML。
        """
        course_id = str(params.get("course_id") or "").strip()
        clazz_id = str(params.get("clazz_id") or "").strip()
        cpi = str(params.get("cpi") or "").strip()
        if not course_id or not clazz_id:
            raise RpcError(-32602, "course.detail requires course_id and clazz_id")
        refresh = _as_bool(params.get("refresh"), False)

        key = (course_id, clazz_id)
        now = time.time()
        if not refresh:
            with self._lock:
                cached = self._course_details.get(key)
                if cached is not None and now - cached[0] < self.COURSE_DETAIL_TTL:
                    return cached[1]

        chaoxing = self._ensure_chaoxing()
        points = chaoxing.get_course_point(course_id, clazz_id, cpi)
        chapters = []
        for index, point in enumerate(points.get("points", [])):
            chapters.append(
                {
                    "index": index,
                    "title": str(point.get("title", "")),
                    "finished": bool(point.get("has_finished")),
                    "job_count": max(0, _as_int(point.get("jobCount"), 1)),
                    "need_unlock": bool(point.get("need_unlock")),
                }
            )
        payload = {
            "course_id": course_id,
            "clazz_id": clazz_id,
            "chapters": chapters,
            "total": len(chapters),
            "finished": sum(1 for chapter in chapters if chapter["finished"]),
            "locked": sum(1 for chapter in chapters if chapter["need_unlock"]),
            "has_locked": bool(points.get("hasLocked")),
        }
        with self._lock:
            if len(self._course_details) >= self.COURSE_DETAIL_CACHE_MAX:
                # 简单防膨胀：超出容量时整体清空（命中一次后又会重建）。
                self._course_details.clear()
            self._course_details[key] = (now, payload)
        return payload

    # ----------------------------------------------------------------- study

    def study_start(self, params: dict) -> dict:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                raise RpcError(STUDY_ALREADY_RUNNING, "已有学习任务在运行")
            course_ids = [str(item).strip() for item in (params.get("course_ids") or [])]
            course_ids = [item for item in course_ids if item]
            if not course_ids:
                raise RpcError(-32602, "study.start requires course_ids")
            options = params.get("options") or {}
            if not isinstance(options, dict):
                raise RpcError(-32602, "study.start options must be an object")
            if "notopen_action" in options:
                allowed = sorted(_NOTOPEN_ACTIONS)
                if str(options["notopen_action"]).strip().lower() not in _NOTOPEN_ACTIONS:
                    raise RpcError(-32602, f"notopen_action 仅允许 {'/'.join(allowed)}")

            # 选中课程引擎侧持久化（[engine] last_course_ids），GUI 重启后可恢复；
            # 不写入 common.course_list，避免改变 CLI 的交互语义。
            self._last_course_ids = course_ids
            try:
                self.config_set({"config": {"engine": {"last_course_ids": ",".join(course_ids)}}})
            except RpcError:
                pass

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
        chaoxing: Chaoxing | None = None
        try:
            self._set_state("loading", "正在准备学习任务")
            chaoxing = self._ensure_chaoxing()

            # 进度钩子：引擎把底层任务事件转成 study.task 事件并维护实时快照，
            # GUI 轮询 study.status 即可在重连后恢复全貌（双向同步的另一半）。
            def _on_progress(data: dict) -> None:
                with self._lock:
                    self._live = dict(data)
                self.bus.emit("study.task", {**data, "run_id": run_id})

            with self._lock:
                self._live = {}
                self._run_started_at = time.time()
            chaoxing.progress_hook = _on_progress
            self.bus.emit(
                "study.task",
                {"kind": "run", "phase": "start", "run_id": run_id, "courses": len(course_ids)},
            )

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
            elapsed = max(0, int(time.time() - self._run_started_at))

            # 学习次数阶段属于本轮任务的一部分：必须在整轮结束事件之前完成，
            # 否则 GUI 会先收到“本轮结束”而状态仍是 running，表现为不同步。
            if config.get("add_learning_count"):
                self._increase_learning_count(chaoxing, selected, config)

            detail = f"完成，失败章节 {failed}，用时 {elapsed // 60}分{elapsed % 60}秒" if elapsed else f"完成，失败章节 {failed}"
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
            self.bus.emit(
                "study.task",
                {"kind": "run", "phase": "finished", "run_id": run_id, "total": len(tasks), "failed": failed, "elapsed": elapsed},
            )
        except RpcError as exc:
            self._set_state("error", exc.message)
            self.bus.emit("study.progress", {"run_id": run_id, "phase": "error", "message": exc.message})
            self.bus.emit("study.task", {"kind": "run", "phase": "error", "run_id": run_id, "message": exc.message})
        except Exception as exc:  # noqa: BLE001 - worker boundary
            logger.error("学习任务异常: {}", exc)
            self._set_state("error", f"{type(exc).__name__}: {exc}")
            self.bus.emit(
                "study.progress",
                {"run_id": run_id, "phase": "error", "message": str(exc)},
            )
            self.bus.emit("study.task", {"kind": "run", "phase": "error", "run_id": run_id, "message": str(exc)})
        finally:
            if chaoxing is not None and chaoxing.progress_hook is not None:
                chaoxing.progress_hook = None
            with self._lock:
                self._processor = None
                self._run_started_at = 0.0
                if self._worker is threading.current_thread():
                    self._worker = None

    def _increase_learning_count(self, chaoxing: Chaoxing, courses: list[dict], config: dict) -> None:
        from api.process import increase_learning_count_for_course

        for course in courses:
            if chaoxing.should_stop():
                break
            self._set_state("running", f"增加章节学习次数：{course.get('title', '')}")
            increase_learning_count_for_course(chaoxing, course, config)

    def study_pause(self) -> dict:
        processor = self._processor
        if processor is None:
            worker = self._worker
            if worker is not None and worker.is_alive():
                raise RpcError(
                    STUDY_NOT_RUNNING,
                    "当前阶段（如增加章节学习次数）不支持暂停，可使用「停止」结束",
                )
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
            # 学习次数等无 processor 的阶段：通过取消钩子停止工作线程，
            # 而不是直接返回（旧实现会误报“没有正在运行的学习任务”）。
            worker = self._worker
            chaoxing = self._chaoxing
            if worker is not None and worker.is_alive() and chaoxing is not None:
                self._set_state("stopping", "正在停止")
                chaoxing.cancel()
                return {"state": "stopping"}
            return {"state": self.state()}
        self._set_state("stopping", "正在停止")
        processor.stop()
        return {"state": "stopping"}

    def study_status(self) -> dict:
        processor = self._processor
        payload: dict[str, Any] = {"state": self.state(), "detail": self._state_detail}
        with self._lock:
            live = dict(self._live) if self._live else None
            started_at = self._run_started_at
            last_course_ids = list(self._last_course_ids)
        if live:
            payload["current"] = live
        if started_at > 0:
            payload["elapsed"] = max(0, int(time.time() - started_at))
        if last_course_ids:
            payload["last_course_ids"] = last_course_ids
        if processor is not None:
            total = len(processor.tasks)
            unfinished = processor.task_queue.unfinished_tasks
            payload.update(
                {
                    "run_id": self._run_id,
                    "total": total,
                    "done": max(0, total - unfinished),
                    "failed": len(processor.failed_tasks),
                    "courses_progress": self._courses_progress(processor),
                }
            )
        elif self._chaoxing is not None:
            payload.update({"courses": len(self._courses)})
        tiku = self._tiku
        if tiku is not None:
            get_stats = getattr(tiku, "get_stats", None)
            if callable(get_stats):
                try:
                    payload["tiku_stats"] = get_stats()
                except Exception:  # noqa: BLE001 - stats are best effort
                    pass
        return payload

    @staticmethod
    def _courses_progress(processor: JobProcessor) -> list[dict]:
        """把章节任务队列折算成每门课程的进度（本轮运行实时快照）。"""
        per_course: dict[str, dict] = {}
        order: list[str] = []
        for task in processor.tasks:
            key = str(task.course.get("courseId", ""))
            if key not in per_course:
                order.append(key)
                per_course[key] = {
                    "course_id": key,
                    "title": str(task.course.get("title", "")),
                    "total": 0,
                    "done": 0,
                    "failed": 0,
                }
            entry = per_course[key]
            entry["total"] += 1
            if task.result is ChapterResult.SUCCESS:
                entry["done"] += 1
        for task in processor.failed_tasks:
            key = str(task.course.get("courseId", ""))
            if key in per_course:
                per_course[key]["failed"] += 1
        return [per_course[key] for key in order]

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

    def tiku_ocs_fetch(self, params: dict) -> dict:
        """从订阅链接自动获取 OCS（AnswererWrapper）题库配置 JSON。

        支持直接返回配置 JSON 的任意题库站/订阅链接；文本中混有说明文字时
        自动截取首个 ``[`` 到最后一个 ``]`` 的片段再解析。
        """
        url = str(params.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise RpcError(-32602, "需要 http(s) 的题库配置订阅链接")

        import requests

        try:
            resp = requests.get(
                url, timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
        except requests.RequestException as exc:
            raise RpcError(-32602, f"获取失败: {exc}") from exc
        if resp.status_code != 200:
            raise RpcError(-32602, f"获取失败: HTTP {resp.status_code}")

        text = resp.text.strip()
        candidates = [text]
        start, end = text.find("["), text.rfind("]")
        if 0 <= start < end:
            candidates.append(text[start : end + 1])
        for candidate in candidates:
            try:
                data = json.loads(candidate)
            except ValueError:
                continue
            if isinstance(data, dict):
                data = [data]
            if not isinstance(data, list):
                continue
            valid = [
                item for item in data
                if isinstance(item, dict) and str(item.get("url", "") or "").strip()
            ]
            if valid:
                return {
                    "ok": True,
                    "count": len(valid),
                    "wrappers": json.dumps(valid, ensure_ascii=False),
                }
        raise RpcError(-32602, "链接内容不是可识别的 OCS 题库配置 JSON（需含 url 字段的对象数组）")

    def tiku_test(self) -> dict:
        try:
            tiku = self._build_tiku()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": str(exc)}
        if getattr(tiku, "DISABLE", False):
            return {"ok": False, "message": "题库未启用或配置无效"}
        get_stats = getattr(tiku, "get_stats", None)
        stats = get_stats() if callable(get_stats) else {}

        # 分源检查：每个题库实例单独报告初始化/连接状态，方便定位是哪一个源出问题
        providers = getattr(tiku, "providers", None) or [tiku]
        banks = []
        for provider in providers:
            entry = {"name": getattr(provider, "name", None) or provider.__class__.__name__}
            if getattr(provider, "DISABLE", False):
                entry.update(ok=False, message="初始化失败或配置无效")
            else:
                try:
                    ok = bool(provider.check_llm_connection())
                    entry.update(ok=ok, message="连接正常" if ok else "连接失败")
                except Exception as exc:  # noqa: BLE001 - single bank must not kill the test
                    entry.update(ok=False, message=str(exc))
            banks.append(entry)
        ok = all(entry["ok"] for entry in banks) if banks else False
        if len(banks) <= 1:
            only = banks[0] if banks else {"ok": False, "message": "无可用题库"}
            return {"ok": only["ok"], "message": only["message"], "stats": stats}
        summary = "；".join(f"{entry['name']}: {entry['message']}" for entry in banks)
        return {"ok": ok, "message": summary, "stats": stats, "banks": banks}

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
