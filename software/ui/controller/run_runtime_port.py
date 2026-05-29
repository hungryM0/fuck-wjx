from __future__ import annotations

import asyncio
import collections.abc
import logging
import threading
from inspect import isawaitable
from typing import Any, Callable, List, Optional, cast

from software.core.engine.runtime_control_port import RuntimeControlPort
from software.core.engine.stop_signal import StopSignalLike


class BoolState:
    def __init__(self, value: bool = False) -> None:
        self._value = bool(value)

    def get(self) -> bool:
        return self._value

    def set(self, value: bool) -> None:
        self._value = bool(value)


class RunRuntimePort(RuntimeControlPort):
    """运行服务传给内核的中性控制端口。"""

    def __init__(
        self,
        *,
        stop_signal: threading.Event,
        notify_random_ip_loading: Callable[[bool, str], Any],
        handle_random_ip_submission: Callable[..., None],
    ) -> None:
        self.random_ip_enabled_state = BoolState(False)
        self.active_drivers: List[Any] = []
        self._active_drivers_lock = threading.Lock()
        self._stop_signal = stop_signal
        self._notify_random_ip_loading = notify_random_ip_loading
        self._handle_random_ip_submission = handle_random_ip_submission
        self._pause_event = threading.Event()
        self._pause_reason = ""

    def pause_run(self, reason: str = "") -> None:
        self._pause_reason = str(reason or "已暂停")
        self._pause_event.set()

    def resume_run(self) -> None:
        self._pause_reason = ""
        self._pause_event.clear()

    def is_paused(self) -> bool:
        return bool(self._pause_event.is_set())

    def get_pause_reason(self) -> str:
        return self._pause_reason or ""

    def wait_if_paused(self, stop_signal: Optional[StopSignalLike] = None) -> None:
        signal = stop_signal or self._stop_signal
        while self.is_paused() and signal and not signal.is_set():
            signal.wait(0.25)

    def on_random_ip_submission(self, stop_signal: Optional[StopSignalLike] = None) -> None:
        signal = stop_signal if isinstance(stop_signal, threading.Event) else None
        try:
            self._handle_random_ip_submission(stop_signal=signal)
        except Exception:
            logging.info("处理随机IP提交流程失败", exc_info=True)

    def on_random_ip_loading_changed(self, loading: bool, message: str = "") -> None:
        try:
            self._notify_random_ip_loading(bool(loading), str(message or ""))
        except Exception:
            logging.info("更新随机IP加载状态失败", exc_info=True)

    def set_random_ip_enabled(self, enabled: bool) -> None:
        self.random_ip_enabled_state.set(bool(enabled))

    def is_random_ip_enabled(self) -> bool:
        return bool(self.random_ip_enabled_state.get())

    def register_cleanup_target(self, target: Any) -> None:
        if target is None:
            return
        with self._active_drivers_lock:
            self.active_drivers.append(target)

    def unregister_cleanup_target(self, target: Any) -> None:
        if target is None:
            return
        with self._active_drivers_lock:
            try:
                self.active_drivers.remove(target)
            except ValueError:
                logging.info("清理目标已不存在，跳过反注册")

    def _drain_cleanup_targets(self) -> List[Any]:
        with self._active_drivers_lock:
            if not self.active_drivers:
                return []
            drained = list(self.active_drivers)
            self.active_drivers.clear()
            return drained

    def cleanup_targets(self) -> None:
        cleaned = 0
        seen: set[int] = set()
        while True:
            drivers = self._drain_cleanup_targets()
            if not drivers:
                break
            for driver in reversed(drivers):
                identifier = id(driver)
                if identifier in seen:
                    continue
                seen.add(identifier)
                try:
                    mark_cleanup_done = getattr(driver, "mark_cleanup_done", None)
                    if callable(mark_cleanup_done) and not mark_cleanup_done():
                        continue
                    aclose_driver = getattr(driver, "aclose", None)
                    if callable(aclose_driver):
                        close_result = aclose_driver()
                        if isawaitable(close_result):
                            asyncio.run(cast(collections.abc.Coroutine[Any, Any, Any], close_result))
                        cleaned += 1
                        continue
                    quit_driver = getattr(driver, "quit", None)
                    if callable(quit_driver):
                        quit_driver()
                        cleaned += 1
                except Exception:
                    logging.warning("[兜底清理] 强制关闭运行时资源失败", exc_info=True)
        if seen:
            logging.info(
                "[兜底清理] 已强制关闭 %d/%d 个运行时资源",
                cleaned,
                len(seen),
            )


__all__ = ["BoolState", "RunRuntimePort"]
