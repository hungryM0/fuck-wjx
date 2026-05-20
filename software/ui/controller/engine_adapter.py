"""运行控制器使用的引擎/UI 适配层。"""

from __future__ import annotations

import asyncio
import collections.abc
import logging
import threading
from inspect import isawaitable
from typing import Any, Callable, List, Optional, cast

from software.core.engine.cleanup import CleanupRunner
from software.core.engine.runtime_actions import (
    RuntimeActionKind,
    RuntimeActionRequest,
    RuntimeActionResult,
    ensure_runtime_action_result,
)
from software.core.task import ExecutionState


class BoolVar:
    """简单的布尔状态封装，用于 UI 适配。"""

    def __init__(self, value: bool = False):
        self._value = bool(value)

    def get(self) -> bool:
        return self._value

    def set(self, value: bool) -> None:
        self._value = bool(value)


class EngineGuiAdapter:
    """传给引擎的 UI 适配器，负责把回调桥接回 Qt 主线程。"""

    def __init__(
        self,
        dispatcher: Callable[[Callable[[], Any]], Any],
        stop_signal: threading.Event,
        quota_request_form_opener: Optional[Callable[[], bool]] = None,
        on_ip_counter: Optional[Callable[[float, float, bool], None]] = None,
        on_random_ip_loading: Optional[Callable[[bool, str], None]] = None,
        message_handler: Optional[Callable[[str, str, str], None]] = None,
        confirm_handler: Optional[Callable[[str, str], bool]] = None,
        async_dispatcher: Optional[Callable[[Callable[[], Any]], Any]] = None,
        cleanup_runner: Optional[CleanupRunner] = None,
    ):
        self.random_ip_enabled_var = BoolVar(False)
        self.active_drivers: List[Any] = []
        self._active_drivers_lock = threading.Lock()
        self._dispatcher = dispatcher
        self._async_dispatcher = async_dispatcher or dispatcher
        self._stop_signal = stop_signal
        self._quota_request_form_opener = quota_request_form_opener
        self._on_ip_counter = on_ip_counter
        self._on_random_ip_loading = on_random_ip_loading
        self._message_handler = message_handler
        self._confirm_handler = confirm_handler
        self._refresh_random_ip_counter_handler: Optional[Callable[[], None]] = None
        self._toggle_random_ip_handler: Optional[Callable[[Optional[bool]], bool]] = None
        self._handle_random_ip_submission_handler: Optional[Callable[[Any], None]] = None
        self.execution_state: Optional[ExecutionState] = None
        self._pause_event = threading.Event()
        self._pause_reason = ""
        del cleanup_runner

    def dispatch_to_ui(self, callback: Callable[[], Any]) -> None:
        try:
            self._dispatcher(callback)
        except Exception:
            logging.info("UI 派发失败，尝试直接执行回调", exc_info=True)
            try:
                callback()
            except Exception:
                logging.info("UI 派发失败且回调直接执行失败", exc_info=True)

    def dispatch_to_ui_async(self, callback: Callable[[], Any]) -> None:
        try:
            self._async_dispatcher(callback)
        except Exception:
            logging.info("异步 UI 派发失败，尝试直接执行回调", exc_info=True)
            try:
                callback()
            except Exception:
                logging.info("异步 UI 派发失败且回调直接执行失败", exc_info=True)

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

    def wait_if_paused(self, stop_signal: Optional[threading.Event] = None) -> None:
        signal = stop_signal or self._stop_signal
        while self.is_paused() and signal and not signal.is_set():
            signal.wait(0.25)

    def stop_run(self) -> None:
        self._stop_signal.set()

    def bind_ui_callbacks(
        self,
        *,
        quota_request_form_opener: Optional[Callable[[], bool]] = None,
        on_ip_counter: Optional[Callable[[float, float, bool], None]] = None,
        on_random_ip_loading: Optional[Callable[[bool, str], None]] = None,
        message_handler: Optional[Callable[[str, str, str], None]] = None,
        confirm_handler: Optional[Callable[[str, str], bool]] = None,
    ) -> None:
        self._quota_request_form_opener = quota_request_form_opener
        self._on_ip_counter = on_ip_counter
        self._on_random_ip_loading = on_random_ip_loading
        self._message_handler = message_handler
        self._confirm_handler = confirm_handler

    def bind_runtime_actions(
        self,
        *,
        refresh_random_ip_counter: Optional[Callable[[], None]] = None,
        toggle_random_ip: Optional[Callable[[Optional[bool]], bool]] = None,
        handle_random_ip_submission: Optional[Callable[[Any], None]] = None,
    ) -> None:
        self._refresh_random_ip_counter_handler = refresh_random_ip_counter
        self._toggle_random_ip_handler = toggle_random_ip
        self._handle_random_ip_submission_handler = handle_random_ip_submission

    def open_quota_request_form(self) -> bool:
        if callable(self._quota_request_form_opener):
            try:
                return bool(self._dispatcher(self._quota_request_form_opener))
            except Exception:
                logging.warning("打开额度申请表单失败", exc_info=True)
                return False
        return False

    def update_random_ip_counter(self, used: float, total: float, custom_api: bool) -> None:
        callback = self._on_ip_counter
        if not callable(callback):
            return

        def _apply() -> None:
            try:
                callback(float(used), float(total), bool(custom_api))
            except Exception:
                logging.info("更新随机IP计数失败", exc_info=True)

        self.dispatch_to_ui_async(_apply)

    def set_random_ip_loading(self, loading: bool, message: str = "") -> None:
        callback = self._on_random_ip_loading
        if not callable(callback):
            return

        def _apply() -> None:
            try:
                callback(bool(loading), str(message or ""))
            except Exception:
                logging.info("更新随机IP加载状态失败", exc_info=True)

        self.dispatch_to_ui_async(_apply)

    def show_message_dialog(self, title: str, message: str, *, level: str = "info") -> None:
        callback = self._message_handler
        if not callable(callback):
            return

        def _apply() -> None:
            callback(str(title or ""), str(message or ""), str(level or "info"))

        self._dispatcher(_apply)

    def show_confirm_dialog(self, title: str, message: str) -> bool:
        callback = self._confirm_handler
        if not callable(callback):
            return False
        try:

            def _apply() -> bool:
                return bool(callback(str(title or ""), str(message or "")))

            return bool(self._dispatcher(_apply))
        except Exception:
            logging.warning("显示确认对话框失败", exc_info=True)
            return False

    def set_random_ip_enabled(self, enabled: bool) -> None:
        self.random_ip_enabled_var.set(bool(enabled))

    def is_random_ip_enabled(self) -> bool:
        return bool(self.random_ip_enabled_var.get())

    def refresh_random_ip_counter(self) -> None:
        callback = self._refresh_random_ip_counter_handler
        if not callable(callback):
            return
        try:
            callback()
        except Exception:
            logging.info("刷新随机IP计数失败", exc_info=True)

    def toggle_random_ip(self, enabled: Optional[bool] = None) -> bool:
        target_enabled = self.is_random_ip_enabled() if enabled is None else bool(enabled)
        callback = self._toggle_random_ip_handler
        if not callable(callback):
            return target_enabled
        try:
            return bool(callback(target_enabled))
        except Exception:
            logging.info("切换随机IP失败", exc_info=True)
            return self.is_random_ip_enabled()

    def handle_random_ip_submission(self, stop_signal: Any = None) -> None:
        callback = self._handle_random_ip_submission_handler
        if not callable(callback):
            return
        try:
            callback(stop_signal)
        except Exception:
            logging.info("处理随机IP提交流程失败", exc_info=True)

    def handle_runtime_actions(self, result: RuntimeActionResult | RuntimeActionRequest | object) -> None:
        action_result = ensure_runtime_action_result(result)
        if not action_result.actions:
            return

        def _apply_actions() -> None:
            for action in action_result.actions:
                self._handle_runtime_action(action)

        self.dispatch_to_ui_async(_apply_actions)

    def _handle_runtime_action(self, action: RuntimeActionRequest) -> None:
        if action.kind == RuntimeActionKind.PAUSE_RUN:
            self.pause_run(action.reason or "已暂停")
            return
        if action.kind == RuntimeActionKind.SHOW_MESSAGE:
            self.show_message_dialog(action.title, action.message, level=action.level or "info")
            return
        if action.kind == RuntimeActionKind.CONFIRM_ENABLE_RANDOM_IP:
            if self.show_confirm_dialog(action.title, action.message):
                self.toggle_random_ip(True)
            return
        if action.kind == RuntimeActionKind.SET_RANDOM_IP_ENABLED:
            self.set_random_ip_enabled(bool(action.enabled))
            return
        if action.kind == RuntimeActionKind.REFRESH_RANDOM_IP_COUNTER:
            self.refresh_random_ip_counter()

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

    def cleanup_browsers(self) -> None:
        cleaned = 0
        seen: set[int] = set()
        while True:
            drivers = self._drain_cleanup_targets()
            if not drivers:
                break
            # LIFO 清理可确保先关 context/page，再关共享 browser pool。
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
                    logging.warning("[兜底清理] 强制关闭浏览器失败", exc_info=True)
        if seen:
            logging.info(
                "[兜底清理] 已强制关闭 %d/%d 个 driver 实例",
                cleaned,
                len(seen),
            )
