# -*- coding: utf-8 -*-
"""Documentation parity tests: config template must match the code."""

from __future__ import annotations

import configparser
import io
import contextlib
import sys
from pathlib import Path

import main

ROOT = Path(__file__).resolve().parent.parent

EXPECTED_SECTIONS = {"common", "tiku", "notification"}

EXPECTED_KEYS = {
    "common": {
        "use_cookies",
        "username",
        "password",
        "course_list",
        "speed",
        "jobs",
        "notopen_action",
        "retry_interval",
        "chapter_max_tries",
        "work_redo_enabled",
        "work_max_retries",
        "add_learning_count",
        "target_count",
        "learning_count_interval",
    },
    "tiku": {
        "provider",
        "check_llm_connection",
        "submit",
        "cover_rate",
        "delay",
        "tokens",
        "true_list",
        "false_list",
        "likeapi_model",
        "url",
        "go_authorization",
        "endpoint",
        "key",
        "model",
        "min_interval_seconds",
        "http_proxy",
        "siliconflow_key",
        "siliconflow_model",
        "manual_mode_default",
        "manual_mode_separator",
        "insecure_skip_verify",
    },
    "notification": {
        "provider",
        "url",
        "tg_chat_id",
    },
}


def _template() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(ROOT / "config_template.ini", encoding="utf-8")
    return parser


def test_config_template_covers_all_sections():
    parser = _template()
    assert EXPECTED_SECTIONS.issubset(set(parser.sections()))


def test_config_template_covers_all_documented_keys():
    parser = _template()
    for section, keys in EXPECTED_KEYS.items():
        missing = keys - set(parser.options(section))
        assert not missing, f"config_template.ini missing keys in [{section}]: {sorted(missing)}"


def test_cli_help_documents_new_options():
    buffer = io.StringIO()
    argv = sys.argv
    sys.argv = ["main.py", "--help"]
    try:
        with contextlib.redirect_stdout(buffer):
            try:
                main.parse_args()
            except SystemExit:
                pass
    finally:
        sys.argv = argv

    help_text = buffer.getvalue()
    assert "--data-dir" in help_text
    assert "--version" in help_text
    assert "尚未实现" in help_text  # --auto-sign must not pretend to work
