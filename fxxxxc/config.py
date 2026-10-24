# -*- coding: utf-8 -*-
"""INI configuration helpers shared by the CLI and the desktop engine."""

from __future__ import annotations

import configparser
import os
from pathlib import Path
from typing import Any

IniData = dict[str, dict[str, Any]]


def load_ini(path: str | os.PathLike) -> dict[str, dict[str, str]]:
    """Read an INI file into ``{section: {key: value}}`` (missing file = {})."""
    parser = configparser.ConfigParser()
    file = Path(path)
    if file.exists():
        parser.read(file, encoding="utf-8")
    return {section: dict(parser.items(section)) for section in parser.sections()}


def save_ini(path: str | os.PathLike, data: IniData) -> None:
    """Write ``{section: {key: value}}`` as UTF-8 INI, creating parents."""
    parser = configparser.ConfigParser()
    for section, items in data.items():
        parser[section] = {key: str(value) for key, value in items.items()}
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("w", encoding="utf-8") as handle:
        parser.write(handle)
