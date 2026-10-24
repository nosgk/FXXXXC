# -*- coding: utf-8 -*-
import os


def _data_dir() -> str:
    return os.path.abspath(os.environ.get("FXXXXC_DATA_DIR") or os.getcwd())


class GlobalConst:
    AESKey = "u2oh6Vu^HWe4_AES"

    # Legacy CLI paths stay relative to the current directory unless the
    # caller sets FXXXXC_DATA_DIR (the desktop engine always does).
    DATA_DIR = _data_dir()
    CONFIG_PATH = os.path.join(DATA_DIR, "config.ini")
    COOKIES_PATH = os.path.join(DATA_DIR, "cookies.txt")
    CACHE_PATH = os.path.join(DATA_DIR, "cache.json")
    LOG_PATH = os.path.join(DATA_DIR, "chaoxing.log")

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Chromium";v="118", "Google Chrome";v="118", "Not=A?Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"'
    }
    VIDEO_HEADERS = {
        "Referer": "https://mooc1.chaoxing.com/ananas/modules/video/index.html?v=2025-0725-1842",
    }
    AUDIO_HEADERS = {
        "Referer": "https://mooc1.chaoxing.com/ananas/modules/audio/index_new.html?v=2025-0725-1842",
    }

    THRESHOLD = 1
