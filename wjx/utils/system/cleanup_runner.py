from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Deque, Optional, Tuple


class CleanupRunner:
    """Run cleanup tasks in a single background worker to avoid blocking the UI."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: Deque[Tuple[Callable[[], None], float]] = deque()
        self._thread: Optional[threading.Thread] = None

    def submit(self, task: Callable[[], None], delay_seconds: float = 0.0) -> None:
        delay = max(0.0, float(delay_seconds or 0.0))
        with self._lock:
            self._queue.append((task, delay))
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._worker, daemon=True, name="CleanupWorker")
            self._thread.start()

    def _worker(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    self._thread = None
                    return
                task, delay = self._queue.popleft()
            if delay > 0:
                time.sleep(delay)
            try:
                task()
            except Exception:
                pass
