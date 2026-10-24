# -*- coding: utf-8 -*-
"""Thread-safe request rate limiter."""

from __future__ import annotations

import random
import threading
import time


class RateLimiter:
    def __init__(self, call_interval: float):
        self.last_call = time.time()
        self.lock = threading.Lock()
        self.call_interval = call_interval

    def limit_rate(self, random_time: bool = False, random_min: float = 0.0, random_max: float = 1.0) -> None:
        with self.lock:
            now = time.time()
            base_wait = max(self.last_call + self.call_interval - now, 0)
            extra_wait = random.uniform(random_min, random_max) if random_time else 0
            call_wait = base_wait + extra_wait
            self.last_call = now + call_wait

        time.sleep(call_wait)
