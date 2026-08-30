from __future__ import annotations

import threading
import time


class PreviewService:
    DEFAULT_MINUTES = 15

    def __init__(self):
        self._lock = threading.RLock()
        self._rows = None
        self._until = 0.0
        self._seq = 0
        self._label = ""

    def start(self, rows, label="", minutes=None):
        minutes = self.DEFAULT_MINUTES if minutes is None else max(1, int(minutes))
        with self._lock:
            self._rows = [dict(row) for row in (rows or [])]
            self._until = time.time() + minutes * 60
            self._seq += 1
            self._label = str(label or "")
            return self.state()

    def stop(self):
        with self._lock:
            self._rows = None
            self._until = 0.0
            self._label = ""
            return self.state()

    def rows(self):
        with self._lock:
            if self._rows is None:
                return None
            if time.time() >= self._until:
                self._rows = None
                self._label = ""
                return None
            return [dict(row) for row in self._rows]

    def state(self):
        with self._lock:
            active = self._rows is not None and time.time() < self._until
            return {
                "active": active,
                "label": self._label if active else "",
                "rows": len(self._rows or []) if active else 0,
                "seconds_left": max(0, int(self._until - time.time())) if active else 0,
                "seq": self._seq,
            }
