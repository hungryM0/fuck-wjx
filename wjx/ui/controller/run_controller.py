"""运行控制器 - 连接 UI 与引擎的业务逻辑桥接层。"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Set

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal

from wjx.core.questions.config import QuestionEntry
from wjx.core.task_context import TaskContext
from wjx.ui.controller.run_controller_parts import (
    RunControllerParsingMixin,
    RunControllerPersistenceMixin,
    RunControllerRuntimeMixin,
)
from wjx.utils.io.load_save import RuntimeConfig
from wjx.utils.system.cleanup_runner import CleanupRunner


class BoolVar:
    """简单的布尔状态封装，用于 UI 适配。"""

    def __init__(self, value: bool = False):
        self._value = bool(value)

    def get(self) -> bool:
        return self._value

    def set(self, value: bool):
        self._value = bool(value)


class EngineGuiAdapter:
    """传给引擎的 UI 适配器，负责把回调桥接回 Qt 主线程。"""

    def __init__(
        self,
        dispatcher: Callable[[Callable[[], None]], None],
        stop_signal: threading.Event,
        quota_request_form_opener: Optional[Callable[[], bool]] = None,
        on_ip_counter: Optional[Callable[[float, float, bool], None]] = None,
        on_random_ip_loading: Optional[Callable[[bool, str], None]] = None,
        message_handler: Optional[Callable[[str, str, str], None]] = None,
        confirm_handler: Optional[Callable[[str, str], bool]] = None,
        async_dispatcher: Optional[Callable[[Callable[[], None]], None]] = None,
        cleanup_runner: Optional[CleanupRunner] = None,
    ):
        self.random_ip_enabled_var = BoolVar(False)
        self.active_drivers: List[Any] = []
        self._dispatcher = dispatcher
        self._async_dispatcher = async_dispatcher or dispatcher
        self._stop_signal = stop_signal
        self._quota_request_form_opener = quota_request_form_opener
        self._on_ip_counter = on_ip_counter
        self._on_random_ip_loading = on_random_ip_loading
        self._message_handler = message_handler
        self._confirm_handler = confirm_handler
        self.task_ctx: Optional[TaskContext] = None
        self._pause_event = threading.Event()
        self._pause_reason = ""
        self._cleanup_runner = cleanup_runner

    def dispatch_to_ui(self, callback: Callable[[], None]) -> None:
        try:
            self._dispatcher(callback)
        except Exception:
            logging.info("UI 派发失败，尝试直接执行回调", exc_info=True)
            try:
                callback()
            except Exception:
                logging.info("UI 派发失败且回调直接执行失败", exc_info=True)

    def dispatch_to_ui_async(self, callback: Callable[[], None]) -> None:
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

    def stop_run(self):
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

    def open_quota_request_form(self) -> bool:
        if callable(self._quota_request_form_opener):
            try:
                return bool(self._quota_request_form_opener())
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
        return callback(str(title or ""), str(message or ""), str(level or "info"))

    def show_confirm_dialog(self, title: str, message: str) -> bool:
        callback = self._confirm_handler
        if not callable(callback):
            return False
        try:
            return bool(callback(str(title or ""), str(message or "")))
        except Exception:
            logging.warning("显示确认对话框失败", exc_info=True)
            return False

    def set_random_ip_enabled(self, enabled: bool) -> None:
        self.random_ip_enabled_var.set(bool(enabled))

    def is_random_ip_enabled(self) -> bool:
        return bool(self.random_ip_enabled_var.get())

    def cleanup_browsers(self) -> None:
        drivers = list(self.active_drivers or [])
        self.active_drivers.clear()
        if drivers:
            logging.info("[兜底清理] 已清理 %d 个 driver 跟踪引用，底座关闭由工作线程负责", len(drivers))


class RunController(
    RunControllerParsingMixin,
    RunControllerRuntimeMixin,
    RunControllerPersistenceMixin,
    QObject,
):
    surveyParsed = Signal(list, str)
    surveyParseFailed = Signal(str)
    runStateChanged = Signal(bool)
    runFailed = Signal(str)
    statusUpdated = Signal(str, int, int)
    threadProgressUpdated = Signal(dict)
    pauseStateChanged = Signal(bool, str)
    cleanupFinished = Signal()
    _uiCallbackQueued = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = RuntimeConfig()
        self.questions_info: List[Dict[str, Any]] = []
        self.question_entries: List[QuestionEntry] = []
        self.survey_title = ""
        self.stop_event = threading.Event()
        self.worker_threads: List[threading.Thread] = []
        self._task_ctx: Optional[TaskContext] = None
        self._cleanup_runner = CleanupRunner()
        self.on_ip_counter: Optional[Callable[[int, int, bool], None]] = None
        self.on_random_ip_loading: Optional[Callable[[bool, str], None]] = None
        self.quota_request_form_opener: Optional[Callable[[], bool]] = None
        self.message_dialog_handler: Optional[Callable[[str, str, str], None]] = None
        self.confirm_dialog_handler: Optional[Callable[[str, str], bool]] = None
        self._engine_adapter_cls = EngineGuiAdapter
        self.adapter = self._create_adapter(self.stop_event, random_ip_enabled=False)
        self.running = False
        self._paused_state = False
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(600)
        self._status_timer.timeout.connect(self._emit_status)
        self._completion_cleanup_done = False
        self._cleanup_scheduled = False
        self._stopped_by_stop_run = False
        self._starting = False
        self._initializing = False
        self._init_stage_text = ""
        self._init_steps: List[Dict[str, str]] = []
        self._init_completed_steps: Set[str] = set()
        self._init_current_step_key = ""
        self._init_gate_stop_event: Optional[threading.Event] = None
        self._pending_question_ctx: Optional[TaskContext] = None
        self._uiCallbackQueued.connect(self._execute_ui_callback)

    def is_initializing(self) -> bool:
        return bool(self._initializing)

    def _execute_ui_callback(self, callback: object) -> None:
        if not callable(callback):
            return
        try:
            callback()
        except Exception:
            logging.info("执行 UI 回调失败", exc_info=True)

    def _dispatch_to_ui_async(self, callback: Callable[[], None]) -> None:
        if not callable(callback):
            return
        if QCoreApplication.instance() is None:
            try:
                callback()
            except Exception:
                logging.info("无 QCoreApplication 时执行回调失败", exc_info=True)
            return
        if threading.current_thread() is threading.main_thread():
            try:
                callback()
            except Exception:
                logging.info("主线程直接执行回调失败", exc_info=True)
            return
        try:
            self._uiCallbackQueued.emit(callback)
        except Exception:
            logging.warning("UI 回调入队失败，尝试直接执行", exc_info=True)
            try:
                callback()
            except Exception:
                logging.info("UI 回调入队失败且直接执行失败", exc_info=True)

    def configure_ui_bridge(
        self,
        *,
        quota_request_form_opener: Optional[Callable[[], bool]] = None,
        on_ip_counter: Optional[Callable[[int, int, bool], None]] = None,
        on_random_ip_loading: Optional[Callable[[bool, str], None]] = None,
        message_handler: Optional[Callable[[str, str, str], None]] = None,
        confirm_handler: Optional[Callable[[str, str], bool]] = None,
    ) -> None:
        self.quota_request_form_opener = quota_request_form_opener
        self.on_ip_counter = on_ip_counter
        self.on_random_ip_loading = on_random_ip_loading
        self.message_dialog_handler = message_handler
        self.confirm_dialog_handler = confirm_handler
        self._sync_adapter_ui_bridge()

    def _sync_adapter_ui_bridge(self, adapter: Optional[EngineGuiAdapter] = None) -> None:
        target = adapter or self.adapter
        if target is None:
            return
        target.bind_ui_callbacks(
            quota_request_form_opener=self.quota_request_form_opener,
            on_ip_counter=self.on_ip_counter,
            on_random_ip_loading=self.on_random_ip_loading,
            message_handler=self.message_dialog_handler,
            confirm_handler=self.confirm_dialog_handler,
        )

