# -*- coding: utf-8 -*-
"""Path resolution for CLI, engine and desktop data directories."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "FXXXXC"
ENV_DATA_DIR = "FXXXXC_DATA_DIR"


def get_data_dir() -> Path:
    """Return the active data directory.

    The CLI keeps the historical current-directory behavior unless
    ``FXXXXC_DATA_DIR`` is set. The desktop engine always sets it.
    """
    return Path(os.environ.get(ENV_DATA_DIR) or os.getcwd()).resolve()


def set_data_dir(path: str | os.PathLike[str]) -> Path:
    resolved = Path(path).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    os.environ[ENV_DATA_DIR] = str(resolved)
    return resolved


def config_path() -> Path:
    return get_data_dir() / "config.ini"


def cookies_path() -> Path:
    return get_data_dir() / "cookies.txt"


def cache_path() -> Path:
    return get_data_dir() / "cache.json"


def log_path() -> Path:
    return get_data_dir() / "chaoxing.log"


def app_data_dir() -> Path:
    """Per-user application data (Windows: %APPDATA%/FXXXXC)."""
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def local_app_data_dir() -> Path:
    """Per-user local data (Windows: %LOCALAPPDATA%/FXXXXC)."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def resource_root() -> Path:
    """Root that contains ``resource/`` in source and PyInstaller builds."""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle)
    return Path(__file__).resolve().parent.parent


def resource_path(relative_path: str) -> Path:
    return resource_root() / relative_path
