"""运行控制器 - 连接 UI 与引擎的业务逻辑桥接层。"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Set

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal

from software.core.questions.config import QuestionEntry
from software.core.task import TaskContext
from software.ui.controller.run_controller_parts import (
    RunControllerParsingMixin,
    RunControllerPersistenceMixin,
    RunControllerRuntimeMixin,
)
from software.core.engine.cleanup import CleanupRunner
from software.io.config import RuntimeConfig


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

        return self._dispatcher(_apply)

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
    runtimeUiStateChanged = Signal(dict)
    randomIpLoadingChanged = Signal(bool, str)
    _uiCallbackQueued = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = RuntimeConfig()
        self.questions_info: List[Dict[str, Any]] = []
        self.question_entries: List[QuestionEntry] = []
        self.survey_title = ""
        self.survey_provider = "wjx"
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
        self._runtime_ui_state: Dict[str, Any] = {}
        self._random_ip_toggle_lock = threading.Lock()
        self._random_ip_toggle_active = False
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

    @staticmethod
    def _normalize_runtime_ui_value(key: str, value: Any) -> Any:
        if key in {"target", "threads"}:
            return max(1, int(value or 1))
        if key in {"random_ip_enabled", "headless_mode", "timed_mode_enabled"}:
            return bool(value)
        if key == "proxy_source":
            normalized = str(value or "default").strip().lower()
            return normalized if normalized in {"default", "benefit", "custom"} else "default"
        if key == "answer_duration":
            raw = value if isinstance(value, (list, tuple)) else (0, 0)
            low = max(0, int(raw[0] if len(raw) >= 1 else 0))
            high = max(low, int(raw[1] if len(raw) >= 2 else low))
            return (low, high)
        return value

    def get_runtime_ui_state(self) -> Dict[str, Any]:
        return dict(self._runtime_ui_state)

    def set_runtime_ui_state(self, emit: bool = True, **updates: Any) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {}
        changed = False
        for key, value in updates.items():
            normalized_value = self._normalize_runtime_ui_value(key, value)
            normalized[key] = normalized_value
            if self._runtime_ui_state.get(key) != normalized_value:
                changed = True
        if normalized:
            self._runtime_ui_state.update(normalized)
        if emit and changed:
            self.runtimeUiStateChanged.emit(dict(self._runtime_ui_state))
        return dict(self._runtime_ui_state)

    def sync_runtime_ui_state_from_config(self, config: RuntimeConfig, *, emit: bool = True) -> Dict[str, Any]:
        return self.set_runtime_ui_state(
            emit=emit,
            target=getattr(config, "target", 1),
            threads=getattr(config, "threads", 1),
            random_ip_enabled=getattr(config, "random_ip_enabled", False),
            headless_mode=getattr(config, "headless_mode", True),
            timed_mode_enabled=getattr(config, "timed_mode_enabled", False),
            proxy_source=getattr(config, "proxy_source", "default"),
            answer_duration=getattr(config, "answer_duration", (0, 0)),
        )

    def notify_random_ip_loading(self, loading: bool, message: str = "") -> None:
        self.randomIpLoadingChanged.emit(bool(loading), str(message or ""))

    def is_random_ip_toggle_active(self) -> bool:
        with self._random_ip_toggle_lock:
            return bool(self._random_ip_toggle_active)

    def toggle_random_ip_async(
        self,
        enabled: bool,
        *,
        adapter: Optional[EngineGuiAdapter] = None,
        on_done: Optional[Callable[[bool], None]] = None,
    ) -> bool:
        target_adapter = adapter or self.adapter
        with self._random_ip_toggle_lock:
            if self._random_ip_toggle_active:
                return False
            self._random_ip_toggle_active = True

        self.notify_random_ip_loading(True, "正在处理...")

        def _finish(final_enabled: bool) -> None:
            with self._random_ip_toggle_lock:
                self._random_ip_toggle_active = False
            self.notify_random_ip_loading(False, "")
            self.set_runtime_ui_state(random_ip_enabled=bool(final_enabled))
            if callable(on_done):
                try:
                    on_done(bool(final_enabled))
                except Exception:
                    logging.info("随机IP异步回调执行失败", exc_info=True)
            self.refresh_random_ip_counter(adapter=target_adapter)

        def _worker() -> None:
            final_enabled = bool(enabled)
            try:
                final_enabled = bool(self.toggle_random_ip(bool(enabled), adapter=target_adapter))
            except Exception:
                logging.warning("随机IP异步切换失败", exc_info=True)
                if target_adapter is not None:
                    try:
                        final_enabled = bool(target_adapter.is_random_ip_enabled())
                    except Exception:
                        final_enabled = False
            finally:
                self._dispatch_to_ui_async(lambda value=bool(final_enabled): _finish(value))

        threading.Thread(
            target=_worker,
            daemon=True,
            name="RandomIPToggle",
        ).start()
        return True

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



