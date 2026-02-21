"""轻量级事件总线（发布-订阅）。

提供进程内跨模块消息传递，替代深层回调链与 Adapter 传递。
引擎只需 ``bus.emit("task_stopped")``，RunController 自动收到通知。

线程安全：emit() 在调用方线程同步执行所有订阅者；
如需切换到主线程，订阅者自行安排（通过 QTimer.singleShot 等）。

用法示例::

    from wjx.utils.event_bus import bus

    # 订阅
    bus.subscribe("task_stopped", my_handler)

    # 发布
    bus.emit("task_stopped", reason="completed")

    # 取消订阅
    bus.unsubscribe("task_stopped", my_handler)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, DefaultDict, Dict, List, Optional
from collections import defaultdict


class EventBus:
    """进程内同步事件总线。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # event_name -> [handler, ...]
        self._handlers: DefaultDict[str, List[Callable[..., None]]] = defaultdict(list)

    def subscribe(self, event: str, handler: Callable[..., None]) -> None:
        """注册事件处理器（幂等，同一 handler 只注册一次）。"""
        with self._lock:
            if handler not in self._handlers[event]:
                self._handlers[event].append(handler)

    def unsubscribe(self, event: str, handler: Callable[..., None]) -> None:
        """取消注册事件处理器（不存在时静默忽略）。"""
        with self._lock:
            try:
                self._handlers[event].remove(handler)
            except ValueError:
                pass

    def emit(self, event: str, **kwargs: Any) -> None:
        """触发事件，同步调用所有订阅者。

        即使某个订阅者抛出异常，也会继续通知其余订阅者。
        """
        with self._lock:
            handlers = list(self._handlers.get(event, []))
        for handler in handlers:
            try:
                handler(**kwargs)
            except Exception as exc:
                logging.debug(
                    "EventBus: handler %r raised on event %r: %s",
                    handler,
                    event,
                    exc,
                    exc_info=True,
                )

    def clear(self, event: Optional[str] = None) -> None:
        """清空事件订阅（event=None 时清空全部）。"""
        with self._lock:
            if event is None:
                self._handlers.clear()
            else:
                self._handlers.pop(event, None)


# 全局单例（进程里只有一条总线就够了）
bus: EventBus = EventBus()

# 预定义的事件名称常量，减少魔法字符串硬编码
EVENT_TASK_STARTED = "task_started"
EVENT_TASK_STOPPED = "task_stopped"
EVENT_TASK_PAUSED = "task_paused"
EVENT_TASK_RESUMED = "task_resumed"
EVENT_TARGET_REACHED = "target_reached"
EVENT_CAPTCHA_DETECTED = "captcha_detected"
EVENT_SUBMIT_SUCCESS = "submit_success"
EVENT_SUBMIT_FAILURE = "submit_failure"
EVENT_IP_COUNTER_UPDATED = "ip_counter_updated"
