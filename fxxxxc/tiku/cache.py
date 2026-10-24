# -*- coding: utf-8 -*-
"""On-disk answer cache with an in-process read cache and atomic writes."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from api.config import GlobalConst as gc
from api.logger import logger


class CacheDAO:
    """Small JSON answer cache.

    The original implementation read and rewrote the whole file for every
    question. This version keeps a per-instance snapshot, checks mtime before
    reuse, and supports batch writes.
    """

    DEFAULT_CACHE_FILE = gc.CACHE_PATH

    def __init__(self, file: str = DEFAULT_CACHE_FILE):
        self.cache_file = Path(file)
        self._lock = threading.RLock()
        self._data: dict | None = None
        self._mtime_ns: int | None = None
        if not self.cache_file.is_file():
            self._write_cache({})

    def _current_mtime(self) -> int | None:
        try:
            return self.cache_file.stat().st_mtime_ns
        except OSError:
            return None

    def _backup_corrupt(self, reason: str) -> None:
        try:
            bak_name = f"{self.cache_file.name}.bak.{int(time.time())}"
            bak_path = self.cache_file.with_name(bak_name)
            shutil.copy2(self.cache_file, bak_path)
            logger.error(f"缓存文件{reason}，已备份为: {bak_path}，将使用空缓存继续运行")
        except Exception as exc:  # noqa: BLE001 - backup is best effort
            logger.error(f"备份损坏缓存失败: {exc}")

    def _load(self) -> dict:
        try:
            text = self.cache_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except UnicodeDecodeError:
            text = self.cache_file.read_bytes().decode("utf-8", errors="ignore")
            self._backup_corrupt("编码错误")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error(f"缓存文件 JSON 解析失败: {exc}, 尝试恢复...")
            start = text.find("{")
            end = text.rfind("}")
            data = None
            if start != -1 and end > start:
                try:
                    data = json.loads(text[start : end + 1])
                except Exception:
                    data = None
            if data is None:
                self._backup_corrupt("已损坏")
                return {}
        if not isinstance(data, dict):
            self._backup_corrupt("格式异常")
            return {}
        return data

    def _read_cache(self) -> dict:
        with self._lock:
            mtime = self._current_mtime()
            if self._data is not None and mtime == self._mtime_ns:
                return self._data
            try:
                data = self._load()
            except Exception as exc:  # noqa: BLE001 - cache must not crash a run
                logger.error(f"读取缓存异常: {exc}")
                data = {}
            self._data = data
            self._mtime_ns = mtime
            return data

    def _write_cache(self, data: dict) -> None:
        try:
            with self._lock:
                parent = self.cache_file.parent
                if not parent.exists():
                    parent.mkdir(parents=True, exist_ok=True)
                fd, tmp_path = tempfile.mkstemp(prefix=self.cache_file.name, dir=str(parent))
                try:
                    with os.fdopen(fd, "w", encoding="utf8") as fp:
                        json.dump(data, fp, ensure_ascii=False, indent=4)
                        fp.flush()
                        os.fsync(fp.fileno())
                    os.replace(tmp_path, str(self.cache_file))
                    self._data = data
                    self._mtime_ns = self._current_mtime()
                except Exception as exc:  # noqa: BLE001
                    try:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except Exception:
                        pass
                    logger.error(f"Failed to write cache atomically: {exc}")
        except IOError as exc:
            logger.error(f"Failed to write cache: {exc}")

    def get_cache(self, question: str) -> Optional[str]:
        return self._read_cache().get(question)

    def add_cache(self, question: str, answer: str) -> None:
        with self._lock:
            data = self._read_cache()
            data[question] = answer
            self._write_cache(data)

    def add_many(self, answers: dict[str, str]) -> None:
        if not answers:
            return
        with self._lock:
            data = self._read_cache()
            data.update(answers)
            self._write_cache(data)
