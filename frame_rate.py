"""Shared application camera rate; does not change camera hardware settings."""

import time

CAMERA_FPS = 15


class FrameLimiter:
    def __init__(self):
        self.last = float('-inf')

    def ready(self):
        now = time.monotonic()
        if now - self.last + 1e-9 < 1 / CAMERA_FPS:
            return False
        self.last = now
        return True
