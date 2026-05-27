"""RunController 关闭收尾辅助。"""

from __future__ import annotations

import threading
from typing import Any, Iterable, List, Optional


def collect_unique_threads(candidates: Iterable[Any]) -> List[threading.Thread]:
    seen: set[int] = set()
    threads: List[threading.Thread] = []
    for candidate in candidates:
        if not isinstance(candidate, threading.Thread):
            continue
        identifier = id(candidate)
        if identifier in seen:
            continue
        seen.add(identifier)
        threads.append(candidate)
    return threads


class RuntimeShutdownHelper:
    """收集运行控制器需要等待的后台线程。"""

    def __init__(self, controller: Any) -> None:
        self.controller = controller

    def collect_threads(self) -> List[threading.Thread]:
        controller = self.controller
        collect_random_ip_threads = getattr(
            controller,
            "collect_random_ip_background_threads",
            lambda: [],
        )
        return collect_unique_threads(
            [
                getattr(controller, "_init_gate_thread", None),
                *list(getattr(controller, "worker_threads", []) or []),
                getattr(controller, "_monitor_thread", None),
                *list(collect_random_ip_threads() or []),
            ]
        )


def clear_finished_thread(value: Optional[threading.Thread]) -> Optional[threading.Thread]:
    if value is not None and not value.is_alive():
        return None
    return value


__all__ = ["RuntimeShutdownHelper", "clear_finished_thread", "collect_unique_threads"]
