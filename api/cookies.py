# -*- coding: utf-8 -*-
import os
import os.path
import tempfile
import threading

import requests

from api.config import GlobalConst as gc
from api.logger import logger

# 定义全局 Cookie 文件锁，保证读写绝对安全
cookie_lock = threading.RLock()


def save_cookies(session: requests.Session):
    """Persist cookies atomically with UTF-8 and best-effort user-only mode."""
    with cookie_lock:
        buffer = ""
        for k, v in session.cookies.items():
            buffer += f"{k}={v};"
        buffer = buffer.removesuffix(";")

        target = os.path.abspath(gc.COOKIES_PATH)
        parent = os.path.dirname(target) or "."
        os.makedirs(parent, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".cookies-", dir=parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(buffer)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, target)
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
        except Exception as exc:  # noqa: BLE001 - persistence must not crash the run
            logger.warning(f"保存 cookies 失败: {exc}")
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def use_cookies() -> dict:
    with cookie_lock:
        if not os.path.exists(gc.COOKIES_PATH):
            return {}

        cookies = {}
        try:
            with open(gc.COOKIES_PATH, "r", encoding="utf-8") as f:
                buffer = f.read().strip()
                if not buffer:
                    return {}
                for item in buffer.split(";"):
                    item = item.strip()
                    if not item:
                        continue
                    parts = item.split("=", 1)
                    if len(parts) == 2:
                        cookies[parts[0]] = parts[1]
        except Exception:
            return {}

        return cookies
